import logging
from typing import Optional


from supabase_auth import AdminUserAttributes, AsyncGoTrueClient, User as AuthUser
from supabase_auth.errors import AuthApiError

from app.config import settings
from app.providers.auth.platform_user import PlatformUser
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

        return True

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

    async def get_valid_session(self) -> AsyncGoTrueClient | None:
        is_active = await self.is_session_active()
        if is_active:
            return self.__client

        result = False
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

        return None

    async def get_valid_session_with_auth(self):
        client = await self.get_valid_session()
        if client is None or self.__session is None:
            raise RuntimeError("Failed to authenticate admin client")

        client = AsyncGoTrueClient(
            url=client._url,
            headers={"Authorization": f"Bearer {self.__session.access_token}"},
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
        return None
    except Exception:
        logger.warning("Auth service unreachable")
        return None


@admin_auth.with_admin_client()
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


@admin_auth.with_admin_client()
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


@admin_auth.with_admin_client()
async def get_user_by_id(id: str, **kwargs):
    client: AsyncGoTrueClient = kwargs["client"]

    try:
        user_response = await client.admin.get_user_by_id(id)

        return PlatformUser(None, user_response.user)
    except (ValueError, AuthApiError):
        return None


@admin_auth.with_admin_client()
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


@admin_auth.with_admin_client()
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
