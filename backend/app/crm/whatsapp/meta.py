"""Meta WhatsApp Cloud API: send messages, read templates and numbers, check and read webhooks.

Credentials stay on the server (settings). Two rules, as for Brevo:

1. Forward-only. Meta retries webhooks and delivers statuses out of order, so `delivered` arriving
   after `read` must not undo the read.
2. Every webhook is checked against the app secret (X-Hub-Signature-256) before anything in it is
   believed.
"""

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

GRAPH = "https://graph.facebook.com"
TEMPLATE_PAGES = 20
# Shown to agents when WhatsApp is not configured; which settings are missing stays on the server.
NOT_AVAILABLE = "WhatsApp is not connected yet"

STATUS_RANK = {"queued": 5, "sent": 10, "delivered": 30, "read": 40, "failed": 100}
REVIEW = {"APPROVED": "approved", "PENDING": "pending", "REJECTED": "rejected", "PAUSED": "paused"}
CATEGORY = {"MARKETING": "marketing", "UTILITY": "utility", "AUTHENTICATION": "authentication"}
# A customer asking to stop (typed, or a "Stop promotions" quick-reply button) or to start again.
OPT_OUT_WORDS = {"stop", "unsubscribe", "stop promotions"}
OPT_IN_WORDS = {"start"}
VARIABLE = re.compile(r"\{\{\s*(\d+)\s*\}\}")


class MetaError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def is_configured() -> bool:
    return bool(
        settings.WHATSAPP_ACCESS_TOKEN
        and settings.WHATSAPP_WABA_ID
        and settings.WHATSAPP_GRAPH_API_VERSION
    )


def webhook_configured() -> bool:
    return bool(settings.WHATSAPP_APP_SECRET and settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN)


def verify_signature(raw_body: bytes, header: str | None) -> bool:
    """X-Hub-Signature-256 is "sha256=" + HMAC-SHA256 of the raw body with the app secret."""
    secret = settings.WHATSAPP_APP_SECRET
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def verify_subscription(mode: str | None, token: str | None) -> bool:
    """Meta's one-time GET when the webhook URL is registered."""
    expected = settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN
    return bool(expected) and mode == "subscribe" and hmac.compare_digest(token or "", expected)


def wa_id_from_phone(raw: str | None) -> str | None:
    """A stored phone as the WhatsApp id Meta uses: digits with country code, no + or 00.

    UAE local mobiles ("050 123 4567") get 971; anything else must already carry its country code.
    """
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    elif len(digits) == 10 and digits.startswith("05"):
        digits = "971" + digits[1:]
    return digits if len(digits) >= 8 else None


def variable_count(body: str) -> int:
    return max((int(n) for n in VARIABLE.findall(body)), default=0)


def fill_template(body: str, params: list[str]) -> str:
    """The body as the customer reads it; used for the CRM's copy of the message."""

    def value(match: re.Match[str]) -> str:
        i = int(match.group(1)) - 1
        return params[i] if 0 <= i < len(params) else match.group(0)

    return VARIABLE.sub(value, body)


def _url(path: str) -> str:
    return f"{GRAPH}/{settings.WHATSAPP_GRAPH_API_VERSION}/{path}"


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN or ''}"}


def _json(res: httpx.Response) -> dict[str, Any]:
    try:
        data = res.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def error_text(data: dict[str, Any], status: int) -> str:
    """Meta's own words for a refused call: the detail when given, else the message."""
    error = data.get("error") or {}
    details = (error.get("error_data") or {}).get("details")
    return str(details or error.get("message") or f"Meta returned HTTP {status}")


async def _call(client: httpx.AsyncClient, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    if not is_configured():
        raise MetaError(NOT_AVAILABLE)
    try:
        res = await client.request(method, url, headers=_headers(), **kwargs)
    except httpx.HTTPError as exc:
        raise MetaError(f"Could not reach WhatsApp: {exc}") from exc
    data = _json(res)
    if res.status_code >= 400:
        raise MetaError(error_text(data, res.status_code), res.status_code)
    return data


async def _send(client: httpx.AsyncClient, phone_number_id: str, payload: dict[str, Any]) -> str:
    data = await _call(
        client,
        "POST",
        _url(f"{phone_number_id}/messages"),
        json={"messaging_product": "whatsapp", "recipient_type": "individual", **payload},
    )
    messages = data.get("messages") or [{}]
    wamid = messages[0].get("id")
    if not wamid:
        raise MetaError("WhatsApp accepted the message but returned no message id")
    return str(wamid)


async def send_text(client: httpx.AsyncClient, *, phone_number_id: str, to: str, body: str) -> str:
    """A free-form reply; only allowed inside the 24-hour customer-service window."""
    return await _send(
        client,
        phone_number_id,
        {"to": to, "type": "text", "text": {"preview_url": False, "body": body}},
    )


async def send_template(
    client: httpx.AsyncClient,
    *,
    phone_number_id: str,
    to: str,
    name: str,
    language: str,
    params: list[str],
) -> str:
    """An approved template; the only way to message first or after the window closes."""
    template: dict[str, Any] = {"name": name, "language": {"code": language}}
    if params:
        template["components"] = [
            {"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}
        ]
    return await _send(
        client, phone_number_id, {"to": to, "type": "template", "template": template}
    )


async def list_templates(client: httpx.AsyncClient) -> list[dict[str, str]]:
    """GET /{WABA_ID}/message_templates, every page; templates in states agents never see (e.g.
    DISABLED) are left out."""
    url: str | None = _url(f"{settings.WHATSAPP_WABA_ID}/message_templates")
    params: dict[str, Any] | None = {
        "fields": "name,language,status,category,components",
        "limit": 100,
    }
    out: list[dict[str, str]] = []
    for _ in range(TEMPLATE_PAGES):
        if not url:
            break
        data = await _call(client, "GET", url, params=params)
        for item in data.get("data") or []:
            review = REVIEW.get(str(item.get("status", "")).upper())
            category = CATEGORY.get(str(item.get("category", "")).upper())
            if not review or not category:
                continue
            body = next(
                (
                    c.get("text") or ""
                    for c in item.get("components") or []
                    if str(c.get("type", "")).upper() == "BODY"
                ),
                "",
            )
            out.append(
                {
                    "name": str(item.get("name", "")),
                    "language": str(item.get("language", "")),
                    "category": category,
                    "review": review,
                    "body": body,
                }
            )
        # The next page URL already carries the query.
        url, params = (data.get("paging") or {}).get("next"), None
    return out


async def list_phone_numbers(client: httpx.AsyncClient) -> list[dict[str, str | None]]:
    """GET /{WABA_ID}/phone_numbers: the numbers registered under the business account."""
    data = await _call(
        client,
        "GET",
        _url(f"{settings.WHATSAPP_WABA_ID}/phone_numbers"),
        params={"fields": "id,display_phone_number,verified_name,quality_rating"},
    )
    return [
        {
            "phone_number_id": str(n.get("id", "")),
            "display_number": str(n.get("display_phone_number", "")),
            "verified_name": n.get("verified_name"),
            "quality_rating": n.get("quality_rating"),
        }
        for n in data.get("data") or []
    ]


async def subscribe_app(client: httpx.AsyncClient) -> bool:
    """POST /{WABA_ID}/subscribed_apps: send this app the business account's webhooks."""
    data = await _call(client, "POST", _url(f"{settings.WHATSAPP_WABA_ID}/subscribed_apps"))
    return bool(data.get("success"))


# ── Webhooks ──


@dataclass(frozen=True)
class InboundMessage:
    phone_number_id: str
    wa_id: str
    wamid: str
    body: str
    contact_name: str | None
    at: datetime


@dataclass(frozen=True)
class StatusUpdate:
    phone_number_id: str
    wamid: str
    status: str
    error: str | None
    at: datetime


def _time(raw: Any) -> datetime:
    """Meta timestamps are unix seconds, as a string."""
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def message_text(message: dict[str, Any]) -> str:
    """What the customer sent, as the CRM shows it. Media is named, not stored."""
    kind = str(message.get("type", ""))
    if kind == "text":
        return str((message.get("text") or {}).get("body", ""))
    if kind == "button":
        return str((message.get("button") or {}).get("text", ""))
    if kind == "interactive":
        reply = message.get("interactive") or {}
        chosen = reply.get("button_reply") or reply.get("list_reply") or {}
        return str(chosen.get("title", ""))
    if kind in {"image", "video", "document", "audio", "sticker"}:
        caption = (message.get(kind) or {}).get("caption")
        return f"[{kind}] {caption}" if caption else f"[{kind}]"
    if kind == "location":
        return "[location]"
    return f"[{kind or 'message'}]"


def parse_webhook(payload: dict[str, Any]) -> tuple[list[InboundMessage], list[StatusUpdate]]:
    """Messages and statuses from one webhook POST; anything not about messages is skipped."""
    messages: list[InboundMessage] = []
    statuses: list[StatusUpdate] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            number = str((value.get("metadata") or {}).get("phone_number_id") or "")
            if not number:
                continue
            names = {
                str(c.get("wa_id")): (c.get("profile") or {}).get("name")
                for c in value.get("contacts") or []
            }
            for m in value.get("messages") or []:
                if not m.get("id") or not m.get("from"):
                    continue
                messages.append(
                    InboundMessage(
                        phone_number_id=number,
                        wa_id=str(m["from"]),
                        wamid=str(m["id"]),
                        body=message_text(m),
                        contact_name=names.get(str(m["from"])),
                        at=_time(m.get("timestamp")),
                    )
                )
            for s in value.get("statuses") or []:
                if not s.get("id") or s.get("status") not in STATUS_RANK:
                    continue
                errors = s.get("errors") or []
                error = None
                if errors:
                    first = errors[0]
                    error = str(
                        (first.get("error_data") or {}).get("details")
                        or first.get("message")
                        or first.get("title")
                        or "Failed"
                    )
                statuses.append(
                    StatusUpdate(
                        phone_number_id=number,
                        wamid=str(s["id"]),
                        status=str(s["status"]),
                        error=error,
                        at=_time(s.get("timestamp")),
                    )
                )
    return messages, statuses


def opt_change(body: str) -> str | None:
    """'out' when the customer asks to stop, 'in' when they ask to start again, else None."""
    word = body.strip().lower().rstrip(".!")
    if word in OPT_OUT_WORDS:
        return "out"
    if word in OPT_IN_WORDS:
        return "in"
    return None


def moves_forward(current: str | None, new: str) -> bool:
    return STATUS_RANK[new] > STATUS_RANK.get(current or "", 0)
