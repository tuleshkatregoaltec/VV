"""Durable document queue with bounded leases and private media references."""

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, update
from sqlmodel import select

from app.crm.document_models import CrmBrokerDocument, CrmBrokerMedia
from app.crm.inbound_models import CrmInboundMatch


async def get_document(db, document_id):
    return await db.get(CrmBrokerDocument, document_id)


async def get_request(db, context, key):
    return (
        await db.exec(
            select(CrmBrokerDocument).where(
                CrmBrokerDocument.organization_id == context.organization_id,
                CrmBrokerDocument.user_id == context.user_id,
                CrmBrokerDocument.idempotency_key == key,
            )
        )
    ).first()


async def selected_matches(db, enquiry_id, organization_id, ids):
    return list(
        (
            await db.exec(
                select(CrmInboundMatch).where(
                    CrmInboundMatch.enquiry_id == enquiry_id,
                    CrmInboundMatch.organization_id == organization_id,
                    CrmInboundMatch.id.in_(ids),
                )
            )
        ).all()
    )


async def selected_media(db, organization_id, enquiry_id, ids):
    return list(
        (
            await db.exec(
                select(CrmBrokerMedia).where(
                    CrmBrokerMedia.organization_id == organization_id,
                    CrmBrokerMedia.enquiry_id == enquiry_id,
                    CrmBrokerMedia.id.in_(ids),
                )
            )
        ).all()
    )


async def claim_document(db, now: datetime):
    await db.execute(
        update(CrmBrokerDocument)
        .where(
            CrmBrokerDocument.status == "running",
            CrmBrokerDocument.lease_until < now,
            CrmBrokerDocument.attempt_count >= 3,
        )
        .values(
            status="failed", error="render_attempts_exhausted", lease_until=None, updated_at=now
        )
    )
    row = (
        await db.exec(
            select(CrmBrokerDocument)
            .where(
                or_(
                    CrmBrokerDocument.status == "queued",
                    (CrmBrokerDocument.status == "running") & (CrmBrokerDocument.lease_until < now),
                ),
                CrmBrokerDocument.attempt_count < 3,
            )
            .order_by(CrmBrokerDocument.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
    ).first()
    if row:
        row.status = "running"
        row.attempt_count += 1
        row.claim_token = str(uuid4())
        row.lease_until = now + timedelta(seconds=90)
        row.updated_at = now
        db.add(row)
    await db.commit()
    return row


async def finish_document(
    db, document_id, token, *, now, object_key=None, checksum=None, error=None
):
    result = await db.execute(
        update(CrmBrokerDocument)
        .where(
            CrmBrokerDocument.id == document_id,
            CrmBrokerDocument.status == "running",
            CrmBrokerDocument.claim_token == token,
        )
        .values(
            status="failed" if error else "completed",
            error=error,
            object_key=object_key,
            sha256=checksum,
            lease_until=None,
            updated_at=now,
        )
    )
    await db.commit()
    return result.rowcount == 1
