from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import List
from datetime import datetime, timezone

from app.db.session import get_db_session
from app.routers.dependencies import require_organization_admin, require_auth
from app.providers.auth.platform_user import PlatformUser
from app.schemas.onboarding import InviteUserRequest
from app.schemas.subscriptions import SubscriptionResponse, CustomerPortalResponse
from app.services.auth_service import (
    invite_user_by_email_admin,
    sync_user_app_metadata,
    get_user_by_id,
)
from app.services.stripe_service import (
    get_subscription_by_org,
    get_customer_portal_url,
)
from app.db.models.auth import Organization
from app.config import settings
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/organization", tags=["organization"])


class OrganizationMemberResponse(BaseModel):
    """Organization member response."""

    id: str
    email: str
    first_name: str
    last_name: str
    is_active: bool
    role: str


@router.get("/members", response_model=List[OrganizationMemberResponse])
async def get_organization_members(
    current_user: PlatformUser = Depends(require_organization_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Get organization members (admin only)."""
    from app.services.organization_service import get_organization_for_user

    organization = await get_organization_for_user(db, current_user.id)

    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    members = []
    for user_id in organization.users:
        user = await get_user_by_id(user_id)
        if user:
            is_active = (
                user.app_metadata.get("is_active", False)
                if isinstance(user.app_metadata, dict)
                else False
            )
            role_data = (
                user.app_metadata.get("role", {})
                if isinstance(user.app_metadata, dict)
                else {}
            )
            role_list = (
                role_data.get("roles", []) if isinstance(role_data, dict) else []
            )
            user_role = (
                "organization_admin" if "organization_admin" in role_list else "user"
            )

            members.append(
                OrganizationMemberResponse(
                    id=user.id,
                    email=user.email,
                    first_name=user.user_metadata.get("first_name", "")
                    if isinstance(user.user_metadata, dict)
                    else "",
                    last_name=user.user_metadata.get("last_name", "")
                    if isinstance(user.user_metadata, dict)
                    else "",
                    is_active=is_active,
                    role=user_role,
                )
            )

    return members


@router.post("/deactivate-user/{user_id}")
async def deactivate_organization_user(
    user_id: str,
    current_user: PlatformUser = Depends(require_organization_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Deactivate a user (admin only)."""
    from app.services.organization_service import get_organization_for_user

    organization = await get_organization_for_user(db, current_user.id)

    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    if user_id not in organization.users:
        raise HTTPException(status_code=404, detail="User not in organization")

    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    await sync_user_app_metadata(user_id=user_id, is_active=False, role="user")

    return {"success": True, "message": f"User {user_id} deactivated"}


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_organization_subscription(
    current_user: PlatformUser = Depends(require_organization_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Get organization subscription details (admin only)."""
    from app.services.organization_service import get_organization_for_user

    organization = await get_organization_for_user(db, current_user.id)

    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    subscription = await get_subscription_by_org(organization.id, db)

    if not subscription:
        raise HTTPException(status_code=404, detail="No subscription found")

    current_members = len(organization.users)
    available_seats = max(0, subscription.seats - current_members)
    excess_users = max(0, current_members - subscription.seats)

    now = datetime.now(timezone.utc)
    within_paid_period = now < subscription.current_period_end

    return SubscriptionResponse(
        id=subscription.id,
        organization_id=subscription.organization_id,
        status=subscription.status,
        seats=subscription.seats,
        current_period_end=subscription.current_period_end,
        cancel_at_period_end=subscription.cancel_at_period_end,
        current_members=current_members,
        available_seats=available_seats,
        excess_users=excess_users,
        within_paid_period=within_paid_period,
    )


@router.get("/customer-portal", response_model=CustomerPortalResponse)
async def get_stripe_customer_portal(
    current_user: PlatformUser = Depends(require_organization_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Get Stripe Customer Portal URL (admin only)."""
    from app.services.organization_service import get_organization_for_user

    organization = await get_organization_for_user(db, current_user.id)

    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    if not organization.stripe_customer_id:
        raise HTTPException(status_code=404, detail="No Stripe customer found")

    return_url = f"{settings.FRONTEND_URL}/settings/organization"
    portal_url = await get_customer_portal_url(
        organization.stripe_customer_id, return_url
    )

    return CustomerPortalResponse(url=portal_url)


@router.post("/invite-user")
async def invite_user_to_organization(
    request: InviteUserRequest,
    current_user: PlatformUser = Depends(require_organization_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Invite user to organization (admin only)."""
    from app.services.organization_service import get_organization_for_user

    organization = await get_organization_for_user(db, current_user.id)

    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    active_user_count = len(organization.users)
    if active_user_count >= organization.max_users:
        raise HTTPException(
            status_code=400,
            detail=f"Organization has reached maximum seat limit ({organization.max_users})",
        )

    result = await invite_user_by_email_admin(
        email=request.email,
        organization_id=request.organization_id,
        redirect_url=request.redirect_url,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result
