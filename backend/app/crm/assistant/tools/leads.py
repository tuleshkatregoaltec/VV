"""Lead tools for the CRM Assistant (Leads = the organisation's inbound enquiries).

Every tool reads its scope from ctx.deps. A lead in another organisation, a missing id and an
Inbox contact that is not a lead all look the same: {"error": "Lead not found"}.
"""

import logging
from collections import Counter
from datetime import date
from typing import Any, Literal, get_args

from fastapi import HTTPException
from pydantic_ai import RunContext

from app.crm import inbound_repository
from app.crm.assistant.actions import create_pending_action, utcnow
from app.crm.assistant.deps import AssistantDeps
from app.crm.assistant.scope import lead_link, load_lead, org_member, org_members
from app.crm.inbound import get_inbound_enquiry, list_inbound_enquiries
from app.crm.inbound_models import (
    CrmInboundActivity,
    InboundEnquiryResponse,
    InboundIntent,
    InboundStatus,
)
from app.crm.renewal_leads import list_renewal_leads

logger = logging.getLogger(__name__)

NOT_FOUND = {"error": "Lead not found"}
MEMBER_NOT_FOUND = {"error": "Member not found"}
DO_NOT_CONTACT = {"error": "This lead has asked not to be contacted"}
STATUSES = set(get_args(InboundStatus))
INTENT_LABELS = {
    "buy": "buying",
    "rent": "renting",
    "sell": "selling",
    "let": "letting",
    "unknown": "property",
}
MAX_RESULTS = 50
# list_inbound_enquiries filters in memory after loading the org's rows; fetch them all, then
# apply the assistant's own filters before the result limit.
_FETCH_ALL = 1000


def _log(tool: str, deps: AssistantDeps) -> None:
    logger.info("assistant tool=%s org=%s", tool, deps.organization_id)


def _money(value: Any) -> str:
    amount = int(value)
    return f"AED {amount / 1_000_000:g}M" if amount >= 1_000_000 else f"AED {amount:,}"


def criteria_summary(criteria: dict[str, Any]) -> str:
    parts = []
    if locations := criteria.get("locations"):
        parts.append(", ".join(locations))
    if criteria.get("bedrooms_min") is not None:
        bedrooms = criteria["bedrooms_min"]
        parts.append("Studio" if bedrooms == 0 else f"{bedrooms}+ bed")
    if property_type := criteria.get("property_type"):
        parts.append(str(property_type))
    low, high = criteria.get("budget_min_aed"), criteria.get("budget_max_aed")
    if low and high:
        parts.append(f"{_money(low)}–{_money(high)}")
    elif high:
        parts.append(f"up to {_money(high)}")
    elif low:
        parts.append(f"from {_money(low)}")
    return " · ".join(parts) or "No preferences yet"


def lead_name(lead: InboundEnquiryResponse) -> str:
    """As the Leads page names it: an owner nobody has identified yet goes by the unit."""
    if lead.contact.full_name:
        return lead.contact.full_name
    unit = " · ".join(
        part
        for part in (
            str(lead.criteria.get("building") or "").strip(),
            f"unit {lead.criteria['unit_number']}" if lead.criteria.get("unit_number") else "",
        )
        if part
    )
    return unit or "Owner not identified"


def lead_card(lead: InboundEnquiryResponse) -> dict[str, Any]:
    last_activity = max(
        (item.created_at for item in lead.activities),
        default=lead.last_contact_at or lead.updated_at,
    )
    return {
        "id": lead.id,
        "name": lead_name(lead),
        "status": lead.status,
        "intent": lead.intent,
        "criteria_summary": criteria_summary(lead.criteria),
        "assignee_user_id": lead.assigned_user_id,
        "next_follow_up": lead.next_follow_up.isoformat() if lead.next_follow_up else None,
        "last_activity": last_activity.isoformat() if last_activity else None,
        "link": lead_link(lead.id),
    }


def _lead_data(lead: InboundEnquiryResponse) -> str:
    """Text written by people outside the company, fenced so the model treats it as data."""
    lines = []
    if lead.raw_notes:
        lines.append(f"Enquiry notes: {lead.raw_notes}")
    for note in lead.notes[-5:]:
        lines.append(f"Note ({note.created_at.date().isoformat()}): {note.body}")
    return "<lead_data>\n" + ("\n".join(lines) or "(none)") + "\n</lead_data>"


async def _org_leads(deps: AssistantDeps, **filters: Any) -> list[InboundEnquiryResponse]:
    result = await list_inbound_enquiries(
        deps.db,
        organization_id=deps.organization_id,
        intent_group=None,
        workspace=None,
        status=filters.get("status"),
        search=filters.get("search"),
        limit=_FETCH_ALL,
        offset=0,
        within_days=filters.get("within_days"),
        leads_only=True,
    )
    return result.enquiries


# The Leads page also lists the agent's Vitevue lease leads (units whose lease is ending in the
# agent's areas). Most are not opened yet, so they have no lead id; they are read-only here.
_LEASE_FETCH = 500


def _lease_name(item: Any) -> str:
    lead = item.lead
    place = lead.building_name or lead.project_name or lead.area_name or "Unit"
    unit = f"{place} · unit {lead.unit_number}" if lead.unit_number else place
    return (item.owner.name if item.owner and item.owner.name else None) or unit


def _lease_card(item: Any) -> dict[str, Any]:
    lead = item.lead
    days = lead.days_to_expiry
    ended = f"lease ended {-days} days ago" if days < 0 else f"lease ends in {days} days"
    details = [lead.property_subtype or lead.property_type, lead.bedrooms, lead.area_name]
    return {
        "id": None,
        "lease_id": lead.lead_id,
        "kind": "vitevue_lease",
        "name": _lease_name(item),
        "status": "new",
        "intent": "sell or let",
        "criteria_summary": " · ".join(
            [
                *(d for d in details if d and d != "Not stated"),
                ended,
                f"AED {lead.annual_rent_aed:,} a year",
            ]
        ),
        "assignee_user_id": None,
        "next_follow_up": None,
        "note": "Vitevue lease lead, not opened yet: open it on the Leads page to change it.",
        "link": "/crm/leads",
    }


async def _unopened_lease_leads(deps: AssistantDeps) -> list[Any] | None:
    """The agent's lease leads that are not stored leads yet; None when the data is unavailable."""
    try:
        result = await list_renewal_leads(
            deps.db,
            user_id=deps.user_id,
            organization_id=deps.organization_id,
            limit=_LEASE_FETCH,
            offset=0,
        )
    except Exception as error:
        logger.warning(
            "assistant lease leads unavailable org=%s error=%s",
            deps.organization_id,
            type(error).__name__,
        )
        return None
    return [item for item in result.items if not item.lead_record_id]


async def search_leads(
    ctx: RunContext[AssistantDeps],
    query: str | None = None,
    status: InboundStatus | None = None,
    intent: InboundIntent | None = None,
    assigned_to_me: bool = False,
    follow_up_due: bool = False,
    within_days: int | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Find this organisation's leads.

    Args:
        query: Name, phone, email or text to search for.
        status: Only leads at this stage.
        intent: Only leads that want to buy, rent, sell or let.
        assigned_to_me: Only leads assigned to the signed-in agent.
        follow_up_due: Only leads whose follow-up date is today or earlier.
        within_days: Only leads that arrived within this many days.
        limit: Maximum leads to return (at most 50).
    """
    deps = ctx.deps
    _log("search_leads", deps)
    leads = await _org_leads(deps, status=status, search=query, within_days=within_days)
    today = date.today()
    if intent:
        leads = [lead for lead in leads if lead.intent == intent]
    if assigned_to_me:
        leads = [lead for lead in leads if lead.assigned_user_id == deps.user_id]
    if follow_up_due:
        leads = [lead for lead in leads if lead.next_follow_up and lead.next_follow_up <= today]
    cards = [lead_card(lead) for lead in leads]

    lease_items = await _unopened_lease_leads(deps)
    # Lease leads are new, unassigned, owner-side (sell or let) and have no follow-up yet.
    lease_fits = (
        status in (None, "new")
        and intent in (None, "sell", "let")
        and not assigned_to_me
        and not follow_up_due
    )
    if lease_items and lease_fits:
        needle = (query or "").strip().lower()
        for item in lease_items:
            card = _lease_card(item)
            haystack = f"{card['name']} {card['criteria_summary']} {item.lead.building_name}"
            if not needle or needle in haystack.lower():
                cards.append(card)

    limit = max(1, min(limit, MAX_RESULTS))
    result: dict[str, Any] = {"leads": cards[:limit], "total": len(cards)}
    if lease_items is None:
        result["lease_leads_unavailable"] = True
    return result


async def get_lead(ctx: RunContext[AssistantDeps], lead_id: int) -> dict[str, Any]:
    """Get one lead's details, recent activity and notes.

    Args:
        lead_id: The lead's id.
    """
    deps = ctx.deps
    _log("get_lead", deps)
    try:
        await load_lead(deps.db, deps.organization_id, lead_id)
        lead = await get_inbound_enquiry(deps.db, lead_id, deps.organization_id)
    except HTTPException as error:
        if error.status_code == 404:
            return NOT_FOUND
        raise
    contact = lead.contact
    return {
        **lead_card(lead),
        "lost_reason": lead.lost_reason,
        "source": lead.source,
        "contact": {
            "has_phone": bool(contact.phone or contact.whatsapp),
            "has_email": bool(contact.email),
            "do_not_contact": contact.do_not_contact,
            "consent_status": contact.consent_status,
        },
        "recent_activities": [
            {"type": item.activity_type, "date": item.created_at.date().isoformat()}
            for item in lead.activities[-5:]
        ],
        "lead_data": _lead_data(lead),
    }


async def lead_pipeline_summary(ctx: RunContext[AssistantDeps]) -> dict[str, Any]:
    """Count this organisation's leads by stage, type and assignee, and overdue follow-ups."""
    deps = ctx.deps
    _log("lead_pipeline_summary", deps)
    leads = await _org_leads(deps)
    lease_items = await _unopened_lease_leads(deps)
    unopened = len(lease_items or [])
    today = date.today()
    by_status = Counter(lead.status for lead in leads)
    by_intent = Counter(lead.intent for lead in leads)
    by_assignee = Counter(lead.assigned_user_id or "unassigned" for lead in leads)
    if unopened:
        by_status["new"] += unopened
        by_intent["sell or let (Vitevue lease leads)"] += unopened
        by_assignee["unassigned"] += unopened
    summary: dict[str, Any] = {
        "total": len(leads) + unopened,
        "by_status": dict(by_status),
        "by_intent": dict(by_intent),
        "by_assignee": dict(by_assignee),
        "lease_leads_not_opened": unopened,
        "overdue_follow_ups": sum(
            1 for lead in leads if lead.next_follow_up and lead.next_follow_up < today
        ),
    }
    if lease_items is None:
        summary["lease_leads_unavailable"] = True
    return summary


async def list_org_members(ctx: RunContext[AssistantDeps]) -> dict[str, Any]:
    """List the people in this organisation, to resolve names like "assign to Sara"."""
    _log("list_org_members", ctx.deps)
    return {"members": await org_members(ctx.deps)}


# Write tools: each one only proposes. The change runs when the user confirms it (actions.py).


async def _lead_for_change(deps: AssistantDeps, lead_id: int) -> InboundEnquiryResponse | None:
    try:
        await load_lead(deps.db, deps.organization_id, lead_id)
        return await get_inbound_enquiry(deps.db, lead_id, deps.organization_id)
    except HTTPException as error:
        if error.status_code == 404:
            return None
        raise


async def _assignee_name(deps: AssistantDeps, user_id: str | None) -> str:
    if not user_id:
        return "Unassigned"
    member = next((m for m in await org_members(deps) if m["user_id"] == user_id), None)
    return member["name"] if member else "Former member"


async def propose_status_change(
    ctx: RunContext[AssistantDeps],
    lead_id: int,
    new_status: InboundStatus,
    lost_reason: str | None = None,
) -> dict[str, Any]:
    """Propose moving a lead to another stage. The user must confirm it.

    Args:
        lead_id: The lead's id.
        new_status: The stage to move the lead to.
        lost_reason: Why the lead was lost; required for closed_lost.
    """
    deps = ctx.deps
    _log("propose_status_change", deps)
    if new_status not in STATUSES:
        return {"error": f"Unknown status. Use one of: {', '.join(sorted(STATUSES))}"}
    lead = await _lead_for_change(deps, lead_id)
    if lead is None:
        return NOT_FOUND
    reason = (lost_reason or "").strip()
    if new_status == "closed_lost" and not reason:
        return {"error": "A lost reason is required to close a lead as lost"}
    if lead.status == new_status:
        return {"error": f"Lead is already {new_status}"}
    payload: dict[str, Any] = {"status": new_status}
    if new_status == "closed_lost":
        payload["lost_reason"] = reason
    return await create_pending_action(
        deps,
        enquiry_id=lead_id,
        action_type="status",
        payload=payload,
        summary=f"Move {lead_name(lead)} to {new_status}",
        before={"status": lead.status},
        after=dict(payload),
    )


async def propose_add_note(
    ctx: RunContext[AssistantDeps], lead_id: int, body: str
) -> dict[str, Any]:
    """Propose adding a note to a lead. The user must confirm it.

    Args:
        lead_id: The lead's id.
        body: The note text.
    """
    deps = ctx.deps
    _log("propose_add_note", deps)
    text = body.strip()
    if not text:
        return {"error": "A note needs some text"}
    if len(text) > 4_000:
        return {"error": "A note can be at most 4000 characters"}
    lead = await _lead_for_change(deps, lead_id)
    if lead is None:
        return NOT_FOUND
    return await create_pending_action(
        deps,
        enquiry_id=lead_id,
        action_type="note",
        payload={"body": text},
        summary=f"Add a note to {lead_name(lead)}",
        before={},
        after={"note": text},
    )


async def propose_follow_up(
    ctx: RunContext[AssistantDeps], lead_id: int, date: date
) -> dict[str, Any]:
    """Propose setting a lead's next follow-up date. The user must confirm it.

    Args:
        lead_id: The lead's id.
        date: The follow-up date (YYYY-MM-DD).
    """
    deps = ctx.deps
    _log("propose_follow_up", deps)
    lead = await _lead_for_change(deps, lead_id)
    if lead is None:
        return NOT_FOUND
    current = lead.next_follow_up.isoformat() if lead.next_follow_up else None
    return await create_pending_action(
        deps,
        enquiry_id=lead_id,
        action_type="follow_up",
        payload={"next_follow_up": date.isoformat()},
        summary=f"Set a follow-up for {lead_name(lead)} on {date.isoformat()}",
        before={"next_follow_up": current},
        after={"next_follow_up": date.isoformat()},
    )


async def propose_assign(
    ctx: RunContext[AssistantDeps], lead_id: int, member_user_id: str
) -> dict[str, Any]:
    """Propose assigning a lead to someone in this organisation. The user must confirm it.

    Args:
        lead_id: The lead's id.
        member_user_id: The user_id of the organisation member (from list_org_members).
    """
    deps = ctx.deps
    _log("propose_assign", deps)
    lead = await _lead_for_change(deps, lead_id)
    if lead is None:
        return NOT_FOUND
    member = await org_member(deps, member_user_id)
    if member is None:
        return MEMBER_NOT_FOUND
    return await create_pending_action(
        deps,
        enquiry_id=lead_id,
        action_type="assign",
        payload={"assigned_user_id": member_user_id},
        summary=f"Assign {lead_name(lead)} to {member['name']}",
        before={"assignee": await _assignee_name(deps, lead.assigned_user_id)},
        after={"assignee": member["name"]},
    )


def share_text(lead: InboundEnquiryResponse) -> str:
    """Plain-text lead summary for a colleague (internal; holds no contact values)."""
    lines = [
        f"Lead: {lead_name(lead)}",
        f"Looking to: {lead.intent}",
        f"Stage: {lead.status}",
        f"Wants: {criteria_summary(lead.criteria)}",
    ]
    if lead.next_follow_up:
        lines.append(f"Next follow-up: {lead.next_follow_up.isoformat()}")
    lines.append(f"Open in CRM: {lead_link(lead.id)}")
    return "\n".join(lines)


def _draft_to_lead(lead: InboundEnquiryResponse) -> str:
    first_name = lead.contact.full_name.split()[0] if lead.contact.full_name else "there"
    looking_for = criteria_summary(lead.criteria)
    wants = "" if looking_for == "No preferences yet" else f" ({looking_for})"
    return (
        f"Hi {first_name}, following up on your {INTENT_LABELS.get(lead.intent, 'property')} "
        f"enquiry{wants}. When is a good time to talk?"
    )


async def propose_share(
    ctx: RunContext[AssistantDeps],
    lead_id: int,
    channel: Literal["copy", "teammate", "whatsapp", "email"],
    recipient: str | None = None,
) -> dict[str, Any]:
    """Share a lead. copy returns a text summary now; teammate shares it with an organisation
    member; whatsapp and email prepare a draft message to the lead that the user sends.

    Args:
        lead_id: The lead's id.
        channel: copy, teammate, whatsapp or email.
        recipient: For teammate, the member's user_id. For whatsapp or email, an optional
            number or address instead of the lead's own.
    """
    deps = ctx.deps
    _log("propose_share", deps)
    lead = await _lead_for_change(deps, lead_id)
    if lead is None:
        return NOT_FOUND
    name = lead_name(lead)

    if channel == "copy":
        inbound_repository.save(
            deps.db,
            CrmInboundActivity(
                enquiry_id=lead_id,
                organization_id=deps.organization_id,
                user_id=deps.user_id,
                activity_type="shared",
                body="Lead summary copied via Assistant",
                metadata_json={"channel": "copy"},
                created_at=utcnow(),
            ),
        )
        await deps.db.commit()
        return {
            "share": {
                "channel": "copy",
                "lead_id": lead_id,
                "summary": f"Summary of {name}",
                "text": share_text(lead),
            }
        }

    if channel == "teammate":
        member = await org_member(deps, recipient or "")
        if member is None:
            return MEMBER_NOT_FOUND
        return await create_pending_action(
            deps,
            enquiry_id=lead_id,
            action_type="share",
            payload={"channel": "teammate", "member_user_id": member["user_id"]},
            summary=f"Share {name} with {member['name']}",
            before={},
            after={"shared_with": member["name"]},
        )

    contact = lead.contact
    if contact.do_not_contact or contact.consent_status == "withdrawn":
        return DO_NOT_CONTACT
    if channel == "whatsapp":
        to = recipient or contact.whatsapp or contact.phone
    else:
        to = recipient or contact.email
    if not to:
        return {"error": f"This lead has no {'phone number' if channel == 'whatsapp' else 'email'}"}
    return await create_pending_action(
        deps,
        enquiry_id=lead_id,
        action_type="share",
        payload={"channel": channel, "to": to, "text": _draft_to_lead(lead)},
        summary=f"Draft a {'WhatsApp message' if channel == 'whatsapp' else 'email'} to {name}",
        before={},
        after={"to": to, "draft": _draft_to_lead(lead)},
    )
