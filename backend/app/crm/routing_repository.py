"""Routing rule persistence. Callers own commits."""

from __future__ import annotations

from sqlalchemy import func, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.inbound_models import CrmInboundEnquiry
from app.crm.routing_models import CrmAgentLanguages, CrmLeadRotation, CrmRoutingRule


async def list_rules(db: AsyncSession, organization_id: str, *, lock: bool = False):
    statement = (
        select(CrmRoutingRule)
        .where(CrmRoutingRule.organization_id == organization_id)
        .order_by(CrmRoutingRule.priority, CrmRoutingRule.id)
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return (await db.exec(statement)).all()


async def lock_rule(db: AsyncSession, organization_id: str, rule_id: int):
    return (
        await db.exec(
            select(CrmRoutingRule)
            .where(CrmRoutingRule.organization_id == organization_id, CrmRoutingRule.id == rule_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()


async def next_priority(db: AsyncSession, organization_id: str) -> int:
    highest = (
        await db.exec(
            select(func.max(CrmRoutingRule.priority)).where(
                CrmRoutingRule.organization_id == organization_id
            )
        )
    ).first()
    return (highest or 0) + 1


def save(db: AsyncSession, record) -> None:
    db.add(record)


async def delete(db: AsyncSession, record) -> None:
    await db.delete(record)


async def due_rotation_enquiry_ids(db: AsyncSession, now, limit: int) -> list[int]:
    return list(
        (
            await db.exec(
                select(CrmLeadRotation.enquiry_id)
                .where(CrmLeadRotation.status == "active", col(CrmLeadRotation.due_at) <= now)
                .order_by(CrmLeadRotation.due_at)
                .limit(limit)
            )
        ).all()
    )


async def lock_enquiry_skip_locked(db: AsyncSession, enquiry_id: int):
    return (
        await db.exec(
            select(CrmInboundEnquiry)
            .where(CrmInboundEnquiry.id == enquiry_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    ).first()


async def lock_rotation(db: AsyncSession, enquiry_id: int):
    return (
        await db.exec(
            select(CrmLeadRotation)
            .where(CrmLeadRotation.enquiry_id == enquiry_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()


async def stop_rotation(db: AsyncSession, enquiry_id: int, *, reason: str, now) -> None:
    await db.exec(
        update(CrmLeadRotation)
        .where(
            col(CrmLeadRotation.enquiry_id) == enquiry_id,
            col(CrmLeadRotation.status) == "active",
        )
        .values(status="stopped", stop_reason=reason, updated_at=now)
    )


async def languages_by_user(
    db: AsyncSession, organization_id: str, user_ids
) -> dict[str, list[str]]:
    """The languages recorded for each of these people (those with none are absent)."""
    ids = sorted(set(user_ids))
    if not ids:
        return {}
    rows = await db.exec(
        select(CrmAgentLanguages).where(
            CrmAgentLanguages.organization_id == organization_id,
            col(CrmAgentLanguages.user_id).in_(ids),
        )
    )
    return {row.user_id: list(row.languages) for row in rows.all()}
