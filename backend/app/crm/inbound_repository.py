from __future__ import annotations

from sqlalchemy import delete, exists, func, or_, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.import_models import CrmPropertyContactClaim
from app.crm.inbound_models import (
    SOLD_OWNER_SOURCE,
    VITEVUE_LEASE_SOURCE,
    CrmInboundActivity,
    CrmInboundAssignmentEvent,
    CrmInboundContact,
    CrmInboundEnquiry,
    CrmInboundImport,
    CrmInboundMatch,
    CrmInboundNote,
)


async def find_contact(db: AsyncSession, email, organization_id, phone):
    conditions = []
    if phone:
        conditions.append(CrmInboundContact.phone == phone)
    if email:
        conditions.append(CrmInboundContact.email == email)
    existing = None
    if conditions:
        result = await db.exec(
            select(CrmInboundContact).where(
                CrmInboundContact.organization_id == organization_id, or_(*conditions)
            )
        )
        existing = result.first()
    return existing


async def find_contact_claims(db: AsyncSession, contact):
    conditions = [
        func.lower(func.trim(CrmPropertyContactClaim.contact_name))
        == contact.full_name.strip().lower()
    ]
    if contact.phone:
        conditions.extend(
            [
                CrmPropertyContactClaim.phone_primary == contact.phone,
                CrmPropertyContactClaim.phone_alternate == contact.phone,
            ]
        )
    if contact.email:
        conditions.append(
            func.lower(CrmPropertyContactClaim.email_primary) == contact.email.lower()
        )
    result = await db.exec(
        select(CrmPropertyContactClaim)
        .where(
            CrmPropertyContactClaim.organization_id == contact.organization_id,
            or_(*conditions),
        )
        .order_by(CrmPropertyContactClaim.confidence_score.desc())
        .limit(100)
    )
    claims = list(result.all())
    return claims


async def find_identity_claims(
    db: AsyncSession, email_to_ids, name_to_ids, organization_id, phone_to_ids
):
    conditions = []
    if name_to_ids:
        conditions.append(
            func.lower(func.trim(CrmPropertyContactClaim.contact_name)).in_(list(name_to_ids))
        )
    if phone_to_ids:
        conditions.extend(
            [
                CrmPropertyContactClaim.phone_primary.in_(list(phone_to_ids)),
                CrmPropertyContactClaim.phone_alternate.in_(list(phone_to_ids)),
            ]
        )
    if email_to_ids:
        conditions.append(func.lower(CrmPropertyContactClaim.email_primary).in_(list(email_to_ids)))
    if not conditions:
        return []
    result = await db.exec(
        select(CrmPropertyContactClaim).where(
            CrmPropertyContactClaim.organization_id == organization_id,
            or_(*conditions),
        )
    )
    return result.all()


def save(db: AsyncSession, record):
    db.add(record)


async def get_crm_inbound_contact(db: AsyncSession, key):
    return await db.get(CrmInboundContact, key)


async def list_enquiry_notes(db: AsyncSession, enquiry):
    return (
        await db.exec(
            select(CrmInboundNote)
            .where(CrmInboundNote.enquiry_id == enquiry.id)
            .order_by(CrmInboundNote.created_at.desc())
        )
    ).all()


async def list_enquiry_activities(db: AsyncSession, enquiry):
    return (
        await db.exec(
            select(CrmInboundActivity)
            .where(CrmInboundActivity.enquiry_id == enquiry.id)
            .order_by(CrmInboundActivity.created_at.desc())
        )
    ).all()


async def list_enquiry_matches(db: AsyncSession, enquiry):
    return (
        await db.exec(select(CrmInboundMatch).where(CrmInboundMatch.enquiry_id == enquiry.id))
    ).all()


async def list_enquiries(db: AsyncSession, visible):
    """The enquiries matching `visible` (assignment.visible_clause: organization and viewer)."""
    return (
        await db.exec(
            select(CrmInboundEnquiry).where(visible).order_by(CrmInboundEnquiry.enquiry_date.desc())
        )
    ).all()


async def list_visible_ids(db: AsyncSession, visible, enquiry_ids):
    return (
        await db.exec(
            select(CrmInboundEnquiry.id).where(
                visible,
                col(CrmInboundEnquiry.id).in_(list(enquiry_ids)),
            )
        )
    ).all()


async def claim_pooled(
    db: AsyncSession, *, organization_id, enquiry_id, team_id, user_id, now
) -> int | None:
    """Take a lead out of its team pool for `user_id` in one statement; the new assignment
    revision, or None when it is no longer waiting in that pool (someone else won)."""
    return (
        await db.exec(
            update(CrmInboundEnquiry)
            .where(
                col(CrmInboundEnquiry.id) == enquiry_id,
                col(CrmInboundEnquiry.organization_id) == organization_id,
                col(CrmInboundEnquiry.team_id) == team_id,
                col(CrmInboundEnquiry.assigned_user_id).is_(None),
                col(CrmInboundEnquiry.pool_released_at).is_not(None),
            )
            .values(
                assigned_user_id=user_id,
                pool_released_at=None,
                assigned_at=now,
                updated_at=now,
                assignment_revision=CrmInboundEnquiry.assignment_revision + 1,
            )
            .returning(CrmInboundEnquiry.assignment_revision)
        )
    ).scalar_one_or_none()


async def list_vitevue_lease_enquiries(db: AsyncSession, organization_id, unit_keys):
    return (
        await db.exec(
            select(CrmInboundEnquiry).where(
                CrmInboundEnquiry.organization_id == organization_id,
                CrmInboundEnquiry.source == VITEVUE_LEASE_SOURCE,
                CrmInboundEnquiry.source_lead_id.in_(list(unit_keys)),  # type: ignore[union-attr]
            )
        )
    ).all()


async def list_recent_former_owner_claims(db: AsyncSession, organization_id, since):
    """Owner-file claims whose unit sold again on or after `since`."""
    return (
        await db.exec(
            select(CrmPropertyContactClaim).where(
                CrmPropertyContactClaim.organization_id == organization_id,
                CrmPropertyContactClaim.ownership_status == "former_owner",
                CrmPropertyContactClaim.later_sale_date >= since,  # type: ignore[operator]
            )
        )
    ).all()


async def list_claims_by_owner_keys(db: AsyncSession, organization_id, owner_keys):
    """Every owner-file claim of these owners (indexed on organization and owner key)."""
    if not owner_keys:
        return []
    return (
        await db.exec(
            select(CrmPropertyContactClaim).where(
                CrmPropertyContactClaim.organization_id == organization_id,
                CrmPropertyContactClaim.owner_key.in_(list(owner_keys)),  # type: ignore[attr-defined]
            )
        )
    ).all()


async def list_sold_owner_enquiries(db: AsyncSession, organization_id):
    """The recently-sold Inbox items, by owner key."""
    rows = (
        await db.exec(
            select(CrmInboundEnquiry).where(
                CrmInboundEnquiry.organization_id == organization_id,
                CrmInboundEnquiry.source == SOLD_OWNER_SOURCE,
            )
        )
    ).all()
    return {row.source_lead_id: row for row in rows if row.source_lead_id}


async def list_enquiry_contacts(db: AsyncSession, all_enquiries):
    return (
        await db.exec(
            select(CrmInboundContact).where(
                CrmInboundContact.id.in_([item.contact_id for item in all_enquiries])  # type: ignore[union-attr]
            )
        )
    ).all()


async def count_matches_by_state(db: AsyncSession, page):
    return (
        await db.exec(
            select(CrmInboundMatch.enquiry_id, CrmInboundMatch.state, func.count())
            .where(CrmInboundMatch.enquiry_id.in_([item.id for item in page]))  # type: ignore[union-attr]
            .group_by(CrmInboundMatch.enquiry_id, CrmInboundMatch.state)
        )
    ).all()


async def get_crm_inbound_enquiry(db: AsyncSession, key):
    return await db.get(CrmInboundEnquiry, key)


async def mark_enquiry_matches_stale(db: AsyncSession, enquiry, enquiry_id):
    return await db.exec(
        CrmInboundMatch.__table__.update()
        .where(
            CrmInboundMatch.enquiry_id == enquiry_id,
            CrmInboundMatch.state.notin_(["saved", "dismissed"]),
        )
        .values(state="stale", updated_at=enquiry.updated_at)
    )


async def find_import_by_digest(db: AsyncSession, digest, organization_id):
    return (
        await db.exec(
            select(CrmInboundImport).where(
                CrmInboundImport.organization_id == organization_id,
                CrmInboundImport.sha256 == digest,
            )
        )
    ).first()


async def list_imports(db: AsyncSession, organization_id):
    return (
        await db.exec(
            select(CrmInboundImport)
            .where(CrmInboundImport.organization_id == organization_id)
            .order_by(CrmInboundImport.created_at.desc())
        )
    ).all()


async def get_import_for_org(db: AsyncSession, import_id, organization_id):
    return (
        await db.exec(
            select(CrmInboundImport).where(
                CrmInboundImport.id == import_id,
                CrmInboundImport.organization_id == organization_id,
            )
        )
    ).first()


async def list_import_contact_ids(db: AsyncSession, import_id, organization_id):
    return (
        await db.exec(
            select(CrmInboundEnquiry.contact_id).where(
                CrmInboundEnquiry.source_import_id == import_id,
                CrmInboundEnquiry.organization_id == organization_id,
            )
        )
    ).all()


async def delete_import_enquiries(db: AsyncSession, import_id, organization_id):
    return await db.exec(
        delete(CrmInboundEnquiry).where(
            CrmInboundEnquiry.source_import_id == import_id,
            CrmInboundEnquiry.organization_id == organization_id,
        )
    )


async def delete_record(db: AsyncSession, record):
    await db.delete(record)


async def delete_orphan_contacts(db: AsyncSession, contact_ids, organization_id):
    return await db.exec(
        delete(CrmInboundContact).where(
            CrmInboundContact.organization_id == organization_id,
            CrmInboundContact.id.in_(contact_ids),  # type: ignore[union-attr]
            ~exists(
                select(CrmInboundEnquiry.id).where(
                    CrmInboundEnquiry.contact_id == CrmInboundContact.id
                )
            ),
        )
    )


async def lock_enquiries(db: AsyncSession, organization_id, enquiry_ids):
    """The organization's enquiries among these ids, row-locked in id order until commit."""
    return (
        await db.exec(
            select(CrmInboundEnquiry)
            .where(
                CrmInboundEnquiry.organization_id == organization_id,
                CrmInboundEnquiry.id.in_(list(enquiry_ids)),  # type: ignore[union-attr]
            )
            .order_by(CrmInboundEnquiry.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()


async def list_assignment_events(db: AsyncSession, organization_id, enquiry_id):
    return (
        await db.exec(
            select(CrmInboundAssignmentEvent)
            .where(
                CrmInboundAssignmentEvent.organization_id == organization_id,
                CrmInboundAssignmentEvent.enquiry_id == enquiry_id,
            )
            .order_by(
                CrmInboundAssignmentEvent.revision.desc(), CrmInboundAssignmentEvent.id.desc()
            )
        )
    ).all()


async def was_claimed(db: AsyncSession, enquiry_id) -> bool:
    """True when the lead's latest assignment change was a claim from a pool."""
    latest = (
        await db.exec(
            select(CrmInboundAssignmentEvent.reason)
            .where(CrmInboundAssignmentEvent.enquiry_id == enquiry_id)
            .order_by(
                CrmInboundAssignmentEvent.revision.desc(), CrmInboundAssignmentEvent.id.desc()
            )
            .limit(1)
        )
    ).first()
    return latest == "claimed"
