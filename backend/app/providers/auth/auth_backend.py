from http.client import HTTPConnection

from starlette.authentication import AuthenticationBackend, AuthenticationError

from app.auth.service import get_auth_user
from app.providers.auth.platform_user import PlatformUser

# based on starlette.authentication.AuthenticationBackend


class AuthBackend(AuthenticationBackend):
    async def authenticate(self, conn: HTTPConnection):
        if "Authorization" not in conn.headers:
            return

        # get token from headers
        auth = conn.headers["Authorization"]

        try:
            scheme, encoded_jwt = auth.split()
        except ValueError:
            # HTTP 400 (defined in middleware) as opposed to 401
            # also does not set application type json
            raise AuthenticationError({"detail": "Invalid credentials"})

        if scheme.lower() != "bearer":
            return

        # auth user
        auth_user = await get_auth_user(encoded_jwt)
        if auth_user is None:
            raise AuthenticationError({"detail": "Invalid credentials"})

        # jwt is valid
        user = PlatformUser(encoded_jwt, auth_user)
        scopes = await user.get_scopes()

        # return objects
        return scopes, user
