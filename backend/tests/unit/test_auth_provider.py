from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.providers.auth import client


async def test_token_limit_update_preserves_other_app_metadata(monkeypatch):
    admin = SimpleNamespace(
        get_user_by_id=AsyncMock(
            return_value=SimpleNamespace(
                user=SimpleNamespace(app_metadata={"is_admin": True, "provider": "email"})
            )
        ),
        update_user_by_id=AsyncMock(),
    )
    monkeypatch.setattr(client, "admin_client", SimpleNamespace(admin=admin))
    await client.update_user_token_limit("user-1", 1234)
    admin.update_user_by_id.assert_awaited_once_with(
        "user-1",
        {"app_metadata": {"is_admin": True, "provider": "email", "daily_token_limit": 1234}},
    )


async def test_magic_link_preserves_redirect_and_creation_flag(monkeypatch):
    auth = SimpleNamespace(sign_in_with_otp=AsyncMock())
    monkeypatch.setattr(client, "auth_client", auth)
    result = await client.send_magic_link_email(
        "invitee@example.com", "https://example.com/invite?token=one", False
    )
    assert result == {"success": True, "error": None}
    auth.sign_in_with_otp.assert_awaited_once_with(
        {
            "email": "invitee@example.com",
            "options": {
                "email_redirect_to": "https://example.com/invite?token=one",
                "should_create_user": False,
            },
        }
    )


async def test_admin_lookup_preserves_revocation_fields_discarded_by_sdk(monkeypatch):
    from datetime import datetime, timezone

    import httpx

    payload = {
        "id": "user-1",
        "aud": "authenticated",
        "app_metadata": {},
        "user_metadata": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "banned_until": "2099-01-01T00:00:00Z",
    }
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    monkeypatch.setattr(
        client.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs)
    )
    user = await client.get_user_by_id("user-1")
    assert not user.is_authenticated
    payload["banned_until"] = "2020-01-01T00:00:00Z"
    assert (await client.get_user_by_id("user-1")).is_authenticated
    payload["deleted_at"] = "2026-01-01T00:00:00Z"
    assert not (await client.get_user_by_id("user-1")).is_authenticated
    payload["banned_until"] = "malformed"
    assert await client.get_user_by_id("user-1") is None
