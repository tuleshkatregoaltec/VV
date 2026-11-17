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


def test_public_auth_client_sends_apikey_when_publishable_key_is_set():
    public_client = client.build_public_auth_client(
        "https://example.supabase.co/auth/v1", "sb_publishable_DUMMYTEST"
    )
    assert public_client._headers["apikey"] == "sb_publishable_DUMMYTEST"
    assert "Authorization" not in public_client._headers


def test_public_auth_client_sends_no_apikey_when_publishable_key_is_unset():
    for unset in (None, ""):
        public_client = client.build_public_auth_client("https://auth.example.com/auth/v1", unset)
        assert "apikey" not in public_client._headers


def test_module_auth_client_follows_publishable_key_setting():
    # Test env sets no AUTH_PUBLISHABLE_KEY, so the module-level client stays as it is today.
    assert client.settings.AUTH_PUBLISHABLE_KEY is None
    assert "apikey" not in client.auth_client._headers
