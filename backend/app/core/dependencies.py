import secrets
import logging
from dataclasses import dataclass
from typing import Optional
from fastapi import Request, HTTPException, Header, Depends

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.auth.service import get_user_by_id
from app.organization.service import get_membership_for_user
from app.config import settings
from app.postgres import get_db_session
from app.token_usage.service import token_usage_service
from app.core.exceptions import AuthError
from app.providers.auth.scopes import AuthScopes
from app.providers.auth.platform_user import PlatformUser

logger = logging.getLogger(__name__)


async def require_auth(request: Request) -> PlatformUser:
    """Dependency to require authentication on routes"""
    if not request.user.is_authenticated:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return request.user


async def require_admin(request: Request) -> PlatformUser:
    """Dependency to require system admin (email match)"""
    if not request.user.is_authenticated:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if request.user.email != settings.SYSTEM_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="System admin access required")

    return request.user


async def require_organization_admin(request: Request) -> PlatformUser:
    """Dependency to require organization admin role on routes"""
    if not request.user.is_authenticated:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Check role from app_metadata in JWT token (not from request body)
    if "organization_admin" not in request.user.app_metadata.role.roles:
        raise HTTPException(
            status_code=403, detail="Organization admin access required"
        )

    return request.user


async def require_api_key(x_api_key: str = Header(...)) -> None:
    if not secrets.compare_digest(x_api_key, settings.SERVICE_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return None


async def require_token_quota(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    current_user: PlatformUser = Depends(require_auth),
) -> None:
    """Dependency to check user has token quota remaining"""

    # Get today's usage
    usage = await token_usage_service.get_today_usage(db, current_user.id)
    user_obj = await get_user_by_id(current_user.id)

    if not user_obj:
        raise HTTPException(status_code=404, detail="User not found")

    tokens_used = usage.total_tokens if usage else 0

    if tokens_used >= user_obj.app_metadata.daily_token_limit:
        raise HTTPException(
            status_code=429,
            detail=f"Daily token limit exceeded ({tokens_used}/{user_obj.app_metadata.daily_token_limit} tokens used today)",
        )

    return None


@dataclass
class AuthContext:
    """Typed authentication context for protected routes"""

    user: PlatformUser
    organization: "Organization"
    membership: "OrganizationMembership"
    subscription: Optional["Subscription"]


async def require_active_subscription(
    current_user: PlatformUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db_session),
) -> AuthContext:
    """
    Require user with active organization subscription.

    Uses organization.subscription_status as single source of truth.
    Allows access when subscription_status in ['active', 'trialing'].

    Returns AuthContext with user, org, membership, subscription.

    Raises:
        403 NO_ORG_MEMBERSHIP: User not in any organization
        402 SUBSCRIPTION_REQUIRED: No subscription, null, or inactive status
        402 SUBSCRIPTION_PAST_DUE: Payment failed
    """
    from app.postgres.models import Organization, Subscription

    # Check membership (enforced single-org via UNIQUE user_id)
    membership = await get_membership_for_user(db, current_user.id)
    if not membership:
        raise AuthError.no_org_membership()

    # Get organization
    organization = await db.get(Organization, membership.organization_id)
    if not organization:
        raise HTTPException(status_code=500, detail="Organization not found")

    # Check subscription_status directly (single source of truth)
    if organization.subscription_status == "past_due":
        raise AuthError.subscription_past_due()

    # Allow access for active and trialing subscriptions
    if organization.subscription_status not in ["active", "trialing"]:
        raise AuthError.subscription_required()

    # Get subscription details (optional, for subscription info endpoints)
    result = await db.exec(
        select(Subscription)
        .where(Subscription.organization_id == organization.id)
        .order_by(Subscription.created_at.desc())
    )
    subscription = result.first()

    return AuthContext(
        user=current_user,
        organization=organization,
        membership=membership,
        subscription=subscription,
    )


async def require_membership(
    current_user: PlatformUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db_session),
) -> AuthContext:
    """
    Require any active organization membership (member or owner).

    Raises:
        403 MEMBERSHIP_REQUIRED: User has no organization membership
        (plus all require_active_subscription errors)
    """
    return await require_active_subscription(current_user, db)


async def require_organization_owner(
    current_user: PlatformUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db_session),
) -> AuthContext:
    """
    Require organization owner with active subscription.

    Raises:
        403 OWNER_REQUIRED: User is not organization owner
        (plus all require_active_subscription errors)
    """
    # Reuse subscription check
    context = await require_active_subscription(current_user, db)

    if context.membership.role != "owner":
        raise AuthError.owner_required()

    return context
