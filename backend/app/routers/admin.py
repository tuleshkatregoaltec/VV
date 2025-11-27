from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select, func
from typing import List
from datetime import datetime, timezone
from workos import WorkOSClient


from backend.app.db.session import get_db_session
from backend.app.db.models import Organisation, User
from backend.app.routers.dependencies import require_auth
from backend.app.config import settings
from backend.app.schemas.organisation import (
    OrganisationCreateRequest,
    OrganisationUpdateRequest,
    OrganisationResponse,
    OrganisationDetailResponse,
)

router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_auth)]
)
workos = WorkOSClient(
    api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID
)


@router.post(
    "/organisations",
    status_code=status.HTTP_201_CREATED,
    response_model=OrganisationResponse,
)
async def create_organisation(
    organisation_in: OrganisationCreateRequest, session: Session = Depends(get_db_session)
):
    if not organisation_in.domains:
        raise HTTPException(status_code=400, detail="At least one domain is required")

    try:
        workos_org = workos.organizations.create_organization(
            name=organisation_in.name,
            domain_data=[{"domain": domain, "state": "pending"} for domain in organisation_in.domains],
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"WorkOS API error: {str(e)}")

    organisation = Organisation(
        id=workos_org.id,
        name=workos_org.name,
        email_domain=organisation_in.domains[0],
        max_users=organisation_in.max_users,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(organisation)
    session.commit()
    session.refresh(organisation)

    return OrganisationResponse(
        id=organisation.id,
        name=organisation.name,
        email_domain=organisation.email_domain,
        max_users=organisation.max_users,
        is_active=organisation.is_active,
        active_user_count=0,
        created_at=organisation.created_at,
        updated_at=organisation.updated_at,
    )



@router.get("/organisations", response_model=List[OrganisationResponse])
async def list_organisations(session: Session = Depends(get_db_session)):
    organisations = session.exec(select(Organisation)).all()

    result = []
    for org in organisations:
        active_count = session.exec(
            select(func.count())
            .select_from(User)
            .where(User.organisation_id == org.id, User.is_active == True)
        ).one()

        result.append(
            OrganisationResponse(
                id=org.id,
                name=org.name,
                email_domain=org.email_domain,
                max_users=org.max_users,
                is_active=org.is_active,
                active_user_count=active_count,
                created_at=org.created_at,
                updated_at=org.updated_at,
            )
        )

    return result


@router.get("/organisations/{org_id}", response_model=OrganisationDetailResponse)
async def get_organisation(org_id: str, session: Session = Depends(get_db_session)):
    """Get organization details with user list"""
    organisation = session.get(Organisation, org_id)
    if not organisation:
        raise HTTPException(status_code=404, detail="Organization not found")

    active_count = session.exec(
        select(func.count())
        .select_from(User)
        .where(User.organisation_id == org_id, User.is_active == True)
    ).one()

    users = session.exec(select(User).where(User.organisation_id == org_id)).all()

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

    return OrganisationDetailResponse(
        organisation=OrganisationResponse(
            id=organisation.id,
            name=organisation.name,
            email_domain=organisation.email_domain,
            max_users=organisation.max_users,
            is_active=organisation.is_active,
            active_user_count=active_count,
            created_at=organisation.created_at,
            updated_at=organisation.updated_at,
        ),
        users=user_list,
    )


@router.put("/organisations/{org_id}", response_model=OrganisationResponse)
async def update_organisation(
    org_id: str,
    organisation_update: OrganisationUpdateRequest,
    session: Session = Depends(get_db_session),
):
    organisation = session.get(Organisation, org_id)
    if not organisation:
        raise HTTPException(status_code=404, detail="Organization not found")

    organisation.max_users = organisation_update.max_users
    organisation.is_active = organisation_update.is_active
    organisation.updated_at = datetime.now(timezone.utc)

    session.add(organisation)
    session.commit()
    session.refresh(organisation)

    active_count = session.exec(
        select(func.count())
        .select_from(User)
        .where(User.organisation_id == org_id, User.is_active == True)
    ).one()

    return OrganisationResponse(
        id=organisation.id,
        name=organisation.name,
        email_domain=organisation.email_domain,
        max_users=organisation.max_users,
        is_active=organisation.is_active,
        active_user_count=active_count,
        created_at=organisation.created_at,
        updated_at=organisation.updated_at,
    )


@router.delete("/organisations/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organisation(org_id: str, session: Session = Depends(get_db_session)):
    """Delete organization from WorkOS and local DB"""
    organisation = session.get(Organisation, org_id)
    if not organisation:
        raise HTTPException(status_code=404, detail="Organization not found")

    try:
        workos.organizations.delete_organization(org_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"WorkOS API error: {str(e)}")

    session.delete(organisation)
    session.commit()
    return None
