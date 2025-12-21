import asyncio
from datetime import datetime, timezone
from typing import Sequence

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession
from workos import WorkOSClient

from backend.app.config import settings
from backend.app.db.models import Organization, User


workos = WorkOSClient(
    api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID
)


async def get_organization_by_id(db: AsyncSession, org_id: str) -> Organization | None:
    """Get organization by ID"""
    return await db.get(Organization, org_id)


async def get_organization_by_domain(
    db: AsyncSession, domain: str
) -> Organization | None:
    """Get organization by email domain"""
    result = await db.exec(
        select(Organization).where(Organization.email_domain == domain)
    )
    return result.first()


async def get_active_user_count(db: AsyncSession, org_id: str) -> int:
    """Count active users in an organization"""
    result = await db.exec(
        select(func.count())
        .select_from(User)
        .where(User.organization_id == org_id, User.is_active)
    )
    return result.one()


async def create_organization(
    db: AsyncSession, name: str, domain: str, max_users: int
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

    db.add(organization)
    await db.commit()
    await db.refresh(organization)
    return organization


async def list_organizations(db: AsyncSession) -> Sequence[Organization]:
    """List all organizations"""
    organizations = await db.exec(select(Organization))
    return organizations.all()


async def update_organization(
    db: AsyncSession, org_id: str, max_users: int, is_active: bool
) -> Organization | None:
    """Update organization settings"""
    organization = await db.get(Organization, org_id)

    if not organization:
        return None

    organization.max_users = max_users
    organization.is_active = is_active
    organization.updated_at = datetime.now(timezone.utc)

    db.add(organization)
    await db.commit()
    await db.refresh(organization)

    return organization


async def delete_organization(db: AsyncSession, org_id: str) -> bool:
    """Delete organization from WorkOS and local DB"""
    organization = await db.get(Organization, org_id)

    if not organization:
        return False

    await asyncio.to_thread(workos.organizations.delete_organization, org_id)

    # Delete locally
    await db.delete(organization)
    await db.commit()

    return True
