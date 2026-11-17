from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.assistant_actions import router as actions
from app.core.dependencies import require_active_subscription
from app.postgres import get_db_session


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(actions.router)
    app.dependency_overrides[get_db_session] = lambda: "session"
    app.dependency_overrides[require_active_subscription] = lambda: SimpleNamespace(
        user=SimpleNamespace(id="trusted-user"), organization=SimpleNamespace(id="trusted-org")
    )
    return app, TestClient(app)


def response():
    now = datetime.now(timezone.utc)
    return dict(
        id="proposal-id",
        kind="create_lead",
        status="awaiting_confirmation",
        title="Create lead",
        preview={"changes": {"full_name": "Test"}},
        created_at=now,
        expires_at=now + timedelta(minutes=15),
        result=None,
    )


def test_action_route_only_accepts_server_actor_and_org(api, monkeypatch):
    _, client = api
    handler = AsyncMock(return_value=response())
    monkeypatch.setattr(actions.service, "propose_action", handler)
    body = dict(
        kind="create_lead",
        conversation_id=1,
        payload={"full_name": "Test"},
        idempotency_key="test-key-123",
    )
    assert (
        client.post(
            "/api/v1/assistant/actions/proposals", json={**body, "user_id": "forged"}
        ).status_code
        == 422
    )
    assert not handler.called
    assert client.post("/api/v1/assistant/actions/proposals", json=body).status_code == 200
    assert handler.call_args.kwargs["user_id"] == "trusted-user"
    assert handler.call_args.kwargs["organization_id"] == "trusted-org"


@pytest.mark.parametrize(
    "verb,path",
    [
        ("post", "/proposals"),
        ("get", "/proposals?conversation_id=1"),
        ("post", "/action/confirm"),
        ("post", "/action/cancel"),
        ("get", "/reminders"),
        ("get", "/viewings"),
        ("get", "/listing-drafts"),
    ],
)
def test_action_routes_require_active_subscription(api, verb, path):
    app, client = api

    def denied():
        raise HTTPException(403, "Subscription required")

    app.dependency_overrides[require_active_subscription] = denied
    assert getattr(client, verb)("/api/v1/assistant/actions" + path).status_code == 403


def test_confirmation_uses_only_persisted_action_and_trusted_context(api, monkeypatch):
    _, client = api
    handler = AsyncMock(return_value=response())
    monkeypatch.setattr(actions.service, "confirm_action", handler)
    result = client.post(
        "/api/v1/assistant/actions/proposal-id/confirm",
        json={"user_id": "forged", "payload": {"full_name": "Changed"}},
    )
    assert result.status_code == 200
    assert handler.call_args.kwargs == dict(
        user_id="trusted-user", organization_id="trusted-org", action_id="proposal-id"
    )
