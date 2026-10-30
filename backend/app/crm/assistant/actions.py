"""Pending assistant actions: proposed by a tool, run only when their user confirms in time."""

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from fastapi import HTTPException

from app.crm import calendar_service, inbound_repository
from app.crm.assistant import repository
from app.crm.assistant.deps import AssistantDeps
from app.crm.assistant.models import AssistantActionResult, CrmAssistantAction
from app.crm.assistant.scope import load_lead, org_member
from app.crm.inbound import add_inbound_note, get_inbound_enquiry, update_inbound_enquiry
from app.crm.inbound_models import CrmInboundActivity, InboundEnquiryUpdate

logger = logging.getLogger(__name__)

ACTION_TTL = timedelta(minutes=10)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def proposed_payload(action: CrmAssistantAction) -> dict[str, Any]:
    """What the chat shows on an action card (and what the model is told it proposed)."""
    return {
        "action_id": action.id,
        "action_type": action.action_type,
        "lead_id": action.enquiry_id,
        "summary": action.summary,
        "before": action.before,
        "after": action.after,
        "channel": action.payload.get("channel"),
        "status": action.status,
        "expires_at": action.expires_at.isoformat(),
    }


async def create_pending_action(
    deps: AssistantDeps,
    *,
    enquiry_id: int,
    action_type: str,
    payload: dict[str, Any],
    summary: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    now = utcnow()
    action = CrmAssistantAction(
        id=uuid4().hex,
        organization_id=deps.organization_id,
        user_id=deps.user_id,
        conversation_id=deps.conversation_id,
        enquiry_id=enquiry_id,
        action_type=action_type,
        payload=payload,
        summary=summary,
        before=before,
        after=after,
        status="pending",
        expires_at=now + ACTION_TTL,
        created_at=now,
    )
    repository.save(deps.db, action)
    await deps.db.commit()
    return proposed_payload(action)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _draft_href(channel: str, to: str, text: str) -> str:
    if channel == "whatsapp":
        digits = re.sub(r"\D", "", to)
        return f"https://wa.me/{digits}?text={quote(text)}"
    return f"mailto:{to}?body={quote(text)}"


async def _pending_action(deps: AssistantDeps, action_id: str) -> CrmAssistantAction:
    action = await repository.get_action(deps.db, action_id, deps.user_id, deps.organization_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    if action.status != "pending":
        raise HTTPException(status_code=409, detail=f"Action already {action.status}")
    if _aware(action.expires_at) <= utcnow():
        action.status = "expired"
        action.resolved_at = utcnow()
        repository.save(deps.db, action)
        await deps.db.commit()
        raise HTTPException(status_code=410, detail="Action expired")
    return action


async def confirm_action(deps: AssistantDeps, *, action_id: str) -> AssistantActionResult:
    """Run a pending action for the signed-in user. Everything is re-checked against the
    current AuthContext scope, then the change goes through the existing Leads services."""
    action = await _pending_action(deps, action_id)
    db, organization_id, user_id = deps.db, deps.organization_id, deps.user_id
    await load_lead(db, organization_id, action.enquiry_id)

    payload = action.payload
    channel = payload.get("channel")
    member = None
    member_user_id = payload.get("assigned_user_id") or payload.get("member_user_id")
    if action.action_type == "assign" or channel == "teammate":
        member = await org_member(deps, member_user_id)
        if member is None:
            raise HTTPException(status_code=404, detail="Member not found")
    if channel in {"whatsapp", "email"}:
        contact = (await get_inbound_enquiry(db, action.enquiry_id, organization_id)).contact
        if contact.do_not_contact or contact.consent_status == "withdrawn":
            raise HTTPException(status_code=409, detail="This lead has asked not to be contacted")

    if not await repository.claim_action(db, action.id):
        raise HTTPException(status_code=409, detail="Action already confirmed")
    # Not committed here: the service below commits the claim, this entry and the change at once.
    inbound_repository.save(
        db,
        CrmInboundActivity(
            enquiry_id=action.enquiry_id,
            organization_id=organization_id,
            user_id=user_id,
            activity_type="assistant",
            body=f"{action.summary} (via Assistant)",
            metadata_json={"action_id": action.id},
            created_at=utcnow(),
        ),
    )
    result = AssistantActionResult(
        action_id=action.id, status="confirmed", lead_id=action.enquiry_id
    )
    service_args = dict(
        enquiry_id=action.enquiry_id, organization_id=organization_id, user_id=user_id
    )
    try:
        if action.action_type == "status":
            await update_inbound_enquiry(
                db, **service_args, payload=InboundEnquiryUpdate(**payload)
            )
        elif action.action_type == "follow_up":
            await update_inbound_enquiry(
                db,
                **service_args,
                payload=InboundEnquiryUpdate(
                    next_follow_up=date.fromisoformat(payload["next_follow_up"])
                ),
            )
        elif action.action_type == "assign":
            await update_inbound_enquiry(
                db,
                **service_args,
                payload=InboundEnquiryUpdate(assigned_user_id=payload["assigned_user_id"]),
            )
        elif action.action_type == "note":
            await add_inbound_note(db, **service_args, body=payload["body"])
        elif channel == "teammate":
            await add_inbound_note(
                db, **service_args, body=f"Shared with {member['name']} via Assistant"
            )
        elif action.action_type == "calendar_event":
            await calendar_service.create_event(
                db,
                user_id=user_id,
                organization_id=organization_id,
                title=payload["title"],
                event_date=date.fromisoformat(payload["date"]),
                event_time=payload["time"],
                end_time=payload["end_time"],
                kind=payload["kind"],
                detail=payload.get("detail", ""),
                lead_id=action.enquiry_id,
            )
        elif channel in {"whatsapp", "email"}:
            inbound_repository.save(
                db,
                CrmInboundActivity(
                    **service_args,
                    activity_type="shared",
                    body=f"{'WhatsApp' if channel == 'whatsapp' else 'Email'} draft opened via Assistant",
                    metadata_json={"channel": channel, "action_id": action.id},
                    created_at=utcnow(),
                ),
            )
            await db.commit()
            result.href = _draft_href(channel, payload["to"], payload["text"])
            result.text = payload["text"]
        else:
            raise HTTPException(status_code=400, detail="Unsupported action")
    except Exception:
        await db.rollback()
        logger.warning("assistant confirm failed action=%s org=%s", action.id, organization_id)
        raise
    logger.info(
        "assistant confirmed action=%s type=%s org=%s",
        action.id,
        action.action_type,
        organization_id,
    )
    return result


async def cancel_action(deps: AssistantDeps, *, action_id: str) -> AssistantActionResult:
    action = await _pending_action(deps, action_id)
    action.status = "cancelled"
    action.resolved_at = utcnow()
    repository.save(deps.db, action)
    await deps.db.commit()
    return AssistantActionResult(action_id=action.id, status="cancelled", lead_id=action.enquiry_id)
