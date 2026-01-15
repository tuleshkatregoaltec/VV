import secrets
import logging
from fastapi import Request, HTTPException, Header, Depends
from typing import Dict

from posthog import Posthog
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.auth_service import get_user_by_id
from app.services.organization_service import get_organization_for_user
from app.config import settings
from app.db.session import get_db_session
from app.db.models.auth import User
from app.services.token_usage_service import token_usage_service

logger = logging.getLogger(__name__)

# Initialize PostHog client for event tracking
posthog_client = Posthog(
    project_api_key=settings.POSTHOG_API_KEY, host=settings.POSTHOG_HOST
)

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


async def require_token_quota(
    request: Request, db: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(require_auth),
) -> None:
    """Dependency to check user has token quota remaining"""
    user_id = current_user.id

    # Get today's usage
    usage = await token_usage_service.get_today_usage(db, user_id)
    user_obj = await get_user_by_id(user_id)

    if not user_obj:
        raise HTTPException(status_code=404, detail="User not found")

    tokens_used = usage.total_tokens if usage else 0

    if tokens_used >= user_obj.metadata.daily_token_limit:
        # Capture PostHog event for rate limit breach
        try:
            event_properties = {
                "user_id": user_id,
                "tokens_used": tokens_used,
                "daily_limit": user_obj.metadata.daily_token_limit,
                "quota_type": "daily_tokens",
                "user_email": user_obj.email,
            }

            # Add organization info if available

            organization = await get_organization_for_user(db, user_id)
            if (organization):
                event_properties["organization_id"] = organization.id
                event_properties["organization_name"] = organization.name

            # Capture the rate limit event
            posthog_client.capture(
                distinct_id=user_id, event="rate_limit_exceeded", properties=event_properties
            )
        except Exception as e:
            # Don't block the request if PostHog capture fails
            logger.error(f"Failed to capture PostHog event for rate limit: {e}")

        raise HTTPException(
            status_code=429,
            detail=f"Daily token limit exceeded ({tokens_used}/{user_obj.metadata.daily_token_limit} tokens used today)",
        )

    return None
