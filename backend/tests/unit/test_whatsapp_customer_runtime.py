from datetime import timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import settings
from app.whatsapp import customer_automation as automation
from app.whatsapp import customer_queue as queue
from app.whatsapp.customer_models import (
    WhatsAppConnection,
    WhatsAppCustomerMessage,
    WhatsAppCustomerThread,
)
from app.whatsapp.models import utcnow
from app.whatsapp.token_crypto import encrypt_token


def config():
    return settings.model_copy(
        update={
            "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": True,
            "WHATSAPP_CUSTOMER_PHONE_NUMBER_ID": "customer-number",
            "WHATSAPP_CUSTOMER_ACCOUNT_ID": "customer-account",
            "WHATSAPP_CUSTOMER_ACCESS_TOKEN": "customer-token",
            "WHATSAPP_CUSTOMER_TEST_RECIPIENT": "919000000000",
            "WHATSAPP_APP_SECRET": "secret",
            "WHATSAPP_GRAPH_API_VERSION": "v25.0",
            "WHATSAPP_PILOT_USER_ID": "user",
            "WHATSAPP_PILOT_ORGANIZATION_ID": "org",
            "WHATSAPP_ACCESS_TOKEN": "private-pilot-token",
        }
    )


def event(
    body="What is the property price?",
    *,
    sender="919000000000",
    account="customer-account",
    phone="customer-number",
    age=0,
):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": account,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": phone},
                            "messages": [
                                {
                                    "id": "wamid.customer",
                                    "from": sender,
                                    "type": "text",
                                    "text": {"body": body},
                                    "timestamp": str(
                                        int((utcnow() - timedelta(hours=age)).timestamp())
                                    ),
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def first_message(payload):
    return payload["entry"][0]["changes"][0]["value"]["messages"][0]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"age": 25},
        {"age": -1},
        {"body": "x" * 8001},
        {"body": ""},
    ],
)
def test_customer_receipts_are_bounded_in_time_and_size(kwargs):
    assert queue.inbound_text(first_message(event(**kwargs)), utcnow()) is None


def test_pilot_test_recipient_applies_only_to_the_env_pilot_number():
    pilot = WhatsAppConnection(
        user_id="user",
        organization_id="org",
        phone_number_id="customer-number",
        account_id="customer-account",
        display_name="Kian",
    )
    other = pilot.model_copy(update={"phone_number_id": "other-agent-number"})
    assert queue.pilot_recipient(pilot, config()) == "919000000000"
    assert queue.pilot_recipient(other, config()) is None


def test_echo_and_status_events_cannot_queue_customer_work():
    from app.whatsapp import customer_intake as intake

    payload = event()
    payload["entry"][0]["changes"][0]["field"] = "smb_message_echoes"
    assert [field for _, field, _ in intake.parse(payload)] == ["smb_message_echoes"]
    payload["entry"][0]["changes"][0]["field"] = "statuses"
    assert intake.parse(payload) == []


def test_unknown_sender_needs_no_saved_contact_when_test_restriction_is_removed():
    raw = first_message(
        event(body="Looking for a two bedroom apartment in Marina", sender="971501111111")
    )
    assert queue.sender_identity(raw) == ("971501111111", None)
    assert queue.inbound_text(raw, utcnow())[1] == "Looking for a two bedroom apartment in Marina"


def test_explicit_approval_bypasses_pause_but_never_optout_or_connection_disable():
    c = config()
    connection = WhatsAppConnection(
        user_id="user",
        organization_id="org",
        phone_number_id="customer-number",
        account_id="customer-account",
        display_name="Kian",
        enabled=True,
        access_token_encrypted="ciphertext",
    )
    thread = WhatsAppCustomerThread(connection_id=connection.id, sender="919000000000", paused=True)
    assert not queue.bound(connection, thread, c)
    assert queue.bound(connection, thread, c, allow_paused=True)
    thread.opted_out = True
    assert not queue.bound(connection, thread, c, allow_paused=True)
    thread.opted_out = False
    connection.enabled = False
    assert not queue.bound(connection, thread, c, allow_paused=True)


async def test_disabled_customer_receives_nothing_without_a_database(monkeypatch):
    from app.whatsapp import customer_intake as intake

    db = AsyncMock()
    monkeypatch.setattr(automation, "get_db_session", db)
    monkeypatch.setattr(intake, "get_db_session", db)
    c = config().model_copy(update={"WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": False})
    assert await intake.receive_customer(event(), c) == 0
    assert await automation.run_customer_once(c) is False
    db.assert_not_called()


async def test_customer_send_uses_real_number_token_and_context(monkeypatch):
    captured = []

    def respond(request):
        captured.append(request)
        return httpx.Response(200, json={"messages": [{"id": "outbound"}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        automation.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    connection = WhatsAppConnection(
        user_id="user",
        organization_id="org",
        phone_number_id="customer-number",
        account_id="customer-account",
        display_name="Business",
        access_token_encrypted=encrypt_token("per-agent-token", config()),
    )
    thread = WhatsAppCustomerThread(connection_id=connection.id, sender="919000000000")
    message = WhatsAppCustomerMessage(
        id="inbound", thread_id=thread.id, sent_at=utcnow(), reply="Approved answer"
    )
    assert await automation.send_reply(connection, thread, message, config()) == "outbound"
    assert captured[0].url.path == "/v25.0/customer-number/messages"
    # The connection's own decrypted token, never the global env token.
    assert captured[0].headers["authorization"] == "Bearer per-agent-token"
    assert b'"message_id":"inbound"' in captured[0].content


def test_meta_rejection_keeps_numeric_codes_without_private_upstream_payload():
    error = automation.MetaSendRejected(
        httpx.Response(
            400,
            json={
                "error": {
                    "code": 131042,
                    "error_subcode": 7,
                    "message": "PRIVATE",
                    "error_data": {"details": "SECRET"},
                }
            },
        )
    )
    assert error.error_code == "meta_131042_7"
    assert str(error) == "meta_131042_7"
    error = automation.MetaSendRejected(httpx.Response(400, text="PRIVATE"))
    assert str(error) == "meta_http_400"
