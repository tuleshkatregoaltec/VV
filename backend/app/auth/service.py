import functools
import logging
from typing import Optional

from supabase_auth import AdminUserAttributes, AsyncGoTrueClient
from supabase_auth import User as AuthUser
from supabase_auth.errors import AuthApiError

from app.config import settings
from app.providers.auth.platform_user import PlatformUser

logger = logging.getLogger(__name__)

auth_client = AsyncGoTrueClient(url=settings.AUTH_URL)
admin_headers = {
    "Authorization": f"Bearer {settings.AUTH_SERVICE_ROLE_KEY}",
    "apikey": settings.AUTH_SERVICE_ROLE_KEY,
}


def get_admin_client() -> AsyncGoTrueClient:
    client = AsyncGoTrueClient(url=settings.AUTH_URL, headers=admin_headers.copy())

    # GoTrue admin helpers use their own header store.
    client.admin._headers.update(admin_headers)

    return client


def with_admin_client():
    """Inject a service-role authenticated admin client into auth admin helpers."""

    def wrapper(func):
        @functools.wraps(func)
        async def wrapped(*args, **kwargs):
            kwargs["client"] = get_admin_client()
            return await func(*args, **kwargs)

        return wrapped

    return wrapper


async def get_auth_user(jwt: str) -> Optional[AuthUser]:
    """
    Get the supabase auth user object for the given jwt, if valid.
    """
    try:
        user_response = await auth_client.get_user(jwt=jwt)
        if user_response and user_response.user:
            return user_response.user
    except AuthApiError:
        return None
    except Exception:
        logger.warning("Auth service unreachable")
        return None


@with_admin_client()
async def update_user_token_limit(user_id: str, daily_token_limit: int, **kwargs):
    """Update user's daily token limit in app_metadata."""
    client: AsyncGoTrueClient = kwargs["client"]

    try:
        user_response = await client.admin.get_user_by_id(user_id)
        current_app_metadata = user_response.user.app_metadata or {}
        current_app_metadata["daily_token_limit"] = daily_token_limit

        update_request = AdminUserAttributes()
        update_request["app_metadata"] = current_app_metadata

        await client.admin.update_user_by_id(user_id, update_request)
    except (ValueError, AuthApiError) as e:
        logger.error(f"Failed to update token limit for user {user_id}: {e}")
        raise


@with_admin_client()
async def update_user_profile_metadata(
    user_id: str, first_name: str, last_name: str, **kwargs
) -> None:
    """Update user profile metadata (first_name, last_name) via admin."""
    client: AsyncGoTrueClient = kwargs["client"]
    update_request = AdminUserAttributes()
    update_request["user_metadata"] = {
        "first_name": first_name,
        "last_name": last_name,
    }
    try:
        await client.admin.update_user_by_id(user_id, update_request)
    except (ValueError, AuthApiError) as e:
        logger.error(f"Failed to update profile for user {user_id}: {e}")
        raise


@with_admin_client()
async def get_user_by_id(id: str, **kwargs):
    client: AsyncGoTrueClient = kwargs["client"]

    try:
        user_response = await client.admin.get_user_by_id(id)

        return PlatformUser(None, user_response.user)
    except (ValueError, AuthApiError):
        return None


@with_admin_client()
async def create_user_admin(
    email: str, password: str, first_name: str, last_name: str, **kwargs
) -> Optional["PlatformUser"]:
    """Create a Supabase user with email/password (auto-confirmed, no invite email)."""
    client: AsyncGoTrueClient = kwargs["client"]
    attrs = AdminUserAttributes()
    attrs["email"] = email
    attrs["password"] = password
    attrs["email_confirm"] = True
    attrs["user_metadata"] = {"first_name": first_name, "last_name": last_name}
    try:
        user_response = await client.admin.create_user(attrs)
        return PlatformUser(None, user_response.user)
    except (ValueError, AuthApiError) as e:
        logger.error(f"Failed to create user {email}: {e}")
        raise


@with_admin_client()
async def delete_user_admin(user_id: str, **kwargs) -> None:
    """Delete a Supabase user by ID."""
    client: AsyncGoTrueClient = kwargs["client"]
    try:
        await client.admin.delete_user(user_id)
    except (ValueError, AuthApiError) as e:
        logger.error(f"Failed to delete user {user_id}: {e}")
        raise


async def send_magic_link_email(
    email: str, redirect_url: str, should_create_user: bool = True
) -> dict:
    """Send passwordless auth email for an existing or new user."""
    client = AsyncGoTrueClient(url=settings.AUTH_URL)
    try:
        await client.sign_in_with_otp(
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
