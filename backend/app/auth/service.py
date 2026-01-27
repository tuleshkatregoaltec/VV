import logging
from typing import Optional

from fastapi.responses import RedirectResponse

from supabase_auth import AdminUserAttributes, AsyncGoTrueClient, User as AuthUser
from supabase_auth.errors import AuthApiError

from app.config import settings
from app.providers.auth.platform_user import PlatformUser
from copy import copy
import asyncio
import functools
from datetime import datetime, timedelta

from supabase_auth import SignInWithEmailAndPasswordCredentials, Session
from supabase_auth.errors import AuthSessionMissingError


class AdminAuth:
    def __init__(self):
        self.__client = AsyncGoTrueClient(url=settings.AUTH_URL)

        self.__user: PlatformUser | None = None
        self.__session: Session | None = None

    async def login_username_pass(self) -> bool:
        """
        returns boolean success
        """

        try:
            credentials = SignInWithEmailAndPasswordCredentials(
                email=settings.AUTH_ADMIN_EMAIL, password=settings.AUTH_ADMIN_PASSWORD
            )

            auth_response = await self.__client.sign_in_with_password(credentials)

            del credentials  # re-create when needed
        except AuthApiError:
            logger.error("Failed to get admin authentication, check admin user/pass.")
            return False

        # succeeded

        self.__user = auth_response.user  # type: ignore
        self.__session = auth_response.session

    async def ensure_valid_refresh(self) -> bool:
        """
        Ensure that we have a valid refresh token
        returns boolean success
        """

        if self.__session is None:
            logger.error("Attempted to refresh login without a session")
            return False

        # check if we need to refresh
        dt_expires_at = datetime.fromtimestamp(self.__session.expires_at)  # type: ignore

        # run 30s earlier than we need to in case it expires mid-operation
        dt_expires_at -= timedelta(seconds=30)

        dt_now = datetime.today()

        if dt_now < dt_expires_at:
            return True

        # needs refreshing
        try:
            auth_response = await self.__client.refresh_session(
                self.__session.refresh_token
            )
        except AuthSessionMissingError:
            logger.error("Failed to refresh token")
            return False

        self.__user = auth_response.user
        self.__session = auth_response.session

        return True

    async def is_session_active(self):
        return await self.__client.get_user() is not None

    def has_session(self):
        return self.__session is not None

    async def get_valid_session(self):
        if not await self.is_session_active():
            # no active session

            # check if we ever had a session
            if self.has_session():
                # refresh
                result = await self.ensure_valid_refresh()
            else:
                # login with user/pass
                result = await self.login_username_pass()

            if result:
                return self.__client

        return self.__client

    async def get_valid_session_with_auth(self):
        await self.get_valid_session()

        client = AsyncGoTrueClient(
            url=self.__client._url,
            headers={"Authorization": f"Bearer ${self.__session.access_token}"},
        )

        # admin funcs don't pass required jwt, do it ourselves
        client.admin._headers["Authorization"] = f"Bearer {self.__session.access_token}"

        return client

    async def get_admin_platform_user(self):
        await self.get_valid_session()

        user_response = await self.__client.get_user()

        if user_response is not None:
            return PlatformUser(None, user_response.user)

    def with_admin_client(self):
        """
        Decorator
        """

        def wrapper(func):
            @functools.wraps(func)
            async def wrapped(*args, **kwargs):
                kwargs["client"] = await self.get_valid_session_with_auth()

                # TODO: if client is None

                return await func(*args, **kwargs)

            return wrapped

        return wrapper


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
