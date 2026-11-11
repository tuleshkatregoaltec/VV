"""HTTP contract for agent self-service WhatsApp connection and the admin overview."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.dependencies import require_active_subscription, require_admin
from app.postgres import get_db_session
from app.whatsapp import connection_router as routes
from app.whatsapp.customer_models import AdminConnectionList, AgentConnectionStatus, ContactPage


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(routes.admin_router)
    app.dependency_overrides[get_db_session] = lambda: "session"
    app.dependency_overrides[require_active_subscription] = lambda: SimpleNamespace(
        user=SimpleNamespace(id="agent"), organization=SimpleNamespace(id="org")
    )
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id="admin")
    return app, TestClient(app)


AGENT_ENDPOINTS = [
    ("get", "/api/v1/whatsapp/signup/config", None),
    ("post", "/api/v1/whatsapp/signup/complete", None),
    ("get", "/api/v1/whatsapp/connection", None),
    ("patch", "/api/v1/whatsapp/connection/automation", None),
    ("post", "/api/v1/whatsapp/connection/disconnect", None),
    ("get", "/api/v1/whatsapp/connection/contacts", None),
    ("put", "/api/v1/whatsapp/connection/contacts/blocked", None),
    ("post", "/api/v1/whatsapp/connection/contacts/sync", None),
]


@pytest.mark.parametrize("method,path,_", AGENT_ENDPOINTS)
def test_every_agent_operation_requires_a_subscription(api, method, path, _):
    app, client = api

    def denied():
        raise HTTPException(402, "Active subscription required")

    app.dependency_overrides[require_active_subscription] = denied
    assert getattr(client, method)(path).status_code == 402


def test_admin_overview_requires_system_admin(api):
    app, client = api

    def denied():
        raise HTTPException(403, "System admin access required")

    app.dependency_overrides[require_admin] = denied
    assert client.get("/api/v1/admin/whatsapp/connections").status_code == 403


def status(**update):
    return AgentConnectionStatus(
        **{"state": "connected", "signup_configured": True, "connection_id": "c", **update}
    )


def test_signup_config_returns_public_values_and_a_bound_state(api, monkeypatch):
    _, client = api
    issued = []

    def signup_state(user_id, organization_id, config):
        issued.append((user_id, organization_id))
        return "123.sig"

    monkeypatch.setattr(routes.connections, "signup_state", signup_state)
    for name, value in {
        "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": True,
        "WHATSAPP_APP_ID": "1723271579129715",
        "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID": "555",
        "WHATSAPP_APP_SECRET": "app-secret",
        "WHATSAPP_GRAPH_API_VERSION": "v25.0",
        "WHATSAPP_TOKEN_ENCRYPTION_KEY": None,
        "ENVIRONMENT": "local",
    }.items():
        monkeypatch.setattr(routes.settings, name, value)
    body = client.get("/api/v1/whatsapp/signup/config").json()
    assert body["configured"] is True and body["state"] == "123.sig"
    assert body["app_id"] == "1723271579129715" and body["config_id"] == "555"
    assert "app-secret" not in str(body)
    assert issued == [("agent", "org")]

    monkeypatch.setattr(routes.settings, "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID", None)
    body = client.get("/api/v1/whatsapp/signup/config").json()
    assert body["configured"] is False and body["state"] is None
    assert body["missing"] == ["WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID"]


def test_complete_uses_the_session_identity_not_the_body(api, monkeypatch):
    _, client = api
    connect = AsyncMock(return_value=status())
    monkeypatch.setattr(routes.connections, "connect", connect)
    response = client.post(
        "/api/v1/whatsapp/signup/complete",
        json={
            "state": "s",
            "code": "c",
            "phone_number_id": "2002",
            "waba_id": "1001",
            "business_id": "3003",
            "event": "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
        },
    )
    assert response.status_code == 200
    kwargs = connect.await_args.kwargs
    assert (kwargs["user_id"], kwargs["organization_id"]) == ("agent", "org")
    assert kwargs["request"].waba_id == "1001"
    rejected = client.post(
        "/api/v1/whatsapp/signup/complete",
        json={"state": "s", "code": "c", "waba_id": "1001", "event": "CANCEL"},
    )
    assert rejected.status_code == 422


def test_status_toggle_disconnect_and_contacts_sync(api, monkeypatch):
    _, client = api
    for name in ("agent_status", "set_automation", "disconnect_agent", "retry_contacts_sync"):
        monkeypatch.setattr(routes.connections, name, AsyncMock(return_value=status()))
    assert client.get("/api/v1/whatsapp/connection").json()["state"] == "connected"
    assert (
        client.patch("/api/v1/whatsapp/connection/automation", json={"enabled": True}).status_code
        == 200
    )
    assert routes.connections.set_automation.await_args.kwargs["enabled"] is True
    assert client.patch("/api/v1/whatsapp/connection/automation", json={}).status_code == 422
    assert client.post("/api/v1/whatsapp/connection/disconnect").status_code == 200
    assert client.post("/api/v1/whatsapp/connection/contacts/sync").status_code == 200


def test_contacts_listing_and_bulk_block(api, monkeypatch):
    _, client = api
    page = AsyncMock(return_value=ContactPage(items=[], total=0, limit=25, offset=50))
    monkeypatch.setattr(routes.connections, "list_agent_contacts", page)
    response = client.get(
        "/api/v1/whatsapp/connection/contacts",
        params={"search": "sara", "blocked": "true", "limit": 25, "offset": 50},
    )
    assert response.status_code == 200
    assert page.await_args.kwargs | {"db": None} == {
        "db": None,
        "user_id": "agent",
        "organization_id": "org",
        "search": "sara",
        "blocked": True,
        "limit": 25,
        "offset": 50,
    }
    assert (
        client.get("/api/v1/whatsapp/connection/contacts", params={"limit": 501}).status_code == 422
    )
    block = AsyncMock(return_value={"updated": 2, "blocked_total": 2})
    monkeypatch.setattr(routes.connections, "block_contacts", block)
    response = client.put(
        "/api/v1/whatsapp/connection/contacts/blocked",
        json={"contact_ids": ["a", "b"], "blocked": True},
    )
    assert response.json() == {"updated": 2, "blocked_total": 2}
    assert (
        client.put(
            "/api/v1/whatsapp/connection/contacts/blocked", json={"blocked": True}
        ).status_code
        == 422
    )


def test_admin_overview_lists_agents(api, monkeypatch):
    _, client = api
    listing = AsyncMock(
        return_value=AdminConnectionList(total=0, connected=0, automation_on=0, items=[])
    )
    monkeypatch.setattr(routes.connections, "admin_connections", listing)
    assert client.get("/api/v1/admin/whatsapp/connections").json()["total"] == 0
    listing.assert_awaited_once()
