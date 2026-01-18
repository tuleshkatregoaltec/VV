import asyncio
from uuid import uuid4
from datetime import datetime, timezone
from typing import Sequence

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from workos import WorkOSClient

from app.config import settings
from app.db.models import Organization

from app.services.auth_service import get_user_by_id


async def get_free_org_id(db: AsyncSession):
    done = False
    while not done:
        uuid = uuid4()
        uuid_str = str(uuid)

        done = await get_organization_by_id(db, uuid_str) is None
    return uuid_str


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


async def get_organization_for_user(
    db: AsyncSession, user_id: str
) -> Organization | None:
    """Get organization by user id"""
    result = await db.exec(
        select(Organization).where(Organization.users.contains([user_id]))
    )
    return result.first()


async def get_active_user_count(db: AsyncSession, org_id: str) -> int:
    """Count active users in an organization"""
    # get list of users

    result = await db.exec(
        select(Organization.users)
        .select_from(Organization)
        .where(Organization.id == org_id)
    )

    count = 0

    for user_id in result:
        user = await get_user_by_id(user_id)

        if user is not None:
            # user exists
            if user.app_metadata.is_active:
                count += 1

    return count


async def create_organization(
    db: AsyncSession, name: str, domain: str, max_users: int
) -> Organization:
    """Create organization in WorkOS and local DB"""

    organization = Organization(
        id=await get_free_org_id(db),
        name=name,
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

    # Delete locally
    await db.delete(organization)
    await db.commit()

    return True
