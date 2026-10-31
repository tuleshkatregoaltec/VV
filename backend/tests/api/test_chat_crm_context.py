from app.core.dependencies import require_token_quota


async def test_chat_identity_is_resolved_from_auth_not_request_fields(client, monkeypatch):
    from app.main import app

    captured = {}

    async def stream(**kwargs):
        captured.update(kwargs)
        yield 'data: {"type": "done"}\n\n'

    monkeypatch.setattr("app.chat.router.stream_chat_response", stream)
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
