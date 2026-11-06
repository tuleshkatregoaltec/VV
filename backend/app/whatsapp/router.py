import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.config import settings
from app.whatsapp.automation import receive
from app.whatsapp.customer_automation import receive_customer
from app.whatsapp.service import event_counts, valid_signature

# Third-party callbacks are excluded from the browser client's OpenAPI contract.
router = APIRouter(prefix="/api/v1/webhooks/whatsapp", include_in_schema=False)
logger = logging.getLogger(__name__)
MAX_BODY_BYTES = 1024 * 1024


def require_demo() -> None:
    if not (settings.WHATSAPP_DEMO_ENABLED or settings.WHATSAPP_CUSTOMER_AUTOMATION_ENABLED):
        raise HTTPException(404, "Not found")


@router.get("", response_class=PlainTextResponse)
async def verify_webhook(
    mode: str = Query(default="", alias="hub.mode", max_length=32),
    token: str = Query(default="", alias="hub.verify_token", max_length=512),
    challenge: str = Query(default="", alias="hub.challenge", max_length=512),
) -> str:
    require_demo()
    expected = settings.WHATSAPP_VERIFY_TOKEN
    if not expected:
        raise HTTPException(503, "Webhook verification is not configured")
    if (
        mode != "subscribe"
        or not challenge
        or not hmac.compare_digest(token.encode(), expected.encode())
    ):
        raise HTTPException(403, "Verification failed")
    return challenge


@router.post("")
async def receive_webhook(request: Request) -> dict[str, str]:
    require_demo()
    if not settings.WHATSAPP_APP_SECRET or not (
        settings.WHATSAPP_PHONE_NUMBER_ID or settings.WHATSAPP_CUSTOMER_PHONE_NUMBER_ID
    ):
        raise HTTPException(503, "Webhook reception is not configured")
    signature = request.headers.get("x-hub-signature-256", "")
    if not signature:
        raise HTTPException(403, "Signature required")
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > MAX_BODY_BYTES:
            raise HTTPException(413, "Payload too large")
    if not valid_signature(bytes(payload), signature, settings.WHATSAPP_APP_SECRET):
        raise HTTPException(403, "Invalid signature")
    try:
        event = json.loads(payload)
        messages, statuses = event_counts(event, settings.WHATSAPP_PHONE_NUMBER_ID)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, "Invalid WhatsApp event") from None
    if settings.WHATSAPP_AUTOMATION_ENABLED or settings.WHATSAPP_CUSTOMER_AUTOMATION_ENABLED:
        try:
            queued = 0
            if settings.WHATSAPP_AUTOMATION_ENABLED and settings.WHATSAPP_DEMO_ENABLED:
                queued += await receive(event, settings)
            if settings.WHATSAPP_CUSTOMER_AUTOMATION_ENABLED:
                queued += await receive_customer(event, settings)
        except ValueError:
            raise HTTPException(503, "Automation configuration is incomplete") from None
        except (TypeError, AttributeError):
            raise HTTPException(400, "Invalid WhatsApp event") from None
        return {"status": "queued" if queued else "ignored_or_duplicate"}
    # Diagnostic mode discards content and performs no CRM/AI/send actions.
    # Retries may repeat these counts. This is not a delivery ledger or inbox.
    logger.info("WhatsApp demo signed event: messages=%d statuses=%d", messages, statuses)
    return {"status": "diagnostic_only"}
