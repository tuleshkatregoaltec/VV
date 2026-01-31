from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel, Field

from app.postgres import get_db_session
from app.core.dependencies import require_auth
from app.providers.auth.platform_user import PlatformUser
from app.organization import service as organization_service
from app.auth.service import update_user_profile_metadata
from app.billing.service import get_subscription_by_org

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


@router.get("/me")
async def get_user(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    current_user: PlatformUser = Depends(require_auth),
):
    """Get current authenticated user with organization and subscription context."""

    # Get organization via membership
    membership = await organization_service.get_membership_for_user(db, current_user.id)

    organization_id = None
    organization_name = None
    role = membership.role if membership else "user"
    subscription_status = None
    subscription_is_active = False

    if membership:
        from app.postgres.models import Organization

        org = await db.get(Organization, membership.organization_id)
        if org:
            organization_id = org.id
            organization_name = org.name

            # Get subscription status for performance (avoid separate API call)
            try:
                subscription = await get_subscription_by_org(org.id, db)
                if subscription:
                    subscription_status = subscription.status
                    subscription_is_active = subscription.status in [
                        "active",
                        "trialing",
                    ]
            except Exception:
                # If subscription lookup fails, set to inactive
                subscription_status = "none"
                subscription_is_active = False

    return JSONResponse(
        content={
            "id": current_user.id,
            "email": current_user.email,
            "first_name": current_user.user_metadata.first_name,
            "last_name": current_user.user_metadata.last_name,
            "organization_id": organization_id,
            "organization_name": organization_name,
            "role": role,
            "subscription_status": subscription_status,
            "subscription_is_active": subscription_is_active,
        }
    )


@router.post("/update-profile", response_model=UpdateProfileResponse)
async def update_profile(
    request: UpdateProfileRequest,
    current_user: PlatformUser = Depends(require_auth),
):
    """Update user profile (first name and last name)."""
    await update_user_profile_metadata(
        current_user.id, request.first_name, request.last_name
    )

    return UpdateProfileResponse(
        success=True, first_name=request.first_name, last_name=request.last_name
    )
