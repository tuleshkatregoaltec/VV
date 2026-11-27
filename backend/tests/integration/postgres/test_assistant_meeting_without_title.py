"""Reported: "Schedule a 30-minute meeting with Mariam Ali tomorrow at 12 PM IST." The request
was complete, yet the assistant asked for a title; "add meeting" was then asked for a title
again, and nothing was proposed.

A title is optional: the server names the meeting after its lead or colleagues. A request
held for clarification keeps its lead, time and duration, and never asks for the title again.
Nothing is saved, and nobody invited, before the user confirms.

The real chat turn and the real agents run with scripted models: a tool call with no title
goes through the same argument validation that refused it. Synthetic agency; Google Calendar
is a recording fake (test_assistant_calendar_meeting); no model is called.
"""

import json
from datetime import date, timedelta

import pytest
from pydantic_ai.messages import UserPromptPart
from test_assistant_calendar_meeting import (
    NOON_IST,
    confirm,
    connect_google,
    events,
    setup_office,
)
from test_assistant_lead_contact_turns import Chat, call, delegate, last_return, say, script

from app.assistant_actions import service as actions
from app.crm.assistant import workflows

THIRTY = (NOON_IST + timedelta(minutes=30)).isoformat()


@pytest.fixture
async def office(pg_session, monkeypatch):
    """The calendar tests' agency; real agents run here (with scripted models), so each turn
    gets a realistic token budget."""
    from unittest.mock import AsyncMock

    from app.crm.assistant import service

    office = await setup_office(pg_session, monkeypatch)
    monkeypatch.setattr(
        service.admission,
        "acquire",
        AsyncMock(return_value=service.admission.TurnLease("l", 150_000)),
    )
    return office


@pytest.fixture
async def google(pg_session, office, monkeypatch):
    return await connect_google(pg_session, office, monkeypatch)


def leads(**request):
    return call("query_my_crm_records", resource="leads", **request)


def meeting_without_title(lead_id, **extra):
    return call(
        "propose_crm_action",
        kind="book_calendar_meeting",
        payload={"starts_at": NOON_IST.isoformat(), "ends_at": THIRTY, "lead_id": lead_id, **extra},
    )


async def stored(pg_session, chat):
    return await actions.list_actions(
        pg_session, **chat.scope, conversation_id=chat.conversation_id
    )


# --- 1. A complete request is proposed at once, with a default title ----------------------


async def test_a_complete_request_without_a_title_is_proposed_with_a_default(
    pg_session, office, google
):
    chat = await Chat(pg_session, office, "omar").start()
    seen = {}

    def propose(messages):
        [row] = last_return(messages)["records"]
        return meeting_without_title(row["id"])

    def answer(messages):
        seen["proposal"] = last_return(messages)
        return say("Here is the meeting for your confirmation.")

    action = script(leads(search="Mariam Ali"), propose, answer)
    shown = await chat.turn(
        "Schedule a 30-minute meeting with Mariam Ali tomorrow at 12 PM IST.",
        coordinator=delegate("prepare_action", "30-minute meeting with Mariam Ali, 12 PM IST"),
        action=action,
    )
    # The title-less call was accepted and proposed, not refused for a missing title.
    assert seen["proposal"]["status"] == "awaiting_confirmation"
    assert "awaiting your confirmation" in shown
    [proposal] = await stored(pg_session, chat)
    assert proposal.preview["changes"]["title"] == "Meeting with Mariam Ali"
    assert proposal.preview["when"] == "27 Nov 2026 10:30–11:00 Dubai time"
    # 3. Proposed is not booked: no event, no request to Google.
    assert await events(pg_session, office.ids["omar"]) == [] and google == []

    # 4. Confirmed: the meeting as requested, at the Dubai time, linked to Mariam's lead.
    done = await confirm(pg_session, chat)
    assert done.status == "succeeded", done.result
    [event] = await events(pg_session, office.ids["omar"])
    assert (event.title, event.kind, event.lead_id) == (
        "Meeting with Mariam Ali",
        "meeting",
        office.mariam.id,
    )
    assert (event.event_date, event.event_time, event.event_end_time) == (
        date(2026, 11, 27),
        "10:30",
        "11:00",
    )
    assert event.guests == []  # A linked lead is not an invited guest.


async def test_a_default_title_names_the_invited_colleague_too(pg_session, office, google):
    chat = await Chat(pg_session, office, "omar").start()

    def propose(messages):
        [match] = last_return(messages)["matches"]
        return meeting_without_title(office.mariam.id, colleague_ids=[match["id"]])

    action = script(
        call("find_meeting_colleagues", search="Track 6"),
        propose,
        say("Ready for your confirmation."),
    )
    await chat.turn(
        "30-minute meeting with Mariam Ali and Track 6 tomorrow at 12 PM IST",
        coordinator=delegate("prepare_action", "Meeting with Mariam Ali and Track 6"),
        action=action,
    )
    [proposal] = await stored(pg_session, chat)
    assert proposal.preview["changes"]["title"] == "Meeting with Mariam Ali and Track 6"
    assert google == []
    assert (await confirm(pg_session, chat)).status == "succeeded"
    [event] = await events(pg_session, office.ids["omar"])
    assert event.guests == ["track6@example.test"]


async def test_a_title_the_user_gave_is_kept(pg_session, office):
    chat = await Chat(pg_session, office, "omar").start()
    action = script(
        meeting_without_title(office.mariam.id, title="Payment plan review"),
        say("Ready for your confirmation."),
    )
    await chat.turn(
        "Meeting with Mariam Ali tomorrow 12 PM IST, call it Payment plan review",
        coordinator=delegate("prepare_action", "Payment plan review with Mariam Ali"),
        action=action,
    )
    [proposal] = await stored(pg_session, chat)
    assert proposal.preview["changes"]["title"] == "Payment plan review"


# --- 2. "add meeting" continues the held request ------------------------------------------


async def test_add_meeting_continues_the_held_request_without_asking_for_a_title(
    pg_session, office, google
):
    chat = await Chat(pg_session, office, "omar").start()

    # Turn 1, as reported: everything is known, yet a title is asked for and held as missing.
    def hold(messages):
        [row] = last_return(messages)["records"]
        return call(
            "hold_pending_request",
            kind="book_calendar_meeting",
            lead_id=row["id"],
            details={
                "starts_at": NOON_IST.isoformat(),
                "duration_minutes": 30,
                "people": ["Mariam Ali"],
                "missing": ["title"],
            },
        )

    first = script(
        leads(search="Mariam Ali"),
        hold,
        say("What title should I use for the meeting proposal?"),
    )
    await chat.turn(
        "Schedule a 30-minute meeting with Mariam Ali tomorrow at 12 PM IST.",
        coordinator=delegate("prepare_action", "30-minute meeting with Mariam Ali at 12 PM IST"),
        action=first,
    )
    assert await stored(pg_session, chat) == []

    # Turn 2: "add meeting". The held request reaches the specialist intact: lead, time,
    # duration and person, and the title is no longer listed as missing.
    seen = {}

    def continue_held(messages):
        # The specialist's task: the user's words plus the server's held request.
        task = next(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        held = task.split("Pending request this message may answer", 1)[1]
        note = json.loads(held[held.index("{") :])
        seen["held"] = note
        details = note["details"]
        start = details["starts_at"]
        end = (NOON_IST + timedelta(minutes=details["duration_minutes"])).isoformat()
        return call(
            "propose_crm_action",
            kind="book_calendar_meeting",
            payload={"starts_at": start, "ends_at": end, "lead_id": note["lead_id"]},
        )

    def answer(messages):
        seen["proposal"] = last_return(messages)
        return say("Here is the meeting for your confirmation.")

    second = script(continue_held, answer)
    shown = await chat.turn(
        "add meeting",
        coordinator=delegate("prepare_action", "add meeting"),
        action=second,
    )
    held = seen["held"]
    assert held["kind"] == "book_calendar_meeting" and held["lead_id"] == office.mariam.id
    assert held["details"]["starts_at"] == NOON_IST.isoformat()
    assert held["details"]["duration_minutes"] == 30
    assert "title" not in json.dumps(held["details"].get("missing", []))
    assert seen["proposal"]["status"] == "awaiting_confirmation"
    assert "awaiting your confirmation" in shown
    [proposal] = await stored(pg_session, chat)
    assert proposal.preview["changes"]["title"] == "Meeting with Mariam Ali"
    # 3. Still nothing written or sent before confirmation.
    assert await events(pg_session, office.ids["omar"]) == [] and google == []

    done = await confirm(pg_session, chat)
    assert done.status == "succeeded", done.result
    [event] = await events(pg_session, office.ids["omar"])
    assert (event.title, event.kind, event.event_time, event.event_end_time, event.lead_id) == (
        "Meeting with Mariam Ali",
        "meeting",
        "10:30",
        "11:00",
        office.mariam.id,
    )


@pytest.mark.parametrize("missing", [["title"], ["meeting title", "start time"]])
def test_a_held_meeting_never_lists_its_title_as_missing(missing):
    """The title is the server's to fill; other missing details stay to be asked for."""
    held = workflows.without_optional_missing(
        "book_calendar_meeting", {"duration_minutes": 30, "missing": missing}
    )
    assert all("title" not in item for item in held.get("missing", []))
    assert held["duration_minutes"] == 30
    if "start time" in missing:
        assert held["missing"] == ["start time"]
