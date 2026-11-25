"""A request clarified over several turns keeps what the user already said.

Private conversations never replay earlier prose to the model. What carries over is the held
request: its kind, lead and the user's own typed details (date, time, duration, people's names
as given, title, criteria), rechecked against current access every turn. These tests run the
real chat turn (`stream_chat_response`) with a scripted model that calls the real tools, so a
regression in history loading, carry-over, rechecks or proposals fails here.

The scripted model stands in for the language model: these tests prove the details reach it and
that only confirmed, validated actions change anything, not how a real model phrases its answer.

Agency (crm_role_support): Nadia manages North (Omar, Sara); Karim manages South (Lina).
"""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from crm_role_support import agency, lead
from sqlalchemy import delete
from sqlmodel import select
from test_assistant_lead_action_turns import Chat

from app.assistant_actions import service as actions
from app.assistant_actions.models import (
    ActionKind,
    AssistantReminder,
    CalendarMeeting,
    CreateReminder,
    UpdateLead,
)
from app.crm.assistant import connector_tools, crm_tools, service, workflows
from app.crm.assistant.workflows import PendingDetails
from app.crm.calendar_models import CrmCalendarEvent
from app.crm.inbound_models import CrmInboundEnquiry
from app.organization.models import OrganizationMembership

DUBAI = timezone(timedelta(hours=4))
FIVE_PM = datetime(2026, 11, 24, 17, 0, tzinfo=DUBAI)


@pytest.fixture
async def office(pg_session, monkeypatch):
    from app.organization import service as organizations

    ids = await agency(pg_session)
    names = {
        "owner": ("Agency", "Owner"),
        "nadia": ("Manager", "1"),
        "omar": ("User", "1"),
        "sara": ("User", "10"),
        "karim": ("Manager", "10"),  # Begins with "Manager 1" but is not that person.
        "lina": ("User", "2"),
    }
    people = {ids[person]: name for person, name in names.items()}

    async def profile(user_id):
        first, last = people.get(user_id, ("Former", "Member"))
        return SimpleNamespace(first_name=first, last_name=last, email=f"{user_id}@example.test")

    monkeypatch.setattr(organizations, "get_user_by_id", profile)
    monkeypatch.setattr(actions, "get_user_by_id", profile)

    async def session():
        yield pg_session

    for module in (workflows, crm_tools, connector_tools):
        monkeypatch.setattr(module, "get_db_session", session)
    monkeypatch.setattr(service.settings, "ASSISTANT_ENABLED", True)
    monkeypatch.setattr(service.settings, "ASSISTANT_TYPED_ROUTING_ENABLED", False)
    monkeypatch.setattr(
        service.admission, "acquire", AsyncMock(return_value=service.admission.TurnLease("l", 1))
    )
    monkeypatch.setattr(service.admission, "finish", AsyncMock())
    jvc = {"locations": ["JVC"]}
    priya = await lead(pg_session, ids, "Priya Rossi", team="north", assignee="sara", criteria=jvc)
    return SimpleNamespace(ids=ids, people=people, priya=priya, monkeypatch=monkeypatch)


def hold(chat, kind=None, lead_id=None, **details):
    return workflows.hold_pending_request(
        chat.ctx("hold"),
        kind=kind,
        lead_id=lead_id,
        details=PendingDetails(**details) if details else None,
    )


async def calendar_events(db, user_id):
    db.expire_all()
    return (
        await db.exec(select(CrmCalendarEvent).where(CrmCalendarEvent.user_id == user_id))
    ).all()


# --- The reported conversation ------------------------------------------------------------


async def test_booking_keeps_the_date_when_duration_and_colleague_follow(pg_session, office):
    """24 November 2026 at 5:00 PM, then "30 min Manager 1 team JVC sales": the time is not
    asked again, Manager 1 is resolved to one colleague, and nothing is booked until confirmed."""
    ids = office.ids
    chat = await Chat(pg_session, office, "omar").start()

    async def asks_for_the_rest():
        # The calendar check makes the conversation private: its prose is never replayed.
        await connector_tools.query_my_calendar(
            chat.ctx("calendar"), date(2026, 11, 24), date(2026, 11, 24)
        )
        held = await hold(
            chat,
            ActionKind.BOOK_CALENDAR_MEETING,
            starts_at=FIVE_PM,
            missing=["duration", "who", "topic"],
        )
        assert held["available"] is True
        return "You're free then. How long is it, who is it with, and what is it about?"

    await chat.turn("Book a meeting on 24 November 2026 at 5:00 PM", asks_for_the_rest)

    async def completes_the_booking():
        replay = chat.history
        assert "How long is it" not in replay  # No private prose...
        assert '"kind": "book_calendar_meeting"' in replay  # ...but the held request,
        assert '"starts_at": "2026-11-24T17:00:00+04:00"' in replay  # with the user's time.
        # Each workflow's task carries it too, without relying on the coordinator.
        assert "2026-11-24T17:00:00+04:00" in workflows.pending_note(chat.deps)
        found = await workflows.find_meeting_colleagues(chat.ctx("lookup"), "Manager 1")
        # Exactly Manager 1, not Manager 10.
        assert found["matches"] == [{"id": ids["nadia"], "display_name": "Manager 1"}]
        assert found["clarification_required"] is False
        proposal = await chat.propose(
            ActionKind.BOOK_CALENDAR_MEETING,
            CalendarMeeting(
                title="Team JVC sales",
                starts_at=FIVE_PM,
                ends_at=FIVE_PM + timedelta(minutes=30),
                colleague_ids=[ids["nadia"]],
            ),
        )
        assert proposal["confirmation_required"] is True
        return "Please confirm the meeting."

    await chat.turn("30 min Manager 1 team JVC sales", completes_the_booking)
    action = chat.deps.proposals[0]
    assert action["status"] == "awaiting_confirmation"
    assert action["preview"]["when"] == "24 Nov 2026 17:00–17:30 Dubai time"
    assert action["preview"]["with"] == ["Manager 1"]
    assert "no invitations are sent" in action["preview"]["consequence"]
    # Proposed is not booked.
    assert await calendar_events(pg_session, ids["omar"]) == []

    # The proposal settled the request.
    async def settled():
        assert "pending request" not in chat.history
        return "Waiting for your confirmation."

    await chat.turn("Thanks", settled)

    confirmed = await actions.confirm_action(pg_session, **chat.scope, action_id=action["id"])
    assert confirmed.status == "succeeded", confirmed.result
    [event] = await calendar_events(pg_session, ids["omar"])
    assert (event.title, event.event_date, event.event_time, event.event_end_time) == (
        "Team JVC sales",
        date(2026, 11, 24),
        "17:00",
        "17:30",
    )
    # Named in the details only: nobody is invited, and Manager 1's calendar is untouched.
    assert event.detail == "With Manager 1" and event.guests == [] and event.lead_id is None
    assert await calendar_events(pg_session, ids["nadia"]) == []


# --- People are resolved, never guessed ---------------------------------------------------


async def test_ambiguous_or_unknown_colleague_is_asked_about_and_the_time_is_kept(
    pg_session, office
):
    ids = office.ids
    office.people[ids["lina"]] = ("Manager", "1")  # A second Manager 1, in South.
    chat = await Chat(pg_session, office, "omar").start()

    async def two_match():
        await hold(chat, ActionKind.BOOK_CALENDAR_MEETING, starts_at=FIVE_PM)
        found = await workflows.find_meeting_colleagues(chat.ctx("lookup"), "Manager 1")
        assert {m["id"] for m in found["matches"]} == {ids["nadia"], ids["lina"]}
        assert found["clarification_required"] is True
        meeting = CalendarMeeting(
            title="JVC sales",
            starts_at=FIVE_PM,
            ends_at=FIVE_PM + timedelta(minutes=30),
            colleague_ids=[ids["nadia"]],
        )
        # Choosing one of them is refused.
        refused = await chat.propose(ActionKind.BOOK_CALENDAR_MEETING, meeting)
        assert refused["available"] is False and refused["clarification_required"] is True
        unknown = await workflows.find_meeting_colleagues(chat.ctx("lookup2"), "Nobody Here")
        assert unknown["matches"] == [] and "No colleague" in unknown["reason"]
        held = await hold(
            chat,
            duration_minutes=30,
            title="JVC sales",
            people=["Manager 1"],
            missing=["which Manager 1"],
        )
        # Merged with what was held before, not replacing it.
        assert held["held"]["details"]["starts_at"] == "2026-11-24T17:00:00+04:00"
        return "There are two people named Manager 1. Which one do you mean?"

    await chat.turn("Book 24 Nov 2026 5 PM, 30 min with Manager 1, JVC sales", two_match)
    assert chat.deps.proposals == []

    async def still_has_everything():
        replay = chat.history
        for given in (
            '"starts_at": "2026-11-24T17:00:00+04:00"',
            '"duration_minutes": 30',
            '"people": ["Manager 1"]',
            '"title": "JVC sales"',
        ):
            assert given in replay
        # An ID never looked up this turn is refused, whoever it is.
        refused = await chat.propose(
            ActionKind.BOOK_CALENDAR_MEETING,
            CalendarMeeting(
                title="JVC sales",
                starts_at=FIVE_PM,
                ends_at=FIVE_PM + timedelta(minutes=30),
                colleague_ids=[ids["karim"]],
            ),
        )
        assert refused["available"] is False
        return "Which Manager 1: North or South?"

    await chat.turn("Hmm, not sure", still_has_everything)
    assert chat.deps.proposals == []
    assert await calendar_events(pg_session, ids["omar"]) == []


# --- Other operations ---------------------------------------------------------------------


async def test_lead_search_clarification_continues_with_the_area(pg_session, office):
    chat = await Chat(pg_session, office, "nadia").start()

    async def which_area():
        await chat.search("Priya")  # Private evidence: later turns replay no prose.
        await hold(chat, search="buyer leads", task="find_leads", missing=["area"])
        return "Which area?"

    await chat.turn("Find my buyer leads", which_area)

    async def searches_jvc():
        assert '"task": "find_leads"' in chat.history
        assert '"search": "buyer leads"' in chat.history
        found = await chat.search("JVC")
        assert [r["id"] for r in found["records"]] == [office.priya.id]
        return "One JVC lead."

    await chat.turn("JVC", searches_jvc)


async def test_follow_up_date_for_a_chosen_lead_is_completed_next_turn(pg_session, office):
    priya = office.priya
    chat = await Chat(pg_session, office, "sara").start()

    async def which_date():
        await chat.search("Priya Rossi")
        await hold(chat, ActionKind.UPDATE_LEAD, priya.id, missing=["follow-up date"])
        return "For which date?"

    await chat.turn("Set a follow-up for Priya", which_date)

    async def proposes():
        assert '"kind": "update_lead"' in chat.history
        assert f'"lead_id": {priya.id}' in chat.history and "Priya" not in chat.history
        proposal = await chat.propose(
            ActionKind.UPDATE_LEAD, UpdateLead(lead_id=priya.id, next_follow_up=date(2026, 12, 1))
        )
        assert proposal["confirmation_required"] is True
        return "Please confirm."

    await chat.turn("1 December 2026", proposes)
    action = chat.deps.proposals[0]
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, priya.id)).next_follow_up is None
    confirmed = await actions.confirm_action(pg_session, **chat.scope, action_id=action["id"])
    assert confirmed.status == "succeeded"
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, priya.id)).next_follow_up == date(2026, 12, 1)


async def test_reminder_title_is_kept_until_the_time_is_given(pg_session, office):
    chat = await Chat(pg_session, office, "sara").start()

    async def when():
        await chat.search("Priya Rossi")
        await hold(
            chat,
            ActionKind.CREATE_REMINDER,
            office.priya.id,
            title="Call Priya about the JVC viewing",
            missing=["when"],
        )
        return "When should I remind you?"

    await chat.turn("Remind me to call Priya about the JVC viewing", when)

    async def proposes():
        assert '"title": "Call Priya about the JVC viewing"' in chat.history
        proposal = await chat.propose(
            ActionKind.CREATE_REMINDER,
            CreateReminder(
                title="Call Priya about the JVC viewing",
                due_at=datetime(2026, 11, 25, 10, tzinfo=DUBAI),
                lead_id=office.priya.id,
            ),
        )
        assert proposal["confirmation_required"] is True
        return "Please confirm the reminder."

    await chat.turn("Tomorrow at 10", proposes)
    mine = select(AssistantReminder).where(AssistantReminder.user_id == office.ids["sara"])
    assert (await pg_session.exec(mine)).all() == []


async def test_a_held_request_ends_with_the_users_membership(pg_session, office):
    ids = office.ids
    chat = await Chat(pg_session, office, "omar").start()

    async def held():
        await hold(chat, ActionKind.BOOK_CALENDAR_MEETING, starts_at=FIVE_PM)
        return "How long?"

    await chat.turn("Book 24 Nov 2026 5 PM", held)
    await pg_session.execute(
        delete(OrganizationMembership).where(OrganizationMembership.user_id == ids["omar"])
    )
    await pg_session.commit()
    messages = await service.get_conversation_messages(
        pg_session, chat.conversation_id, **chat.scope, include_retrieval_context=True
    )
    assert all("_pending_action" not in (m.meta_data or {}) for m in messages)
