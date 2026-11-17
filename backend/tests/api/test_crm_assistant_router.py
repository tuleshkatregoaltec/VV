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
    monkeypatch.setattr(
        "app.crm.assistant.router.repository.count_conversations", AsyncMock(return_value=51)
    )

    response = await client.get("/api/v1/crm/assistant/conversations")

    assert response.status_code == 200
    assert response.json() == {"conversations": [], "total": 51}
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


async def test_confirm_passes_an_edited_email(client, monkeypatch):
    service = AsyncMock(
        return_value=AssistantActionResult(action_id="abc", status="confirmed", lead_id=7)
    )
    monkeypatch.setattr("app.crm.assistant.router.confirm_action", service)

    response = await client.post(
        "/api/v1/crm/assistant/actions/abc/confirm",
        json={"edits": {"subject": "New subject", "body": "New message"}},
    )

    assert response.status_code == 200
    edits = service.await_args.kwargs["edits"]
    assert (edits.subject, edits.body) == ("New subject", "New message")


async def test_confirm_refuses_an_empty_edited_email(client, monkeypatch):
    service = AsyncMock()
    monkeypatch.setattr("app.crm.assistant.router.confirm_action", service)
    response = await client.post(
        "/api/v1/crm/assistant/actions/abc/confirm",
        json={"edits": {"subject": " ", "body": "New message"}},
    )
    assert response.status_code == 422
    service.assert_not_awaited()


async def test_transcribe_returns_the_words_and_uses_the_signed_in_user(client, monkeypatch):
    service = AsyncMock(return_value="Move Ahmed to qualified")
    monkeypatch.setattr("app.crm.assistant.router.transcribe", service)
    from app.main import app

    app.dependency_overrides[require_token_quota] = lambda: None

    response = await client.post(
        "/api/v1/crm/assistant/transcribe",
        files={"audio": ("voice.wav", b"RIFF....WAVE", "audio/wav")},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "Move Ahmed to qualified"}
    assert service.await_args.kwargs["user_id"] == "test-user-id"
    assert service.await_args.kwargs["audio"] == b"RIFF....WAVE"


async def test_transcribe_rejects_a_bad_recording(client, monkeypatch):
    from app.crm.assistant.voice import InvalidAudio
    from app.main import app

    monkeypatch.setattr(
        "app.crm.assistant.router.transcribe",
        AsyncMock(side_effect=InvalidAudio("Recording must be WAV audio.")),
    )
    app.dependency_overrides[require_token_quota] = lambda: None

    response = await client.post(
        "/api/v1/crm/assistant/transcribe",
        files={"audio": ("voice.webm", b"not audio", "audio/webm")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Recording must be WAV audio."


async def test_transcribe_provider_failure_does_not_leak_or_log_what_was_said(
    client, monkeypatch, caplog
):
    """Provider errors can quote the audio's words; the agent and the logs get neither."""
    from app.main import app

    monkeypatch.setattr(
        "app.crm.assistant.router.transcribe",
        AsyncMock(side_effect=RuntimeError("provider said: move Ahmed +971501234567")),
    )
    app.dependency_overrides[require_token_quota] = lambda: None

    response = await client.post(
        "/api/v1/crm/assistant/transcribe",
        files={"audio": ("voice.wav", b"RIFF....WAVE", "audio/wav")},
    )

    assert response.status_code == 502
    assert "Ahmed" not in response.text
    assert "Ahmed" not in caplog.text
    assert "+971" not in caplog.text


async def test_transcribe_requires_auth(client_no_auth):
    response = await client_no_auth.post(
        "/api/v1/crm/assistant/transcribe",
        files={"audio": ("voice.wav", b"RIFF....WAVE", "audio/wav")},
    )
    assert response.status_code == 401


async def test_earlier_messages_offset_reaches_the_scoped_service(client, monkeypatch):
    monkeypatch.setattr(
        "app.crm.assistant.router.get_conversation", AsyncMock(return_value=object())
    )
    messages = AsyncMock(return_value=[])
    monkeypatch.setattr("app.crm.assistant.router.get_messages_with_action_status", messages)
    response = await client.get(
        "/api/v1/crm/assistant/conversations/7/messages?limit=200&offset=200"
    )
    assert response.status_code == 200
    assert messages.await_args.args[1:] == (7, "test-user-id", "1", 200, 200)
