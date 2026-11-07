import logging
import time
from typing import Optional

from supabase_auth import AdminUserAttributes, AsyncGoTrueClient
from supabase_auth import User as AuthUser
from supabase_auth.errors import AuthApiError

from app.config import settings
from app.core.cache import RedisCache
from app.providers.auth import AuthenticatedUser
from app.providers.auth.user_cache import AuthUserCache

logger = logging.getLogger(__name__)

auth_base_url = str(settings.AUTH_URL).rstrip("/")


def build_public_auth_client(base_url: str, publishable_key: Optional[str]) -> AsyncGoTrueClient:
    """Client for user-scoped auth calls; sends `apikey` only when a publishable key is set."""
    headers = {"apikey": publishable_key} if publishable_key else None
    return AsyncGoTrueClient(url=base_url, headers=headers)


auth_client = build_public_auth_client(auth_base_url, settings.AUTH_PUBLISHABLE_KEY)

_admin_headers = {
    "Authorization": f"Bearer {settings.AUTH_SERVICE_ROLE_KEY}",
    "apikey": settings.AUTH_SERVICE_ROLE_KEY,
}
admin_client = AsyncGoTrueClient(url=auth_base_url, headers=_admin_headers)
admin_client.admin._headers.update(_admin_headers)


# Shared across worker processes through Redis; see user_cache.py for the rules and staleness.
# Signing out does not evict a token: it stays accepted for up to the cache TTL (60 s).
_user_cache = AuthUserCache(RedisCache(settings.REDIS_URL, settings.REDIS_PASSWORD).redis)


async def get_auth_user(jwt: str) -> Optional[AuthUser]:
    """Get the Supabase auth user object for the given jwt, if valid (cached briefly)."""
    cached = await _user_cache.get(jwt)
    if cached is not None:
        return cached
    started_at = time.time()
    try:
        user_response = await auth_client.get_user(jwt=jwt)
        if user_response and user_response.user:
            await _user_cache.put(jwt, user_response.user, started_at=started_at)
            return user_response.user
    except AuthApiError:
        return None
    except Exception:
        logger.warning("Auth service unreachable")
        return None
    return None


async def update_user_token_limit(user_id: str, daily_token_limit: int) -> None:
    """Update user's daily token limit in app_metadata."""
    try:
        user_response = await admin_client.admin.get_user_by_id(user_id)
        current_app_metadata = user_response.user.app_metadata or {}
        current_app_metadata["daily_token_limit"] = daily_token_limit

        update_request = AdminUserAttributes()
        update_request["app_metadata"] = current_app_metadata

        await admin_client.admin.update_user_by_id(user_id, update_request)
    except (ValueError, AuthApiError) as e:
        logger.error(f"Failed to update token limit for user {user_id}: {e}")
        raise
    finally:
        await _user_cache.invalidate_user(user_id)


async def update_user_profile_metadata(user_id: str, first_name: str, last_name: str) -> None:
    """Update user profile metadata (first_name, last_name) via admin."""
    try:
        user_response = await admin_client.admin.get_user_by_id(user_id)
        current_user_metadata = user_response.user.user_metadata or {}
        current_user_metadata["first_name"] = first_name
        current_user_metadata["last_name"] = last_name

        update_request = AdminUserAttributes()
        update_request["user_metadata"] = current_user_metadata
        await admin_client.admin.update_user_by_id(user_id, update_request)
    except (ValueError, AuthApiError) as e:
        logger.error(f"Failed to update profile for user {user_id}: {e}")
        raise
    finally:
        await _user_cache.invalidate_user(user_id)


async def get_user_by_id(user_id: str) -> Optional[AuthenticatedUser]:
    try:
        user_response = await admin_client.admin.get_user_by_id(user_id)
        return AuthenticatedUser(None, user_response.user)
    except (ValueError, AuthApiError):
        return None


async def create_user_admin(
    email: str, password: str, first_name: str, last_name: str
) -> Optional[AuthenticatedUser]:
    """Create a Supabase user with email/password (auto-confirmed, no invite email)."""
    attrs = AdminUserAttributes()
    attrs["email"] = email
    attrs["password"] = password
    attrs["email_confirm"] = True
    attrs["user_metadata"] = {"first_name": first_name, "last_name": last_name}
    try:
        user_response = await admin_client.admin.create_user(attrs)
        return AuthenticatedUser(None, user_response.user)
    except (ValueError, AuthApiError) as e:
        logger.error(f"Failed to create user {email}: {e}")
        raise


async def delete_user_admin(user_id: str) -> None:
    """Delete a Supabase user by ID."""
    try:
        await admin_client.admin.delete_user(user_id)
    except (ValueError, AuthApiError) as e:
        logger.error(f"Failed to delete user {user_id}: {e}")
        raise
    finally:
        await _user_cache.invalidate_user(user_id)


async def send_magic_link_email(
    email: str, redirect_url: str, should_create_user: bool = True
) -> dict:
    """Send passwordless auth email for an existing or new user."""
    try:
        await auth_client.sign_in_with_otp(
            {
                "email": email,
                "options": {
                    "email_redirect_to": redirect_url,
                    "should_create_user": should_create_user,
                },
            }
        )
        return {"success": True, "error": None}
    except AuthApiError as e:
        logger.error(f"Failed to send magic link to {email}: {e}")
        return {"success": False, "error": str(e)}
