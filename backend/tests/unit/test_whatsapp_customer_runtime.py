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


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sender": "919111111111"},
        {"account": "wrong"},
        {"phone": "wrong"},
        {"age": 25},
        {"age": -1},
        {"body": "x" * 8001},
        {"body": ""},
    ],
)
def test_customer_receipts_cannot_cross_configured_account_number_or_recipient(kwargs):
    assert queue.inbound_messages(event(**kwargs), config()) == []


def test_echo_and_status_events_cannot_queue_customer_work():
    payload = event()
    payload["entry"][0]["changes"][0]["field"] = "smb_message_echoes"
    assert queue.inbound_messages(payload, config()) == []
    payload["entry"][0]["changes"][0]["field"] = "messages"
    payload["entry"][0]["changes"][0]["value"].pop("messages")
    assert queue.inbound_messages(payload, config()) == []


def test_unknown_sender_needs_no_saved_contact_when_test_restriction_is_removed():
    c = config().model_copy(update={"WHATSAPP_CUSTOMER_TEST_RECIPIENT": None})
    incoming = queue.inbound_messages(
        event(body="Looking for a two bedroom apartment in Marina", sender="971501111111"), c
    )
    assert len(incoming) == 1
    assert incoming[0][1] == "971501111111"


def test_explicit_approval_bypasses_pause_but_never_optout_or_connection_disable():
    c = config()
    connection = WhatsAppConnection(
        user_id="user",
        organization_id="org",
        phone_number_id="customer-number",
        account_id="customer-account",
        display_name="Kian",
        enabled=True,
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
    db = AsyncMock()
    monkeypatch.setattr(automation, "get_db_session", db)
    c = config().model_copy(update={"WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": False})
    assert await automation.receive_customer(event(), c) == 0
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
    )
    thread = WhatsAppCustomerThread(connection_id=connection.id, sender="919000000000")
    message = WhatsAppCustomerMessage(
        id="inbound", thread_id=thread.id, sent_at=utcnow(), reply="Approved answer"
    )
    assert await automation.send_reply(connection, thread, message, config()) == "outbound"
    assert captured[0].url.path == "/v25.0/customer-number/messages"
    assert captured[0].headers["authorization"] == "Bearer customer-token"
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
