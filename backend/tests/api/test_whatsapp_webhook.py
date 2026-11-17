import hashlib
import hmac
import json
import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.whatsapp import router as webhook
from app.whatsapp.logging import CallbackQueryFilter


@pytest.fixture
async def webhook_client(monkeypatch):
    monkeypatch.setattr(webhook.settings, "WHATSAPP_DEMO_ENABLED", True)
    monkeypatch.setattr(webhook.settings, "WHATSAPP_AUTOMATION_ENABLED", False)
    monkeypatch.setattr(webhook.settings, "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED", False)
    monkeypatch.setattr(webhook.settings, "WHATSAPP_VERIFY_TOKEN", "test-verify-token")
    monkeypatch.setattr(webhook.settings, "WHATSAPP_APP_SECRET", "test-app-secret")
    monkeypatch.setattr(webhook.settings, "WHATSAPP_PHONE_NUMBER_ID", "123")
    app = FastAPI()
    app.include_router(webhook.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def signed(payload: bytes) -> dict[str, str]:
    digest = hmac.new(b"test-app-secret", payload, hashlib.sha256).hexdigest()
    return {"x-hub-signature-256": "sha256=" + digest}


async def test_meta_can_verify_endpoint_but_wrong_token_cannot(webhook_client):
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "test-verify-token",
        "hub.challenge": "42",
    }
    response = await webhook_client.get("/api/v1/webhooks/whatsapp", params=params)
    assert response.status_code == 200
    assert response.text == "42"
    assert response.headers["content-type"].startswith("text/plain")
    params["hub.verify_token"] = "wrong"
    assert (await webhook_client.get("/api/v1/webhooks/whatsapp", params=params)).status_code == 403


async def test_missing_credentials_fail_closed(webhook_client, monkeypatch):
    monkeypatch.setattr(webhook.settings, "WHATSAPP_APP_SECRET", None)
    assert (await webhook_client.post("/api/v1/webhooks/whatsapp", json={})).status_code == 503
    monkeypatch.setattr(webhook.settings, "WHATSAPP_DEMO_ENABLED", False)
    assert (await webhook_client.get("/api/v1/webhooks/whatsapp")).status_code == 404


async def test_tampered_payload_is_rejected(webhook_client):
    original = b'{"object":"whatsapp_business_account"}'
    response = await webhook_client.post(
        "/api/v1/webhooks/whatsapp", content=original + b" ", headers=signed(original)
    )
    assert response.status_code == 403
    assert (
        await webhook_client.post("/api/v1/webhooks/whatsapp", content=original)
    ).status_code == 403


async def test_verified_diagnostic_discards_content_and_scopes_counts(webhook_client, caplog):
    values = [
        {"metadata": {"phone_number_id": "123"}, "messages": [{"text": {"body": "PRIVATE"}}]},
        {"metadata": {"phone_number_id": "other"}, "messages": [{}, {}]},
        {"metadata": {"phone_number_id": "123"}, "statuses": [{"status": "delivered"}]},
    ]
    payload = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": value} for value in values]}],
        }
    ).encode()
    with caplog.at_level(logging.INFO, logger="app.whatsapp.router"):
        response = await webhook_client.post(
            "/api/v1/webhooks/whatsapp", content=payload, headers=signed(payload)
        )
    assert response.status_code == 200
    assert response.json() == {"status": "diagnostic_only"}
    assert "messages=1 statuses=1" in caplog.text
    assert "PRIVATE" not in caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        b"invalid",
        b"[]",
        b'{"object":"wrong"}',
        b'{"object":"whatsapp_business_account","entry":null}',
    ],
)
async def test_malformed_signed_payloads_are_rejected(webhook_client, payload):
    response = await webhook_client.post(
        "/api/v1/webhooks/whatsapp", content=payload, headers=signed(payload)
    )
    assert response.status_code == 400


async def test_large_payload_is_rejected(webhook_client):
    payload = b"x" * (webhook.MAX_BODY_BYTES + 1)
    response = await webhook_client.post(
        "/api/v1/webhooks/whatsapp", content=payload, headers=signed(payload)
    )
    assert response.status_code == 413


def test_verification_token_is_removed_from_access_logs():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        "%s %s %s %s %s",
        ("client", "GET", "/api/v1/webhooks/whatsapp?hub.verify_token=SECRET", "1.1", 200),
        None,
    )
    assert CallbackQueryFilter().filter(record)
    assert "SECRET" not in record.getMessage()


async def test_customer_only_signed_webhook_does_not_enable_private_pilot(
    webhook_client, monkeypatch
):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(webhook.settings, "WHATSAPP_DEMO_ENABLED", False)
    monkeypatch.setattr(webhook.settings, "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED", True)
    monkeypatch.setattr(webhook.settings, "WHATSAPP_PHONE_NUMBER_ID", None)
    monkeypatch.setattr(webhook.settings, "WHATSAPP_CUSTOMER_PHONE_NUMBER_ID", "customer")
    customer = AsyncMock(return_value=1)
    private = AsyncMock()
    monkeypatch.setattr(webhook, "receive_customer", customer)
    monkeypatch.setattr(webhook, "receive", private)
    payload = b'{"object":"whatsapp_business_account","entry":[]}'
    response = await webhook_client.post(
        "/api/v1/webhooks/whatsapp", content=payload, headers=signed(payload)
    )
    assert response.status_code == 200
    assert response.json() == {"status": "queued"}
    customer.assert_awaited_once()
    private.assert_not_called()
    response = await webhook_client.post(
        "/api/v1/webhooks/whatsapp", content=payload + b" ", headers=signed(payload)
    )
    assert response.status_code == 403
    assert customer.await_count == 1


async def test_both_enabled_channels_receive_the_verified_event(webhook_client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(webhook.settings, "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED", True)
    monkeypatch.setattr(webhook.settings, "WHATSAPP_AUTOMATION_ENABLED", True)
    customer, private = AsyncMock(return_value=0), AsyncMock(return_value=1)
    monkeypatch.setattr(webhook, "receive_customer", customer)
    monkeypatch.setattr(webhook, "receive", private)
    payload = b'{"object":"whatsapp_business_account","entry":[]}'
    response = await webhook_client.post(
        "/api/v1/webhooks/whatsapp", content=payload, headers=signed(payload)
    )
    assert response.status_code == 200
    customer.assert_awaited_once()
    private.assert_awaited_once()
