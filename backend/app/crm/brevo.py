"""Brevo transactional email: send one message, read its delivery events, apply them to a send.

Ported from the CVBuilder email pipeline (src/CRM/lib/brevo.js, emailTracking.js, brevoEvents.js).
Two rules carried over:

1. Forward-only. Brevo retries events and delivers them out of order, so `delivered` arriving
   after `opened` must not undo the open. Every timestamp keeps the first time we heard of it.
2. Webhook (push) and statistics API (pull) feed the same `apply_event`, and a repeated event is
   a no-op, so both can run, overlap and repeat without corrupting a send.
"""

import hashlib
import hmac
import html
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.config import settings
from app.crm.email_models import CrmEmailSend

API = "https://api.brevo.com/v3"
EVENTS_PAGE = 100
EVENTS_MAX = 20000
# Shown to agents when Brevo is not configured; which settings are missing stays on the server.
NOT_AVAILABLE = "Email sending is not available yet"

STATUS_RANK = {
    "queued": 5,
    "sent": 10,
    "deferred": 20,
    "delivered": 30,
    "opened": 40,
    "clicked": 50,
    "bounced": 90,
    "spam": 95,
    "unsubscribed": 95,
    "replied": 98,
    "failed": 100,
}


@dataclass(frozen=True)
class Meaning:
    status: str | None
    stamp: str | None = None


# Keys are letters only: the webhook says `hard_bounce`, the docs `hardBounce`, the statistics API
# `hardBounces`. Proxy opens (Apple Mail privacy prefetch) are recorded but count as nothing.
EVENTS: dict[str, Meaning] = {
    "request": Meaning("sent"),
    "sent": Meaning("sent"),
    "delivered": Meaning("delivered", "delivered_at"),
    "deferred": Meaning("deferred"),
    "opened": Meaning("opened", "opened_at"),
    "uniqueopened": Meaning("opened", "opened_at"),
    "loadedbyproxy": Meaning(None),
    "proxyopen": Meaning(None),
    "click": Meaning("clicked", "clicked_at"),
    "clicked": Meaning("clicked", "clicked_at"),
    "softbounce": Meaning("deferred", "bounced_at"),
    "hardbounce": Meaning("bounced", "bounced_at"),
    "blocked": Meaning("bounced", "bounced_at"),
    "invalidemail": Meaning("bounced", "bounced_at"),
    "error": Meaning("failed"),
    "spam": Meaning("spam"),
    "complaint": Meaning("spam"),
    "unsubscribed": Meaning("unsubscribed"),
    # Not a Brevo event: recorded when inbound parsing receives a reply to this send.
    "replied": Meaning("replied"),
}
OPEN_EVENTS = {"opened", "uniqueopened"}
CLICK_EVENTS = {"click", "clicked"}


class BrevoError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def is_configured() -> bool:
    return bool(settings.BREVO_API_KEY and settings.BREVO_SENDER_EMAIL)


def canonical_event(raw: Any) -> str | None:
    key = re.sub(r"[^a-z]", "", str(raw or "").lower())
    if key in EVENTS:
        return key
    if key.endswith("s") and key[:-1] in EVENTS:
        return key[:-1]
    return None


def message_id_variants(raw: Any) -> list[str]:
    """Brevo's message-id arrives as "<abc@host>" or "abc@host"; match either."""
    text = str(raw or "").strip()
    if not text:
        return []
    bare = text.strip("<>")
    return list(dict.fromkeys([text, bare, f"<{bare}>"]))


def event_time(raw: Any) -> datetime:
    """Brevo sends `ts`/`ts_event` (unix seconds) or `date` ("2026-08-25 11:02:31" or ISO)."""
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.isdigit():
            return datetime.fromtimestamp(int(text), tz=timezone.utc)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def apply_event(send: CrmEmailSend, event: Any, at: Any = None, link: str | None = None) -> bool:
    """Record one Brevo event on a send. False when the event is unknown or already recorded."""
    key = canonical_event(event)
    if key is None:
        return False
    when = event_time(at)
    entry = {"event": key, "at": when.isoformat(), "link": link or None}
    if entry in (send.events or []):
        return False
    # Kept in time order whatever order they arrive in: Brevo's statistics API lists newest first.
    send.events = sorted([*(send.events or []), entry], key=lambda e: e["at"])

    meaning = EVENTS[key]
    if meaning.stamp and getattr(send, meaning.stamp) is None:
        setattr(send, meaning.stamp, when)
    if meaning.status and STATUS_RANK[meaning.status] > STATUS_RANK.get(send.status, 0):
        send.status = meaning.status
    send.updated_at = datetime.now(timezone.utc)
    return True


def count_events(send: CrmEmailSend) -> tuple[int, int]:
    """Human opens and clicks; proxy prefetches are left out."""
    events = send.events or []
    opens = sum(1 for e in events if e.get("event") in OPEN_EVENTS)
    clicks = sum(1 for e in events if e.get("event") in CLICK_EVENTS)
    return opens, clicks


def render_template(template: str, *, name: str, email: str) -> str:
    """Fill {{name}}, {{first_name}}, {{email}}; unknown tokens stay as written."""
    values = {"name": name, "first_name": (name.split() or [""])[0], "email": email}
    return re.sub(
        r"\{\{\s*(\w+)\s*\}\}",
        lambda m: values.get(m.group(1), m.group(0)),
        template,
    )


# Messages are plain text with three link forms; only http(s) links are ever made clickable.
#   [button: Book a viewing](https://…)  → a button      [the shortlist](https://…) → a link
#   https://…                            → a link
# Brevo rewrites every link for click tracking, so each click comes back as a `click` event.
LINKS = re.compile(
    r"\[button:\s*(?P<button>[^\]\n]+?)\s*\]\((?P<button_url>https?://[^\s)]+)\)"
    r"|\[(?P<text>[^\]\n]+?)\]\((?P<text_url>https?://[^\s)]+)\)"
    r"|(?P<url>https?://[^\s<>()]+[^\s<>().,;:!?'\"])"
)
BUTTON_STYLE = (
    "display:inline-block;padding:12px 22px;background:#2563eb;color:#ffffff;"
    "text-decoration:none;border-radius:6px;font-weight:600"
)


def _link_html(match: re.Match[str]) -> str:
    if match["button"]:
        url, label = match["button_url"], match["button"]
        return f'<a href="{html.escape(url)}" style="{BUTTON_STYLE}">{html.escape(label)}</a>'
    url = match["text_url"] or match["url"]
    label = match["text"] or match["url"]
    return f'<a href="{html.escape(url)}">{html.escape(label)}</a>'


def _paragraph_html(paragraph: str) -> str:
    out, last = [], 0
    for match in LINKS.finditer(paragraph):
        out.append(html.escape(paragraph[last : match.start()]))
        out.append(_link_html(match))
        last = match.end()
    out.append(html.escape(paragraph[last:]))
    return "".join(out).replace("\n", "<br>")


def text_to_html(text: str) -> str:
    """Message text to email HTML: blank lines make paragraphs, newlines <br>, links and buttons."""
    paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    return "".join(f"<p>{_paragraph_html(p)}</p>" for p in paragraphs)


def text_to_plain(text: str) -> str:
    """The plain-text part: a button or link reads as "Label: https://…"."""

    def plain(match: re.Match[str]) -> str:
        label = match["button"] or match["text"]
        url = match["button_url"] or match["text_url"] or match["url"]
        return f"{label}: {url}" if label else url

    return LINKS.sub(plain, text)


def reply_address(tag: str) -> str | None:
    """Use an opaque authenticated token, never the sequential store id, for reply routing."""
    domain = (settings.BREVO_INBOUND_DOMAIN or "").strip().lower()
    if domain:
        token = hmac.new(
            settings.SESSION_SECRET.encode(),
            f"crm-email-reply:{tag}".encode(),
            hashlib.sha256,
        ).hexdigest()[:40]
        return f"reply+{token}@{domain}"
    return settings.BREVO_REPLY_TO or None


def matches_reply_address(address: str, send_id: int) -> bool:
    if not settings.BREVO_INBOUND_DOMAIN:
        return False
    expected = reply_address(str(send_id))
    return bool(
        expected and hmac.compare_digest(address.strip().lower().encode(), expected.encode())
    )


def _headers() -> dict[str, str]:
    return {
        "api-key": settings.BREVO_API_KEY or "",
        "accept": "application/json",
        "content-type": "application/json",
    }


async def send_email(
    client: httpx.AsyncClient,
    *,
    to: str,
    to_name: str | None,
    subject: str,
    text: str,
    tag: str,
) -> str | None:
    """POST /smtp/email. Returns Brevo's messageId; raises BrevoError with Brevo's message."""
    if not is_configured():
        raise BrevoError(NOT_AVAILABLE)
    payload: dict[str, Any] = {
        "sender": {
            "email": settings.BREVO_SENDER_EMAIL,
            **({"name": settings.BREVO_SENDER_NAME} if settings.BREVO_SENDER_NAME else {}),
        },
        "to": [{"email": to, **({"name": to_name} if to_name else {})}],
        "subject": subject,
        "htmlContent": text_to_html(text),
        "textContent": text_to_plain(text),
        "tags": [tag],
        # Survives on the message itself, so even a bounce without the tag can be matched.
        "headers": {"X-Mailin-custom": tag},
    }
    reply_to = reply_address(tag)
    if reply_to:
        payload["replyTo"] = {"email": reply_to}
    try:
        res = await client.post(f"{API}/smtp/email", json=payload, headers=_headers())
    except httpx.HTTPError as exc:
        raise BrevoError(f"Could not reach Brevo: {exc}") from exc
    data = _json(res)
    if res.status_code >= 400:
        raise BrevoError(
            data.get("message") or f"Brevo returned HTTP {res.status_code}", res.status_code
        )
    return data.get("messageId")


async def fetch_events(
    client: httpx.AsyncClient, *, start: date, end: date
) -> AsyncIterator[dict[str, Any]]:
    """GET /smtp/statistics/events for a date window, newest first, page by page."""
    if not settings.BREVO_API_KEY:
        raise BrevoError(NOT_AVAILABLE)
    # Brevo rejects a future end date.
    end = min(end, datetime.now(timezone.utc).date())
    offset = 0
    while offset < EVENTS_MAX:
        params = {
            "limit": EVENTS_PAGE,
            "offset": offset,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "sort": "desc",
        }
        try:
            res = await client.get(
                f"{API}/smtp/statistics/events", params=params, headers=_headers()
            )
        except httpx.HTTPError as exc:
            raise BrevoError(f"Could not reach Brevo: {exc}") from exc
        data = _json(res)
        if res.status_code >= 400:
            raise BrevoError(
                data.get("message") or f"Brevo returned HTTP {res.status_code}", res.status_code
            )
        events = data.get("events") or []
        for event in events:
            yield event
        if len(events) < EVENTS_PAGE:
            return
        offset += EVENTS_PAGE


def _json(res: httpx.Response) -> dict[str, Any]:
    try:
        data = res.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True)
class InboundEmail:
    message_id: str | None
    in_reply_to: str | None
    from_email: str
    from_name: str | None
    # Every To and Cc address, lower-case: our authenticated reply address may be either.
    recipients: list[str]
    subject: str
    body: str
    attachments: list[str]
    received_at: datetime


def parse_inbound(item: dict[str, Any]) -> InboundEmail | None:
    """One item of Brevo's inbound parsing payload, or None without a usable sender.

    The body prefers Brevo's extracted message (the reply without the quoted history below it).
    """
    sender = item.get("From") or {}
    from_email = str(sender.get("Address") or "").strip().lower()
    if "@" not in from_email:
        return None
    recipients = [
        str(r.get("Address") or "").strip().lower()
        for r in [*(item.get("To") or []), *(item.get("Cc") or [])]
        if isinstance(r, dict) and r.get("Address")
    ]
    body = (
        item.get("ExtractedMarkdownMessage")
        or item.get("RawTextBody")
        or item.get("RawHtmlBody")
        or ""
    )
    return InboundEmail(
        message_id=(str(item["MessageId"]).strip() or None) if item.get("MessageId") else None,
        in_reply_to=(str(item["InReplyTo"]).strip() or None) if item.get("InReplyTo") else None,
        from_email=from_email,
        from_name=(str(sender.get("Name") or "").strip() or None),
        recipients=recipients,
        subject=str(item.get("Subject") or "").strip() or "(no subject)",
        body=str(body).strip(),
        attachments=[
            str(a.get("Name"))
            for a in item.get("Attachments") or []
            if isinstance(a, dict) and a.get("Name")
        ],
        received_at=_mail_date(item.get("SentAtDate")),
    )


def _mail_date(raw: Any) -> datetime:
    """Brevo's SentAtDate is an RFC 2822 date ("Thu, 29 Oct 2026 10:02:31 +0400")."""
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = parsedate_to_datetime(raw.strip())
        except (TypeError, ValueError):
            return datetime.now(timezone.utc)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)
