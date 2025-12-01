from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import List
from datetime import datetime, timezone

from backend.app.db.session import get_db_session
from backend.app.db.models import User
from backend.app.routers.dependencies import require_auth
# Import your service functions
from backend.app.services.organisation_service import (
    create_organisation as create_organisation_service,
    list_organisations as list_organisations_service,
    get_organisation_by_id,
    get_active_user_count,
    update_organisation as update_organisation_service,
    delete_organisation as delete_organisation_service,
)
from backend.app.schemas.organisation import (
    OrganisationCreateRequest,
    OrganisationUpdateRequest,
    OrganisationResponse,
    OrganisationDetailResponse,
)
from backend.app.schemas.user import UserUpdateRequest

router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_auth)]
)


@router.post(
    "/organisations",
    status_code=status.HTTP_201_CREATED,
    response_model=OrganisationResponse,
)
async def create_organisation(
    organisation_in: OrganisationCreateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new organisation"""
    if not organisation_in.domain:
        raise HTTPException(status_code=400, detail="Domain must be provided.")

    try:
        organisation = await create_organisation_service(
            session=session,
            name=organisation_in.name,
            domain=organisation_in.domain,
            max_users=organisation_in.max_users,
        )
        response = OrganisationResponse.model_validate(organisation)
        response.active_user_count = 0
        return response
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to create organisation: {str(e)}"
        )

@router.get("/organisations", response_model=List[OrganisationResponse])
async def list_organisation(session: AsyncSession = Depends(get_db_session)):
    """List all organisations with user counts"""
    organisations = await list_organisations_service(session)

    result = []
    for org in organisations:
        active_count = await get_active_user_count(session, org.id)
        response = OrganisationResponse.model_validate(org)
        response.active_user_count = active_count
        result.append(response)

    return result

@router.get("/organisations/{org_id}", response_model=OrganisationDetailResponse)
async def get_organisation(
    org_id: str, session: AsyncSession = Depends(get_db_session)
):
    """Get organisation details with user list"""
    organisation = await get_organisation_by_id(session, org_id)
    if not organisation:
        raise HTTPException(status_code=404, detail="Organisation not found")

    active_count = await get_active_user_count(session, org_id)

    result = await session.exec(select(User).where(User.organisation_id == org_id))
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

    org_response = OrganisationResponse.model_validate(organisation)
    org_response.active_user_count = active_count

    return OrganisationDetailResponse(
        organisation=org_response,
        users=user_list,
    )

@router.put("/organisations/{org_id}", response_model=OrganisationResponse)
async def update_organisation(
    org_id: str,
    organisation_update: OrganisationUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Update organisation settings"""
    organisation = await update_organisation_service(
        session=session,
        org_id=org_id,
        max_users=organisation_update.max_users,
        is_active=organisation_update.is_active,
    )

    if not organisation:
        raise HTTPException(status_code=404, detail="Organisation not found")

    active_count = await get_active_user_count(session, org_id)

    response = OrganisationResponse.model_validate(organisation)
    response.active_user_count = active_count
    return response

@router.delete("/organisations/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organisation(
    org_id: str, session: AsyncSession = Depends(get_db_session)
):
    """Delete organisation"""
    success = await delete_organisation_service(session, org_id)
    if not success:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return None

@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    user_update: UserUpdateRequest,
    session: AsyncSession = Depends(get_db_session)
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
        "updated_at": user.updated_at
    }
