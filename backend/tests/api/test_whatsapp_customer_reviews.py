from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.dependencies import require_active_subscription
from app.postgres import get_db_session
from app.whatsapp import customer_router as routes
from app.whatsapp.customer_models import WhatsAppCustomerMessage
from app.whatsapp.customer_service import message_response
from app.whatsapp.models import utcnow


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_db_session] = lambda: "session"
    app.dependency_overrides[require_active_subscription] = lambda: SimpleNamespace(
        user=SimpleNamespace(id="owner"), organization=SimpleNamespace(id="org")
    )
    return app, TestClient(app)


ENDPOINTS = [
    ("get", "/connections"),
    ("post", "/connections"),
    ("get", "/connections/c"),
    ("patch", "/connections/c"),
    ("delete", "/connections/c"),
    ("put", "/connections/c/knowledge"),
    ("get", "/connections/c/threads"),
    ("get", "/connections/c/listings"),
    ("post", "/connections/c/listings"),
    ("put", "/connections/c/listings/l"),
    ("post", "/connections/c/listings/l/revoke"),
    ("post", "/threads/t/takeover"),
    ("post", "/threads/t/resume"),
    ("get", "/threads/t/messages"),
    ("get", "/notifications"),
    ("post", "/notifications/m/seen"),
    ("post", "/messages/m/approve"),
    ("post", "/messages/m/cancel"),
    ("patch", "/messages/m"),
]


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_whatsapp_customer_every_operation_requires_subscription(api, method, path):
    app, client = api

    def denied():
        raise HTTPException(402, "Active subscription required")

    app.dependency_overrides[require_active_subscription] = denied
    assert getattr(client, method)("/api/v1/whatsapp" + path).status_code == 402


@pytest.mark.parametrize(
    "body", [{}, {"expected_revision": 0}, {"expected_revision": 1, "user_id": "forged"}]
)
def test_whatsapp_customer_decisions_require_revision_and_reject_forged_owner(api, body):
    _, client = api
    assert client.post("/api/v1/whatsapp/messages/m/approve", json=body).status_code == 422


def test_whatsapp_customer_notification_scope_comes_from_session(api, monkeypatch):
    _, client = api
    handler = AsyncMock(return_value=[])
    monkeypatch.setattr(routes.service, "list_notifications", handler)
    assert client.get("/api/v1/whatsapp/notifications?user_id=forged").status_code == 200
    assert handler.call_args.kwargs == dict(
        user_id="owner", organization_id="org", limit=100, offset=0
    )
    assert client.get("/api/v1/whatsapp/notifications?limit=101").status_code == 422


@pytest.mark.parametrize(
    "facts",
    [
        [{"id": "a", "text": "one"}, {"id": "a", "text": "two"}],
        [{"id": "a", "text": "x" * 1001}],
        [{"id": str(index), "text": "fact"} for index in range(21)],
    ],
)
def test_whatsapp_customer_knowledge_is_bounded_and_unambiguous(api, facts):
    _, client = api
    assert (
        client.put(
            "/api/v1/whatsapp/connections/c/knowledge", json={"approved_knowledge": facts}
        ).status_code
        == 422
    )


def test_whatsapp_customer_ignored_history_redacts_source_and_generated_text():
    message = WhatsAppCustomerMessage(
        id="m",
        thread_id="t",
        content="PRIVATE",
        sent_at=utcnow(),
        status="ignored",
        reply="PRIVATE REPLY",
        reason="PRIVATE REASON",
        evidence_ids=["private"],
    )
    response = message_response(message).model_dump_json()
    assert "PRIVATE" not in response
    assert '"content":null' in response
    assert '"evidence_ids":[]' in response


@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("post", "/approve", {"expected_revision": 1}),
        ("post", "/cancel", {"expected_revision": 1}),
        ("patch", "", {"expected_revision": 1, "reply": "Reviewed reply"}),
    ],
)
def test_whatsapp_customer_meta_ids_with_encoded_slashes_are_reviewable(
    api, monkeypatch, method, suffix, body
):
    _, client = api
    message = WhatsAppCustomerMessage(
        id="wamid.A/B+C=",
        thread_id="thread",
        sent_at=utcnow(),
        status="approval_required",
        reply="Reviewed reply",
    )
    handler = AsyncMock(return_value=message_response(message))
    monkeypatch.setattr(routes.service, "decide", handler)
    response = getattr(client, method)(
        "/api/v1/whatsapp/messages/wamid.A%2FB%2BC%3D" + suffix,
        json=body,
    )
    assert response.status_code == 200
    assert handler.call_args.kwargs["message_id"] == "wamid.A/B+C="
    assert handler.call_args.kwargs["user_id"] == "owner"
    assert handler.call_args.kwargs["request"].expected_revision == 1


def test_whatsapp_customer_notification_ids_with_encoded_slashes_are_reviewable(api, monkeypatch):
    _, client = api
    message = WhatsAppCustomerMessage(
        id="wamid.A/B+C=",
        thread_id="thread",
        sent_at=utcnow(),
        status="approval_required",
    )
    handler = AsyncMock(return_value=message_response(message))
    monkeypatch.setattr(routes.service, "mark_seen", handler)
    response = client.post(
        "/api/v1/whatsapp/notifications/wamid.A%2FB%2BC%3D/seen",
        json={"expected_revision": 1},
    )
    assert response.status_code == 200
    assert handler.call_args.kwargs["message_id"] == "wamid.A/B+C="


def publication_payload():
    from datetime import timedelta

    return dict(
        title="Approved apartment",
        location="Dubai Marina",
        property_type="apartment",
        transaction="rent",
        price_aed=150000,
        availability="available",
        expires_at=(utcnow() + timedelta(hours=1)).isoformat(),
        approved_for_customer=True,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"approved_for_customer": 1},
        {"approved_for_customer": False},
        {"user_id": "forged"},
        {"owner_phone": "+971500000000"},
        {"expires_at": None},
    ],
)
def test_publication_api_rejects_implicit_approval_private_fields_and_missing_expiry(api, change):
    _, client = api
    assert (
        client.post(
            "/api/v1/whatsapp/connections/c/listings", json=publication_payload() | change
        ).status_code
        == 422
    )


def test_publication_api_uses_authenticated_scope_and_safe_response(api, monkeypatch):
    from app.whatsapp.customer_models import WhatsAppPublishedListing

    _, client = api
    row = WhatsAppPublishedListing(connection_id="c", **publication_payload())
    handler = AsyncMock(return_value=row)
    monkeypatch.setattr(routes.service, "publish_listing", handler)
    response = client.post("/api/v1/whatsapp/connections/c/listings", json=publication_payload())
    assert response.status_code == 201
    assert handler.call_args.kwargs["user_id"] == "owner"
    assert handler.call_args.kwargs["organization_id"] == "org"
    assert response.json()["revision"] == 1
    assert "user_id" not in response.json() and "approved_for_customer" not in response.json()
    assert (
        client.put(
            "/api/v1/whatsapp/connections/c/listings/l", json=publication_payload()
        ).status_code
        == 422
    )
    assert (
        client.post("/api/v1/whatsapp/connections/c/listings/l/revoke", json={}).status_code == 422
    )
