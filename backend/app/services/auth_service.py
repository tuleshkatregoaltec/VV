import logging
from typing import Optional

from fastapi.responses import RedirectResponse

from supabase_auth import AdminUserAttributes, AsyncGoTrueClient, User as AuthUser
from supabase_auth.errors import AuthApiError

from app.config import settings
from app.providers.auth.platform_user import PlatformUser

from app.services.admin_auth_service import AdminAuth

logger = logging.getLogger(__name__)

auth_client = AsyncGoTrueClient(url="https://auth.vitevue.com")

admin_auth = AdminAuth()


async def get_auth_user(jwt: str) -> Optional[AuthUser]:
    """
    Get the supabase auth user object for the given jwt, if valid.
    """
    try:
        user_response = await auth_client.get_user(jwt=jwt)
    except AuthApiError:
        # invalid token, token not valid
        return None

    return user_response.user


async def logout_user(user: PlatformUser):
    await auth_client.admin.sign_out(user.token)
    return RedirectResponse(url=settings.FRONTEND_URL)


@admin_auth.with_admin_client()
async def update_user_metadata(user: PlatformUser, **kwargs):
    client: AsyncGoTrueClient = kwargs["client"]
    update_request = AdminUserAttributes()
    update_request["user_metadata"] = user.metadata
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
