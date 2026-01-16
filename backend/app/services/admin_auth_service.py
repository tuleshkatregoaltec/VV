import asyncio
import functools
import logging
from datetime import datetime, timedelta

from supabase_auth import (
    AsyncGoTrueClient,
    SignInWithEmailAndPasswordCredentials,
    Session,
)
from supabase_auth.errors import AuthApiError, AuthSessionMissingError

from app.config import settings
from app.providers.auth.platform_user import PlatformUser
from app.config import settings

from copy import copy

logger = logging.getLogger(__name__)


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

        self.__user = auth_response.user #type: ignore
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
        dt_expires_at = datetime.fromtimestamp(self.__session.expires_at) #type: ignore

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
