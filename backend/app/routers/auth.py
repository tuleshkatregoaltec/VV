from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.db.session import get_db_session
from backend.app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login():
    """Redirect to WorkOS login page"""
    authorization_url = await auth_service.get_authorization_url()
    return RedirectResponse(url=authorization_url)


@router.get("/callback")
async def auth_callback(
    request: Request,
    code: str | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Handle OAuth callback from WorkOS"""
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    return await auth_service.handle_callback(request, code, db)


@router.get("/logout")
async def logout(request: Request):
    """Logout user and clear session"""
    return await auth_service.logout_user(request)


@router.get("/session")
async def get_session(request: Request):
    """Get current session info"""
    session_info = await auth_service.get_session_info(request)

    if not session_info:
        return JSONResponse(
            status_code=401, content={"authenticated": False, "user": None}
        )

    return JSONResponse(content=session_info)


@router.get("/me")
async def get_user(request: Request):
    """Get current authenticated user (protected endpoint)"""
    user = await auth_service.get_current_user(request)
    return JSONResponse(content=user)
