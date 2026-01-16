import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_db_session
from app.routers.dependencies import require_admin
from app.schemas.organization import (
    OrganizationCreateRequest,
    OrganizationDetailResponse,
    OrganizationResponse,
    OrganizationUpdateRequest,
)
from app.schemas.user import UserUpdateRequest
from app.schemas.token_usage import UserTokenStatsResponse
from app.services.organization_service import (
    create_organization as create_organization_service,
    delete_organization as delete_organization_service,
    get_active_user_count,
    get_organization_by_id,
    list_organizations as list_organizations_service,
    update_organization as update_organization_service,
)
from app.services.token_usage_service import token_usage_service

from app.services.auth_service import get_user_by_id, update_app_metadata

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


@router.post(
    "/organizations",
    status_code=status.HTTP_201_CREATED,
    response_model=OrganizationResponse,
)
async def create_organization(
    organization_in: OrganizationCreateRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new organization"""
    if not organization_in.domain:
        raise HTTPException(status_code=400, detail="Domain must be provided.")

    try:
        organization = await create_organization_service(
            db=db,
            name=organization_in.name,
            domain=organization_in.domain,
            max_users=organization_in.max_users,
        )
        response = OrganizationResponse.model_validate(organization)
        response.active_user_count = 0
        return response
    except Exception:
        logger.exception("Failed to create organization")
        raise HTTPException(status_code=400, detail="Failed to create organization")


@router.get("/organizations", response_model=List[OrganizationResponse])
async def list_organization(db: AsyncSession = Depends(get_db_session)):
    """List all organizations with user counts"""
    organizations = await list_organizations_service(db)

    result = []
    for org in organizations:
        active_count = await get_active_user_count(db, org.id)
        response = OrganizationResponse.model_validate(org)
        response.active_user_count = active_count
        result.append(response)

    return result


@router.get("/organizations/{org_id}", response_model=OrganizationDetailResponse)
async def get_organization(org_id: str, db: AsyncSession = Depends(get_db_session)):
    """Get organization details with user list"""
    organization = await get_organization_by_id(db, org_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    active_count = await get_active_user_count(db, org_id)


    user_list = []

    for user_id in organization.users:
        user = await get_user_by_id(user_id)

        if user is not None:

            usage = await token_usage_service.get_today_usage(db, user.id)
            tokens_used = usage.total_tokens if usage else 0
            daily_limit = user.metadata.daily_token_limit
            usage_percentage = (tokens_used / daily_limit * 100) if daily_limit > 0 else 0

            user_list.append(
                {
                    "id": user.id,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.metadata.first_name,
                    "is_active": user.metadata.last_name,
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
):
    """Update organization settings"""
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
async def delete_organization(org_id: str, db: AsyncSession = Depends(get_db_session)):
    """Delete organization"""
    success = await delete_organization_service(db, org_id)
    if not success:
        raise HTTPException(status_code=404, detail="Organization not found")
    return None


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    user_update: UserUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Update user is_active status and/or daily token limit"""

    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user_update.is_active is not None:
        user.metadata.is_active = user_update.is_active
    if user_update.daily_token_limit is not None:
        user.metadata.daily_token_limit = user_update.daily_token_limit
    # (updated by goauth) user.updated_at = datetime.now(timezone.utc)

    update_app_metadata(user)

    return {
        "id": user.id,
        "email": user.email,
        "is_active": user.metadata.is_active,
        "updated_at": user.auth_user.updated_at,
    }