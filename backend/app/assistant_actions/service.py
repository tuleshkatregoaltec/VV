"""Propose exact changes; execute only after authenticated UI confirmation."""

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.assistant_actions import connectors, repository
from app.assistant_actions.delivery import dispatch_claimed
from app.assistant_actions.models import (
    ActionKind,
    ActionProposalRequest,
    ActionProposalResponse,
    AssistantAction,
    AssistantListingDraft,
    AssistantOutbox,
    AssistantReminder,
    AssistantViewing,
    ListingDraftResponse,
    ReminderResponse,
    ViewingResponse,
)
from app.auth.service import get_user_by_id
from app.crm.inbound_models import CrmInboundContact, CrmInboundEnquiry, CrmInboundNote
from app.organization.service import get_organization_members

EXTERNAL_KINDS = {
    ActionKind.SEND_MESSAGE,
    ActionKind.PUBLISH_LISTING,
    ActionKind.BOOK_EXTERNAL_VIEWING,
}


def _now():
    return datetime.now(timezone.utc)


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _request_hash(request, user_id, organization_id):
    return _hash(
        {
            "actor": user_id,
            "organization": organization_id,
            "request": request.model_dump(mode="json", exclude_unset=True),
        }
    )


def _response(row):
    return ActionProposalResponse(
        id=row.id,
        kind=row.kind,
        status=row.status,
        title=row.kind.replace("_", " ").capitalize(),
        preview=row.preview,
        created_at=row.created_at,
        expires_at=row.expires_at,
        result=row.result,
    )


async def _authorize(db, user_id, organization_id, conversation_id=None):
    # Lock the org before memberships so assignment confirmations have consistent ordering.
    organization = await repository.organization(db, organization_id)
    if organization is None or organization.subscription_status not in {"active", "trialing"}:
        raise HTTPException(403, "An active organization subscription is required")
    if not await repository.membership(db, user_id=user_id, organization_id=organization_id):
        raise HTTPException(403, "Active organization membership is required")
    if conversation_id is not None:
        if not await repository.conversation(
            db,
            user_id=user_id,
            organization_id=organization_id,
            conversation_id=conversation_id,
        ):
            raise HTTPException(404, "Conversation not found")


async def _resources(db, request, user_id, organization_id):
    """Lock every target and take a versioned snapshot used again on confirmation."""
    payload = request.payload
    resources = {}
    lead_id = getattr(payload, "lead_id", None)
    if lead_id is not None:
        lead = await repository.own_lead(
            db,
            user_id=user_id,
            organization_id=organization_id,
            lead_id=lead_id,
        )
        if lead is None:
            raise HTTPException(404, "Own lead not found")
        resources["lead"] = lead
    for key, model in (
        ("reminder", AssistantReminder),
        ("viewing", AssistantViewing),
        ("listing", AssistantListingDraft),
    ):
        record_id = getattr(payload, f"{key}_id", None)
        if record_id is not None:
            record = await repository.own_record(
                db,
                model,
                user_id=user_id,
                organization_id=organization_id,
                record_id=record_id,
            )
            if record is None:
                raise HTTPException(404, "Own record not found")
            resources[key] = record
            # A linked task never grants access to a reassigned lead.
            linked_lead = getattr(record, "lead_id", None)
            if linked_lead is not None:
                lead = await repository.own_lead(
                    db,
                    user_id=user_id,
                    organization_id=organization_id,
                    lead_id=linked_lead,
                )
                if lead is None:
                    raise HTTPException(404, "Own lead not found")
                resources["lead"] = lead
    if "lead" in resources:
        contact = await repository.lead_contact(
            db,
            organization_id=organization_id,
            contact_id=resources["lead"].contact_id,
        )
        if contact is None:
            raise HTTPException(404, "Own lead contact not found")
        resources["contact"] = contact
    if request.kind == ActionKind.ASSIGN_LEAD:
        if not await repository.membership(
            db,
            user_id=payload.assignee_id,
            organization_id=organization_id,
        ):
            raise HTTPException(404, "Organization member not found")
    if request.kind == ActionKind.DELETE_LEAD:
        dependents = await repository.lead_dependents(db, lead_id=payload.lead_id)
        # Matches have no individual owner; deleting them could destroy another agent's work.
        if any(getattr(item, "user_id", None) != user_id for item in dependents):
            raise HTTPException(
                409, "Lead has shared or colleague-authored records; deletion refused"
            )
        resources["dependents"] = dependents
    snapshot = {}
    for key, record in resources.items():
        if key == "dependents":
            snapshot[key] = sorted(f"{type(item).__name__}:{item.id}" for item in record)
        else:
            snapshot[key] = _hash(record.model_dump(mode="json"))
    return resources, snapshot


def _target_preview(request, resources):
    """Human-readable confirmation evidence from already authorized records only."""
    preview = {}
    if "lead" in resources:
        name = resources["contact"].full_name.strip()[:200] or "Unnamed contact"
        preview["lead"] = f"{name} (lead #{resources['lead'].id})"
    for key in ("reminder", "viewing", "listing"):
        if key in resources:
            record = resources[key]
            preview["target"] = f"{record.title[:200]} ({key} #{record.id})"
    consequences = {
        ActionKind.UPDATE_LEAD: "Updates this lead's enquiry fields; retains its shared contact details.",
        ActionKind.ASSIGN_LEAD: "Assigns this lead to the selected organization member. You lose assistant access if it is assigned to someone else.",
        ActionKind.DELETE_LEAD: "Permanently deletes this lead enquiry and your notes and activities on it. The shared contact is retained. This cannot be undone.",
        ActionKind.ADD_NOTE: "Adds this note to the selected lead's enquiry history.",
        ActionKind.CREATE_REMINDER: "Saves a reminder in your list; notification delivery is not configured.",
        ActionKind.UPDATE_REMINDER: "Replaces this reminder's title and due time.",
        ActionKind.DELETE_REMINDER: "Permanently deletes this reminder. This cannot be undone.",
        ActionKind.SCHEDULE_VIEWING: "Creates an internal viewing appointment for this lead; no invitations are sent.",
        ActionKind.CANCEL_VIEWING: "Marks this internal viewing appointment cancelled; no cancellation messages are sent.",
        ActionKind.UPDATE_LISTING_DRAFT: "Replaces this private listing draft's details; it remains unpublished.",
        ActionKind.SEND_MESSAGE: "Records a disconnected message request for this lead; nothing is sent.",
        ActionKind.PUBLISH_LISTING: "Records a disconnected publication request for this draft; nothing is published.",
        ActionKind.BOOK_EXTERNAL_VIEWING: "Records a disconnected booking request for this lead; no external booking or invitation is made.",
    }
    if request.kind in consequences:
        preview["consequence"] = consequences[request.kind]
    return preview


async def propose_action(
    db, *, user_id: str, organization_id: str, request: ActionProposalRequest
) -> ActionProposalResponse:
    await _authorize(db, user_id, organization_id, request.conversation_id)
    request_hash = _request_hash(request, user_id, organization_id)
    existing = await repository.action_by_key(
        db,
        user_id=user_id,
        organization_id=organization_id,
        idempotency_key=request.idempotency_key,
    )
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "Idempotency key already belongs to different arguments")
        response = await _visible_response(db, existing, user_id, organization_id)
        await db.commit()
        return response
    resources, snapshot = await _resources(db, request, user_id, organization_id)
    payload = request.payload.model_dump(mode="json", exclude_unset=True)
    preview = {**_target_preview(request, resources), "changes": payload}
    if request.kind == ActionKind.ASSIGN_LEAD:
        try:
            async with asyncio.timeout(3):
                assignee = await get_user_by_id(request.payload.assignee_id)
            name = _display_name(assignee.first_name, assignee.last_name) if assignee else None
        except Exception:
            name = None
        if name:
            preview["assignee"] = name
    if request.kind in EXTERNAL_KINDS:
        ready, delivery, consequence = await connectors.readiness(
            db,
            request.kind,
            request.payload,
            user_id=user_id,
            organization_id=organization_id,
            contact=resources.get("contact"),
        )
        preview["delivery"] = delivery
        if ready and consequence:
            preview["consequence"] = consequence
        if ready and request.kind == ActionKind.SEND_MESSAGE:
            preview["recipient"] = resources["contact"].email.strip()
    elif request.kind in {ActionKind.SCHEDULE_VIEWING, ActionKind.CANCEL_VIEWING}:
        preview["delivery"] = "Internal calendar record only; no invitations will be sent"
    elif request.kind in {ActionKind.CREATE_REMINDER, ActionKind.UPDATE_REMINDER}:
        preview["delivery"] = "Stored in your reminder list; no notification delivery is configured"
    elif request.kind in {ActionKind.CREATE_LISTING_DRAFT, ActionKind.UPDATE_LISTING_DRAFT}:
        preview["delivery"] = "Private listing draft only; not published"
    now = _now()
    row = AssistantAction(
        user_id=user_id,
        organization_id=organization_id,
        conversation_id=request.conversation_id,
        kind=request.kind.value,
        status="awaiting_confirmation",
        idempotency_key=request.idempotency_key,
        request_hash=request_hash,
        payload=payload,
        snapshot=snapshot,
        preview=preview,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )
    db.add(row)
    await db.commit()
    return _response(row)


async def _load(db, user_id, organization_id, action_id):
    await _authorize(db, user_id, organization_id)
    row = await repository.action(
        db,
        user_id=user_id,
        organization_id=organization_id,
        action_id=action_id,
    )
    if row is None:
        raise HTTPException(404, "Action not found")
    if not await repository.conversation(
        db,
        user_id=user_id,
        organization_id=organization_id,
        conversation_id=row.conversation_id,
    ):
        raise HTTPException(404, "Conversation not found")
    return row


def _expire(row):
    if row.status == "awaiting_confirmation" and row.expires_at <= _now():
        row.status = "expired"
        row.completed_at = _now()


async def _visible_response(db, row, user_id, organization_id):
    """Stored previews are private evidence, not permanent access to a moved target."""
    try:
        request = ActionProposalRequest(
            kind=row.kind,
            conversation_id=row.conversation_id,
            payload=row.payload,
            idempotency_key=row.idempotency_key,
        )
        _, snapshot = await _resources(db, request, user_id, organization_id)
        if row.status == "awaiting_confirmation" and snapshot != row.snapshot:
            row.status = "failed"
            row.completed_at = _now()
            row.result = {"message": "Record changed since preview; create a new proposal"}
        # Create requests have no input target; their result becomes the protected resource.
        if row.status == "succeeded" and row.result:
            if row.kind == ActionKind.CREATE_LEAD:
                target = await repository.own_lead(
                    db,
                    user_id=user_id,
                    organization_id=organization_id,
                    lead_id=row.result["lead_id"],
                )
                if target is None:
                    raise HTTPException(404, "Target unavailable")
            for kind, key, model in (
                (ActionKind.CREATE_REMINDER, "reminder_id", AssistantReminder),
                (ActionKind.SCHEDULE_VIEWING, "viewing_id", AssistantViewing),
                (ActionKind.CREATE_LISTING_DRAFT, "listing_id", AssistantListingDraft),
            ):
                if row.kind == kind:
                    target = await repository.own_record(
                        db,
                        model,
                        user_id=user_id,
                        organization_id=organization_id,
                        record_id=row.result[key],
                    )
                    if target is None:
                        raise HTTPException(404, "Target unavailable")
    except HTTPException:
        if row.status == "awaiting_confirmation":
            row.status, row.completed_at = "failed", _now()
        response = _response(row)
        response.preview = {"available": False, "message": "Target is no longer accessible"}
        response.result = {"message": "Target is no longer accessible"}
        return response
    return _response(row)


async def get_action(db, *, user_id, organization_id, action_id):
    row = await _load(db, user_id, organization_id, action_id)
    _expire(row)
    response = await _visible_response(db, row, user_id, organization_id)
    await db.commit()
    return response


async def list_actions(db, *, user_id, organization_id, conversation_id):
    await _authorize(db, user_id, organization_id, conversation_id)
    rows = await repository.actions(
        db,
        user_id=user_id,
        organization_id=organization_id,
        conversation_id=conversation_id,
    )
    responses = []
    for row in rows:
        _expire(row)
        responses.append(await _visible_response(db, row, user_id, organization_id))
    await db.commit()
    return responses


async def cancel_action(db, *, user_id, organization_id, action_id):
    row = await _load(db, user_id, organization_id, action_id)
    _expire(row)
    if row.status == "awaiting_confirmation":
        row.status, row.completed_at = "cancelled", _now()
    response = await _visible_response(db, row, user_id, organization_id)
    await db.commit()
    return response


async def confirm_action(db, *, user_id, organization_id, action_id):
    row = await _load(db, user_id, organization_id, action_id)
    _expire(row)
    if row.status != "awaiting_confirmation":
        response = await _visible_response(db, row, user_id, organization_id)
        await db.commit()
        return response
    request = ActionProposalRequest(
        kind=row.kind,
        conversation_id=row.conversation_id,
        payload=row.payload,
        idempotency_key=row.idempotency_key,
    )
    try:
        if _request_hash(request, user_id, organization_id) != row.request_hash:
            raise HTTPException(409, "Action arguments changed; create a new proposal")
        resources, snapshot = await _resources(db, request, user_id, organization_id)
        if snapshot != row.snapshot:
            raise HTTPException(409, "Record changed since preview; create a new proposal")
    except HTTPException as error:
        row.status = "failed"
        row.result = {"message": error.detail}
    else:
        # A savepoint prevents a partial mutation from being committed on execution failure.
        ready = False
        if request.kind in EXTERNAL_KINDS:
            ready, _, _ = await connectors.readiness(
                db,
                request.kind,
                request.payload,
                user_id=user_id,
                organization_id=organization_id,
                contact=resources.get("contact"),
            )
        async with db.begin_nested():
            row.result = await _execute(db, row, request, resources, queue=ready)
        if request.kind not in EXTERNAL_KINDS:
            row.status = "succeeded"
        else:
            row.status = "queued" if ready else "not_connected"
    if row.status != "queued":
        row.completed_at = _now()
    response = await _visible_response(db, row, user_id, organization_id)
    await db.commit()
    if response.status == "queued":
        # The claim marks it unknown before the network call; a crash can never send twice.
        await dispatch_confirmed(
            db,
            user_id=user_id,
            organization_id=organization_id,
            action_id=action_id,
            adapter=connectors.adapter_for(
                db, request.kind, user_id=user_id, organization_id=organization_id
            ),
        )
        return await get_action(
            db, user_id=user_id, organization_id=organization_id, action_id=action_id
        )
    return response


async def _execute(db, row, request, resources, *, queue=False):
    kind, payload, now = request.kind, request.payload, _now()
    owner = {"user_id": row.user_id, "organization_id": row.organization_id}
    if kind in EXTERNAL_KINDS:
        db.add(
            AssistantOutbox(
                action_id=row.id,
                **owner,
                kind=kind.value,
                status="queued" if queue else "not_connected",
                payload=row.payload,
                created_at=now,
            )
        )
        if queue:
            return {"message": "Confirmed; sending now."}
        return {"message": "No connector configured. Nothing was sent, published, or booked."}
    if kind == ActionKind.CREATE_LEAD:
        contact = CrmInboundContact(
            organization_id=row.organization_id,
            full_name=payload.full_name,
            phone=payload.phone,
            email=payload.email,
            created_at=now,
            updated_at=now,
        )
        db.add(contact)
        await db.flush()
        lead = CrmInboundEnquiry(
            organization_id=row.organization_id,
            contact_id=contact.id,
            created_by_user_id=row.user_id,
            assigned_user_id=row.user_id,
            intent=payload.intent,
            raw_notes=payload.notes,
            source="Assistant",
            enquiry_date=now,
            created_at=now,
            updated_at=now,
        )
        db.add(lead)
        await db.flush()
        return {"lead_id": lead.id, "message": "Lead created"}
    if kind in {ActionKind.UPDATE_LEAD, ActionKind.ASSIGN_LEAD}:
        lead = resources["lead"]
        if kind == ActionKind.ASSIGN_LEAD:
            lead.assigned_user_id = payload.assignee_id
        else:
            for key, value in payload.model_dump(exclude_unset=True, exclude={"lead_id"}).items():
                setattr(lead, key, value)
        lead.updated_at = now
        return {"lead_id": lead.id, "message": "Lead updated"}
    if kind == ActionKind.DELETE_LEAD:
        for dependent in resources["dependents"]:
            await db.delete(dependent)
        await db.delete(resources["lead"])
        return {"lead_id": payload.lead_id, "message": "Enquiry deleted; shared contact preserved"}
    if kind == ActionKind.ADD_NOTE:
        note = CrmInboundNote(
            **owner,
            enquiry_id=payload.lead_id,
            body=payload.body,
            created_at=now,
        )
        db.add(note)
        resources["lead"].updated_at = now
        await db.flush()
        return {"note_id": note.id, "lead_id": payload.lead_id, "message": "Note added"}
    if kind == ActionKind.CREATE_REMINDER:
        item = AssistantReminder(**owner, **payload.model_dump(), updated_at=now)
        db.add(item)
        await db.flush()
        return {
            "reminder_id": item.id,
            "message": "Reminder saved; notification delivery is not configured",
        }
    if kind == ActionKind.UPDATE_REMINDER:
        item = resources["reminder"]
        item.title, item.due_at, item.updated_at = payload.title, payload.due_at, now
        return {"reminder_id": item.id, "message": "Reminder updated"}
    if kind == ActionKind.DELETE_REMINDER:
        await db.delete(resources["reminder"])
        return {"reminder_id": payload.reminder_id, "message": "Reminder deleted"}
    if kind == ActionKind.SCHEDULE_VIEWING:
        item = AssistantViewing(**owner, **payload.model_dump(), updated_at=now)
        db.add(item)
        await db.flush()
        return {"viewing_id": item.id, "message": "Internal viewing scheduled; no invitations sent"}
    if kind == ActionKind.CANCEL_VIEWING:
        item = resources["viewing"]
        item.status, item.updated_at = "cancelled", now
        return {"viewing_id": item.id, "message": "Internal viewing cancelled; no invitations sent"}
    if kind == ActionKind.CREATE_LISTING_DRAFT:
        item = AssistantListingDraft(**owner, **payload.model_dump(), updated_at=now)
        db.add(item)
        await db.flush()
        return {"listing_id": item.id, "message": "Listing draft saved; not published"}
    if kind == ActionKind.UPDATE_LISTING_DRAFT:
        item = resources["listing"]
        for key, value in payload.model_dump(exclude={"listing_id"}).items():
            setattr(item, key, value)
        item.updated_at = now
        return {"listing_id": item.id, "message": "Listing draft updated; not published"}
    raise HTTPException(400, "Unsupported action")


async def _list_records(db, model, response_model, user_id, organization_id):
    await _authorize(db, user_id, organization_id)
    rows = await repository.records(db, model, user_id=user_id, organization_id=organization_id)
    result = []
    for row in rows:
        lead_id = getattr(row, "lead_id", None)
        if lead_id is not None and not await repository.own_lead(
            db,
            user_id=user_id,
            organization_id=organization_id,
            lead_id=lead_id,
        ):
            continue
        result.append(response_model.model_validate(row))
    await db.commit()
    return result


async def list_reminders(db, *, user_id, organization_id):
    return await _list_records(db, AssistantReminder, ReminderResponse, user_id, organization_id)


async def list_viewings(db, *, user_id, organization_id):
    return await _list_records(db, AssistantViewing, ViewingResponse, user_id, organization_id)


async def list_listing_drafts(db, *, user_id, organization_id):
    return await _list_records(
        db, AssistantListingDraft, ListingDraftResponse, user_id, organization_id
    )


async def claim_external_dispatch(db, *, user_id, organization_id, action_id):
    """Future worker boundary: only a separately configured, confirmed queued action.

    No production path currently queues an action. Claims become unknown *before*
    network I/O so a crash or timeout cannot cause an automatic duplicate send.
    """
    row = await _load(db, user_id, organization_id, action_id)
    outbox = await repository.outbox(
        db,
        user_id=user_id,
        organization_id=organization_id,
        action_id=action_id,
    )
    if (
        row.kind not in EXTERNAL_KINDS
        or row.status != "queued"
        or outbox is None
        or outbox.status != "queued"
        or outbox.claimed_at is not None
    ):
        await db.commit()
        return None
    request = ActionProposalRequest(
        kind=row.kind,
        conversation_id=row.conversation_id,
        payload=row.payload,
        idempotency_key=row.idempotency_key,
    )
    try:
        if _request_hash(request, user_id, organization_id) != row.request_hash:
            raise HTTPException(409, "Action arguments changed")
        _, snapshot = await _resources(db, request, user_id, organization_id)
        if snapshot != row.snapshot or outbox.payload != row.payload or outbox.kind != row.kind:
            raise HTTPException(409, "Target or action changed")
    except HTTPException:
        row.status = outbox.status = "failed"
        row.result = {"message": "Action authorization or target changed before dispatch"}
        await db.commit()
        return None
    row.status = outbox.status = "unknown"
    row.result = {"message": "Delivery outcome is pending reconciliation; do not resend"}
    outbox.claimed_at = _now()
    await db.commit()
    return request.payload


async def dispatch_confirmed(db, *, user_id, organization_id, action_id, adapter):
    """Claim once, dispatch once, record the outcome; None when nothing is claimable."""
    payload = await claim_external_dispatch(
        db, user_id=user_id, organization_id=organization_id, action_id=action_id
    )
    if payload is None:
        return None
    outcome = await dispatch_claimed(adapter, payload=payload, idempotency_key=action_id)
    await record_external_outcome(
        db,
        user_id=user_id,
        organization_id=organization_id,
        action_id=action_id,
        status=outcome.status,
        message=outcome.message,
    )
    return outcome


async def record_external_outcome(
    db, *, user_id, organization_id, action_id, status, message: str | None = None
):
    """Persist only a claim's safe outcome, including after offboarding during delivery."""
    if status not in {"succeeded", "failed", "unknown", "not_connected"}:
        raise ValueError("Invalid delivery outcome")
    row = await repository.action(
        db,
        user_id=user_id,
        organization_id=organization_id,
        action_id=action_id,
    )
    outbox = await repository.outbox(
        db,
        user_id=user_id,
        organization_id=organization_id,
        action_id=action_id,
    )
    if row and outbox and outbox.claimed_at and row.status == outbox.status == "unknown":
        row.status = outbox.status = status
        row.result = {"message": message or f"External action outcome: {status}"}
        row.completed_at = _now()
    await db.commit()


def _display_name(first_name, last_name):
    name = " ".join(f"{first_name or ''} {last_name or ''}".split())
    return name[:200] or None


async def lookup_assignees(db, *, user_id: str, organization_id: str, search: str):
    """Bounded business-name lookup within the actor's current organization only."""
    if not isinstance(search, str) or not 2 <= len(search.strip()) <= 80:
        raise HTTPException(422, "Enter between 2 and 80 characters of a member's name")
    prefix = " ".join(search.split()).casefold()
    await _authorize(db, user_id, organization_id)
    organization = await repository.organization(db, organization_id)
    # Release database locks while the existing public directory adapter fetches profiles.
    await db.commit()
    try:
        async with asyncio.timeout(10):
            members = await get_organization_members(organization, db)
    except Exception:
        await db.rollback()
        await _authorize(db, user_id, organization_id)
        await db.commit()
        return {
            "available": False,
            "reason": "Organization member names are temporarily unavailable",
        }
    await _authorize(db, user_id, organization_id)
    current_ids = await repository.member_ids(db, organization_id=organization_id)
    matches = []
    for member in members:
        if member["id"] not in current_ids:
            continue
        name = _display_name(member.get("first_name"), member.get("last_name"))
        if name and name.casefold().startswith(prefix):
            matches.append({"id": member["id"], "display_name": name})
    matches.sort(key=lambda item: (item["display_name"].casefold(), item["id"]))
    await db.commit()
    return {
        "available": True,
        "matches": matches[:10],
        "clarification_required": len(matches) > 1,
        "truncated": len(matches) > 10,
    }
