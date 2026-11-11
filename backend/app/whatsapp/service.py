import hashlib
import hmac
from datetime import date

import httpx

from app.config import Settings


def valid_signature(payload: bytes, signature: str, app_secret: str) -> bool:
    expected = "sha256=" + hmac.new(app_secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.encode())


def event_counts(event: object, phone_number_id: str) -> tuple[int, int]:
    if not isinstance(event, dict) or event.get("object") != "whatsapp_business_account":
        raise ValueError("Invalid WhatsApp event")
    messages = statuses = 0
    for entry in event.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if value.get("metadata", {}).get("phone_number_id") != phone_number_id:
                continue
            inbound, updates = value.get("messages", []), value.get("statuses", [])
            if not isinstance(inbound, list) or not isinstance(updates, list):
                raise ValueError("Invalid WhatsApp event")
            messages += len(inbound)
            statuses += len(updates)
    return messages, statuses


def readiness(config: Settings) -> dict[str, bool]:
    return {
        "enabled": config.WHATSAPP_DEMO_ENABLED,
        "verification_configured": bool(config.WHATSAPP_VERIFY_TOKEN),
        "signature_validation_configured": bool(config.WHATSAPP_APP_SECRET),
        "access_token_configured": bool(config.WHATSAPP_ACCESS_TOKEN),
        "phone_number_configured": bool(config.WHATSAPP_PHONE_NUMBER_ID),
        "test_recipient_configured": bool(config.WHATSAPP_TEST_RECIPIENT),
        "graph_version_configured": bool(config.WHATSAPP_GRAPH_API_VERSION),
        "automation_enabled": config.WHATSAPP_AUTOMATION_ENABLED,
        "pilot_identity_configured": bool(
            config.WHATSAPP_PILOT_USER_ID and config.WHATSAPP_PILOT_ORGANIZATION_ID
        ),
    }


async def send_test_template(config: Settings) -> str:
    status = readiness(config)
    if not all(
        status[key]
        for key in (
            "enabled",
            "access_token_configured",
            "phone_number_configured",
            "test_recipient_configured",
            "graph_version_configured",
        )
    ):
        raise ValueError("WhatsApp demo configuration is incomplete; run the status command.")
    template = {"name": config.WHATSAPP_TEST_TEMPLATE, "language": {"code": "en_US"}}
    if config.WHATSAPP_TEST_TEMPLATE == "jaspers_market_order_confirmation_v1":
        # Meta's sample template uses fictional order details, not CRM records.
        template["components"] = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": "John Doe"},
                    {"type": "text", "text": "123456"},
                    {"type": "text", "text": date.today().strftime("%b %d, %Y")},
                ],
            }
        ]
    url = (
        f"https://graph.facebook.com/{config.WHATSAPP_GRAPH_API_VERSION}/"
        f"{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {config.WHATSAPP_ACCESS_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "to": config.WHATSAPP_TEST_RECIPIENT,
                "type": "template",
                "template": template,
            },
        )
    # Never print upstream bodies/errors, which can contain private identifiers.
    if response.status_code != 200:
        raise ValueError(f"Meta rejected the test request (HTTP {response.status_code}).")
    data = response.json()
    messages = data.get("messages", [])
    if not messages or not isinstance(messages[0].get("id"), str):
        raise ValueError("Meta did not return a message ID.")
    return messages[0]["id"]
