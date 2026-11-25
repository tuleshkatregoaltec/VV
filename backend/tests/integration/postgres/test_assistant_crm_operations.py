"""Second-pass CRM operations through the assistant, with the CRM's own rules.

- Moving an agent between teams: organization owners and administrators only (the CRM's Teams
  page), one confirmed change that rewrites both teams' memberships through the CRM's team
  writes, all or nothing.
- Rescheduling and deleting ("cancelling") one's own calendar events, as CRM › Calendar does:
  the same move rule (keeps the length, records the old slot) and the same delete, which removes
  the Google copy first. The calendar commits and syncs itself, so these run after confirmation
  and report the calendar's real outcome; a failure is never reported as done.
- Existing lead operations stay correct after they succeed (a completed unassignment is shown as
  completed, not as unavailable) and lead lookup accepts a partial name.

Agency (crm_role_support): Nadia manages North (Track 8, User 10); Karim manages South (User 2).
Google is never called: its client is stubbed. Models are scripted where a chat turn runs.
"""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from crm_role_support import lead
from fastapi import HTTPException
from sqlalchemy import update
from test_assistant_lead_contact_turns import (
    Chat,
    call,
    delegate,
    last_return,
    say,
    script,
    setup_office,
)
from test_assistant_team_management import confirm, propose, roster

from app.assistant_actions import service as actions
from app.assistant_actions.models import ActionKind
from app.crm import calendar_service
from app.crm.calendar_models import CrmCalendarConnection, CrmCalendarEvent
from app.crm.inbound_models import CrmInboundEnquiry
from app.organization.models import (
    Organization,
    OrganizationMembership,
    OrganizationTeam,
    OrganizationTeamMember,
)


@pytest.fixture
async def office(pg_session, monkeypatch):
    office = await setup_office(pg_session, monkeypatch)
    # No Google Calendar unless a test connects one.
    monkeypatch.setattr(calendar_service, "configured", lambda: False)
    rival_org, stranger = str(uuid4()), f"stranger-{uuid4().hex[:6]}"
    pg_session.add(Organization(id=rival_org, name="Rival", subscription_status="active"))
    await pg_session.flush()
    pg_session.add(
        OrganizationMembership(organization_id=rival_org, user_id=stranger, role="owner")
    )
    rival_team = OrganizationTeam(organization_id=rival_org, name="North")
    pg_session.add(rival_team)
    await pg_session.commit()
    office.ids.update(rival_org=rival_org, stranger=stranger, rival_team=rival_team.id)
    return office


def move(ids, person="omar", source="north", target="south"):
    return {"member_id": ids[person], "from_team_id": ids[source], "to_team_id": ids[target]}


async def event(db, ids, person, **fields):
    row = CrmCalendarEvent(
        organization_id=fields.pop("org", ids["org"]),
        user_id=ids[person],
        title=fields.pop("title", "Viewing at Marina Gate"),
        event_date=fields.pop("event_date", date(2026, 12, 1)),
        event_time=fields.pop("event_time", "10:00"),
        event_end_date=fields.pop("event_end_date", date(2026, 12, 1)),
        event_end_time=fields.pop("event_end_time", "11:30"),
        updated_at=datetime.now(UTC),
        **fields,
    )
    db.add(row)
    await db.commit()
    return row.id


async def stored(db, event_id):
    db.expire_all()
    return await db.get(CrmCalendarEvent, event_id)


# --- Moving an agent between teams -----------------------------------------------------------


async def test_owner_moves_an_agent_only_after_confirmation(pg_session, office):
    ids = office.ids
    held = await lead(pg_session, ids, "Agent's Lead", team="north", assignee="omar")
    action = await propose(pg_session, ids, "owner", ActionKind.MOVE_TEAM_AGENT, move(ids))
    assert action.status == "awaiting_confirmation"
    assert action.preview["person"] == "Track 8"
    assert (action.preview["from_team"], action.preview["to_team"]) == ("North", "South")
    assert "changes" not in action.preview  # Names, never raw IDs.
    assert (ids["omar"], "agent") in await roster(pg_session, ids["north"])  # Not yet.

    done = await confirm(pg_session, ids, "owner", action.id)
    assert (done.status, done.result["message"]) == (
        "succeeded",
        "Track 8 moved from North to South",
    )
    assert ids["omar"] not in {person for person, _ in await roster(pg_session, ids["north"])}
    assert (ids["omar"], "agent") in await roster(pg_session, ids["south"])
    # Their lead stays theirs, with the team that owns it, as the CRM's Teams page leaves it.
    pg_session.expire_all()
    row = await pg_session.get(CrmInboundEnquiry, held.id)
    assert (row.assigned_user_id, row.team_id) == (ids["omar"], ids["north"])


@pytest.mark.parametrize("person", ["nadia", "omar"])
async def test_managers_and_agents_cannot_move_agents(pg_session, office, person):
    ids = office.ids
    with pytest.raises(HTTPException) as refused:
        await propose(pg_session, ids, person, ActionKind.MOVE_TEAM_AGENT, move(ids))
    assert (refused.value.status_code, refused.value.detail) == (403, actions.TEAM_ADMIN_ONLY)


@pytest.mark.parametrize(
    ("payload", "status", "detail"),
    [
        (lambda ids: move(ids, person="nadia"), 409, "This person manages North"),
        (lambda ids: move(ids, person="lina"), 409, "This person is not in North"),
        (lambda ids: {**move(ids), "to_team_id": ids["rival_team"]}, 404, "Team not found"),
        (lambda ids: {**move(ids), "member_id": ids["stranger"]}, 409, "not a member"),
    ],
)
async def test_a_move_the_crm_would_not_make_is_refused_before_proposal(
    pg_session, office, payload, status, detail
):
    ids = office.ids
    with pytest.raises(HTTPException) as refused:
        await propose(pg_session, ids, "owner", ActionKind.MOVE_TEAM_AGENT, payload(ids))
    assert refused.value.status_code == status and detail in refused.value.detail
    assert await roster(pg_session, ids["rival_team"]) == set()


async def test_an_agent_already_in_the_target_team_is_refused(pg_session, office):
    ids = office.ids
    pg_session.add(
        OrganizationTeamMember(
            team_id=ids["south"], organization_id=ids["org"], user_id=ids["omar"], role="agent"
        )
    )
    await pg_session.commit()
    with pytest.raises(HTTPException) as refused:
        await propose(pg_session, ids, "owner", ActionKind.MOVE_TEAM_AGENT, move(ids))
    assert refused.value.detail == "This person is already in South"


async def test_confirmation_rechecks_membership_and_permission(pg_session, office):
    ids = office.ids
    # The agent leaves North in the CRM before the confirmation: nothing is changed.
    action = await propose(pg_session, ids, "owner", ActionKind.MOVE_TEAM_AGENT, move(ids))
    await pg_session.exec(
        OrganizationTeamMember.__table__.delete().where(
            OrganizationTeamMember.user_id == ids["omar"]
        )
    )
    await pg_session.commit()
    done = await confirm(pg_session, ids, "owner", action.id)
    assert done.status == "failed"
    assert ids["omar"] not in {person for person, _ in await roster(pg_session, ids["south"])}

    # An administrator demoted before confirming: refused, nothing changed.
    admin = update(OrganizationMembership).where(OrganizationMembership.user_id == ids["karim"])
    await pg_session.exec(admin.values(organization_admin=True))
    await pg_session.commit()
    action = await propose(
        pg_session, ids, "karim", ActionKind.MOVE_TEAM_AGENT, move(ids, person="sara")
    )
    await pg_session.exec(admin.values(organization_admin=False))
    await pg_session.commit()
    done = await confirm(pg_session, ids, "karim", action.id)
    assert done.status == "failed"
    assert (ids["sara"], "agent") in await roster(pg_session, ids["north"])
    assert ids["sara"] not in {person for person, _ in await roster(pg_session, ids["south"])}


async def test_a_move_in_chat_needs_both_teams_and_the_agent_looked_up(pg_session, office):
    ids = office.ids
    chat = await Chat(pg_session, office, "owner").start()
    told: list = []

    def guessed(messages):
        told.append(last_return(messages))
        return say("Which teams do you mean?")

    proposal = call("propose_crm_action", kind="move_team_agent", payload=move(ids))
    await chat.turn(
        "Move Track 8 from North to South",
        coordinator=delegate("prepare_action", "Move Track 8 from North to South"),
        action=script(proposal, guessed),
    )
    assert told[0]["available"] is False and told[0]["clarification_required"] is True

    shown = await chat.turn(
        "Move Track 8 from North to South",
        coordinator=delegate("prepare_action", "Move Track 8 from North to South"),
        action=script(
            call("find_teams", search="North"),
            call("find_teams", search="South"),
            call("find_team_people", search="Track 8"),
            proposal,
            say("I've moved Track 8 to South."),
        ),
    )
    assert "awaiting your confirmation" in shown and "I've moved" not in shown
    assert (ids["omar"], "agent") in await roster(pg_session, ids["north"])


# --- Rescheduling and cancelling calendar events ---------------------------------------------


async def test_reschedule_keeps_the_length_records_the_old_slot_and_waits_for_confirmation(
    pg_session, office
):
    ids = office.ids
    event_id = await event(pg_session, ids, "omar")
    payload = {"event_id": event_id, "date": "2026-12-03", "time": "15:00"}
    action = await propose(pg_session, ids, "omar", ActionKind.RESCHEDULE_CALENDAR_EVENT, payload)
    assert action.preview["event"] == "Viewing at Marina Gate"
    assert action.preview["currently"] == "1 Dec 2026 10:00–11:30 Dubai time"
    assert action.preview["new_time"] == "3 Dec 2026 15:00 Dubai time"
    assert "Google Calendar is not connected" in action.preview["delivery"]
    assert (await stored(pg_session, event_id)).event_date == date(2026, 12, 1)  # Not yet.

    done = await confirm(pg_session, ids, "omar", action.id)
    assert done.status == "succeeded"
    assert done.result["message"].startswith("Moved Viewing at Marina Gate to 3 Dec 2026 15:00")
    row = await stored(pg_session, event_id)
    assert (row.event_date, row.event_time, row.event_end_time) == (
        date(2026, 12, 3),
        "15:00",
        "16:30",  # The 90-minute length is kept.
    )
    assert row.rescheduled_from == [{"date": "2026-12-01", "time": "10:00"}]
    # Completed stays visible as completed afterwards.
    shown = await actions.get_action(
        pg_session, user_id=ids["omar"], organization_id=ids["org"], action_id=action.id
    )
    assert shown.status == "succeeded" and shown.preview.get("available") is not False


async def test_cancel_deletes_the_event_as_the_crm_does(pg_session, office):
    ids = office.ids
    event_id = await event(pg_session, ids, "omar")
    action = await propose(
        pg_session, ids, "omar", ActionKind.CANCEL_CALENDAR_EVENT, {"event_id": event_id}
    )
    assert "cannot be undone" in action.preview["consequence"]
    assert await stored(pg_session, event_id) is not None
    done = await confirm(pg_session, ids, "omar", action.id)
    assert (done.status, done.result["message"]) == (
        "succeeded",
        "Deleted Viewing at Marina Gate from your calendar",
    )
    assert await stored(pg_session, event_id) is None


@pytest.mark.parametrize(
    ("owner", "actor"),
    [("nadia", "omar"), ("omar", "nadia"), ("stranger", "omar")],  # Not their own event.
)
async def test_only_ones_own_events_can_be_changed(pg_session, office, owner, actor):
    ids = office.ids
    org = ids["rival_org"] if owner == "stranger" else ids["org"]
    event_id = await event(pg_session, ids, owner, org=org)
    for kind, payload in (
        (ActionKind.RESCHEDULE_CALENDAR_EVENT, {"event_id": event_id, "date": "2026-12-05"}),
        (ActionKind.CANCEL_CALENDAR_EVENT, {"event_id": event_id}),
    ):
        with pytest.raises(HTTPException) as refused:
            await propose(pg_session, ids, actor, kind, payload)
        assert (refused.value.status_code, refused.value.detail) == (
            404,
            "Calendar event not found",
        )
    assert await stored(pg_session, event_id) is not None


async def test_moving_to_the_same_time_is_refused(pg_session, office):
    ids = office.ids
    event_id = await event(pg_session, ids, "omar")
    with pytest.raises(HTTPException) as refused:
        await propose(
            pg_session,
            ids,
            "omar",
            ActionKind.RESCHEDULE_CALENDAR_EVENT,
            {"event_id": event_id, "date": "2026-12-01", "time": "10:00"},
        )
    assert refused.value.status_code == 409


async def test_confirmation_rechecks_the_event_as_it_was_previewed(pg_session, office):
    ids = office.ids
    event_id = await event(pg_session, ids, "omar")
    action = await propose(
        pg_session,
        ids,
        "omar",
        ActionKind.RESCHEDULE_CALENDAR_EVENT,
        {"event_id": event_id, "date": "2026-12-03", "time": "15:00"},
    )
    # The user moves the event themselves in CRM › Calendar before confirming.
    await pg_session.exec(
        update(CrmCalendarEvent).where(CrmCalendarEvent.id == event_id).values(event_time="12:00")
    )
    await pg_session.commit()
    done = await confirm(pg_session, ids, "omar", action.id)
    assert done.status == "failed"
    row = await stored(pg_session, event_id)
    assert (row.event_date, row.event_time) == (date(2026, 12, 1), "12:00")


@pytest.fixture
def google(pg_session, office, monkeypatch):
    """A connected Google Calendar whose API answers as each test decides (never called)."""
    ids = office.ids
    pg_session.add(
        CrmCalendarConnection(
            organization_id=ids["org"],
            user_id=ids["omar"],
            google_email="omar@example.test",
            refresh_token_encrypted="not-a-real-token",
            updated_at=datetime.now(UTC),
        )
    )
    monkeypatch.setattr(calendar_service, "configured", lambda: True)

    async def token(connection):
        return "stub-token"

    monkeypatch.setattr(calendar_service, "_access_token", token)
    state = SimpleNamespace(fail=False, calls=[])

    async def google_api(method, url, **kwargs):
        state.calls.append(method)
        if state.fail:
            request = httpx.Request(method, url)
            raise httpx.HTTPStatusError(
                "unavailable", request=request, response=httpx.Response(503, request=request)
            )
        return {}

    monkeypatch.setattr(calendar_service, "_google", google_api)
    return state


async def test_a_failed_cancellation_is_never_reported_as_done(pg_session, office, google):
    """Google refuses the deletion: the CRM keeps the event, the action fails with the
    reason, and the conversation never says it was cancelled or completed."""
    ids = office.ids
    event_id = await event(pg_session, ids, "omar", google_event_id="g-1")
    google.fail = True
    chat = await Chat(pg_session, office, "omar").start()

    def propose_cancel(messages):
        return call(
            "propose_crm_action",
            kind="cancel_calendar_event",
            payload={"event_id": event_id},
        )

    await chat.turn(
        "Cancel my Marina Gate viewing",
        coordinator=delegate("prepare_action", "Cancel my Marina Gate viewing"),
        action=script(
            call("query_my_calendar", start="2026-12-01", end="2026-12-01"),
            propose_cancel,
            say("Done, I've cancelled the viewing."),
        ),
    )
    [proposal] = await actions.list_actions(
        pg_session,
        user_id=ids["omar"],
        organization_id=ids["org"],
        conversation_id=chat.conversation_id,
    )
    done = await confirm(pg_session, ids, "omar", proposal.id)
    assert done.status == "failed"
    assert "was not deleted" in done.result["message"]
    assert "DELETE" in google.calls
    assert await stored(pg_session, event_id) is not None  # Still on the calendar.

    from app.crm.assistant.service import get_conversation_messages

    shown = (await get_conversation_messages(pg_session, chat.conversation_id, **chat.scope))[
        -1
    ].content
    assert "failed" in shown and "not confirmed as done" in shown
    for claim in ("completed", "I've cancelled", "Done"):
        assert claim not in shown


async def test_a_reschedule_saved_in_the_crm_but_not_in_google_is_partial(
    pg_session, office, google, monkeypatch
):
    ids = office.ids
    event_id = await event(pg_session, ids, "omar", google_event_id="g-2")

    async def sync_fails(db, *, connection, token):
        raise httpx.ConnectError("Google unreachable")

    monkeypatch.setattr(calendar_service, "_sync_pending", sync_fails)
    action = await propose(
        pg_session,
        ids,
        "omar",
        ActionKind.RESCHEDULE_CALENDAR_EVENT,
        {"event_id": event_id, "date": "2026-12-04", "time": "09:00"},
    )
    assert "Google Calendar (omar@example.test)" in action.preview["delivery"]
    done = await confirm(pg_session, ids, "omar", action.id)
    assert done.status == "partially_succeeded"
    assert "Google Calendar was not updated" in done.result["message"]
    assert (await stored(pg_session, event_id)).event_date == date(2026, 12, 4)


# --- Existing lead operations, re-checked ----------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "pooled_after"),
    [(ActionKind.UNASSIGN_LEAD, False), (ActionKind.RELEASE_TO_POOL, True)],
)
async def test_a_completed_unassignment_or_release_stays_visible_as_completed(
    pg_session, office, kind, pooled_after
):
    """Before the fix, the 'already unassigned / already in the pool' check also ran when
    showing the finished action, so a successful change was shown as no longer available."""
    ids = office.ids
    target = await lead(pg_session, ids, "Pool Candidate", team="north", assignee="sara")
    action = await propose(pg_session, ids, "nadia", kind, {"lead_id": target.id})
    done = await confirm(pg_session, ids, "nadia", action.id)
    assert done.status == "succeeded"
    assert done.preview.get("available") is not False
    shown = await actions.get_action(
        pg_session, user_id=ids["nadia"], organization_id=ids["org"], action_id=action.id
    )
    assert shown.status == "succeeded" and shown.preview.get("available") is not False
    pg_session.expire_all()
    row = await pg_session.get(CrmInboundEnquiry, target.id)
    assert row.assigned_user_id is None
    assert (row.pool_released_at is not None) is pooled_after
    # Doing it again is still refused while it would be a no-op.
    with pytest.raises(HTTPException) as refused:
        await propose(pg_session, ids, "nadia", kind, {"lead_id": target.id})
    assert refused.value.status_code == 409


async def test_reassignment_is_proposed_then_applied_and_rechecked(pg_session, office):
    ids = office.ids
    target = await lead(pg_session, ids, "Reassign Me", team="north", assignee="sara")
    action = await propose(
        pg_session,
        ids,
        "nadia",
        ActionKind.ASSIGN_LEAD,
        {"lead_id": target.id, "assignee_id": ids["omar"]},
    )
    assert (action.preview["current_assignee"], action.preview["new_assignee"]) == (
        "User 10",
        "Track 8",
    )
    done = await confirm(pg_session, ids, "nadia", action.id)
    assert done.status == "succeeded"
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, target.id)).assigned_user_id == ids["omar"]
    # South's manager cannot reassign North's lead, and an agent cannot reassign at all.
    for person, assignee in (("karim", "lina"), ("omar", "sara")):
        with pytest.raises(HTTPException) as refused:
            await propose(
                pg_session,
                ids,
                person,
                ActionKind.ASSIGN_LEAD,
                {"lead_id": target.id, "assignee_id": ids[assignee]},
            )
        assert refused.value.status_code in {403, 404}


async def test_a_lead_is_found_by_part_of_its_name_within_access(pg_session, office):
    """'bilal' finds Bilal Hameed (case-insensitive, part of the name) for those who may see it;
    South's manager finds nothing."""
    ids = office.ids
    from app.crm.assistant import query_my_records
    from app.crm.assistant.models import CrmAssistantQuery

    request = CrmAssistantQuery(resource="leads", search="bilal", include_contact_details=True)
    seen = await query_my_records(
        pg_session, request, user_id=ids["nadia"], organization_id=ids["org"]
    )
    assert [row["contact_name"] for row in seen.records] == ["Bilal Hameed"]
    assert seen.records[0]["handled_by"] == "User 10" and seen.records[0]["phone"]
    hidden = await query_my_records(
        pg_session, request, user_id=ids["karim"], organization_id=ids["org"]
    )
    assert hidden.total == 0 and hidden.records == []
