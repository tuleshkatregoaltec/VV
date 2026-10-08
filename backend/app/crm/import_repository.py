from __future__ import annotations

from sqlalchemy import and_, delete, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.import_models import (
    CrmContactImport,
    CrmContactList,
    CrmPropertyContactClaim,
)


async def list_rental_refresh_claims(db: AsyncSession, import_id, organization_id):
    statement = select(CrmPropertyContactClaim).where(
        CrmPropertyContactClaim.organization_id == organization_id
    )
    if import_id is not None:
        statement = statement.where(CrmPropertyContactClaim.import_id == import_id)
    claims = (await db.exec(statement.with_for_update())).all()
    return claims


async def list_claims_for_rematch(
    db, audit_resolution_methods, import_id, only_unmatched, organization_id
):
    statement = select(CrmPropertyContactClaim).where(
        CrmPropertyContactClaim.organization_id == organization_id
    )
    if import_id is not None:
        statement = statement.where(CrmPropertyContactClaim.import_id == import_id)
    if audit_resolution_methods:
        statement = statement.where(
            CrmPropertyContactClaim.evidence["property_identity_resolution"]["method"]
            .as_string()
            .in_(sorted(audit_resolution_methods))
        )
    elif only_unmatched:
        statement = statement.where(CrmPropertyContactClaim.ownership_status == "unmatched")
    claims = (await db.exec(statement)).all()
    return claims


async def count_import_claim_metrics(db: AsyncSession, organization_id, record_id):
    has_contact = or_(
        CrmPropertyContactClaim.phone_primary.is_not(None),
        CrmPropertyContactClaim.phone_alternate.is_not(None),
        CrmPropertyContactClaim.email_primary.is_not(None),
    )
    metrics_result = await db.exec(
        select(
            func.count(),
            func.count().filter(has_contact),
            func.count().filter(CrmPropertyContactClaim.lead_id.is_not(None)),
            func.count().filter(
                and_(
                    CrmPropertyContactClaim.lead_id.is_not(None),
                    has_contact,
                    CrmPropertyContactClaim.ownership_status.in_(
                        ("verified_current_owner", "probable_current_owner")
                    ),
                )
            ),
        ).where(
            CrmPropertyContactClaim.organization_id == organization_id,
            CrmPropertyContactClaim.import_id == record_id,
        )
    )
    candidate_rows, valid_contacts, rental_opportunities, contact_ready = (
        int(value or 0) for value in metrics_result.one()
    )
    return candidate_rows, valid_contacts, rental_opportunities, contact_ready


def save(db: AsyncSession, record):
    db.add(record)


async def find_import_by_digest(db: AsyncSession, organization_id, sha256):
    return (
        await db.exec(
            select(CrmContactImport).where(
                CrmContactImport.organization_id == organization_id,
                CrmContactImport.sha256 == sha256,
            )
        )
    ).first()


def save_all(db: AsyncSession, records):
    db.add_all(records)


async def find_import_list(db: AsyncSession, record):
    return (
        await db.exec(select(CrmContactList).where(CrmContactList.source_import_id == record.id))
    ).first()


async def list_imports(db: AsyncSession, organization_id):
    return (
        await db.exec(
            select(CrmContactImport)
            .where(CrmContactImport.organization_id == organization_id)
            .order_by(CrmContactImport.created_at.desc())
        )
    ).all()


async def get_import_for_org(db: AsyncSession, import_id, organization_id):
    return (
        await db.exec(
            select(CrmContactImport).where(
                CrmContactImport.id == import_id,
                CrmContactImport.organization_id == organization_id,
            )
        )
    ).first()


async def find_import_list_for_org(db: AsyncSession, import_id, organization_id):
    return (
        await db.exec(
            select(CrmContactList).where(
                CrmContactList.source_import_id == import_id,
                CrmContactList.organization_id == organization_id,
            )
        )
    ).first()


async def delete_import_claims(db: AsyncSession, import_id, organization_id):
    return await db.exec(
        delete(CrmPropertyContactClaim).where(
            CrmPropertyContactClaim.import_id == import_id,
            CrmPropertyContactClaim.organization_id == organization_id,
        )
    )


async def delete_import_lists(db: AsyncSession, import_id, organization_id):
    return await db.exec(
        delete(CrmContactList).where(
            CrmContactList.source_import_id == import_id,
            CrmContactList.organization_id == organization_id,
        )
    )


async def delete_record(db: AsyncSession, record):
    await db.delete(record)


async def list_imports_by_ids(db: AsyncSession, import_ids, organization_id):
    return (
        await db.exec(
            select(CrmContactImport).where(
                CrmContactImport.organization_id == organization_id,
                CrmContactImport.id.in_(sorted(import_ids)),
            )
        )
    ).all()


async def count_claims_by_status(db: AsyncSession, organization_id, record_id):
    return (
        await db.exec(
            select(CrmPropertyContactClaim.ownership_status, func.count())
            .where(
                CrmPropertyContactClaim.organization_id == organization_id,
                CrmPropertyContactClaim.import_id == record_id,
            )
            .group_by(CrmPropertyContactClaim.ownership_status)
        )
    ).all()


async def list_import_ids(db: AsyncSession, organization_id):
    return (
        await db.exec(
            select(CrmContactImport.id).where(CrmContactImport.organization_id == organization_id)
        )
    ).all()
