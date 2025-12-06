from fastapi import Request, HTTPException
from typing import Dict

from backend.app.services.auth_service import get_current_user


async def require_auth(request: Request) -> Dict:
    """Dependency to require authentication on routes"""
    return await get_current_user(request)


async def require_admin(request: Request) -> Dict:
    """Dependency to require admin role on routes"""
    user = await get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
