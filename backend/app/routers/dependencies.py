import secrets
from fastapi import Request, HTTPException, Header
from typing import Dict

from app.services.auth_service import get_current_user
from app.config import settings


async def require_auth(request: Request) -> Dict:
    """Dependency to require authentication on routes"""
    return await get_current_user(request)


async def require_admin(request: Request) -> Dict:
    """Dependency to require admin role on routes"""
    user = await get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def require_api_key(x_api_key: str = Header(...)) -> None:
    if not secrets.compare_digest(x_api_key, settings.SERVICE_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return None
