"""Scoped and bounded broker reads. Authorization and commits belong to the service."""

from sqlalchemy import and_, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.broker_models import CrmBrokerAction
from app.crm.inbound_models import (
    CrmInboundContact,
    CrmInboundEnquiry,
    CrmInboundMatch,
    CrmInboundNote,
)
from app.organization.models import OrganizationMembership


def enquiry_scope(context, scope="mine"):
    conditions = [CrmInboundEnquiry.organization_id == context.organization_id]
    if scope == "mine":
        conditions.append(
            or_(
                CrmInboundEnquiry.assigned_user_id == context.user_id,
                and_(
                    CrmInboundEnquiry.assigned_user_id.is_(None),
                    CrmInboundEnquiry.created_by_user_id == context.user_id,
                ),
            )
        )
    return conditions


async def membership(db: AsyncSession, context, *, lock=False):
    stmt = (
        select(OrganizationMembership)
        .where(
            OrganizationMembership.organization_id == context.organization_id,
            OrganizationMembership.user_id == context.user_id,
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        stmt = stmt.with_for_update()
    return (await db.exec(stmt)).first()


async def enquiry(db: AsyncSession, context, enquiry_id, scope="mine", *, lock=False):
    stmt = (
        select(CrmInboundEnquiry)
        .where(
            *enquiry_scope(context, scope),
            CrmInboundEnquiry.id == enquiry_id,
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        stmt = stmt.with_for_update()
    return (await db.exec(stmt)).first()


async def list_enquiries(
    db: AsyncSession, context, request, *, due_before=None, demand_intent=None
):
    conditions = enquiry_scope(context, request.scope)
    if intent := demand_intent or getattr(request, "intent", None):
        conditions.append(CrmInboundEnquiry.intent == intent)
    if statuses := getattr(request, "statuses", None):
        conditions.append(CrmInboundEnquiry.status.in_(statuses))
    if due_before is not None:
        conditions.extend(
            [
                CrmInboundEnquiry.next_follow_up <= due_before,
                CrmInboundEnquiry.status.notin_(["won", "closed_lost", "disqualified"]),
            ]
        )
    counts = (
        await db.exec(
            select(
                func.count(CrmInboundEnquiry.id),
                func.count(func.distinct(CrmInboundEnquiry.contact_id)),
            ).where(*conditions)
        )
    ).one()
    rows = (
        await db.exec(
            select(CrmInboundEnquiry)
            .where(*conditions)
            .order_by(CrmInboundEnquiry.next_follow_up.asc().nullslast(), CrmInboundEnquiry.id)
            .limit(request.limit)
            .offset(getattr(request, "offset", 0))
        )
    ).all()
    return list(rows), int(counts[0]), int(counts[1])


async def contact(db: AsyncSession, enquiry):
    return (
        await db.exec(
            select(CrmInboundContact).where(
                CrmInboundContact.id == enquiry.contact_id,
                CrmInboundContact.organization_id == enquiry.organization_id,
            )
        )
    ).first()


async def notes(db: AsyncSession, enquiry):
    return (
        await db.exec(
            select(CrmInboundNote)
            .where(
                CrmInboundNote.enquiry_id == enquiry.id,
                CrmInboundNote.organization_id == enquiry.organization_id,
            )
            .order_by(CrmInboundNote.created_at.desc(), CrmInboundNote.id.desc())
            .limit(10)
        )
    ).all()


async def matches(db: AsyncSession, enquiry, *, match_ids=None):
    conditions = [
        CrmInboundMatch.enquiry_id == enquiry.id,
        CrmInboundMatch.organization_id == enquiry.organization_id,
    ]
    if match_ids is not None:
        conditions.append(CrmInboundMatch.id.in_(match_ids))
    total = (
        await db.exec(select(func.count()).select_from(CrmInboundMatch).where(*conditions))
    ).one()
    rows = (
        await db.exec(
            select(CrmInboundMatch)
            .where(*conditions)
            .order_by(CrmInboundMatch.score.desc(), CrmInboundMatch.id)
            .limit(100)
        )
    ).all()
    return list(rows), total


async def action(db: AsyncSession, context, proposal_id):
    return (
        await db.exec(
            select(CrmBrokerAction)
            .where(
                CrmBrokerAction.id == str(proposal_id),
                CrmBrokerAction.user_id == context.user_id,
                CrmBrokerAction.organization_id == context.organization_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
    ).first()
