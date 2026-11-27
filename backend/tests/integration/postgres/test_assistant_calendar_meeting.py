"""Reported: "Schedule a 30-minute meeting with Mariam Ali tomorrow at 12 PM IST." The
assistant saved it on the CRM calendar and Google Calendar, at the right time (12:00 IST =
10:30 Dubai), but as a Call, with no guests.

- A meeting is saved as a meeting.
- Mariam Ali is a lead: the event is linked to her lead; that is not an invitation.
- A colleague found by name, with an email on file, is invited through Google Calendar when it
  is connected (the only invitation delivery the CRM has); otherwise the proposal says plainly
  that nobody is invited, and why.
- Nothing is written, and no invitation goes out, before confirmation; who is invited is
  rechecked when the user confirms.

Synthetic agency (crm_role_support); Google Calendar is a recording fake; no model is called.
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
from app.assistant_actions.models import ActionKind, CalendarMeeting
from app.crm import calendar_service
from app.crm.assistant import connector_tools, crm_tools, service, workflows
from app.crm.calendar_models import CrmCalendarConnection, CrmCalendarEvent
from app.organization.models import OrganizationMembership, OrganizationTeamMember

IST = timezone(timedelta(hours=5, minutes=30))
NOON_IST = datetime(2026, 11, 27, 12, 0, tzinfo=IST)  # 10:30 in Dubai.


@pytest.fixture
async def office(pg_session, monkeypatch):
    return await setup_office(pg_session, monkeypatch)


async def setup_office(pg_session, monkeypatch):
    """The agency, its member names and emails, and Mariam Ali's lead (shared set-up)."""
    from app.organization import service as organizations

    ids = await agency(pg_session)
    names = {
        "owner": ("Agency", "Owner"),
        "nadia": ("Nadia", "Manager"),
        "omar": ("User", "1"),  # The signed-in agent.
        "sara": ("Track", "6"),  # A colleague with an email on file.
        "karim": ("Karim", "South"),
        "lina": ("Track", "7"),  # A colleague with no email on file.
    }
    people = {ids[person]: name for person, name in names.items()}
    emails = {ids["sara"]: "track6@example.test"}

    async def profile(user_id):
        first, last = people.get(user_id, ("Former", "Member"))
        return SimpleNamespace(first_name=first, last_name=last, email=emails.get(user_id))

    for module in (organizations, actions):
        monkeypatch.setattr(module, "get_user_by_id", profile)

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
    mariam = await lead(pg_session, ids, "Mariam Ali", team="north", assignee="omar")
    return SimpleNamespace(
        ids=ids, people=people, emails=emails, mariam=mariam, monkeypatch=monkeypatch
    )


@pytest.fixture
async def google(pg_session, office, monkeypatch):
    return await connect_google(pg_session, office, monkeypatch)


async def connect_google(pg_session, office, monkeypatch):
    """Omar's Google Calendar, connected; every request is recorded, none leaves the test."""
    sent = []

    async def fake(method, url, *, token, params=None, body=None):
        sent.append({"method": method, "params": params, "body": body})
        if office.google_fails:
            raise calendar_service.httpx.ConnectError("Google unreachable")
        saved = {"id": (body or {}).get("id", "g-1"), "status": "confirmed", "etag": "e1"}
        create = ((body or {}).get("conferenceData") or {}).get("createRequest")
        if create and office.meet_supported:
            # Google's answer when it created the conference.
            saved["hangoutLink"] = "https://meet.google.com/abc-defg-hij"
        elif create:
            # When the account cannot create Meet: no link, the request marked failed.
            saved["conferenceData"] = {"createRequest": {"status": {"statusCode": "failure"}}}
        return saved

    office.google_fails = False
    office.meet_supported = True
    pg_session.add(
        CrmCalendarConnection(
            organization_id=office.ids["org"],
            user_id=office.ids["omar"],
            google_email="user1@example.test",
            refresh_token_encrypted="synthetic",
            updated_at=datetime.now(timezone.utc),
        )
    )
    await pg_session.commit()
    monkeypatch.setattr(calendar_service, "configured", lambda: True)
    monkeypatch.setattr(calendar_service, "_access_token", AsyncMock(return_value="token"))
    monkeypatch.setattr(calendar_service, "_google", fake)
    return sent


async def events(db, user_id):
    db.expire_all()
    rows = await db.exec(select(CrmCalendarEvent).where(CrmCalendarEvent.user_id == user_id))
    return rows.all()


def meeting(office, colleagues=(), lead=True):
    return CalendarMeeting(
        title="Meeting with Mariam Ali",
        starts_at=NOON_IST,
        ends_at=NOON_IST + timedelta(minutes=30),
        lead_id=office.mariam.id if lead else None,
        colleague_ids=[office.ids[c] for c in colleagues],
    )


async def propose(pg_session, office, chat, colleagues=(), lead=True):
    result = {}

    async def book():
        for name in colleagues:
            found = await workflows.find_meeting_colleagues(
                chat.ctx(f"lookup-{name}"), " ".join(office.people[office.ids[name]])
            )
            assert found["clarification_required"] is False, found
        result.update(
            await chat.propose(ActionKind.BOOK_CALENDAR_MEETING, meeting(office, colleagues, lead))
        )
        return "Please confirm the meeting."

    await chat.turn("Schedule a 30-minute meeting with Mariam Ali tomorrow at 12 PM IST", book)
    return result


async def confirm(pg_session, chat):
    [action] = await actions.list_actions(
        pg_session, **chat.scope, conversation_id=chat.conversation_id
    )
    return await actions.confirm_action(pg_session, **chat.scope, action_id=action.id)


# --- 1 and 6. A meeting, at the Dubai time ------------------------------------------------


async def test_a_meeting_is_saved_as_a_meeting_at_the_dubai_time(pg_session, office):
    chat = await Chat(pg_session, office, "omar").start()
    proposal = await propose(pg_session, office, chat)
    assert proposal["confirmation_required"] is True
    assert proposal["preview"]["when"] == "27 Nov 2026 10:30–11:00 Dubai time"
    assert await events(pg_session, office.ids["omar"]) == []  # Proposed is not saved.
    done = await confirm(pg_session, chat)
    assert done.status == "succeeded", done.result
    [event] = await events(pg_session, office.ids["omar"])
    assert event.kind == "meeting"
    assert (event.event_date, event.event_time, event.event_end_time) == (
        date(2026, 11, 27),
        "10:30",
        "11:00",
    )
    assert event.lead_id == office.mariam.id


# --- 2. A linked lead is not an invitation ------------------------------------------------


async def test_the_linked_lead_is_never_presented_or_sent_as_invited(pg_session, office, google):
    chat = await Chat(pg_session, office, "omar").start()
    proposal = await propose(pg_session, office, chat)
    invitations = proposal["preview"]["invitations"]
    # The link alone is no invitation: here her stored address is not usable (it holds a
    # space), so she is not invited (test_assistant_meeting_guest_and_meet covers a usable one).
    assert "Mariam Ali (lead) is not invited: no usable email on file" in invitations
    assert "will email an invitation" not in " ".join(invitations)
    done = await confirm(pg_session, chat)
    assert done.status == "succeeded"
    [event] = await events(pg_session, office.ids["omar"])
    assert event.guests == [] and event.lead_id == office.mariam.id
    [insert] = [call for call in google if call["method"] == "POST"]
    assert insert["body"]["attendees"] == []
    assert "invitation" not in done.result["message"].casefold()


# --- 3. A colleague with an email is invited through Google Calendar ------------------------


async def test_a_found_colleague_with_an_email_is_invited_through_google(
    pg_session, office, google
):
    chat = await Chat(pg_session, office, "omar").start()
    proposal = await propose(pg_session, office, chat, colleagues=["sara"])
    invitations = proposal["preview"]["invitations"]
    assert (
        "Google Calendar will email an invitation to Track 6 at track6@example.test" in invitations
    )
    # Before confirmation: nothing saved, nothing sent to Google.
    assert await events(pg_session, office.ids["omar"]) == [] and google == []
    done = await confirm(pg_session, chat)
    assert done.status == "succeeded", done.result
    [event] = await events(pg_session, office.ids["omar"])
    assert event.kind == "meeting" and event.guests == ["track6@example.test"]
    [insert] = [call for call in google if call["method"] == "POST"]
    assert insert["body"]["attendees"] == [{"email": "track6@example.test"}]
    assert insert["params"]["sendUpdates"] == "all"
    assert "Google Calendar sent an invitation to Track 6" in done.result["message"]


# --- 4. Honest when nobody can be invited -----------------------------------------------------


async def test_without_google_nobody_is_invited_and_the_proposal_says_so(pg_session, office):
    chat = await Chat(pg_session, office, "omar").start()
    proposal = await propose(pg_session, office, chat, colleagues=["sara"])
    invitations = " ".join(proposal["preview"]["invitations"])
    assert "Track 6 is not invited: Google Calendar is not connected" in invitations
    assert "no invitations are sent" in proposal["preview"]["consequence"]
    done = await confirm(pg_session, chat)
    [event] = await events(pg_session, office.ids["omar"])
    # Never stored as a guest either: a later Google sync would invite them unannounced.
    assert event.guests == [] and event.detail == "With Track 6"
    assert "invitation" not in done.result["message"].casefold()


async def test_a_colleague_without_an_email_is_named_but_not_invited(pg_session, office, google):
    chat = await Chat(pg_session, office, "omar").start()
    proposal = await propose(pg_session, office, chat, colleagues=["sara", "lina"])
    invitations = " ".join(proposal["preview"]["invitations"])
    assert "Google Calendar will email an invitation to Track 6" in invitations
    assert "Track 7 is not invited: no email on file" in invitations
    done = await confirm(pg_session, chat)
    [event] = await events(pg_session, office.ids["omar"])
    assert event.guests == ["track6@example.test"]
    assert "Track 7" not in done.result["message"].split("invitation")[-1]


async def test_a_google_failure_never_claims_an_invitation(pg_session, office, google):
    office.google_fails = True
    chat = await Chat(pg_session, office, "omar").start()
    await propose(pg_session, office, chat, colleagues=["sara"])
    done = await confirm(pg_session, chat)
    assert done.status == "partially_succeeded"
    assert "sent an invitation" not in done.result["message"]
    assert "No invitation has been sent" in done.result["message"]


async def test_an_ambiguous_colleague_is_never_booked(pg_session, office):
    ids = office.ids
    twin = f"twin-{ids['org'][:6]}"
    office.people[twin] = ("Track", "6")
    pg_session.add(OrganizationMembership(organization_id=ids["org"], user_id=twin))
    await pg_session.commit()
    chat = await Chat(pg_session, office, "omar").start()
    seen = {}

    async def book():
        seen["found"] = await workflows.find_meeting_colleagues(chat.ctx("lookup"), "Track 6")
        seen["proposal"] = await chat.propose(
            ActionKind.BOOK_CALENDAR_MEETING, meeting(office, ["sara"])
        )
        return "Two colleagues are called Track 6. Which one?"

    await chat.turn("Meeting with Mariam Ali and Track 6 at 12 PM IST", book)
    assert seen["found"]["clarification_required"] is True
    assert seen["proposal"]["available"] is False
    assert not await actions.list_actions(
        pg_session, **chat.scope, conversation_id=chat.conversation_id
    )


# --- 5. Rechecked at confirmation -----------------------------------------------------------


@pytest.mark.parametrize("change", ["colleague_left", "google_disconnected", "email_changed"])
async def test_who_is_invited_is_rechecked_at_confirmation(pg_session, office, google, change):
    ids = office.ids
    chat = await Chat(pg_session, office, "omar").start()
    await propose(pg_session, office, chat, colleagues=["sara"])
    if change == "colleague_left":
        for model in (OrganizationTeamMember, OrganizationMembership):
            await pg_session.exec(delete(model).where(model.user_id == ids["sara"]))
    elif change == "google_disconnected":
        await pg_session.exec(
            delete(CrmCalendarConnection).where(CrmCalendarConnection.user_id == ids["omar"])
        )
    else:
        office.emails[ids["sara"]] = "someone-else@example.test"
    await pg_session.commit()
    done = await confirm(pg_session, chat)
    assert done.status == "failed"
    assert await events(pg_session, ids["omar"]) == [] and google == []


async def test_losing_the_lead_before_confirmation_books_nothing(pg_session, office, google):
    ids = office.ids
    chat = await Chat(pg_session, office, "omar").start()
    await propose(pg_session, office, chat, colleagues=["sara"])
    from app.crm import assignment

    owner = await assignment.load_scope(pg_session, ids["org"], ids["owner"])
    await assignment.reassign(
        pg_session, owner, [office.mariam.id], ids["lina"], team_id=ids["south"]
    )
    await pg_session.commit()
    done = await confirm(pg_session, chat)
    assert done.status == "failed"
    assert await events(pg_session, ids["omar"]) == [] and google == []
