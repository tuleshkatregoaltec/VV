from fastapi import Request
from typing import Dict

from backend.app.services.auth_service import get_current_user


async def require_auth(request: Request) -> Dict:
    """Dependency to require authentication on routes"""
    return await get_current_user(request)
