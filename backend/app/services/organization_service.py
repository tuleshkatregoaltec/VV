from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import Sequence
from datetime import datetime, timezone
import asyncio

from workos import WorkOSClient
from backend.app.db.models import Organization, User
from backend.app.config import settings


workos = WorkOSClient(
    api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID
)


async def get_organization_by_id(
    session: AsyncSession, org_id: str
) -> Organization | None:
    """Get organization by ID"""
    return await session.get(Organization, org_id)


async def get_organization_by_domain(
    session: AsyncSession, domain: str
) -> Organization | None:
    """Get organization by email domain"""
    result = await session.exec(
        select(Organization).where(Organization.email_domain == domain)
    )
    return result.first()


async def get_active_user_count(session: AsyncSession, org_id: str) -> int:
    """Count active users in an organization"""
    result = await session.exec(
        select(func.count())
        .select_from(User)
        .where(User.organization_id == org_id, User.is_active)
    )
    return result.one()


async def create_organization(
    session: AsyncSession, name: str, domain: str, max_users: int
) -> Organization:
    """Create organization in WorkOS and local DB"""

    workos_org = await asyncio.to_thread(
        workos.organizations.create_organization,
        name=name,
        domain_data=[{"domain": domain, "state": "pending"}],
    )

    organization = Organization(
        id=workos_org.id,
        name=workos_org.name,
        email_domain=domain,
        max_users=max_users,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    session.add(organization)
    await session.commit()
    await session.refresh(organization)
    return organization


async def list_organizations(session: AsyncSession) -> Sequence[Organization]:
    """List all organizations"""
    organizations = await session.exec(select(Organization))
    return organizations.all()


async def update_organization(
    session: AsyncSession, org_id: str, max_users: int, is_active: bool
) -> Organization | None:
    """Update organization settings"""
    organization = await session.get(Organization, org_id)

    if not organization:
        return None

    organization.max_users = max_users
    organization.is_active = is_active
    organization.updated_at = datetime.now(timezone.utc)

    session.add(organization)
    await session.commit()
    await session.refresh(organization)

    return organization


async def delete_organization(session: AsyncSession, org_id: str) -> bool:
    """Delete organization from WorkOS and local DB"""
    organization = await session.get(Organization, org_id)

    if not organization:
        return False

    await asyncio.to_thread(workos.organizations.delete_organization, org_id)

    # Delete locally
    await session.delete(organization)
    await session.commit()

    return True
