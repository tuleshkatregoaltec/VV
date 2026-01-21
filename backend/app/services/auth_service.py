import logging
from typing import Optional

from fastapi.responses import RedirectResponse

from supabase_auth import AdminUserAttributes, AsyncGoTrueClient, User as AuthUser
from supabase_auth.errors import AuthApiError

from app.config import settings
from app.providers.auth.platform_user import PlatformUser
from app.config import settings

from app.services.admin_auth_service import AdminAuth

logger = logging.getLogger(__name__)

auth_client = AsyncGoTrueClient(url=settings.AUTH_URL)

admin_auth = AdminAuth()


async def get_auth_user(jwt: str) -> Optional[AuthUser]:
    """
    Get the supabase auth user object for the given jwt, if valid.
    """
    try:
        user_response = await auth_client.get_user(jwt=jwt)
        if user_response and user_response.user:
            return user_response.user
    except AuthApiError:
        # invalid token, token not valid
        return None


@admin_auth.with_admin_client()
async def update_app_metadata(user: PlatformUser, **kwargs):
    client: AsyncGoTrueClient = kwargs["client"]
    update_request = AdminUserAttributes()
    update_request["app_metadata"] = user.app_metadata.model_dump()
    try:
        await client.admin.update_user_by_id(user.id, update_request)
    except (ValueError, AuthApiError):  # invalid uuid, user not found
        logger.error(f"Failed to update metadata for user {user.id}")


@admin_auth.with_admin_client()
async def get_user_by_id(id: str, **kwargs):
    client: AsyncGoTrueClient = kwargs["client"]

    try:
        user_response = await client.admin.get_user_by_id(id)

        return PlatformUser(None, user_response.user)
    except (ValueError, AuthApiError):  # invalid uuid, user not found
        return None


@admin_auth.with_admin_client()
async def sync_user_app_metadata(
    user_id: str, is_active: bool, role: str, **kwargs
) -> None:
    """Update user app_metadata with is_active and role."""
    client: AsyncGoTrueClient = kwargs["client"]
    update_request = AdminUserAttributes()
    update_request["app_metadata"] = {
        "is_active": is_active,
        "role": {"roles": [role]},
    }
    try:
        await client.admin.update_user_by_id(user_id, update_request)
    except (ValueError, AuthApiError) as e:
        logger.error(f"Failed to update metadata for user {user_id}: {e}")
        raise


@admin_auth.with_admin_client()
async def invite_user_by_email_admin(
    email: str, organization_id: str, redirect_url: str, **kwargs
) -> dict:
    """Send invitation email to user via Supabase admin."""
    client: AsyncGoTrueClient = kwargs["client"]
    try:
        await client.admin.invite_user_by_email(
            email,
            options={
                "data": {"organization_id": organization_id},
                "redirect_to": redirect_url,
            },
        )
        return {"success": True, "error": None}
    except AuthApiError as e:
        logger.error(f"Failed to invite user {email}: {e}")
        return {"success": False, "error": str(e)}
