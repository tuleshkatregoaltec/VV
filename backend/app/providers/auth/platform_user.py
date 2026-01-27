from typing import List
from starlette.authentication import BaseUser, AuthCredentials
from typing import List

from supabase_auth import User
from pydantic import BaseModel, Field

from app.providers.auth.scopes import AuthScopes

from pydantic import Field, BaseModel


class UserRoles(BaseModel):
    roles: List[str] = Field(default_factory=list)


class UserAppMetadata(BaseModel):
    provider: str = Field(default="")
    providers: List[str] = Field(default=[])

    role: UserRoles = Field(default_factory=lambda: UserRoles())
    daily_token_limit: int = Field(default=500000)


class UserMetadata(BaseModel):
    first_name: str = Field(default="")
    last_name: str = Field(default="")


class PlatformUser(BaseUser):
    def __init__(self, jwt: str, user: User) -> None:
        # JWT needed to be able to sign out specific users, this class only has a lifecycle of the current request.
        self.__jwt: str = jwt
        self.__auth_user: User = user

        if hasattr(self.auth_user, "app_metadata") and isinstance(
            self.auth_user.app_metadata, dict
        ):
            self.__app_metadata = UserAppMetadata.model_validate(
                self.auth_user.app_metadata
            )
        else:
            self.__app_metadata = UserAppMetadata()

        if hasattr(self.auth_user, "user_metadata") and isinstance(
            self.auth_user.user_metadata, dict
        ):
            self.__user_metadata = UserMetadata.model_validate(
                self.auth_user.user_metadata
            )
        else:
            self.__user_metadata = UserMetadata()

    @property
    # TODO: check if *still* authed?
    def is_authenticated(self) -> bool:
        """
        Was the user authenticated as the time of this object's creation.
        """
        return True

    # region Supabase Auth User

    @property
    def auth_user(self) -> User:
        """
        Authentication provider user object.
        """
        return self.__auth_user

    @property
    def token(self) -> str:
        """
        JWT token used this request to create this object
        """
        return self.__jwt

    @property
    def id(self) -> str:
        return self.__auth_user.id

    @property
    def email(self) -> str:
        return self.__auth_user.email or ""

    # @property.setter
    # def auth_user(self, value: User):
    #    self.__auth_user = value

    # endregion

    # def display_name(self) -> str:
    #    return self.username

    @property
    def app_metadata(self):
        return self.__app_metadata

    @property
    def user_metadata(self):
        return self.__user_metadata

    def is_admin(self):
        return "admin" in self.app_metadata.role.roles

    async def get_scopes(self) -> AuthCredentials:
        scopes = AuthCredentials()

        if self.is_admin():
            scopes.scopes.append(AuthScopes.GLOBAL_ADMIN.value)

        return scopes

    async def get_user_info(self) -> dict:
        """
        Construct a user info dict that the frontend expects.
        """
        # return {"user": user, "access_token": access_token, "authenticated": True}

        role = "user"

        if self.is_admin():
            role = "admin"

        return {
            "id": self.auth_user.id,
            "email": self.auth_user.email,
            "first_name": self.user_metadata.first_name,
            "last_name": self.user_metadata.last_name,
            "role": role,
        }
