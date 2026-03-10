from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth.service import update_user_profile_metadata
from app.core.dependencies import require_auth
from app.organization import service as organization_service
from app.postgres import get_db_session
from app.providers.auth.platform_user import PlatformUser

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class UpdateProfileRequest(BaseModel):
    """Request to update user profile"""

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)


class UpdateProfileResponse(BaseModel):
    """Response for profile update"""

    success: bool
    first_name: str
    last_name: str


class AuthMeResponse(BaseModel):
    id: str
    email: str
    first_name: str
    last_name: str
    organization_id: str | None
    organization_name: str | None
    role: str
    is_owner: bool
    subscription_status: str | None


@router.get("/me", response_model=AuthMeResponse)
async def get_user(
    db: AsyncSession = Depends(get_db_session),
    current_user: PlatformUser = Depends(require_auth),
) -> AuthMeResponse:
    """
    Get current authenticated user with organization and subscription context.

    Returns first_name/last_name from Supabase auth user_metadata.
    Returns subscription_status from organization.subscription_status (single source of truth).
    """

    # Get organization via membership
    membership = await organization_service.get_membership_for_user(db, current_user.id)

    organization_id = None
    organization_name = None
    role = "user"
    is_owner = False
    subscription_status = None

    if membership:
        from app.postgres.models import Organization

        is_owner = membership.role == "owner"
        role = membership.role

        org = await db.get(Organization, membership.organization_id)
        if org:
            organization_id = org.id
            organization_name = org.name

            # Use org.subscription_status as single source of truth
            subscription_status = org.subscription_status

    # System admin overrides the membership role
    if current_user.is_admin():
        role = "admin"

    return AuthMeResponse(
        id=current_user.id,
        email=current_user.email,
        first_name=current_user.user_metadata.first_name,
        last_name=current_user.user_metadata.last_name,
        organization_id=organization_id,
        organization_name=organization_name,
        role=role,
        is_owner=is_owner,
        subscription_status=subscription_status,
    )


@router.post("/update-profile", response_model=UpdateProfileResponse)
async def update_profile(
    request: UpdateProfileRequest,
    current_user: PlatformUser = Depends(require_auth),
):
    """Update user profile (first name and last name)."""
    await update_user_profile_metadata(current_user.id, request.first_name, request.last_name)

    return UpdateProfileResponse(
        success=True, first_name=request.first_name, last_name=request.last_name
    )
