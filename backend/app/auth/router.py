from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from datetime import datetime, timezone

from app.postgres import get_db_session
from app.core.dependencies import require_auth
from app.providers.auth.platform_user import PlatformUser
from app.auth import service as auth_service
from app.organization import service as organization_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/me")
async def get_user(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    current_user: PlatformUser = Depends(require_auth),
):
    """Get current authenticated user with organization context."""

    # Get organization via membership
    membership = await organization_service.get_membership_for_user(db, current_user.id)

    organization_id = None
    organization_name = None
    role = membership.role if membership else "user"

    # Check if global admin
    if current_user.is_admin():
        role = "admin"

    if membership:
        from app.postgres.models import Organization
        org = await db.get(Organization, membership.organization_id)
        if org:
            organization_id = org.id
            organization_name = org.name

    return JSONResponse(content={
        "id": current_user.id,
        "email": current_user.email,
        "first_name": current_user.user_metadata.first_name,
        "last_name": current_user.user_metadata.last_name,
        "organization_id": organization_id,
        "organization_name": organization_name,
        "role": role,
    })
