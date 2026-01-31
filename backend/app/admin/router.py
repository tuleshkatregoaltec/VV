import logging
from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.dependencies import require_admin
from app.postgres import get_db_session
from app.token_usage.models import UserTokenUsage, UserTokenStatsResponse
from app.auth.service import get_user_by_id, update_user_token_limit
from app.organization.models import Organization, OrganizationMembership
from app.organization.service import get_membership_for_user
from app.billing.models import Subscription
from app.admin.models import (
    OrganizationListResponse,
    OrganizationMemberResponse,
    UserDetailResponse,
    UpdateUserRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


@router.get("/token-usage", response_model=List[UserTokenStatsResponse])
async def list_token_usage(
    db: AsyncSession = Depends(get_db_session), _admin: None = Depends(require_admin)
):
    """Admin: list today's token usage for all users."""
    today = date.today()
    stmt = select(UserTokenUsage).where(UserTokenUsage.date == today)
    result = await db.exec(stmt)
    usages = result.all()

    out: List[UserTokenStatsResponse] = []
    for usage in usages:
        user = await get_user_by_id(usage.user_id)
        daily_limit = getattr(user.app_metadata, "daily_token_limit", 0) if user else 0
        tokens_used = usage.total_tokens if usage else 0
        remaining = max(0, daily_limit - tokens_used)
        usage_percentage = (tokens_used / daily_limit * 100) if daily_limit > 0 else 0.0

        out.append(
            UserTokenStatsResponse(
                user_id=usage.user_id,
                tokens_used_today=tokens_used,
                daily_limit=daily_limit,
                usage_percentage=usage_percentage,
                remaining_tokens=remaining,
            )
        )

    return out


@router.get("/organizations", response_model=List[OrganizationListResponse])
async def list_all_organizations(
    current_user: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """List all organizations with stats (system admin only)."""

    # Get all organizations
    orgs_stmt = select(Organization)
    orgs_result = await db.execute(orgs_stmt)
    organizations = orgs_result.scalars().all()

    response = []
    for org in organizations:
        # Get member count
        members_stmt = select(func.count(OrganizationMembership.id)).where(
            OrganizationMembership.organization_id == org.id
        )
        members_result = await db.execute(members_stmt)
        user_count = members_result.scalar() or 0

        # Get subscription
        sub_stmt = select(Subscription).where(Subscription.organization_id == org.id)
        sub_result = await db.execute(sub_stmt)
        subscription = sub_result.scalar_one_or_none()

        # Get owner email
        owner = await get_user_by_id(org.owner_user_id)
        owner_email = owner.email if owner else "unknown"

        response.append(
            OrganizationListResponse(
                id=org.id,
                name=org.name,
                owner_email=owner_email,
                user_count=user_count,
                subscription_status=subscription.status if subscription else "none",
                seats=subscription.seats if subscription else 0,
                created_at=org.created_at,
            )
        )

    return response


@router.get(
    "/organizations/{organization_id}/members",
    response_model=List[OrganizationMemberResponse],
)
async def list_organization_members(
    organization_id: str,
    current_user: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """List all members in an organization (system admin only)."""

    # Verify organization exists
    org = await db.get(Organization, organization_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Get memberships
    stmt = select(OrganizationMembership).where(
        OrganizationMembership.organization_id == organization_id
    )
    result = await db.execute(stmt)
    memberships = result.scalars().all()

    response = []
    for membership in memberships:
        user = await get_user_by_id(membership.user_id)
        if user:
            response.append(
                OrganizationMemberResponse(
                    id=membership.user_id,
                    email=user.email,
                    first_name=user.user_metadata.first_name,
                    last_name=user.user_metadata.last_name,
                    role=membership.role,
                    joined_at=membership.created_at,
                )
            )

    return response


@router.get("/users/{user_id}", response_model=UserDetailResponse)
async def get_user_details(
    user_id: str,
    current_user: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Get user details (system admin only)."""

    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get membership
    membership = await get_membership_for_user(db, user_id)

    organization_id = None
    organization_name = None
    role = "user"

    if membership:
        org = await db.get(Organization, membership.organization_id)
        if org:
            organization_id = org.id
            organization_name = org.name
            role = membership.role

    return UserDetailResponse(
        id=user.id,
        email=user.email,
        first_name=user.user_metadata.first_name,
        last_name=user.user_metadata.last_name,
        organization_id=organization_id,
        organization_name=organization_name,
        role=role,
        daily_token_limit=user.app_metadata.daily_token_limit,
    )


@router.patch("/users/{user_id}", response_model=UserDetailResponse)
async def update_user(
    user_id: str,
    request: UpdateUserRequest,
    current_user: None = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Update user fields (system admin only)."""

    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update token limit if provided
    if request.daily_token_limit is not None:
        await update_user_token_limit(user_id, request.daily_token_limit)

    # Get updated user
    user = await get_user_by_id(user_id)

    # Get membership for response
    membership = await get_membership_for_user(db, user_id)

    organization_id = None
    organization_name = None
    role = "user"

    if membership:
        org = await db.get(Organization, membership.organization_id)
        if org:
            organization_id = org.id
            organization_name = org.name
            role = membership.role

    return UserDetailResponse(
        id=user.id,
        email=user.email,
        first_name=user.user_metadata.first_name,
        last_name=user.user_metadata.last_name,
        organization_id=organization_id,
        organization_name=organization_name,
        role=role,
        daily_token_limit=user.app_metadata.daily_token_limit,
    )
