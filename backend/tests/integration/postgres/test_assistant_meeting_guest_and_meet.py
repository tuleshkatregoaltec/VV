"""Reported: "Schedule a 30-minute meeting with Mariam Ali tomorrow at 12 PM IST." The
assistant reported a completed meeting, but CRM › Calendar showed it as a Follow-up, with no
guests and no Google Meet.

- A meeting stays a Meeting, also after CRM › Calendar pulls it back from Google.
- Mariam Ali's lead email, when usable (a lead the user can see, a valid address, not marked
  do not contact), is a Google Calendar guest; a lead link alone is not an invitation.
- Google Meet is requested through Google Calendar; only a link Google returned is reported.
- The proposal shows who will be invited (with the address) and whether a Meet link will be
  created, or why not. Nothing is written, invited or created before confirmation; the lead,
  email and Google connection are rechecked when the user confirms.
- 12 PM IST is 10:30 in Dubai.

Synthetic agency; Google Calendar is a recording fake (test_assistant_calendar_meeting); no
model is called and nothing leaves the test.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import delete, update
from test_assistant_calendar_meeting import (
    NOON_IST,
    confirm,
    connect_google,
    events,
    propose,
    setup_office,
)
from test_assistant_lead_action_turns import Chat

from app.crm import assignment, calendar_service, calendar_visibility
from app.crm.calendar_models import CalendarEventResponse, CrmCalendarConnection
from app.crm.inbound_models import CrmInboundContact, CrmInboundEnquiry

MARIAM = "mariam.ali@example.test"
MEET = "https://meet.google.com/abc-defg-hij"


@pytest.fixture
async def office(pg_session, monkeypatch):
    office = await setup_office(pg_session, monkeypatch)
    await set_contact(pg_session, office, email=MARIAM)
    return office


@pytest.fixture
async def google(pg_session, office, monkeypatch):
    return await connect_google(pg_session, office, monkeypatch)


async def set_contact(pg_session, office, **values):
    contact_id = (await pg_session.get(CrmInboundEnquiry, office.mariam.id)).contact_id
    await pg_session.exec(
        update(CrmInboundContact).where(CrmInboundContact.id == contact_id).values(**values)
    )
    await pg_session.commit()


def inserts(google):
    return [call for call in google if call["method"] == "POST"]


# --- 2, 3 and 6. Mariam invited by email, with Google Meet, at the Dubai time ----------------


async def test_mariam_is_invited_with_a_meet_link_at_the_dubai_time(pg_session, office, google):
    chat = await Chat(pg_session, office, "omar").start()
    proposal = await propose(pg_session, office, chat)
    preview = proposal["preview"]
    # Before confirmation: who is invited, at which address, and the Meet link to come.
    assert (
        f"Google Calendar will email an invitation to Mariam Ali (lead) at {MARIAM}"
        in (preview["invitations"])
    )
    assert preview["video"] == "A Google Meet link will be created and sent with the invitation"
    assert preview["when"] == "27 Nov 2026 10:30–11:00 Dubai time"
    # 5. Nothing written, invited or created yet.
    assert await events(pg_session, office.ids["omar"]) == [] and google == []

    done = await confirm(pg_session, chat)
    assert done.status == "succeeded", done.result
    [event] = await events(pg_session, office.ids["omar"])
    assert (event.kind, event.lead_id, event.guests, event.meet, event.meet_link) == (
        "meeting",
        office.mariam.id,
        [MARIAM],
        True,
        MEET,
    )
    assert (event.event_date, event.event_time, event.event_end_time) == (
        date(2026, 11, 27),
        "10:30",
        "11:00",
    )
    [insert] = inserts(google)
    body = insert["body"]
    assert body["attendees"] == [{"email": MARIAM}] and insert["params"]["sendUpdates"] == "all"
    assert body["conferenceData"]["createRequest"]["conferenceSolutionKey"] == {
        "type": "hangoutsMeet"
    }
    assert body["start"]["dateTime"] == "2026-11-27T10:30:00+04:00"
    message = done.result["message"]
    assert "Google Calendar sent an invitation to Mariam Ali" in message
    assert f"Google Meet link: {MEET}" in message


# --- 1. A Meeting stays a Meeting when CRM › Calendar reopens it ----------------------------


async def test_the_meeting_type_survives_the_google_round_trip(pg_session, office, google):
    chat = await Chat(pg_session, office, "omar").start()
    await propose(pg_session, office, chat)
    assert (await confirm(pg_session, chat)).status == "succeeded"
    [insert] = inserts(google)
    # CRM › Calendar pulls the event back from Google as Google now holds it.
    pulled = {
        **insert["body"],
        "status": "confirmed",
        "etag": "e2",
        "hangoutLink": MEET,
        "attendees": [{"email": MARIAM, "responseStatus": "needsAction"}],
    }
    [event] = await events(pg_session, office.ids["omar"])
    await calendar_service._store_google_event(
        pg_session, event=pulled, user_id=office.ids["omar"], organization_id=office.ids["org"]
    )
    await pg_session.commit()
    [event] = await events(pg_session, office.ids["omar"])
    assert event.kind == "meeting" and event.guests == [MARIAM]
    # What the edit form is given when it reopens the event (GET /calendar/events/{id}).
    scope = await assignment.load_scope(pg_session, office.ids["org"], office.ids["omar"])
    shown = CalendarEventResponse.model_validate(
        await calendar_visibility.get_for_viewer(pg_session, scope, event.id)
    )
    assert (shown.kind, shown.time, shown.end_time, shown.meet) == (
        "meeting",
        "10:30",
        "11:00",
        True,
    )


# --- 4. No misleading success ------------------------------------------------------------


@pytest.mark.parametrize(
    ("contact", "reason"),
    [
        ({"email": None}, "no usable email on file"),
        ({"email": "mariam ali@example.test"}, "no usable email on file"),
        ({"do_not_contact": True}, "marked do not contact"),
    ],
)
async def test_without_a_usable_email_mariam_is_not_invited(
    pg_session, office, google, contact, reason
):
    await set_contact(pg_session, office, **contact)
    chat = await Chat(pg_session, office, "omar").start()
    proposal = await propose(pg_session, office, chat)
    lines = " ".join(proposal["preview"]["invitations"])
    assert f"Mariam Ali (lead) is not invited: {reason}" in lines
    assert MARIAM not in lines or reason != "no usable email on file"
    done = await confirm(pg_session, chat)
    [event] = await events(pg_session, office.ids["omar"])
    assert event.guests == []
    assert inserts(google)[0]["body"]["attendees"] == []
    assert "invitation" not in done.result["message"].casefold()


async def test_without_google_there_is_no_invitation_and_no_meet(pg_session, office):
    chat = await Chat(pg_session, office, "omar").start()
    proposal = await propose(pg_session, office, chat)
    preview = proposal["preview"]
    assert (
        "Mariam Ali (lead) is not invited: Google Calendar is not connected, so no invitations "
        "can be sent"
    ) in preview["invitations"]
    assert preview["video"] == "No Google Meet link: Google Calendar is not connected"
    done = await confirm(pg_session, chat)
    [event] = await events(pg_session, office.ids["omar"])
    assert (event.kind, event.guests, event.meet) == ("meeting", [], False)
    message = done.result["message"].casefold()
    assert "invitation" not in message and "meet link:" not in message


async def test_an_unsupported_meet_is_reported_as_not_created(pg_session, office, google):
    office.meet_supported = False
    chat = await Chat(pg_session, office, "omar").start()
    await propose(pg_session, office, chat)
    done = await confirm(pg_session, chat)
    [event] = await events(pg_session, office.ids["omar"])
    assert event.meet_link is None
    message = done.result["message"]
    assert "Google Calendar sent an invitation to Mariam Ali" in message
    assert "Google Meet link" not in message.replace("No Google Meet link", "")
    assert "No Google Meet link was created" in message


async def test_a_google_failure_claims_neither_invitation_nor_meet(pg_session, office, google):
    office.google_fails = True
    chat = await Chat(pg_session, office, "omar").start()
    await propose(pg_session, office, chat)
    done = await confirm(pg_session, chat)
    assert done.status == "partially_succeeded"
    message = done.result["message"]
    assert "sent an invitation" not in message and "Google Meet link:" not in message
    assert "No invitation has been sent" in message and "No Google Meet link was created" in message


# --- 5. Rechecked at confirmation --------------------------------------------------------


@pytest.mark.parametrize("change", ["email_changed", "google_disconnected", "lead_out_of_reach"])
async def test_lead_email_and_google_are_rechecked_at_confirmation(
    pg_session, office, google, change
):
    ids = office.ids
    chat = await Chat(pg_session, office, "omar").start()
    await propose(pg_session, office, chat)
    if change == "email_changed":
        await set_contact(pg_session, office, email="someone.else@example.test")
    elif change == "google_disconnected":
        await pg_session.exec(
            delete(CrmCalendarConnection).where(CrmCalendarConnection.user_id == ids["omar"])
        )
        await pg_session.commit()
    else:
        owner = await assignment.load_scope(pg_session, ids["org"], ids["owner"])
        await assignment.reassign(
            pg_session, owner, [office.mariam.id], ids["lina"], team_id=ids["south"]
        )
        await pg_session.commit()
    done = await confirm(pg_session, chat)
    assert done.status == "failed"
    assert await events(pg_session, ids["omar"]) == [] and google == []


async def test_a_colleague_and_mariam_are_both_invited(pg_session, office, google):
    chat = await Chat(pg_session, office, "omar").start()
    proposal = await propose(pg_session, office, chat, colleagues=["sara"])
    lines = proposal["preview"]["invitations"]
    assert "Google Calendar will email an invitation to Track 6 at track6@example.test" in lines
    assert f"Google Calendar will email an invitation to Mariam Ali (lead) at {MARIAM}" in lines
    assert (await confirm(pg_session, chat)).status == "succeeded"
    [event] = await events(pg_session, office.ids["omar"])
    assert sorted(event.guests) == sorted(["track6@example.test", MARIAM])
    assert event.event_time == "10:30" and event.event_end_time == (
        (NOON_IST + timedelta(minutes=30))
        .astimezone(calendar_service.BUSINESS_TZ)
        .strftime("%H:%M")
    )
