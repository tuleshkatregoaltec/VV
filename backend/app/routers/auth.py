from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlmodel import Session

from backend.app.services import auth_service
from backend.app.db.session import get_db_session

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
    session: Session = Depends(get_db_session),
):
    """Handle OAuth callback from WorkOS"""
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    return await auth_service.handle_callback(request, code, session)


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
