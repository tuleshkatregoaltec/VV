"""Database access only; authorization decisions live in service.py."""

from sqlmodel import select

from app.assistant_actions.models import AssistantAction
from app.chat import models as chat_models
from app.crm.inbound_models import (
    CrmInboundActivity,
    CrmInboundContact,
    CrmInboundMatch,
    CrmInboundNote,
)
from app.organization.models import Organization, OrganizationMembership


def _locked(statement):
    # Refresh an identity-map entry after waiting for a concurrent transaction.
    return statement.with_for_update().execution_options(populate_existing=True)


async def membership(db, *, user_id, organization_id):
    return (
        await db.exec(
            _locked(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == user_id,
                    OrganizationMembership.organization_id == organization_id,
                )
            )
        )
    ).first()


async def organization(db, organization_id):
    return (
        await db.exec(
            _locked(
                select(Organization).where(
                    Organization.id == organization_id,
                )
            )
        )
    ).first()


async def conversation(db, *, user_id, organization_id, conversation_id):
    return (
        await db.exec(
            _locked(
                select(chat_models.Conversation).where(
                    chat_models.Conversation.id == conversation_id,
                    chat_models.Conversation.user_id == user_id,
                    chat_models.Conversation.organization_id == organization_id,
                )
            )
        )
    ).first()


async def action(db, *, user_id, organization_id, action_id):
    return (
        await db.exec(
            _locked(
                select(AssistantAction).where(
                    AssistantAction.id == action_id,
                    AssistantAction.user_id == user_id,
                    AssistantAction.organization_id == organization_id,
                )
            )
        )
    ).first()


async def action_by_key(db, *, user_id, organization_id, idempotency_key):
    return (
        await db.exec(
            select(AssistantAction).where(
                AssistantAction.user_id == user_id,
                AssistantAction.organization_id == organization_id,
                AssistantAction.idempotency_key == idempotency_key,
            )
        )
    ).first()


async def actions(db, *, user_id, organization_id, conversation_id):
    return (
        await db.exec(
            select(AssistantAction)
            .where(
                AssistantAction.user_id == user_id,
                AssistantAction.organization_id == organization_id,
                AssistantAction.conversation_id == conversation_id,
            )
            .order_by(AssistantAction.created_at.desc())
            .limit(100)
        )
    ).all()


async def visible_lead(db, *, user_id, organization_id, lead_id, lock=False):
    """The lead when the user's CRM role lets them see it (crm/assignment.py), else None."""
    from fastapi import HTTPException

    from app.crm import assignment

    scope = await assignment.load_scope(db, organization_id, user_id)
    try:
        return await assignment.load_visible(db, scope, lead_id, lock=lock)
    except HTTPException:
        return None


async def own_record(db, model, *, user_id, organization_id, record_id):
    return (
        await db.exec(
            _locked(
                select(model).where(
                    model.id == record_id,
                    model.user_id == user_id,
                    model.organization_id == organization_id,
                )
            )
        )
    ).first()


async def records(db, model, *, user_id, organization_id):
    return (
        await db.exec(
            select(model)
            .where(
                model.user_id == user_id,
                model.organization_id == organization_id,
            )
            .order_by(model.id.desc())
            .limit(100)
        )
    ).all()


async def has_others_assignment_history(db, *, lead_id, user_id) -> bool:
    from app.crm.inbound_models import CrmInboundAssignmentEvent

    return (
        await db.exec(
            select(CrmInboundAssignmentEvent.id)
            .where(
                CrmInboundAssignmentEvent.enquiry_id == lead_id,
                CrmInboundAssignmentEvent.actor_user_id != user_id,
            )
            .limit(1)
        )
    ).first() is not None


async def lead_dependents(db, *, lead_id):
    result = []
    for model in (CrmInboundNote, CrmInboundActivity, CrmInboundMatch):
        result.extend(
            (
                await db.exec(
                    _locked(
                        select(model).where(
                            model.enquiry_id == lead_id,
                        )
                    )
                )
            ).all()
        )
    return result


async def outbox(db, *, user_id, organization_id, action_id):
    from app.assistant_actions.models import AssistantOutbox

    return (
        await db.exec(
            _locked(
                select(AssistantOutbox).where(
                    AssistantOutbox.action_id == action_id,
                    AssistantOutbox.user_id == user_id,
                    AssistantOutbox.organization_id == organization_id,
                )
            )
        )
    ).first()


async def lead_contact(db, *, organization_id, contact_id):
    """Resolve a label only after the service authorizes the parent enquiry."""
    return (
        await db.exec(
            _locked(
                select(CrmInboundContact).where(
                    CrmInboundContact.id == contact_id,
                    CrmInboundContact.organization_id == organization_id,
                )
            )
        )
    ).first()


async def member_ids(db, *, organization_id):
    return set(
        (
            await db.exec(
                select(OrganizationMembership.user_id).where(
                    OrganizationMembership.organization_id == organization_id,
                )
            )
        ).all()
    )
