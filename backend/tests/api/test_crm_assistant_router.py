from unittest.mock import AsyncMock

from app.core.dependencies import require_token_quota
from app.crm.assistant.models import AssistantActionResult


async def test_confirm_requires_auth(client_no_auth):
    response = await client_no_auth.post("/api/v1/crm/assistant/actions/abc/confirm")
    assert response.status_code == 401


async def test_confirm_uses_auth_context_ids(client, monkeypatch):
    """The scope is the signed-in user's; an organisation in the body is ignored."""
    service = AsyncMock(
        return_value=AssistantActionResult(action_id="abc", status="confirmed", lead_id=7)
    )
    monkeypatch.setattr("app.crm.assistant.router.confirm_action", service)

    response = await client.post(
        "/api/v1/crm/assistant/actions/abc/confirm",
        json={"organization_id": "someone-elses-org", "user_id": "someone-else"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
    deps = service.await_args.args[0]
    assert (deps.user_id, deps.organization_id) == ("test-user-id", "1")
    assert service.await_args.kwargs["action_id"] == "abc"


async def test_cancel_uses_auth_context_ids(client, monkeypatch):
    service = AsyncMock(
        return_value=AssistantActionResult(action_id="abc", status="cancelled", lead_id=7)
    )
    monkeypatch.setattr("app.crm.assistant.router.cancel_action", service)

    response = await client.post("/api/v1/crm/assistant/actions/abc/cancel")

    assert response.status_code == 200
    deps = service.await_args.args[0]
    assert (deps.user_id, deps.organization_id) == ("test-user-id", "1")


async def test_conversation_list_is_scoped_to_the_signed_in_user(client, monkeypatch):
    service = AsyncMock(return_value=[])
    monkeypatch.setattr("app.crm.assistant.router.list_conversations", service)

    response = await client.get("/api/v1/crm/assistant/conversations")

    assert response.status_code == 200
    assert response.json() == {"conversations": [], "total": 0}
    assert service.await_args.args[1:3] == ("test-user-id", "1")


async def test_messages_of_someone_elses_conversation_are_not_found(client, monkeypatch):
    monkeypatch.setattr("app.crm.assistant.router.get_conversation", AsyncMock(return_value=None))
    response = await client.get("/api/v1/crm/assistant/conversations/9/messages")
    assert response.status_code == 404


async def test_stream_passes_auth_scoped_deps(client, monkeypatch):
    seen = {}

    async def fake_stream(db, *, conversation_id, user_message, deps):
        seen.update(conversation_id=conversation_id, deps=deps, text=user_message)
        yield 'data: {"type": "done"}\n\n'

    monkeypatch.setattr("app.crm.assistant.router.stream_assistant_response", fake_stream)
    from app.main import app

    # Cleared by the mock_auth fixture after the test.
    app.dependency_overrides[require_token_quota] = lambda: None

    response = await client.post(
        "/api/v1/crm/assistant/conversations/5/messages/stream",
        json={"message": "Leads due today", "organization_id": "someone-elses-org"},
    )

    assert response.status_code == 200
    assert response.text == 'data: {"type": "done"}\n\n'
    assert seen["conversation_id"] == 5 and seen["text"] == "Leads due today"
    assert (seen["deps"].user_id, seen["deps"].organization_id) == ("test-user-id", "1")
