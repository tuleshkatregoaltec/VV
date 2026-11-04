import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import pytest
from conftest import get_app, make_mock_auth_context

from app.core.dependencies import require_active_owner
from app.crm.whatsapp import meta
from app.crm.whatsapp.models import (
    WhatsAppCampaignCounts,
    WhatsAppCampaignDetail,
    WhatsAppThreadResponse,
)
from app.postgres import get_db_session

WEBHOOK = "/api/v1/crm/whatsapp/webhook"


@pytest.fixture
def webhook_secrets(monkeypatch):
    monkeypatch.setattr(meta.settings, "WHATSAPP_APP_SECRET", "app-secret")
    monkeypatch.setattr(meta.settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", "verify-me")


@pytest.fixture
def no_db():
    async def override():
        yield None

    app = get_app()
    app.dependency_overrides[get_db_session] = override
    yield
    app.dependency_overrides.pop(get_db_session, None)


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()


async def test_meta_can_register_the_webhook_with_our_verify_token(client_no_auth, webhook_secrets):
    response = await client_no_auth.get(
        WEBHOOK,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-me",
            "hub.challenge": "1158201444",
        },
    )
    assert response.status_code == 200
    # Meta expects the challenge echoed back as the plain body.
    assert response.text == "1158201444"


async def test_webhook_registration_is_refused_with_a_wrong_token(client_no_auth, webhook_secrets):
    response = await client_no_auth.get(
        WEBHOOK, params={"hub.mode": "subscribe", "hub.verify_token": "guess", "hub.challenge": "1"}
    )
    assert response.status_code == 403


async def test_an_unsigned_webhook_is_rejected_before_anything_is_stored(
    client_no_auth, webhook_secrets, no_db, monkeypatch
):
    receive = AsyncMock()
    monkeypatch.setattr("app.crm.whatsapp.router.service.receive_webhook", receive)
    body = json.dumps({"entry": []}).encode()

    for headers in ({}, {"x-hub-signature-256": "sha256=" + "0" * 64}):
        response = await client_no_auth.post(WEBHOOK, content=body, headers=headers)
        assert response.status_code == 401
    receive.assert_not_awaited()


async def test_a_signed_webhook_is_processed(client_no_auth, webhook_secrets, no_db, monkeypatch):
    receive = AsyncMock(return_value={"messages": 1, "statuses": 0})
    monkeypatch.setattr("app.crm.whatsapp.router.service.receive_webhook", receive)
    payload = {"entry": [{"changes": []}]}
    body = json.dumps(payload).encode()

    response = await client_no_auth.post(
        WEBHOOK, content=body, headers={"x-hub-signature-256": _sign(body)}
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "messages": 1, "statuses": 0}
    assert receive.await_args.args[1] == payload


async def test_chat_routes_need_a_signed_in_subscriber(client_no_auth):
    for method, path in (
        ("get", "/api/v1/crm/whatsapp/chats"),
        ("get", "/api/v1/crm/whatsapp/status"),
        ("post", "/api/v1/crm/whatsapp/leads/1/reply"),
    ):
        response = await getattr(client_no_auth, method)(path)
        assert response.status_code in {401, 403}, path


def test_number_setup_is_for_the_organization_owner_only():
    """Which agent sends from which number is a manager decision; an agent who could reassign
    numbers could send as a colleague."""

    def calls(dependant):
        yield dependant.call
        for sub in dependant.dependencies:
            yield from calls(sub)

    setup = {
        ("GET", "/api/v1/crm/whatsapp/numbers"),
        ("PUT", "/api/v1/crm/whatsapp/numbers/{phone_number_id}"),
        ("GET", "/api/v1/crm/whatsapp/meta/numbers"),
        ("POST", "/api/v1/crm/whatsapp/meta/subscribe"),
        # Promotions from the campaign number are a manager's decision too.
        ("GET", "/api/v1/crm/whatsapp/campaign/audience"),
        ("GET", "/api/v1/crm/whatsapp/campaigns"),
        ("POST", "/api/v1/crm/whatsapp/campaigns"),
        ("GET", "/api/v1/crm/whatsapp/campaigns/{campaign_id}"),
        ("POST", "/api/v1/crm/whatsapp/campaigns/{campaign_id}/resume"),
        ("GET", "/api/v1/crm/whatsapp/campaign/chats"),
        ("GET", "/api/v1/crm/whatsapp/campaign/chats/{wa_id}"),
        ("POST", "/api/v1/crm/whatsapp/campaign/chats/{wa_id}/reply"),
    }
    found = set()
    for route in get_app().routes:
        for method in getattr(route, "methods", None) or ():
            if (method, route.path) in setup:
                found.add((method, route.path))
                assert require_active_owner in set(calls(route.dependant)), route.path
    assert found == setup


async def test_a_chat_is_read_as_the_signed_in_agent(client, no_db, monkeypatch):
    thread = AsyncMock(
        return_value=WhatsAppThreadResponse(
            wa_number="+971501234567", opted_out=False, window_ends_at=None, messages=[]
        )
    )
    monkeypatch.setattr("app.crm.whatsapp.router.service.chat_thread", thread)

    response = await client.get("/api/v1/crm/whatsapp/chats/971501234567")

    assert response.status_code == 200
    # Scoped to the agent: the service only ever reads that agent's own number.
    assert thread.await_args.kwargs["user_id"] == "test-user-id"
    assert thread.await_args.kwargs["organization_id"] == "1"


async def test_a_whatsapp_id_must_be_digits(client, no_db, monkeypatch):
    reply = AsyncMock()
    monkeypatch.setattr("app.crm.whatsapp.router.service.reply_to_chat", reply)

    response = await client.post(
        "/api/v1/crm/whatsapp/chats/+97150abc/reply", json={"body": "Hello"}
    )

    assert response.status_code == 422
    reply.assert_not_awaited()


async def test_an_empty_reply_is_refused(client, no_db, monkeypatch):
    reply = AsyncMock()
    monkeypatch.setattr("app.crm.whatsapp.router.service.reply_to_chat", reply)

    response = await client.post("/api/v1/crm/whatsapp/chats/971501234567/reply", json={"body": ""})

    assert response.status_code == 422
    reply.assert_not_awaited()


@pytest.fixture
def owner(no_db):
    app = get_app()
    app.dependency_overrides[require_active_owner] = lambda: make_mock_auth_context()
    yield
    app.dependency_overrides.pop(require_active_owner, None)


async def test_a_new_campaign_is_saved_first_and_sent_in_the_background(
    client_no_auth, owner, monkeypatch
):
    """The manager gets an answer straight away; sending hundreds of messages must not hold
    the request open."""
    detail = WhatsAppCampaignDetail(
        id=42,
        name="Dubai Marina",
        template_name="new_listing_alert",
        template_language="en",
        status="sending",
        created_at="2026-11-02T10:00:00Z",
        completed_at=None,
        counts=WhatsAppCampaignCounts(total=2, pending=2),
        template_body="Hi {{1}}",
        params=["{first_name}"],
        recipients=[],
    )
    create = AsyncMock(return_value=detail)
    run = AsyncMock()
    monkeypatch.setattr("app.crm.whatsapp.router.campaigns.create_campaign", create)
    monkeypatch.setattr("app.crm.whatsapp.router.campaigns.run_campaign", run)

    response = await client_no_auth.post(
        "/api/v1/crm/whatsapp/campaigns",
        json={
            "name": "Dubai Marina",
            "template_name": "new_listing_alert",
            "language": "en",
            "params": ["{first_name}"],
            "enquiry_ids": [1, 2],
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == 42
    assert create.await_args.kwargs["organization_id"] == "1"
    run.assert_awaited_once_with(42)


async def test_a_campaign_needs_at_least_one_lead(client_no_auth, owner, monkeypatch):
    create = AsyncMock()
    monkeypatch.setattr("app.crm.whatsapp.router.campaigns.create_campaign", create)
    response = await client_no_auth.post(
        "/api/v1/crm/whatsapp/campaigns",
        json={"name": "x", "template_name": "t", "language": "en", "enquiry_ids": []},
    )
    assert response.status_code == 422
    create.assert_not_awaited()
