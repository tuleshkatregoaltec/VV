import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import List
from datetime import datetime, timezone

from app.postgres import get_db_session
from app.core.dependencies import (
    require_auth,
    require_admin,
    require_organization_owner,
    AuthContext,
)
from app.providers.auth.platform_user import PlatformUser
from app.organization.models import (
    InviteUserRequest,
    CompleteProfileRequest,
    OrganizationCreateRequest,
    OrganizationDetailResponse,
    OrganizationResponse,
    OrganizationUpdateRequest,
    UserUpdateRequest,
    ValidateInviteTokenResponse,
    AcceptInviteRequest,
    AcceptInviteResponse,
    InviteConflictResponse,
    OwnerOrganizationCreateRequest,
    OwnerOrganizationCreateResponse,
)
from app.billing.models import SubscriptionResponse, CustomerPortalResponse
from app.auth.service import (
    invite_user_by_email_admin,
    get_user_by_id,
    update_user_token_limit,
)
from app.organization.service import (
    get_organization_for_user,
    create_organization as create_organization_service,
    delete_organization as delete_organization_service,
    get_active_user_count,
    get_organization_by_id,
    list_organizations as list_organizations_service,
    update_organization as update_organization_service,
    remove_user_from_organization,
    get_member_count,
    get_membership_for_user,
    add_user_to_organization,
    create_invitation,
    get_invitation_by_token,
    mark_invitation_accepted,
)
from app.organization.models import OrganizationMembership
from app.billing.service import (
    get_subscription_by_org,
    get_customer_portal_url,
)
from app.postgres.models import Organization
from app.config import settings
from pydantic import BaseModel
from app.token_usage.service import token_usage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/organization", tags=["organization"])


@router.post("/create", response_model=OwnerOrganizationCreateResponse)
async def create_owner_organization(
    request: OwnerOrganizationCreateRequest,
    current_user: PlatformUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Create organization for owner during self-signup (before checkout).

    Idempotent: If user already owns an organization, updates and returns existing org_id.
    This allows users to retry checkout after abandoning payment.
    """
    from uuid import uuid4

    # Check if user already owns an organization (idempotency)
    result = await db.exec(
        select(OrganizationMembership)
        .where(OrganizationMembership.user_id == current_user.id)
        .where(OrganizationMembership.role == "owner")
    )
    existing_membership = result.first()

    if existing_membership:
        # User already owns an org - update existing org (retry scenario)
        org = await db.get(Organization, existing_membership.organization_id)
        if not org:
            raise HTTPException(
                status_code=500,
                detail="Organization membership exists but org not found",
            )

        # Update org details for retry
        org.name = request.name
        org.max_users = request.max_users
        org.updated_at = datetime.now(timezone.utc)

        db.add(org)
        await db.commit()
        await db.refresh(org)

        logger.info(
            f"Updated existing org {org.id} for user {current_user.id} (retry/abandon scenario)"
        )

        return OwnerOrganizationCreateResponse(
            organization_id=org.id,
            name=org.name,
            max_users=org.max_users,
            is_new=False,
        )

    # Create new organization
    org_id = str(uuid4())
    org = Organization(
        id=org_id,
        name=request.name,
        owner_user_id=current_user.id,
        max_users=request.max_users,
        subscription_status=None,  # No subscription yet
        is_active=False,  # Inactive until payment succeeds
        stripe_customer_id=None,  # Created during checkout
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    db.add(org)

    # Add owner membership
    membership = OrganizationMembership(
        organization_id=org.id,
        user_id=current_user.id,
        role="owner",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(membership)

    try:
        await db.commit()
        await db.refresh(org)
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create organization for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create organization: {str(e)}"
        )

    logger.info(f"Created new organization {org.id} for user {current_user.id}")

    return OwnerOrganizationCreateResponse(
        organization_id=org.id,
        name=org.name,
        max_users=org.max_users,
        is_new=True,
    )


class OrganizationMemberResponse(BaseModel):
    """Organization member response."""

    id: str
    email: str
    first_name: str
    last_name: str
    role: str


@router.get("/members", response_model=List[OrganizationMemberResponse])
async def get_organization_members(
    context: AuthContext = Depends(require_organization_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Get organization members (query from memberships table)"""
    result = await db.exec(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == context.organization.id
        )
    )
    members = result.all()

    response = []
    for member in members:
        user_obj = await get_user_by_id(member.user_id)
        if user_obj:
            response.append(
                OrganizationMemberResponse(
                    id=member.user_id,
                    email=user_obj.email,
                    first_name=user_obj.user_metadata.first_name,
                    last_name=user_obj.user_metadata.last_name,
                    role=member.role,
                )
            )

    return response


@router.delete("/members/{user_id}")
async def remove_member(
    user_id: str,
    context: AuthContext = Depends(require_organization_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Remove user from organization (delete membership to free seat)"""
    if user_id == context.user.id:
        raise HTTPException(
            status_code=400, detail="Cannot remove yourself from organization"
        )

    success = await remove_user_from_organization(db, context.organization.id, user_id)

    if not success:
        raise HTTPException(status_code=404, detail="User not found in organization")

    return {"success": True}


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_organization_subscription(
    context: AuthContext = Depends(require_organization_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Get organization subscription details (owner only)."""

    if not context.subscription:
        raise HTTPException(status_code=404, detail="No subscription found")

    current_members = await get_member_count(db, context.organization.id)
    available_seats = max(0, context.subscription.seats - current_members)
    excess_users = max(0, current_members - context.subscription.seats)

    now = datetime.now(timezone.utc)
    within_paid_period = now < context.subscription.current_period_end

    return SubscriptionResponse(
        id=context.subscription.id,
        organization_id=context.subscription.organization_id,
        status=context.subscription.status,
        seats=context.subscription.seats,
        current_period_end=context.subscription.current_period_end,
        cancel_at_period_end=context.subscription.cancel_at_period_end,
        current_members=current_members,
        available_seats=available_seats,
        excess_users=excess_users,
        within_paid_period=within_paid_period,
    )


@router.get("/customer-portal", response_model=CustomerPortalResponse)
async def get_stripe_customer_portal(
    context: AuthContext = Depends(require_organization_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Get Stripe Customer Portal URL (admin only)."""

    organization = context.organization

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
    context: AuthContext = Depends(require_organization_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Invite user to organization (admin only)."""

    organization = context.organization

    active_user_count = await get_member_count(db, organization.id)
    if active_user_count >= organization.max_users:
        raise HTTPException(
            status_code=400,
            detail=f"Organization has reached maximum seat limit ({organization.max_users})",
        )

    # Create invitation record
    invitation = await create_invitation(
        db=db,
        organization_id=request.organization_id,
        email=request.email,
        invited_by_user_id=context.user.id,
        role="member",
    )

    # Include token in redirect URL
    redirect_url_with_token = f"{request.redirect_url}?token={invitation.token}"

    result = await invite_user_by_email_admin(
        email=request.email,
        organization_id=request.organization_id,
        redirect_url=redirect_url_with_token,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.get("/validate-invite-token", response_model=ValidateInviteTokenResponse)
async def validate_invite_token(
    token: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Validate invitation token and return organization details."""
    invitation = await get_invitation_by_token(db, token)

    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    # Check if expired
    now = datetime.now(timezone.utc)
    if invitation.expires_at < now:
        raise HTTPException(status_code=400, detail="Invitation has expired")

    # Check if already accepted
    if invitation.status == "accepted":
        raise HTTPException(status_code=400, detail="Invitation already accepted")

    # Get organization details
    organization = await get_organization_by_id(db, invitation.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    return ValidateInviteTokenResponse(
        organization_name=organization.name,
        organization_id=organization.id,
        role=invitation.role,
        email=invitation.email,
        expires_at=invitation.expires_at,
        status=invitation.status,
    )


@router.post("/accept-invite")
async def accept_invite(
    request: AcceptInviteRequest,
    current_user: PlatformUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db_session),
):
    """Accept organization invitation with conflict detection."""
    invitation = await get_invitation_by_token(db, request.token)

    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    # Check if expired
    now = datetime.now(timezone.utc)
    if invitation.expires_at < now:
        raise HTTPException(status_code=400, detail="Invitation has expired")

    # Check if already accepted
    if invitation.status == "accepted":
        raise HTTPException(status_code=400, detail="Invitation already accepted")

    # Validate email matches
    if invitation.email.lower() != current_user.email.lower():
        raise HTTPException(
            status_code=403, detail="Invitation email does not match your account"
        )

    # Check for existing membership (conflict detection)
    existing_membership = await get_membership_for_user(db, current_user.id)

    if existing_membership:
        # User already has a membership - return conflict details
        current_org = await get_organization_by_id(
            db, existing_membership.organization_id
        )
        if not current_org:
            raise HTTPException(
                status_code=500, detail="Current organization not found"
            )

        member_count = await get_member_count(db, current_org.id)
        is_single_seat = member_count == 1

        conflict_response = InviteConflictResponse(
            conflict=True,
            current_org_id=current_org.id,
            current_org_name=current_org.name,
            current_role=existing_membership.role,
            member_count=member_count,
            is_single_seat=is_single_seat,
        )
        raise HTTPException(status_code=409, detail=conflict_response.model_dump())

    # No conflict - create membership
    await add_user_to_organization(
        db=db,
        org_id=invitation.organization_id,
        user_id=current_user.id,
        role=invitation.role,
    )

    # Mark invitation as accepted
    await mark_invitation_accepted(db, invitation)

    # Get organization details
    organization = await get_organization_by_id(db, invitation.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    return AcceptInviteResponse(
        success=True,
        organization_id=organization.id,
        organization_name=organization.name,
        role=invitation.role,
    )


@router.post("/complete-profile")
async def complete_profile_setup(
    request: CompleteProfileRequest,
    current_user: PlatformUser = Depends(require_auth),
    db: AsyncSession = Depends(get_db_session),
):
    """Add invited user to organization."""
    stmt = select(Organization).where(Organization.id == request.organization_id)
    result = await db.execute(stmt)
    organization = result.scalar_one_or_none()

    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Check if user already has a membership
    existing_membership = await get_membership_for_user(db, current_user.id)

    if not existing_membership:
        # Create membership with member role
        await add_user_to_organization(
            db, organization.id, current_user.id, role="member"
        )

    return {"success": True}


# --- Organization management endpoints (migrated from admin) ---


@router.post(
    "/organizations",
    status_code=201,
    response_model=OrganizationResponse,
)
async def create_organization(
    organization_in: OrganizationCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    _admin: None = Depends(require_admin),
):
    """Create a new organization (admin only)."""
    try:
        organization = await create_organization_service(
            db=db,
            name=organization_in.name,
            max_users=organization_in.max_users,
        )
        response = OrganizationResponse.model_validate(organization)
        response.active_user_count = 0
        return response
    except Exception as e:
        logger.exception(f"Failed to create organization: {e}")
        raise HTTPException(status_code=400, detail="Failed to create organization")


@router.get("/organizations", response_model=List[OrganizationResponse])
async def list_organization(
    db: AsyncSession = Depends(get_db_session), _admin: None = Depends(require_admin)
):
    """List all organizations with user counts (admin only)."""
    organizations = await list_organizations_service(db)

    result = []
    for org in organizations:
        active_count = await get_active_user_count(db, org.id)
        response = OrganizationResponse.model_validate(org)
        response.active_user_count = active_count
        result.append(response)

    return result


@router.get("/organizations/{org_id}", response_model=OrganizationDetailResponse)
async def get_organization(
    org_id: str,
    db: AsyncSession = Depends(get_db_session),
    context: AuthContext = Depends(require_organization_owner),
):
    """Get organization details with user list (organization admin)."""
    organization = await get_organization_by_id(db, org_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    active_count = await get_active_user_count(db, org_id)

    user_list = []

    # Get all memberships for this organization
    memberships_result = await db.exec(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == org_id
        )
    )
    memberships = memberships_result.all()

    for membership in memberships:
        user = await get_user_by_id(membership.user_id)

        if user is not None:
            usage = await token_usage_service.get_today_usage(db, user.id)
            tokens_used = usage.total_tokens if usage else 0
            daily_limit = user.app_metadata.daily_token_limit
            usage_percentage = (
                (tokens_used / daily_limit * 100) if daily_limit > 0 else 0
            )

            user_list.append(
                {
                    "id": user.id,
                    "email": user.email,
                    "first_name": user.user_metadata.first_name,
                    "last_name": user.user_metadata.last_name,
                    "created_at": user.auth_user.created_at,
                    "last_login": user.auth_user.last_sign_in_at,
                    "daily_token_limit": daily_limit,
                    "tokens_used_today": tokens_used,
                    "usage_percentage": usage_percentage,
                }
            )

    org_response = OrganizationResponse.model_validate(organization)
    org_response.active_user_count = active_count

    return OrganizationDetailResponse(
        organization=org_response,
        users=user_list,
    )


@router.put("/organizations/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: str,
    organization_update: OrganizationUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    context: AuthContext = Depends(require_organization_owner),
):
    """Update organization settings (organization admin)."""
    organization = await update_organization_service(
        db=db,
        org_id=org_id,
        max_users=organization_update.max_users,
        is_active=organization_update.is_active,
    )

    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    active_count = await get_active_user_count(db, org_id)

    response = OrganizationResponse.model_validate(organization)
    response.active_user_count = active_count
    return response


@router.delete("/organizations/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    org_id: str,
    db: AsyncSession = Depends(get_db_session),
    _admin: None = Depends(require_admin),
):
    """Delete organization (admin only)."""
    success = await delete_organization_service(db, org_id)
    if not success:
        raise HTTPException(status_code=404, detail="Organization not found")
    return None


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    user_update: UserUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    context: AuthContext = Depends(require_organization_owner),
) -> dict:
    """Update user daily token limit (organization admin)."""

    if user_update.daily_token_limit is None:
        raise HTTPException(status_code=400, detail="daily_token_limit is required")

    await update_user_token_limit(user_id, user_update.daily_token_limit)

    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "id": user.id,
        "email": user.email,
        "daily_token_limit": user.app_metadata.daily_token_limit,
        "updated_at": user.auth_user.updated_at,
    }
