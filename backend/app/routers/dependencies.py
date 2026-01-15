import secrets
from fastapi import Request, HTTPException, Header
from typing import Dict

from app.config import settings

from app.providers.auth.scopes import AuthScopes
from app.providers.auth.platform_user import PlatformUser

async def require_auth(request: Request) -> PlatformUser:
    """Dependency to require authentication on routes"""
    if (not request.user.is_authenticated):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    return request.user


async def require_admin(request: Request) -> PlatformUser:
    """Dependency to require admin role on routes"""
    # note that scopes will be empty if user is not authenticated
    if AuthScopes.GLOBAL_ADMIN.value not in request.auth.scopes:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    return request.user


async def require_api_key(x_api_key: str = Header(...)) -> None:
    if not secrets.compare_digest(x_api_key, settings.SERVICE_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return None
