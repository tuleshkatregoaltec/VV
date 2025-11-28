from sqlmodel import Session, select, func
from typing import Optional
from datetime import datetime, timezone
from workos import WorkOSClient
from backend.app.db.models import Organisation, User
from backend.app.config import settings


workos = WorkOSClient(
    api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID
)


def get_organisation_by_id(session: Session, org_id: str) -> Optional[Organisation]:
    """Get organisation by ID"""
    return session.get(Organisation, org_id)


def get_organisation_by_domain(session: Session, domain: str) -> Optional[Organisation]:
    """Get organisation by email domain"""
    return session.exec(
        select(Organisation).where(Organisation.email_domain == domain)
    ).first()


def get_active_user_count(session: Session, org_id: str) -> int:
    """Count active users in an organisation"""
    return session.exec(
        select(func.count())
        .select_from(User)
        .where(User.organisation_id == org_id, User.is_active == True)
    ).one()


def create_organisation(
    session: Session, name: str, domains: list[str], max_users: int = 5
) -> Organisation:
    """Create organisation in WorkOS and local DB"""
    # Create in WorkOS
    workos_org = workos.organizations.create_organization(
        name=name,
        domain_data=[{"domain": domain, "state": "pending"} for domain in domains],
    )

    # Create locally
    organisation = Organisation(
        id=workos_org.id,
        name=workos_org.name,
        email_domain=domains[0],
        max_users=max_users,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(organisation)
    session.commit()
    session.refresh(organisation)
    return organisation


def list_organisations(session: Session) -> list[Organisation]:
    """List all organisations"""
    return list(session.exec(select(Organisation)).all())


def update_organisation(
    session: Session, org_id: str, max_users: int, is_active: bool
) -> Optional[Organisation]:
    """Update organisation settings"""
    organisation = session.get(Organisation, org_id)
    if not organisation:
        return None

    organisation.max_users = max_users
    organisation.is_active = is_active
    organisation.updated_at = datetime.now(timezone.utc)

    session.add(organisation)
    session.commit()
    session.refresh(organisation)
    return organisation


def delete_organisation(session: Session, org_id: str) -> bool:
    """Delete organisation from WorkOS and local DB"""
    organisation = session.get(Organisation, org_id)
    if not organisation:
        return False

    # Delete from WorkOS
    workos.organizations.delete_organization(org_id)

    # Delete locally
    session.delete(organisation)
    session.commit()
    return True
