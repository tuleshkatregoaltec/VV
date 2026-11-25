from app.core.dependencies import require_token_quota


async def test_chat_identity_is_resolved_from_auth_not_request_fields(client, monkeypatch):
    from app.main import app

    captured = {}

    async def stream(**kwargs):
        captured.update(kwargs)
        yield 'data: {"type": "done"}\n\n'

    monkeypatch.setattr("app.crm.assistant.router.stream_chat_response", stream)
    app.dependency_overrides[require_token_quota] = lambda: None
    response = await client.post(
        "/api/v1/chat/conversations/7/messages/stream",
        json={
            "message": "Show my CRM leads",
            "user_id": "colleague",
            "organization_id": "another-org",
            "role": "owner",
        },
    )
    assert response.status_code == 200
    assert captured["user_id"] == "test-user-id"
    assert captured["organization_id"] == 1
    assert captured["user_message"] == "Show my CRM leads"


async def test_crm_chat_stream_requires_authentication(client_no_auth):
    response = await client_no_auth.post(
        "/api/v1/chat/conversations/7/messages/stream", json={"message": "Show CRM"}
    )
    assert response.status_code in {401, 403}


async def test_http_stream_close_awaits_provider_cleanup_before_releasing_session(monkeypatch):
    import asyncio

    from conftest import make_mock_auth_context

    from app.crm.assistant import router

    closed = asyncio.Event()

    async def stream(**kwargs):
        try:
            yield 'data: {"type": "thinking"}\n\n'
            await asyncio.Event().wait()
        finally:
            closed.set()

    monkeypatch.setattr(router, "stream_chat_response", stream)
    response = await router.send_message(
        7,
        router.SendMessageRequest(message="Show my leads"),
        context=make_mock_auth_context(),
        db=None,
        _=None,
    )
    assert await anext(response.body_iterator) == 'data: {"type": "thinking"}\n\n'
    await response.body_iterator.aclose()
    assert closed.is_set()
