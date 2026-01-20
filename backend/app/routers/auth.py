from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from datetime import datetime, timezone

from app.db.session import get_db_session
from app.routers.dependencies import require_auth

from app.providers.auth.platform_user import PlatformUser

from app.services import auth_service
from app.services import organization_service
from app.schemas.onboarding import SyncUserResponse
from app.db.models.subscriptions import Subscription

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/sync", response_model=SyncUserResponse)
async def sync_user_organization(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    current_user: PlatformUser = Depends(require_auth),
):
    """Sync user organization membership and activation status."""
    organization = await organization_service.get_organization_for_user(
        db, current_user.id
    )

    if not organization:
        await auth_service.sync_user_app_metadata(
            user_id=current_user.id,
            is_active=False,
            role="user",
        )
        raise HTTPException(
            status_code=404,
            detail="User does not belong to any organization. Please contact support.",
        )

    if not organization.is_active:
        await auth_service.sync_user_app_metadata(
            user_id=current_user.id,
            is_active=False,
            role="user",
        )
        raise HTTPException(
            status_code=403,
            detail="Organization is deactivated. Please contact your administrator.",
        )

    is_org_admin = organization.organization_admin_id == current_user.id
    role = "organization_admin" if is_org_admin else "user"

    subscription = None
    if organization.subscription_id:
        stmt = select(Subscription).where(
            Subscription.id == organization.subscription_id
        )
        result = await db.execute(stmt)
        subscription = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    within_paid_period = (
        subscription is not None and now < subscription.current_period_end
    )

    active_user_count = len(organization.users)

    if within_paid_period:
        is_active = True
    else:
        is_active = active_user_count <= organization.max_users

        if subscription and subscription.cancel_at_period_end:
            await auth_service.sync_user_app_metadata(
                user_id=current_user.id,
                is_active=False,
                role=role,
            )
            raise HTTPException(
                status_code=403,
                detail="Subscription has expired. Please renew to regain access.",
            )

    if not is_active:
        await auth_service.sync_user_app_metadata(
            user_id=current_user.id,
            is_active=False,
            role=role,
        )
        raise HTTPException(
            status_code=403,
            detail="Organization has exceeded seat limit. Administrator must remove users or upgrade subscription.",
        )

    await auth_service.sync_user_app_metadata(
        user_id=current_user.id,
        is_active=True,
        role=role,
    )

    return SyncUserResponse(
        success=True,
        organization_id=organization.id,
        is_active=True,
        role=role,
    )


@router.get("/me")
async def get_user(
    request: Request,
    current_user: PlatformUser = Depends(require_auth),
):
    """Get current authenticated user."""

    return JSONResponse(content=await current_user.get_user_info())
