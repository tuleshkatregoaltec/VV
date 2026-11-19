"""Whose calendar events the signed-in person may read, and what a colleague's event reveals.

Owners and organization administrators read every member's events; a manager reads their own
and their supervised teams' members'; anyone else reads only their own. The set is derived from
`assignment.load_scope` on every request, never from the client. Writes stay owner-only
(`router._own_event`).
"""

import asyncio
from datetime import date

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth.service import get_user_by_id
from app.crm import assignment, calendar_service
from app.crm.assignment import AssignmentScope
from app.crm.calendar_models import CrmCalendarEvent
from app.crm.calendar_service import serialize_event
from app.organization import repository as org_repository
from app.organization import teams as org_teams

FORMER_MEMBER = "Former member"
# Identity-provider lookups run at most this many at a time.
NAME_LOOKUPS = 10
KIND_TITLES = {
    "viewing": "Viewing",
    "call": "Call",
    "follow_up": "Follow-up",
    "deal_date": "Deal date",
    "deadline": "Deadline",
}

REDACTED_VISIBILITY = {"private", "confidential"}
BUSY_TITLE = "Busy"
# A colleague's private event: only when it is and whether it blocks time leave the server.
# `kind` is a placeholder the response type requires; the client keys off `redacted`.
BUSY_BLOCK = {
    "title": BUSY_TITLE,
    "detail": "",
    "location": "",
    "guests": [],
    "guests_can_modify": False,
    "guests_can_invite_others": True,
    "guests_can_see_other_guests": True,
    "meet": False,
    "meet_link": None,
    "reminders": [],
    "reminders_use_default": False,
    "kind": "follow_up",
    "lead_id": None,
    "listing_id": None,
    "record": None,
    "context": None,
    "outcome": None,
    "rescheduled_from": [],
    "redacted": True,
}


def serialize_for_viewer(
    event: CrmCalendarEvent,
    *,
    viewer_id: str,
    owner_name: str,
    lead_visible: bool,
    owner_role: str | None = None,
) -> dict:
    """The owner's full event, or a colleague's read-only view of it."""
    data = serialize_event(event)
    data["owner_role"] = owner_role
    if viewer_id == event.user_id:
        return data
    data.update(agent=owner_name, can_edit=False)
    if event.visibility in REDACTED_VISIBILITY:
        data.update(BUSY_BLOCK)
    elif event.lead_id is not None and not lead_visible:
        # The viewer may read this colleague's calendar but not that lead: a viewing's title
        # ("Viewing · <client>"), note, listing, place and guests all name the client.
        data.update(
            title=KIND_TITLES.get(event.kind, BUSY_TITLE),
            detail="",
            listing_id=None,
            location="",
            guests=[],
            lead_id=None,
            record=None,
            context=None,
        )
    return data


async def readable_user_ids(db: AsyncSession, scope: AssignmentScope) -> frozenset[str]:
    if scope.organization_admin:
        # Every member, including people in no team: team_members only covers teams.
        members = await org_repository.list_memberships(db, scope.organization_id)
        return frozenset({scope.user_id, *(m.user_id for m in members)})
    supervised = (scope.team_members.get(team, frozenset()) for team in scope.supervised_team_ids)
    return frozenset({scope.user_id}).union(*supervised)


async def owner_names(db: AsyncSession, organization_id: str, user_ids: set[str]) -> dict[str, str]:
    """Display names for these event owners only, looked up concurrently.

    A missing user or a failed lookup shows "Former member" rather than failing the calendar.
    """
    gate = asyncio.Semaphore(NAME_LOOKUPS)

    async def name(user_id: str) -> str:
        try:
            async with gate:
                user = await get_user_by_id(user_id)
        except Exception:
            return FORMER_MEMBER
        if user is None:
            return FORMER_MEMBER
        return (
            f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email or FORMER_MEMBER
        )

    ids = sorted(user_ids)
    return dict(zip(ids, await asyncio.gather(*(name(uid) for uid in ids)), strict=True))


async def owner_roles(db: AsyncSession, organization_id: str, user_ids: set[str]) -> dict[str, str]:
    """Each owner's role label: Owner, Admin, Manager (supervises a team) or Agent."""
    if not user_ids:
        return {}
    members = {m.user_id: m for m in await org_repository.list_memberships(db, organization_id)}
    supervisors = {
        row.user_id
        for row in await org_teams.list_team_memberships(db, organization_id)
        if row.role == "supervisor"
    }

    def role(user_id: str) -> str:
        member = members.get(user_id)
        if member is None:
            return FORMER_MEMBER
        if member.role == "owner":
            return "Owner"
        if member.organization_admin:
            return "Admin"
        return "Manager" if user_id in supervisors else "Agent"

    return {user_id: role(user_id) for user_id in user_ids}


async def _present(db: AsyncSession, scope: AssignmentScope, rows: list[CrmCalendarEvent]):
    """A serializer for these rows as this viewer may see them."""
    others = [row for row in rows if row.user_id != scope.user_id]
    leads = {row.lead_id for row in others if row.lead_id is not None}
    visible = await assignment.visible_ids(db, scope, leads) if leads else set()
    names = await owner_names(db, scope.organization_id, {row.user_id for row in others})
    # Roles only matter when colleagues' events are on screen ("You" vs "Agent Demo · Agent").
    roles = (
        await owner_roles(db, scope.organization_id, {row.user_id for row in rows})
        if others
        else {}
    )

    def serialize(row: CrmCalendarEvent) -> dict:
        return serialize_for_viewer(
            row,
            viewer_id=scope.user_id,
            owner_name=names.get(row.user_id, FORMER_MEMBER),
            lead_visible=row.lead_id in visible,
            owner_role=roles.get(row.user_id),
        )

    return serialize


async def list_for_viewer(
    db: AsyncSession, scope: AssignmentScope, start: date, end: date
) -> list[dict]:
    rows = await calendar_service.stored_events(
        db,
        organization_id=scope.organization_id,
        user_ids=await readable_user_ids(db, scope),
        start=start,
        end=end,
    )
    return calendar_service.expand_occurrences(rows, start, end, await _present(db, scope, rows))


async def get_for_viewer(db: AsyncSession, scope: AssignmentScope, event_id: int) -> dict | None:
    """The event when its owner is in this viewer's readable set; otherwise None (a 404)."""
    readable = await readable_user_ids(db, scope)
    row = (
        await db.exec(
            select(CrmCalendarEvent).where(
                CrmCalendarEvent.id == event_id,
                CrmCalendarEvent.organization_id == scope.organization_id,
                col(CrmCalendarEvent.user_id).in_(sorted(readable)),
            )
        )
    ).first()
    if row is None:
        return None
    return (await _present(db, scope, [row]))(row)
