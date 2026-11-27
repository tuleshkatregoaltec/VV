"""Propose exact changes; execute only after authenticated UI confirmation."""

import asyncio
import hashlib
import json
import re
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
from app.crm import assignment, inbound
from app.crm.inbound_models import CrmInboundContact, CrmInboundEnquiry, CrmInboundNote
from app.organization import teams as org_teams
from app.organization.models import TeamMemberInput, TeamMembersUpdateRequest
from app.organization.service import get_organization_members

EXTERNAL_KINDS = {
    ActionKind.SEND_MESSAGE,
    ActionKind.PUBLISH_LISTING,
    ActionKind.BOOK_EXTERNAL_VIEWING,
    ActionKind.BOOK_CALENDAR_MEETING,
    # The CRM calendar saves and syncs Google itself (it commits), so these run after the
    # confirmation is recorded and report the calendar's own outcome.
    ActionKind.RESCHEDULE_CALENDAR_EVENT,
    ActionKind.CANCEL_CALENDAR_EVENT,
}
# Changes to a lead itself: a pooled lead stays read-only to agents until they claim it.
EDIT_KINDS = {
    ActionKind.UPDATE_LEAD,
    ActionKind.ADD_NOTE,
    ActionKind.SCHEDULE_VIEWING,
    ActionKind.CANCEL_VIEWING,
    ActionKind.SEND_MESSAGE,
    ActionKind.BOOK_EXTERNAL_VIEWING,
    ActionKind.BOOK_CALENDAR_MEETING,
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
        title=TITLES.get(row.kind, row.kind.replace("_", " ").capitalize()),
        preview=row.preview,
        created_at=row.created_at,
        expires_at=row.expires_at,
        result=row.result,
    )


# The CRM's own name for a team's managers: its Teams page calls the role Supervisor.
TITLES = {ActionKind.SET_TEAM_MANAGER: "Set team supervisor"}
REASSIGN_KINDS = {ActionKind.ASSIGN_LEAD, ActionKind.UNASSIGN_LEAD, ActionKind.RELEASE_TO_POOL}
NO_LEAD_DELETION = (
    "The CRM does not support deleting leads, so the assistant cannot delete one. "
    "You can change its stage instead (for example to lost or disqualified)."
)


TEAM_KINDS = {
    ActionKind.CREATE_TEAM,
    ActionKind.DELETE_TEAM,
    ActionKind.ADD_TEAM_AGENT,
    ActionKind.REMOVE_TEAM_MEMBER,
    ActionKind.SET_TEAM_MANAGER,
    ActionKind.UPDATE_TEAM_MEMBERS,
    ActionKind.MOVE_TEAM_AGENT,
}
# Every proposal for an existing team previews its whole roster and is refused on confirmation
# once that roster changed; so only one may await confirmation per team at a time.
PENDING_TEAM_CHANGE = (
    "Another change to this team is already awaiting your confirmation. Confirm or cancel it "
    "first; to change several members at once, propose them together as one change."
)
CALENDAR_EVENT_KINDS = {ActionKind.RESCHEDULE_CALENDAR_EVENT, ActionKind.CANCEL_CALENDAR_EVENT}
TEAM_ADMIN_ONLY = (
    "Only the organization's owner or an administrator can create or delete teams or change "
    "their members and managers, as on the CRM's Teams page."
)
ROLE_NAMES = {"supervisor": "supervisor", "agent": "agent"}
# A role said after a colleague's name ("Track 6 agent"); never a name on its own.
_ROLE_WORDS = {"agent", "manager", "supervisor"}


async def _team_resources(db, request, scope, organization_id, *, pending):
    """The CRM's Teams rules (organization/router.py: organization administrators only) and
    the team's current membership, locked; the state checks apply while it awaits confirmation.
    """
    if not scope.organization_admin:
        raise HTTPException(403, TEAM_ADMIN_ONLY)
    payload = request.payload
    if request.kind == ActionKind.CREATE_TEAM:
        # A taken name is refused by the CRM when the team is created; its members must each
        # still belong to the organization, now and again on confirmation.
        if payload.members:
            members = await repository.member_ids(db, organization_id=organization_id)
            if any(member.member_id not in members for member in payload.members):
                raise HTTPException(409, "That person is not a member of your organization")
        return {}
    if request.kind == ActionKind.MOVE_TEAM_AGENT:
        return await _transfer_resources(db, payload, organization_id, pending=pending)
    team = await repository.team(db, organization_id=organization_id, team_id=payload.team_id)
    if team is None:
        if not pending and request.kind == ActionKind.DELETE_TEAM:
            return {}  # Deleted, as confirmed.
        raise HTTPException(404, "Team not found in your organization")
    members = await repository.team_members(db, organization_id=organization_id, team_id=team.id)
    if request.kind == ActionKind.UPDATE_TEAM_MEMBERS and pending:
        in_organization = await repository.member_ids(db, organization_id=organization_id)
        roles = {member.user_id: member.role for member in members}
        for change in payload.members:
            name = await _person_name(change.member_id)
            if change.member_id not in in_organization:
                raise HTTPException(409, f"{name} is not a member of your organization")
            if roles.get(change.member_id) == change.role:
                raise HTTPException(
                    409, f"{name} is already in this team as {ROLE_NAMES[change.role]}"
                )
    person = getattr(payload, "member_id", None)
    if person is not None:
        if person not in await repository.member_ids(db, organization_id=organization_id):
            raise HTTPException(409, "That person is not a member of your organization")
        role = next((member.role for member in members if member.user_id == person), None)
        if pending and request.kind == ActionKind.ADD_TEAM_AGENT and role:
            raise HTTPException(409, f"Already in this team as {ROLE_NAMES[role]}")
        if pending and request.kind == ActionKind.REMOVE_TEAM_MEMBER and role is None:
            raise HTTPException(409, "This person is not in this team")
        if pending and request.kind == ActionKind.SET_TEAM_MANAGER and role == "supervisor":
            others = [m for m in members if m.role == "supervisor" and m.user_id != person]
            if not (payload.replace_existing and others):
                raise HTTPException(409, "This person is already a supervisor of this team")
    return {"team": team, "team_members": list(members)}


async def _transfer_resources(db, payload, organization_id, *, pending):
    """Both teams and their members, locked in a fixed order. While it awaits confirmation the
    person must be an agent of the first team and not yet in the second."""
    teams = {}
    for team_id in sorted({payload.from_team_id, payload.to_team_id}):
        team = await repository.team(db, organization_id=organization_id, team_id=team_id)
        if team is None:
            raise HTTPException(404, "Team not found in your organization")
        members = await repository.team_members(
            db, organization_id=organization_id, team_id=team.id
        )
        teams[team_id] = (team, list(members))
    if payload.member_id not in await repository.member_ids(db, organization_id=organization_id):
        raise HTTPException(409, "That person is not a member of your organization")
    (source, source_members), (target, target_members) = (
        teams[payload.from_team_id],
        teams[payload.to_team_id],
    )
    if pending:
        role = next((m.role for m in source_members if m.user_id == payload.member_id), None)
        if role is None:
            raise HTTPException(409, f"This person is not in {source.name}")
        if role == "supervisor":
            raise HTTPException(
                409,
                f"This person manages {source.name}; only agents are moved. Change the "
                "team's managers instead.",
            )
        if any(m.user_id == payload.member_id for m in target_members):
            raise HTTPException(409, f"This person is already in {target.name}")
    return {
        "team": source,
        "team_members": source_members,
        "to_team": target,
        "to_team_members": target_members,
    }


async def _calendar_resources(db, request, user_id, organization_id, *, pending):
    """The user's own event, as CRM › Calendar allows (crm/router.py _own_event), locked."""
    event = await repository.own_calendar_event(
        db, user_id=user_id, organization_id=organization_id, event_id=request.payload.event_id
    )
    if event is None:
        if not pending and request.kind == ActionKind.CANCEL_CALENDAR_EVENT:
            return {}  # Deleted, as confirmed.
        raise HTTPException(404, "Calendar event not found")
    if pending and request.kind == ActionKind.RESCHEDULE_CALENDAR_EVENT:
        if (event.event_date, event.event_time) == (request.payload.date, request.payload.time):
            raise HTTPException(409, "The event is already at that date and time")
    return {"calendar_event": event}


def _refuse_unsupported(kind):
    """Capabilities the CRM itself does not offer are refused before any lead is read."""
    if kind == ActionKind.DELETE_LEAD:
        raise HTTPException(403, NO_LEAD_DELETION)


def _lead_rights(scope, kind, lead, *, pending=True):
    """The CRM's own rules for this change on this lead (crm/assignment.py, crm/inbound.py),
    applied on proposal, on confirmation and when a request is held between turns."""
    if kind in EDIT_KINDS:
        assignment.require_edit(scope, lead)
    if kind == ActionKind.LOG_CONTACT:
        # As crm/inbound.log_contact: logging contact on a lead in the pool of a team the user
        # belongs to takes it; on any other lead it needs edit rights.
        pooled = lead.assigned_user_id is None and lead.pool_released_at is not None
        if not (pooled and lead.team_id in scope.member_team_ids):
            assignment.require_edit(scope, lead)
    if kind in REASSIGN_KINDS and not scope.may_reassign(lead):
        raise HTTPException(403, "You cannot reassign this lead")
    if kind == ActionKind.RELEASE_TO_POOL:
        if lead.team_id is None or lead.team_id not in scope.team_members:
            raise HTTPException(
                403, "This lead is not in a team you manage; choose its team in the CRM first"
            )
        if pending and lead.assigned_user_id is None and lead.pool_released_at is not None:
            raise HTTPException(409, "This lead is already waiting in its team's pool")


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


async def _resources(db, request, user_id, organization_id, *, pending=True):
    """Lock every target and take a versioned snapshot used again on confirmation.

    `pending` is false when showing a finished action: its effect may have changed the
    target (a removed member, a deleted team), so only access is checked, not the state."""
    payload = request.payload
    _refuse_unsupported(request.kind)
    # Lead authority is the CRM's own (crm/assignment.py): agent, manager or administrator.
    scope = await assignment.load_scope(db, organization_id, user_id)
    resources = {"scope": scope}
    if request.kind in TEAM_KINDS:
        resources.update(
            await _team_resources(db, request, scope, organization_id, pending=pending)
        )
    if request.kind in CALENDAR_EVENT_KINDS:
        resources.update(
            await _calendar_resources(db, request, user_id, organization_id, pending=pending)
        )
    lead_id = getattr(payload, "lead_id", None)
    if lead_id is not None:
        resources["lead"] = await assignment.load_visible(db, scope, lead_id, lock=True)
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
                resources["lead"] = await assignment.load_visible(db, scope, linked_lead, lock=True)
    if "lead" in resources:
        contact = await repository.lead_contact(
            db,
            organization_id=organization_id,
            contact_id=resources["lead"].contact_id,
        )
        if contact is None:
            raise HTTPException(404, "Lead contact not found")
        resources["contact"] = contact
        _lead_rights(scope, request.kind, resources["lead"], pending=pending)
    if request.kind == ActionKind.ASSIGN_LEAD:
        # Raises when the assignee is not in a team this user may assign into.
        assignment.assignable_team(scope, payload.assignee_id, None, resources["lead"].team_id)
    if request.kind == ActionKind.UNASSIGN_LEAD and pending:
        # Only while it awaits confirmation: once done, the lead is unassigned by design.
        if resources["lead"].assigned_user_id is None:
            raise HTTPException(409, "This lead is already unassigned")
    if request.kind == ActionKind.BOOK_CALENDAR_MEETING and payload.colleague_ids:
        # Named colleagues must still be members of this organization (other than the user).
        members = await repository.member_ids(db, organization_id=organization_id)
        if any(item == user_id or item not in members for item in payload.colleague_ids):
            raise HTTPException(
                409, "A named colleague is not a current member of your organization"
            )
        resources["colleagues"] = sorted(payload.colleague_ids)
    if request.kind == ActionKind.BOOK_CALENDAR_MEETING:
        # Who Google Calendar would invite, and whether it makes a Meet link: rechecked on
        # confirmation, so a disconnected calendar or a changed email never sends an
        # invitation, or promises a link, the user did not see.
        resources["invitations"] = await meeting_invitations(
            db, payload, user_id=user_id, organization_id=organization_id
        )
    snapshot = {}
    for key, record in resources.items():
        if key == "scope":
            continue
        if key == "colleagues":
            snapshot[key] = record
        elif key == "invitations":
            snapshot[key] = _hash(record)
        elif key in {"team_members", "to_team_members"}:
            snapshot[key] = sorted([member.user_id, member.role] for member in record)
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
        ActionKind.ASSIGN_LEAD: "Assigns this lead to the selected team member and records it in the lead's assignment history.",
        ActionKind.UNASSIGN_LEAD: "Removes the lead's assignee; the lead, its team and its history are kept, and it is recorded in the assignment history. Nothing is deleted.",
        ActionKind.LOG_CONTACT: "Logs this contact on the lead's history, as the CRM's Log contact does. A lead waiting in your team's pool becomes yours.",
        ActionKind.RELEASE_TO_POOL: "Removes the lead's assignee and shares it in its team's pool; the first team member to log contact takes it. Recorded in the assignment history.",
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
        ActionKind.BOOK_CALENDAR_MEETING: "Adds this meeting to your own calendar. Named colleagues appear in its details only; no invitations are sent.",
        ActionKind.CREATE_TEAM: "Creates this team with no members, as the CRM's Teams page does. Add its supervisors and agents afterwards.",
        ActionKind.DELETE_TEAM: "Deletes this team. Its members stay in the organization. The CRM refuses if leads or routing rules still use the team.",
        ActionKind.ADD_TEAM_AGENT: "Adds this person to the team as an agent.",
        ActionKind.REMOVE_TEAM_MEMBER: "Removes this person from the team; they stay in the organization and keep the leads assigned to them.",
        ActionKind.UPDATE_TEAM_MEMBERS: "Saves these people's roles in the team together, as the CRM's Teams page saves its members: all of them or, if the CRM refuses, none. Everyone else in the team stays as they are.",
        ActionKind.SET_TEAM_MANAGER: "Makes this person a supervisor of the team, who manages it, imports leads and assigns them (added, or promoted from agent).",
        ActionKind.MOVE_TEAM_AGENT: "Moves this agent out of the first team and into the second as an agent. They stay in the organization and keep the leads assigned to them; those leads stay with the team that owns them.",
    }
    if request.kind in consequences:
        preview["consequence"] = consequences[request.kind]
    if request.kind == ActionKind.CREATE_TEAM and request.payload.members:
        preview["consequence"] = (
            "Creates this team with the supervisors and agents listed, together, as the CRM's "
            "Teams page sets them: supervisors manage the team, import leads and assign them; "
            "agents receive leads and work on them."
        )
    return preview


def _event_when(event_date, event_time, end_date=None, end_time=None) -> str:
    day = f"{event_date.day} {event_date:%b %Y}"
    if event_time is None:
        return f"{day}, all day"
    end = f"–{end_time}" if end_time and (end_date in (None, event_date)) else ""
    return f"{day} {event_time}{end} Dubai time"


def _calendar_preview(request, event):
    """The event as the user knows it (title and time), never its ID."""
    preview = {
        "event": event.title,
        "currently": _event_when(
            event.event_date, event.event_time, event.event_end_date, event.event_end_time
        ),
    }
    if event.repeat and event.repeat != "none":
        preview["repeats"] = (
            f"{event.repeat}; the whole series moves or is deleted, as in CRM › Calendar"
        )
    if request.kind == ActionKind.RESCHEDULE_CALENDAR_EVENT:
        preview["new_time"] = _event_when(request.payload.date, request.payload.time)
    return preview


async def _team_preview(request, resources):
    """Names, never IDs: the team, the person and the team's current managers and agents."""
    payload = request.payload
    if request.kind == ActionKind.CREATE_TEAM:
        preview = {"team": payload.name}
        if payload.members:
            for role, label in (("supervisor", "supervisors"), ("agent", "agents")):
                preview[label] = [
                    await _person_name(m.member_id) for m in payload.members if m.role == role
                ]
        return preview
    if request.kind == ActionKind.MOVE_TEAM_AGENT:
        return {
            "person": await _person_name(payload.member_id),
            "from_team": resources["team"].name,
            "to_team": resources["to_team"].name,
        }
    members = resources["team_members"]
    preview = {
        "team": resources["team"].name,
        "current_supervisors": [
            await _person_name(m.user_id) for m in members if m.role == "supervisor"
        ],
        "current_agents": [await _person_name(m.user_id) for m in members if m.role == "agent"],
    }
    if request.kind == ActionKind.UPDATE_TEAM_MEMBERS:
        current = {member.user_id: member.role for member in members}
        for role, label in (("supervisor", "becoming_supervisors"), ("agent", "becoming_agents")):
            names = [await _person_name(m.member_id) for m in payload.members if m.role == role]
            if names:
                preview[label] = names
        changing = [
            f"{await _person_name(m.member_id)} ({ROLE_NAMES[current[m.member_id]]} to "
            f"{ROLE_NAMES[m.role]})"
            for m in payload.members
            if current.get(m.member_id) not in (None, m.role)
        ]
        if changing:
            preview["changing_role"] = changing
    if getattr(payload, "member_id", None):
        preview["person"] = await _person_name(payload.member_id)
    if request.kind == ActionKind.SET_TEAM_MANAGER and payload.replace_existing:
        leaving = [
            await _person_name(m.user_id)
            for m in members
            if m.role == "supervisor" and m.user_id != payload.member_id
        ]
        if leaving:
            preview["supervisors_leaving_the_team"] = leaving
    return preview


async def _with_meeting_title(db, request, user_id, organization_id):
    """A meeting without a title is named after whom it is with: "Meeting with Mariam Ali",
    from the lead (only one this user can see) and the colleagues' verified names. Applied
    before hashing, so the stored request, its confirmation and any retry carry the same title."""
    payload = request.payload
    if request.kind != ActionKind.BOOK_CALENDAR_MEETING or payload.title:
        return request
    names = []
    if payload.lead_id is not None:
        lead = await repository.visible_lead(
            db, user_id=user_id, organization_id=organization_id, lead_id=payload.lead_id
        )
        contact = (
            await repository.lead_contact(
                db, organization_id=organization_id, contact_id=lead.contact_id
            )
            if lead
            else None
        )
        if contact and contact.full_name.strip():
            names.append(contact.full_name.strip())
    names += [await _person_name(item) for item in payload.colleague_ids]
    title = ("Meeting with " + " and ".join(names))[:200] if names else "Meeting"
    return request.model_copy(update={"payload": payload.model_copy(update={"title": title})})


async def propose_action(
    db, *, user_id: str, organization_id: str, request: ActionProposalRequest
) -> ActionProposalResponse:
    await _authorize(db, user_id, organization_id, request.conversation_id)
    request = await _with_meeting_title(db, request, user_id, organization_id)
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
    if request.kind in TEAM_KINDS:
        await _one_pending_change_per_team(db, payload, user_id, organization_id)
    preview = {**_target_preview(request, resources), "changes": payload}
    if request.kind in REASSIGN_KINDS:
        preview["current_assignee"] = await _person_name(resources["lead"].assigned_user_id)
        preview["new_assignee"] = (
            await _person_name(request.payload.assignee_id)
            if request.kind == ActionKind.ASSIGN_LEAD
            else "Team pool"
            if request.kind == ActionKind.RELEASE_TO_POOL
            else "Unassigned"
        )
    if request.kind in TEAM_KINDS:
        # Names only: the raw arguments are IDs.
        preview.pop("changes")
        preview.update(await _team_preview(request, resources))
    if request.kind in CALENDAR_EVENT_KINDS:
        preview.pop("changes")
        preview.update(_calendar_preview(request, resources["calendar_event"]))
    if request.kind == ActionKind.BOOK_CALENDAR_MEETING:
        preview["when"] = connectors.dubai_span(request.payload.starts_at, request.payload.ends_at)
        if request.payload.colleague_ids:
            preview["with"] = [await _person_name(item) for item in request.payload.colleague_ids]
        invitations = await _invitation_lines(request.payload, resources)
        if invitations:
            preview["invitations"] = invitations
        preview["video"] = (
            "A Google Meet link will be created and sent with the invitation"
            if resources["invitations"]["meet"]
            else "No Google Meet link: Google Calendar is not connected"
        )
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
        plan = resources.get("invitations") or {}
        if plan.get("invited") or (plan.get("lead") or {}).get("email"):
            preview["consequence"] = (
                "Adds this meeting to your own calendar. Google Calendar emails an invitation, "
                "with the Google Meet link, to each person listed as invited; nobody else is "
                "invited."
            )
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


def _team_ids(payload: dict) -> set[str]:
    return {payload[key] for key in ("team_id", "from_team_id", "to_team_id") if payload.get(key)}


async def _one_pending_change_per_team(db, payload: dict, user_id, organization_id):
    """Refuse a team proposal while another of this user's proposals for the same team still
    awaits confirmation and could succeed; both preview the same roster, so confirming one
    would make the other stale. An expired, stale or inaccessible one is settled instead."""
    teams = _team_ids(payload)
    if not teams:
        return  # A new team has no roster yet.
    waiting = await repository.awaiting_actions(
        db, user_id=user_id, organization_id=organization_id, kinds=TEAM_KINDS
    )
    for row in waiting:
        if not teams & _team_ids(row.payload or {}):
            continue
        _expire(row)
        if row.status == "awaiting_confirmation":
            await _visible_response(db, row, user_id, organization_id)
        if row.status == "awaiting_confirmation":
            await db.commit()
            raise HTTPException(409, PENDING_TEAM_CHANGE)


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
        resources, snapshot = await _resources(
            db, request, user_id, organization_id, pending=row.status == "awaiting_confirmation"
        )
        if row.status == "awaiting_confirmation" and snapshot != row.snapshot:
            row.status = "failed"
            row.completed_at = _now()
            row.result = {"message": "Record changed since preview; create a new proposal"}
        # Create requests have no input target; their result becomes the protected resource.
        if row.status == "succeeded" and row.result:
            if row.kind == ActionKind.CREATE_LEAD:
                target = await repository.visible_lead(
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
    response = _response(row)
    if row.status == "succeeded" and row.kind in REASSIGN_KINDS and "lead" in resources:
        await _show_assignment_outcome(response, row, resources["lead"])
    return response


async def _show_assignment_outcome(response, row, lead) -> None:
    """A confirmed (re)assignment's card states who holds the lead now, read from the CRM; the
    proposal's "new assignee" was only what was asked for. The stored preview is unchanged."""
    preview = dict(response.preview)
    previous = preview.pop("current_assignee", None)
    preview.pop("new_assignee", None)
    if lead.assigned_user_id is None:
        holder = "Team pool" if lead.pool_released_at is not None else "Unassigned"
    else:
        holder = await _person_name(lead.assigned_user_id)
    response.preview = {**preview, "previous_assignee": previous, "current_assignee": holder}
    if row.kind == ActionKind.ASSIGN_LEAD:
        asked = (row.payload or {}).get("assignee_id")
        message = (
            f"Lead assigned to {holder}"
            if lead.assigned_user_id == asked
            else f"Lead assigned; it is now with {holder}"
        )
        response.result = {**(response.result or {}), "message": message}


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
        try:
            async with db.begin_nested():
                row.result = await _execute(db, row, request, resources, queue=ready)
        except HTTPException as error:
            # The CRM refused the change (a taken team name, a team still in use): nothing
            # was saved, and it is reported as failed with the CRM's reason.
            row.status = "failed"
            row.result = {"message": error.detail}
        else:
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
                db,
                request.kind,
                user_id=user_id,
                organization_id=organization_id,
                person_name=_person_name,
                invitations=meeting_invitations,
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
    if kind in TEAM_KINDS:
        return await _execute_team(db, row, request, resources)
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
            # As in the CRM's lead creation: only a known intent makes a confirmed opportunity.
            record_kind="opportunity" if payload.intent != "unknown" else "unqualified_contact",
            intent=payload.intent,
            confirmed_data={"intent": payload.intent} if payload.intent != "unknown" else {},
            raw_notes=payload.notes,
            source="Assistant",
            enquiry_date=now,
            created_at=now,
            updated_at=now,
        )
        db.add(lead)
        await db.flush()
        # As in the CRM: the creator holds it, in their team, with an assignment history entry.
        team = await assignment.check_new_assignee(db, resources["scope"], row.user_id)
        assignment.record_assignment(
            db,
            lead,
            row.user_id,
            actor_user_id=row.user_id,
            reason="created",
            now=now,
            team_id=team,
        )
        return {"lead_id": lead.id, "message": "Lead created"}
    if kind in {ActionKind.UPDATE_LEAD, ActionKind.ASSIGN_LEAD, ActionKind.UNASSIGN_LEAD}:
        lead = resources["lead"]
        if kind in {ActionKind.ASSIGN_LEAD, ActionKind.UNASSIGN_LEAD}:
            # The CRM's authorized reassignment: history, owning team, pool and rotation.
            assignee = payload.assignee_id if kind == ActionKind.ASSIGN_LEAD else None
            await assignment.reassign(db, resources["scope"], [lead.id], assignee, reason="manual")
            return {
                "lead_id": lead.id,
                "message": "Lead assigned" if assignee else "Lead unassigned",
            }
        changes = payload.model_dump(exclude_unset=True, exclude={"lead_id"})
        for key, value in changes.items():
            setattr(lead, key, value)
        # Keep the classification as the CRM's own lead update does (crm/inbound.py).
        if changes.get("intent") and changes["intent"] != "unknown":
            lead.record_kind = "opportunity"
            lead.confirmed_data = {**(lead.confirmed_data or {}), "intent": changes["intent"]}
        if lead.intent == "unknown":
            lead.record_kind = "unqualified_contact"
        lead.updated_at = now
        return {"lead_id": lead.id, "message": "Lead updated"}
    if kind == ActionKind.LOG_CONTACT:
        lead = resources["lead"]
        holder = lead.assigned_user_id
        # The CRM's own write: claim from the pool or edit check, rotation, counters, history.
        await inbound.log_contact(
            db,
            resources["scope"],
            enquiry_id=lead.id,
            activity_type=payload.activity_type,
            body=payload.body,
        )
        taken = holder is None and lead.assigned_user_id == row.user_id
        return {
            "lead_id": lead.id,
            "message": "Contact logged; the lead is now yours" if taken else "Contact logged",
        }
    if kind == ActionKind.RELEASE_TO_POOL:
        lead = resources["lead"]
        await assignment.release(db, resources["scope"], [lead.id], lead.team_id)
        return {"lead_id": lead.id, "message": "Lead shared in its team's pool"}
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


async def _execute_team(db, row, request, resources):
    """Through the CRM's own team writes (organization/teams.py), in the confirmation's
    savepoint; a CRM refusal raises and nothing is kept."""
    kind, payload, organization_id = request.kind, request.payload, row.organization_id
    if kind == ActionKind.CREATE_TEAM:
        team = await org_teams.stage_team(db, organization_id, payload.name)
        if not payload.members:
            return {"team_id": team.id, "message": f"Team {team.name} created"}
        # Its roster in the same savepoint, through the CRM's own write: all or nothing.
        await _save_roster(
            db, organization_id, team, {m.member_id: m.role for m in payload.members}
        )
        count = len(payload.members)
        return {
            "team_id": team.id,
            "message": f"Team {team.name} created with {count} member{'s' * (count != 1)}",
        }
    team = resources["team"]
    name = team.name
    if kind == ActionKind.DELETE_TEAM:
        await org_teams.stage_team_deletion(db, team)
        return {"message": f"Team {name} deleted"}
    if kind == ActionKind.MOVE_TEAM_AGENT:
        target = resources["to_team"]
        person = await _person_name(payload.member_id)
        source_roles = {m.user_id: m.role for m in resources["team_members"]}
        target_roles = {m.user_id: m.role for m in resources["to_team_members"]}
        source_roles.pop(payload.member_id)
        target_roles[payload.member_id] = "agent"
        # Both teams change in the confirmation's savepoint: all or nothing.
        for changed, roles in ((team, source_roles), (target, target_roles)):
            await org_teams.stage_team_members(
                db,
                organization_id,
                changed,
                TeamMembersUpdateRequest(
                    members=[
                        TeamMemberInput(user_id=user, role=role)
                        for user, role in sorted(roles.items())
                    ]
                ),
            )
        return {"team_id": target.id, "message": f"{person} moved from {name} to {target.name}"}
    roles = {member.user_id: member.role for member in resources["team_members"]}
    if kind == ActionKind.UPDATE_TEAM_MEMBERS:
        for change in payload.members:
            roles[change.member_id] = change.role
        await _save_roster(db, organization_id, team, roles)
        parts = []
        for role, plural in (("supervisor", "supervisors"), ("agent", "agents")):
            names = [await _person_name(m.member_id) for m in payload.members if m.role == role]
            if names:
                who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
                parts.append(
                    f"{who} {'is' if len(names) == 1 else 'are'} now "
                    f"{'a ' + role if len(names) == 1 else plural} of {name}"
                )
        return {"team_id": team.id, "message": "; ".join(parts)}
    person = await _person_name(payload.member_id)
    if kind == ActionKind.ADD_TEAM_AGENT:
        roles[payload.member_id] = "agent"
        message = f"{person} added to {name} as an agent"
    elif kind == ActionKind.REMOVE_TEAM_MEMBER:
        roles.pop(payload.member_id)
        message = f"{person} removed from {name}"
    else:
        if payload.replace_existing:
            roles = {user: role for user, role in roles.items() if role != "supervisor"}
        roles[payload.member_id] = "supervisor"
        message = f"{person} is now a supervisor of {name}"
    await _save_roster(db, organization_id, team, roles)
    return {"team_id": team.id, "message": message}


async def _save_roster(db, organization_id, team, roles: dict[str, str]) -> None:
    """The team's members through the CRM's own write, then read back: a change is reported
    only when the stored roster is exactly the one confirmed, else nothing is kept."""
    await org_teams.stage_team_members(
        db,
        organization_id,
        team,
        TeamMembersUpdateRequest(
            members=[
                TeamMemberInput(user_id=user, role=role) for user, role in sorted(roles.items())
            ]
        ),
    )
    stored = await repository.team_members(db, organization_id=organization_id, team_id=team.id)
    if {member.user_id: member.role for member in stored} != roles:
        raise HTTPException(409, "The team's members were not saved as confirmed; nothing changed")


async def _list_records(db, model, response_model, user_id, organization_id):
    await _authorize(db, user_id, organization_id)
    rows = await repository.records(db, model, user_id=user_id, organization_id=organization_id)
    result = []
    for row in rows:
        lead_id = getattr(row, "lead_id", None)
        if lead_id is not None and not await repository.visible_lead(
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
    if status not in {"succeeded", "partially_succeeded", "failed", "unknown", "not_connected"}:
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


async def _person_email(user_id: str) -> str | None:
    """A verified member's email from the directory, for a calendar invitation only."""
    try:
        async with asyncio.timeout(3):
            person = await get_user_by_id(user_id)
        email = (getattr(person, "email", None) or "").strip() if person else ""
    except Exception:
        email = ""
    return email or None


# An address Google Calendar can invite: one word, an @, a dotted domain.
_USABLE_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


async def meeting_invitations(db, payload, *, user_id: str, organization_id: str) -> dict:
    """Whom a meeting's invitation would reach, and whether it gets a Google Meet link.

    The CRM's only invitation channel is the user's connected Google Calendar: attendees,
    with Google sending the emails and the Meet link. Colleagues need an email on file. The
    linked lead is invited only at a usable address on a lead this user can see, and never
    when marked do not contact."""
    connection = await connectors.google_connection(
        db, user_id=user_id, organization_id=organization_id
    )
    google = connection is not None
    emails = {item: await _person_email(item) for item in payload.colleague_ids}
    invited = [item for item in payload.colleague_ids if google and emails[item]]
    lead = None
    if payload.lead_id is not None:
        visible = await repository.visible_lead(
            db, user_id=user_id, organization_id=organization_id, lead_id=payload.lead_id
        )
        contact = (
            await repository.lead_contact(
                db, organization_id=organization_id, contact_id=visible.contact_id
            )
            if visible
            else None
        )
        if contact is not None:
            email = (contact.email or "").strip()
            reason = None
            if contact.do_not_contact:
                reason = "marked do not contact"
            elif not _USABLE_EMAIL.fullmatch(email):
                reason = "no usable email on file"
            elif not google:
                reason = "Google Calendar is not connected, so no invitations can be sent"
            lead = {
                "name": contact.full_name.strip()[:200] or "The lead",
                "email": None if reason else email,
                "reason": reason,
            }
    return {
        "google": google,
        "meet": google,
        "invited": invited,
        "emails": {item: emails[item] for item in invited},
        "lead": lead,
    }


async def _invitation_lines(payload, resources) -> list[str]:
    """What the proposal says about invitations, person by person, with the address each
    invitation goes to; the linked lead is invited only as `meeting_invitations` decides."""
    plan = resources.get("invitations") or {"google": False, "invited": [], "lead": None}
    lines = []
    for item in payload.colleague_ids:
        name = await _person_name(item)
        if item in plan["invited"]:
            lines.append(
                f"Google Calendar will email an invitation to {name} at {plan['emails'][item]}"
            )
        elif not plan["google"]:
            lines.append(
                f"{name} is not invited: Google Calendar is not connected, so no invitations "
                "can be sent"
            )
        else:
            lines.append(f"{name} is not invited: no email on file")
    lead = plan.get("lead")
    if lead and lead["email"]:
        lines.append(
            f"Google Calendar will email an invitation to {lead['name']} (lead) at {lead['email']}"
        )
    elif lead:
        lines.append(f"{lead['name']} (lead) is not invited: {lead['reason']}")
    return lines


async def _person_name(user_id: str | None) -> str:
    """A verified member's display name for a preview; never an ID or email."""
    if user_id is None:
        return "Unassigned"
    try:
        async with asyncio.timeout(3):
            person = await get_user_by_id(user_id)
        name = _display_name(person.first_name, person.last_name) if person else None
    except Exception:
        name = None
    return name or "A team member (name unavailable)"


async def _member_matches(db, organization_id: str, search: str, allowed):
    """Organization members whose display name starts with `search`, among `allowed(ids)`.

    None when the member directory is unavailable. A full name typed exactly ("User 1") means
    that person, not every name it begins ("User 10", "User 1 Khan"); two people with that
    exact name stay ambiguous.
    """
    prefix = " ".join(search.split()).casefold()
    organization = await repository.organization(db, organization_id)
    # Release database locks while the existing public directory adapter fetches profiles.
    await db.commit()
    try:
        async with asyncio.timeout(10):
            members = await get_organization_members(organization, db)
    except Exception:
        await db.rollback()
        return None
    # Memberships and teams may have changed during the directory call: re-read them now.
    current_ids = await allowed(await repository.member_ids(db, organization_id=organization_id))
    matches = []
    for member in members:
        if member["id"] not in current_ids:
            continue
        name = _display_name(member.get("first_name"), member.get("last_name"))
        if name and name.casefold().startswith(prefix):
            matches.append({"id": member["id"], "display_name": name})
    exact = [item for item in matches if item["display_name"].casefold() == prefix]
    matches = exact or matches
    matches.sort(key=lambda item: (item["display_name"].casefold(), item["id"]))
    return matches


def _check_search(search):
    if not isinstance(search, str) or not 2 <= len(search.strip()) <= 80:
        raise HTTPException(422, "Enter between 2 and 80 characters of a member's name")


def _match_result(matches, none_reason):
    result = {
        "available": True,
        "matches": matches[:10],
        "clarification_required": len(matches) != 1,
        "truncated": len(matches) > 10,
    }
    if not matches:
        result["reason"] = none_reason
    return result


async def lookup_assignees(db, *, user_id: str, organization_id: str, search: str):
    """Bounded business-name lookup of the people this user may assign a lead to."""
    _check_search(search)
    await _authorize(db, user_id, organization_id)
    # Same authority as the CRM: managers assign into their teams, administrators into all.
    scope = await assignment.load_scope(db, organization_id, user_id)
    if not scope.can_assign:
        await db.commit()
        return {
            "available": False,
            "reason": "Only managers and organization administrators can assign leads",
        }

    async def assignable(member_ids):
        await _authorize(db, user_id, organization_id)
        current = await assignment.load_scope(db, organization_id, user_id)
        return member_ids & current.eligible_user_ids

    matches = await _member_matches(db, organization_id, search, assignable)
    words = search.split()
    if matches == [] and len(words) > 1 and words[-1].casefold() in _ROLE_WORDS:
        # "Track 6 agent": the person's name followed by their role, when no name has it.
        matches = await _member_matches(db, organization_id, " ".join(words[:-1]), assignable)
    if matches is None:
        await _authorize(db, user_id, organization_id)
        await db.commit()
        return {
            "available": False,
            "reason": "Organization member names are temporarily unavailable",
        }
    reason = "No one you can assign this lead to has that name"
    if not matches:
        # The CRM assigns a lead to one person, whose team it then belongs to: a team's name is
        # not an assignee. Said only of a team this user may assign into.
        wanted = " ".join(search.split())
        if any(
            team.name.casefold() == wanted.casefold()
            and (scope.organization_admin or team.id in scope.supervised_team_ids)
            for team in await org_teams.list_org_teams(db, organization_id)
        ):
            reason = (
                f"{wanted} is a team, not a person. The CRM assigns a lead to one person and "
                "the lead then belongs to their team: ask which member should handle it."
            )
        else:
            reason = await _not_an_assignee(db, scope, organization_id, wanted) or reason
    await db.commit()
    return _match_result(matches, reason)


async def _all_members(db, organization_id, search):
    """Members of the organization with this name (the directory's own matching)."""

    async def everyone(member_ids):
        return member_ids

    return await _member_matches(db, organization_id, search, everyone) or []


async def _not_an_assignee(db, scope, organization_id, wanted) -> str | None:
    """Why a name that is not an eligible assignee was given: an existing colleague outside
    the teams this user assigns into, or a lead they can see (the lead, not its new handler)."""
    if await _all_members(db, organization_id, wanted):
        teams = {team.id: team.name for team in await org_teams.list_org_teams(db, organization_id)}
        allowed = ", ".join(sorted(teams[t] for t in scope.team_members if t in teams)) or "none"
        return (
            f"{wanted} is a member of your organization, but not in a team whose leads you can "
            f"assign (you assign to members of: {allowed}). Ask the user who in those teams "
            "should handle the lead."
        )
    if await repository.visible_lead_named(db, scope, wanted):
        return (
            f"{wanted} is a lead you can see, not a colleague: a lead is given to a colleague. "
            "Ask the user who should handle it."
        )
    return None


async def _not_a_team(db, scope, organization_id, wanted) -> str | None:
    """What a name given as a team really is: a colleague, or a lead this user can see."""
    if await _all_members(db, organization_id, wanted):
        return (
            f"{wanted} is a person in your organization, not a team. To give a lead to them, "
            "look them up with find_assignment_colleagues."
        )
    if await repository.visible_lead_named(db, scope, wanted):
        return f"{wanted} is a lead you can see, not a team."
    return None


async def _not_a_member(db, scope, wanted) -> str | None:
    """A name given as a team member that is a lead this user can see."""
    if await repository.visible_lead_named(db, scope, wanted):
        return (
            f"{wanted} is a lead you can see, not a member of your organization. To give the "
            "lead to someone, look up the colleague who should handle it with "
            "find_assignment_colleagues."
        )
    return None


async def lookup_colleagues(db, *, user_id: str, organization_id: str, search: str):
    """Bounded business-name lookup of fellow organization members, to name in a meeting.

    Any member may look up colleagues by name; only IDs and display names are returned.
    """
    _check_search(search)
    await _authorize(db, user_id, organization_id)

    async def others(member_ids):
        await _authorize(db, user_id, organization_id)
        return member_ids - {user_id}

    matches = await _member_matches(db, organization_id, search, others)
    if matches is None:
        await _authorize(db, user_id, organization_id)
        await db.commit()
        return {
            "available": False,
            "reason": "Organization member names are temporarily unavailable",
        }
    await db.commit()
    return _match_result(matches, "No colleague in your organization has that name")


async def _team_scope(db, user_id, organization_id):
    await _authorize(db, user_id, organization_id)
    return await assignment.load_scope(db, organization_id, user_id)


async def has_other_supervisors(
    db, *, user_id: str, organization_id: str, team_id: str, people: set[str]
) -> bool:
    """Whether the team has a supervisor other than `people`: only then is replacing its
    supervisors, rather than adding one beside them (the CRM's default), a choice to make."""
    scope = await _team_scope(db, user_id, organization_id)
    if not scope.organization_admin:
        await db.commit()
        return True  # Not this user's to change; the proposal explains the refusal.
    members = await repository.team_members(db, organization_id=organization_id, team_id=team_id)
    await db.commit()
    return any(m.role == "supervisor" and m.user_id not in people for m in members)


async def lookup_teams(db, *, user_id: str, organization_id: str, search: str):
    """Teams of this organization by name, for the owner or an administrator to manage.

    "Dubai Marina CRM team" finds "Dubai Marina" (the CRM's own name matching); otherwise the
    name's start or any word of it. Only IDs and names are returned.
    """
    from app.crm.assistant import same_team

    _check_search(search)
    scope = await _team_scope(db, user_id, organization_id)
    wanted = " ".join(search.split())
    if not scope.organization_admin:
        hint = await _not_a_team(db, scope, organization_id, wanted)
        await db.commit()
        return {
            "available": False,
            "reason": f"{hint} {TEAM_ADMIN_ONLY}" if hint else TEAM_ADMIN_ONLY,
        }
    teams = await org_teams.list_org_teams(db, organization_id)
    await db.commit()
    exact = [team for team in teams if same_team(team.name, search)]
    folded = wanted.casefold()
    found = exact or [
        team
        for team in teams
        if team.name.casefold().startswith(folded) or folded in team.name.casefold().split()
    ]
    matches = [{"id": team.id, "name": team.name} for team in found]
    result = {
        "available": True,
        "matches": matches[:10],
        "clarification_required": len(matches) != 1,
        "truncated": len(matches) > 10,
    }
    if not matches:
        result["reason"] = (
            await _not_a_team(db, scope, organization_id, wanted)
            or "Your organization has no team with that name"
        )
        await db.commit()
    return result


async def lookup_team_people(db, *, user_id: str, organization_id: str, search: str):
    """Organization members by name, for the owner or an administrator to place in a team
    (anyone in the organization may join a team, including the user)."""
    _check_search(search)
    scope = await _team_scope(db, user_id, organization_id)
    wanted = " ".join(search.split())
    if not scope.organization_admin:
        hint = await _not_a_member(db, scope, wanted)
        await db.commit()
        return {
            "available": False,
            "reason": f"{hint} {TEAM_ADMIN_ONLY}" if hint else TEAM_ADMIN_ONLY,
        }

    async def members(member_ids):
        await _authorize(db, user_id, organization_id)
        return member_ids

    matches = await _member_matches(db, organization_id, search, members)
    if matches is None:
        await db.commit()
        return {
            "available": False,
            "reason": "Organization member names are temporarily unavailable",
        }
    reason = await _not_a_member(db, scope, wanted) if not matches else None
    await db.commit()
    return _match_result(matches, reason or "No one in your organization has that name")


async def pending_target(
    db, *, user_id: str, organization_id: str, kind: ActionKind | None, lead_id: int | None
):
    """Whether this user may still continue `kind` on this lead; nothing is written.

    `kind` None holds a chosen lead whose action is still being clarified: visibility only.
    `lead_id` None holds a request that has no lead yet: membership only.

    The same checks a proposal makes (membership, visibility, edit and reassignment rights), so
    a request held between turns never outlives the user's access to its lead.
    """
    await _authorize(db, user_id, organization_id)
    if kind == ActionKind.DELETE_LEAD:
        await db.commit()
        return {"available": False, "reason": NO_LEAD_DELETION}
    if lead_id is None:
        await db.commit()
        return {"available": True}
    scope = await assignment.load_scope(db, organization_id, user_id)
    try:
        lead = await assignment.load_visible(db, scope, lead_id)
        if kind is not None:
            _lead_rights(scope, kind, lead)
    except HTTPException as error:
        await db.commit()
        detail = error.detail
        reason = detail.get("message") if isinstance(detail, dict) else detail
        return {"available": False, "reason": str(reason)}
    await db.commit()
    return {"available": True}
