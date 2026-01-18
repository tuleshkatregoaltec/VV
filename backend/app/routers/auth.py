from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_db_session
from app.routers.dependencies import require_auth

from app.providers.auth.platform_user import PlatformUser


from app.services import auth_service
from app.services import organization_service
from app.config import settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/sync")
async def sync_callback(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    current_user: PlatformUser = Depends(require_auth),
):
    """
    Sync orgs and activity state
    """

    organization = await organization_service.get_organization_for_user(
        db, current_user.id
    )

    should_commit = False

    if not organization:
        # no org, try to match on email

        if current_user.app_metadata.is_active:
            # active but no org, mark as inactive
            current_user.app_metadata.is_active = False
            await auth_service.update_app_metadata(current_user)


        email_domain = current_user.email.split("@")[1].lower()

        organization = await organization_service.get_organization_by_domain(
            db, email_domain
        )


        if not organization:
            # No org found by membership or domain
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/no-org")

    # user has (one) org (get_org_for_user returned first OR matched by domain)

    # check if org is active
    if not organization.is_active:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/deactivated")

    # check if user is active
    if not current_user.app_metadata.is_active:
        active_user_count = await organization_service.get_active_user_count(
            db, organization.id
        )
        # Determine if user should be active based on org limit
        is_active = active_user_count < organization.max_users

        if is_active:
            # set user as active
            current_user.app_metadata.is_active = True
            await auth_service.update_app_metadata(current_user)

            should_commit = True
        else:
            # user not active and no free slots
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/deactivated")
    
    if should_commit:
        # sync
        await organization_service.add_user_to_organization(db, organization.id, current_user.id)

    # user is active, return success
    return JSONResponse(content={"success": True})


@router.get("/me")
async def get_user(
    request: Request,
    current_user: PlatformUser = Depends(require_auth),
):
    """Get current authenticated user (protected endpoint)"""

    return JSONResponse(content=await current_user.get_user_info())
