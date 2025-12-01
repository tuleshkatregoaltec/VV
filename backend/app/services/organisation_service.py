from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import Sequence
from datetime import datetime, timezone
import asyncio

from workos import WorkOSClient
from backend.app.db.models import Organisation, User
from backend.app.config import settings


workos = WorkOSClient(
    api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID
)


async def get_organisation_by_id(session: AsyncSession, org_id: str) -> Organisation | None:
    """Get organisation by ID"""
    return await session.get(Organisation, org_id)


async def get_organisation_by_domain(session: AsyncSession, domain: str) -> Organisation | None:
    """Get organisation by email domain"""
    result = await session.exec(
        select(Organisation).where(Organisation.email_domain == domain)
    )
    return result.first()


async def get_active_user_count(session: AsyncSession, org_id: str) -> int:
    """Count active users in an organisation"""
    result = await session.exec(
        select(func.count())
        .select_from(User)
        .where(User.organisation_id == org_id, User.is_active == True)
    )
    return result.one()


async def create_organisation(
    session: AsyncSession, name: str, domain: str, max_users: int
) -> Organisation:
    """Create organisation in WorkOS and local DB"""

    workos_org = await asyncio.to_thread(
        workos.organizations.create_organization,
        name=name,
        domain_data=[{"domain": domain, "state": "pending"}],
    )

    organisation = Organisation(
        id=workos_org.id,
        name=workos_org.name,
        email_domain=domain,
        max_users=max_users,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    session.add(organisation)
    await session.commit()
    await session.refresh(organisation)
    return organisation


async def list_organisations(session: AsyncSession) -> Sequence[Organisation]:
    """List all organisations"""
    organisations = await session.exec(select(Organisation))
    return organisations.all()


async def update_organisation(
    session: AsyncSession, org_id: str, max_users: int, is_active: bool
) -> Organisation | None:
    """Update organisation settings"""
    organisation = await session.get(Organisation, org_id)
    
    if not organisation:
        return None

    organisation.max_users = max_users
    organisation.is_active = is_active
    organisation.updated_at = datetime.now(timezone.utc)

    session.add(organisation)
    await session.commit()
    await session.refresh(organisation)
    
    return organisation


async def delete_organisation(session: AsyncSession, org_id: str) -> bool:
    """Delete organisation from WorkOS and local DB"""
    organisation = await session.get(Organisation, org_id)
    
    if not organisation:
        return False

    await asyncio.to_thread(workos.organizations.delete_organization, org_id)

    # Delete locally
    await session.delete(organisation)
    await session.commit()
    
    return True
