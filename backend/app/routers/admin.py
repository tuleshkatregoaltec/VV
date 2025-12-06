from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import List
from datetime import datetime, timezone

from backend.app.db.session import get_db_session
from backend.app.db.models import User
from backend.app.routers.dependencies import require_admin

# Import your service functions
from backend.app.services.organization_service import (
    create_organization as create_organization_service,
    list_organizations as list_organizations_service,
    get_organization_by_id,
    get_active_user_count,
    update_organization as update_organization_service,
    delete_organization as delete_organization_service,
)
from backend.app.schemas.organization import (
    OrganizationCreateRequest,
    OrganizationUpdateRequest,
    OrganizationResponse,
    OrganizationDetailResponse,
)
from backend.app.schemas.user import UserUpdateRequest

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
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new organization"""
    if not organization_in.domain:
        raise HTTPException(status_code=400, detail="Domain must be provided.")

    try:
        organization = await create_organization_service(
            session=session,
            name=organization_in.name,
            domain=organization_in.domain,
            max_users=organization_in.max_users,
        )
        response = OrganizationResponse.model_validate(organization)
        response.active_user_count = 0
        return response
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to create organization: {str(e)}"
        )


@router.get("/organizations", response_model=List[OrganizationResponse])
async def list_organization(session: AsyncSession = Depends(get_db_session)):
    """List all organizations with user counts"""
    organizations = await list_organizations_service(session)

    result = []
    for org in organizations:
        active_count = await get_active_user_count(session, org.id)
        response = OrganizationResponse.model_validate(org)
        response.active_user_count = active_count
        result.append(response)

    return result


@router.get("/organizations/{org_id}", response_model=OrganizationDetailResponse)
async def get_organization(
    org_id: str, session: AsyncSession = Depends(get_db_session)
):
    """Get organization details with user list"""
    organization = await get_organization_by_id(session, org_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    active_count = await get_active_user_count(session, org_id)

    result = await session.exec(select(User).where(User.organization_id == org_id))
    users = result.all()

    user_list = [
        {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "last_login": user.last_login,
        }
        for user in users
    ]

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
    session: AsyncSession = Depends(get_db_session),
):
    """Update organization settings"""
    organization = await update_organization_service(
        session=session,
        org_id=org_id,
        max_users=organization_update.max_users,
        is_active=organization_update.is_active,
    )

    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    active_count = await get_active_user_count(session, org_id)

    response = OrganizationResponse.model_validate(organization)
    response.active_user_count = active_count
    return response


@router.delete("/organizations/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    org_id: str, session: AsyncSession = Depends(get_db_session)
):
    """Delete organization"""
    success = await delete_organization_service(session, org_id)
    if not success:
        raise HTTPException(status_code=404, detail="Organization not found")
    return None


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    user_update: UserUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Update user is_active status"""

    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = user_update.is_active
    user.updated_at = datetime.now(timezone.utc)

    session.add(user)
    await session.commit()
    await session.refresh(user)

    return {
        "id": user.id,
        "email": user.email,
        "is_active": user.is_active,
        "updated_at": user.updated_at,
    }
