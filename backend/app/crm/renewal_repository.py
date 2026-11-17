from __future__ import annotations

from sqlalchemy import ARRAY, String, any_, literal
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.import_models import CrmPropertyContactClaim
from app.crm.models import CrmAgentAreaPreference

# Include disposals and uncertain rows: filtering them out first can resurrect an
# older verified acquisition for the same person.


async def get_area_preference(db: AsyncSession, user_id, organization_id):
    return (
        await db.exec(
            select(CrmAgentAreaPreference).where(
                CrmAgentAreaPreference.user_id == user_id,
                CrmAgentAreaPreference.organization_id == organization_id,
            )
        )
    ).first()


async def list_current_owner_claims(db: AsyncSession, organization_id, candidate_keys):
    return (
        await db.exec(
            select(CrmPropertyContactClaim)
            .where(
                CrmPropertyContactClaim.organization_id == organization_id,
                CrmPropertyContactClaim.unit_candidate_key.in_(candidate_keys),  # type: ignore[union-attr]
            )
            .order_by(CrmPropertyContactClaim.confidence_score.desc())  # type: ignore[attr-defined]
        )
    ).all()


async def list_imported_unit_keys(db: AsyncSession, organization_id) -> list[str]:
    """Potential imported units; current assessment and contact policy decide known owners."""
    return list(
        (
            await db.exec(
                select(CrmPropertyContactClaim.unit_candidate_key)
                .where(
                    CrmPropertyContactClaim.organization_id == organization_id,
                    CrmPropertyContactClaim.unit_candidate_key.is_not(None),  # type: ignore[union-attr]
                    CrmPropertyContactClaim.unit_candidate_key != "",
                )
                .distinct()
            )
        ).all()
    )


async def has_imported_unit_keys(
    db: AsyncSession, organization_id, candidate_keys: list[str]
) -> bool:
    """Manual-only units do not depend on imported ownership evidence availability."""
    if not candidate_keys:
        return False
    keys = any_(literal(sorted(set(candidate_keys)), ARRAY(String)))
    return (
        await db.exec(
            select(CrmPropertyContactClaim.id)
            .where(
                CrmPropertyContactClaim.organization_id == organization_id,
                CrmPropertyContactClaim.unit_candidate_key == keys,
            )
            .limit(1)
        )
    ).first() is not None


def save(db: AsyncSession, record):
    db.add(record)
