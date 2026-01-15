from starlette.authentication import BaseUser, AuthCredentials


from supabase_auth import User

from app.providers.auth.scopes import AuthScopes

import dataclasses


@dataclasses.dataclass
class UserRoles:
    roles: list[str] = dataclasses.field(default_factory=[])

@dataclasses.dataclass
class UserMetadata:
    first_name: str =  dataclasses.field(default_factory=str)
    last_name: str =  dataclasses.field(default_factory=str)
    role: str = dataclasses.field(default_factory=UserRoles)
    is_active: bool = dataclasses.field(default_factory=False)


    @classmethod
    def parse_dict(cls, data: dict):
        return cls(**data)
    
    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


class PlatformUser(BaseUser):
    def __init__(self, jwt: str, user: User) -> None:
        # JWT needed to be able to sign out specific users, this class only has a lifecycle of the current request.
        self.__jwt: str = jwt
        self.__auth_user: User = user


        if hasattr(self.auth_user, "user_metadata"):
            self.__metadata = UserMetadata.parse_dict(self.auth_user.user_metadata)
        else:
            self.__metadata = UserMetadata()

    @property
    # TODO: check if *still* authed?
    def is_authenticated(self) -> bool:
        """
        Was the user authenticated as the time of this object's creation.
        """
        return True

    

    #region Supabase Auth User

    @property
    def auth_user(self) -> User:
        """
        Authentication provider user object.
        """
        return self.__auth_user
    

    @property
    def token(self) -> User:
        """
        JWT token used this request to create this object
        """
        return self.__jwt

    @property
    def id(self) -> str:
        return self.__auth_user.id
    
    @property
    def email(self) -> str:
        return self.__auth_user.email
    
    @property
    def first_name(self) -> str:
        return self.__auth_user
    
    
    #@property.setter
    #def auth_user(self, value: User):
    #    self.__auth_user = value

    #endregion

    #def display_name(self) -> str:
    #    return self.username


    
    @property
    def metadata(self):
        return self.__metadata
        
    def is_admin(self):
        return "admin" in self.metadata.role
    
    async def get_scopes(self) -> AuthCredentials:
        scopes = AuthCredentials()

        if (self.is_admin()):
            scopes.scopes.append(AuthScopes.GLOBAL_ADMIN.value)

        return scopes


    async def get_user_info(self) -> dict:
        """
        Construct a user info dict that the frontend expects.
        """
        #return {"user": user, "access_token": access_token, "authenticated": True}

        role = "user"

        if (self.is_admin()):
            role = "admin"

        return {
            "id": self.auth_user.id,
            "email": self.auth_user.email,
            # TODO: populate below
            "first_name": "First", # TODO: require first name
            "last_name": "Last", # TODO: see above
            "organization_id": "ORG_ID",
            "organization_name": "ORG_NAME",
            "role": role
        }
    