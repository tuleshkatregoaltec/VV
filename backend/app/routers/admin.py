from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List
from pydantic import BaseModel
from backend.app.db.session import get_db_session
from backend.app.db.models import Organisation
from backend.app.routers.dependencies import require_auth
from backend.app.config import settings
from workos import WorkOSClient

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_auth)])

workos = WorkOSClient(api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID)

class OrganisationCreateRequest(BaseModel):
    name: str
    domains: List[str]
    max_users: int = 5

@router.post("/organisations")
async def create_organisation(org_in: OrganisationCreateRequest, session: Session = Depends(get_db_session)):
    if not org_in.domains:
        raise HTTPException(400, "At least one domain is required")

    try:
        workos_org = workos.organizations.create_organization(
            name=org_in.name,
            domain_data=[{"domain": domain, "state": "pending"} for domain in org_in.domains]
        )
    except Exception as e:
        raise HTTPException(400, f"WorkOS API error: {e}")

    organisation = Organisation(
        id=workos_org.id,
        name=workos_org.name,
        email_domain=org_in.domains[0],
        max_users=org_in.max_users,
        is_active=True
    )
    session.add(organisation)
    session.commit()
    session.refresh(organisation)
    return organisation

@router.get("/organisations")
async def list_organisations(session: Session = Depends(get_db_session)):
    return session.exec(select(Organisation)).all()

@router.get("/organisations/{org_id}")
async def get_organisation(org_id: str, session: Session = Depends(get_db_session)):
    organisation = session.get(Organisation, org_id)
    if not organisation:
        raise HTTPException(404, "Organization not found")
    return organisation

@router.put("/organisations/{org_id}")
async def update_organisation(
    org_id: str,
    org_in: OrganisationCreateRequest,  # Reuse or create update schema with optional fields
    session: Session = Depends(get_db_session)
):
    organisation = session.get(Organisation, org_id)
    if not organisation:
        raise HTTPException(404, "Organization not found")

    try:
        workos_org = workos.organizations.update_organization(
            organization_id=org_id,
            name=org_in.name,
            domain_data=[{"domain": domain, "state": "verified"} for domain in org_in.domains]
        )
    except Exception as e:
        raise HTTPException(400, f"WorkOS API error: {e}")

    organisation.name = workos_org.name
    organisation.email_domain = org_in.domains[0]
    organisation.max_users = org_in.max_users
    session.add(organisation)
    session.commit()
    session.refresh(organisation)
    return organisation

@router.delete("/organisations/{org_id}")
async def delete_organisation(org_id: str, session: Session = Depends(get_db_session)):
    organisation = session.get(Organisation, org_id)
    if not organisation:
        raise HTTPException(404, "Organization not found")
    try:
        workos.organizations.delete_organization(org_id)
    except Exception as e:
        raise HTTPException(400, f"WorkOS API error: {e}")
    session.delete(organisation)
    session.commit()
    return {"detail": "Organization deleted"}
