import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from supabase_auth import AsyncGoTrueClient, User as AuthUser
from supabase_auth.errors import AuthApiError

from app.config import settings
from app.db.models import User
from app.services.organization_service import (
    get_active_user_count,
    get_organization_by_domain,
    get_organization_by_id,
)

from app.providers.auth.platform_user import PlatformUser

logger = logging.getLogger(__name__)

auth_client = AsyncGoTrueClient(url="https://auth.vitevue.com")

async def get_auth_user(jwt: str) -> Optional[AuthUser]:
    """
    Get the supabase auth user object for the given jwt, if valid.
    """
    try:
        user_response = await auth_client.get_user(jwt=jwt)
    except AuthApiError:
        # invalid token, token not valid
        return None
    
    return user_response.user


async def logout_user(user: PlatformUser):
    await auth_client.admin.sign_out(user.token)

    return RedirectResponse(url=settings.FRONTEND_URL)
