from enum import Enum


class AuthScopes(Enum):
    GLOBAL_ADMIN = "admin"
    AUTHENTICATED_USER = "authenticated"