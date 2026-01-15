from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_db_session
from app.routers.dependencies import require_auth

from app.providers.auth.platform_user import PlatformUser


from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


# TODO: add /sync endpoint called from frontend when signed in

# @router.get("/callback")
# async def auth_callback(
#    request: Request,
#    code: str | None = None,
#    db: AsyncSession = Depends(get_db_session),
# ):
#    """Handle OAuth callback from WorkOS"""
#    if not code:
#       raise HTTPException(status_code=400, detail="Missing authorization code")
#    return await auth_service.handle_callback(request, code, db)


@router.get("/logout")
async def logout(
    request: Request,
    current_user: PlatformUser = Depends(require_auth),
):
    """Logout user and clear session"""
    return await auth_service.logout_user(current_user)


@router.get("/me")
async def get_user(
    request: Request,
    current_user: PlatformUser = Depends(require_auth),
):
    """Get current authenticated user (protected endpoint)"""

    return JSONResponse(content=current_user.get_user_info())
