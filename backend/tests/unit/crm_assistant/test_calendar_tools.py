"""Calendar section: the assistant reads only the signed-in agent's calendar, and books an event
for a lead only after the agent confirms, through the existing calendar service."""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from assistant_helpers import ORG_A, ORG_B, USER, FakeSession, ctx, make_deps, make_lead
from fastapi import HTTPException

from app.crm.assistant import actions
from app.crm.assistant.models import CrmAssistantAction
from app.crm.assistant.tools import calendar as tools
from app.crm.inbound_models import CrmInboundActivity

TOMORROW = date.today() + timedelta(days=1)


@pytest.fixture
def session():
    return FakeSession()


@pytest.fixture
def calendar(monkeypatch):
    """The existing calendar service, recorded. create_event commits, like the real one."""
    calls = {"list": [], "create": []}

    async def list_events(db, *, user_id, organization_id, start, end):
        calls["list"].append((user_id, organization_id, start, end))
        return [
            {
                "id": 9,
                "date": start.isoformat(),
                "time": "10:00",
                "end_time": "11:00",
                "kind": "viewing",
                "title": "Viewing · Ashwin Vyas",
                "lead_id": 1,
                "location": "",
                "detail": "Bring the keys",
                "google_sync_status": "synced",
            }
        ]

    async def create_event(db, **kwargs):
        calls["create"].append(kwargs)
        await db.commit()
        return {"id": 10, **kwargs}

    monkeypatch.setattr(tools.calendar_service, "list_events", list_events)
    monkeypatch.setattr(actions.calendar_service, "create_event", create_event)
    return calls


async def test_list_events_reads_only_the_signed_in_agents_calendar(calendar):
    result = await tools.list_calendar_events(ctx(make_deps(ORG_A)), start_date=TOMORROW, days=500)

    [(user_id, organization_id, start, end)] = calendar["list"]
    assert (user_id, organization_id, start) == (USER, ORG_A, TOMORROW)
    assert end == TOMORROW + timedelta(days=59)  # at most 60 days
    [event] = result["events"]
    assert event["title"] == "Viewing · Ashwin Vyas"
    assert event["lead_link"] == "/crm/leads?lead=1"
    assert "detail" not in event


async def test_calendar_failure_is_reported_not_raised(monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("google down")

    monkeypatch.setattr(tools.calendar_service, "list_events", broken)
    result = await tools.list_calendar_events(ctx(make_deps()))
    assert result == {"error": "The calendar could not be loaded right now"}


async def test_propose_viewing_stores_a_pending_event_and_books_nothing(
    fake_leads, session, calendar
):
    fake_leads.add(make_lead(1, name="Ashwin Vyas"))
    result = await tools.propose_calendar_event(
        ctx(make_deps(db=session)), lead_id=1, kind="viewing", date=TOMORROW, time="15:00"
    )

    assert calendar["create"] == []
    [action] = session.of_type(CrmAssistantAction)
    assert action.action_type == "calendar_event"
    assert action.payload == {
        "kind": "viewing",
        "title": "Viewing · Ashwin Vyas",
        "date": TOMORROW.isoformat(),
        "time": "15:00",
        "end_time": "16:00",
        "detail": "",
    }
    assert result["after"]["event"] == "Viewing · Ashwin Vyas"
    assert result["after"]["when"].endswith("15:00–16:00")


async def test_propose_rejects_bad_times_and_past_dates(fake_leads, session):
    fake_leads.add(make_lead(1))
    deps = make_deps(db=session)
    assert await tools.propose_calendar_event(
        ctx(deps), lead_id=1, kind="call", date=TOMORROW, time="25:00"
    ) == {"error": "Use a 24-hour time like 15:00"}
    assert await tools.propose_calendar_event(
        ctx(deps), lead_id=1, kind="call", date=date.today() - timedelta(days=1), time="10:00"
    ) == {"error": "That date is in the past"}
    assert session.added == []


async def test_propose_for_other_org_lead_is_not_found(fake_leads, session):
    fake_leads.add(make_lead(5), organization_id=ORG_B)
    result = await tools.propose_calendar_event(
        ctx(make_deps(ORG_A, db=session)), lead_id=5, kind="viewing", date=TOMORROW, time="10:00"
    )
    assert result == {"error": "Lead not found"}
    assert session.added == []


def _stored_event(**overrides):
    payload = {
        "kind": "viewing",
        "title": "Viewing · Ashwin Vyas",
        "date": TOMORROW.isoformat(),
        "time": "15:00",
        "end_time": "16:00",
        "detail": "",
        **overrides,
    }
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return CrmAssistantAction(
        id="cal1",
        organization_id=ORG_A,
        user_id=USER,
        enquiry_id=1,
        action_type="calendar_event",
        payload=payload,
        summary="Book Viewing · Ashwin Vyas",
        status="pending",
        expires_at=now + timedelta(minutes=10),
        created_at=now,
    )


async def test_confirm_books_through_the_calendar_service(
    fake_leads, session, calendar, monkeypatch
):
    fake_leads.add(make_lead(1, name="Ashwin Vyas"))
    action = _stored_event()

    async def get_action(db, action_id, user_id, organization_id):
        same_scope = (user_id, organization_id) == (USER, ORG_A)
        return action if action_id == "cal1" and same_scope else None

    async def claim(db, action_id):
        if action.status != "pending":
            return False
        action.status = "confirmed"
        return True

    monkeypatch.setattr(actions.repository, "get_action", get_action)
    monkeypatch.setattr(actions.repository, "claim_action", claim)

    result = await actions.confirm_action(make_deps(db=session), action_id="cal1")

    [booked] = calendar["create"]
    assert (booked["user_id"], booked["organization_id"]) == (USER, ORG_A)
    assert booked["lead_id"] == 1 and booked["kind"] == "viewing"
    assert (booked["event_date"], booked["event_time"], booked["end_time"]) == (
        TOMORROW,
        "15:00",
        "16:00",
    )
    assert booked["title"] == "Viewing · Ashwin Vyas"
    [activity] = session.of_type(CrmInboundActivity)
    assert activity.body == "Book Viewing · Ashwin Vyas (via Assistant)"
    assert result.status == "confirmed" and session.commits == 1

    with pytest.raises(HTTPException) as error:
        await actions.confirm_action(make_deps(db=session), action_id="cal1")
    assert error.value.status_code == 409
    assert len(calendar["create"]) == 1


async def test_confirm_by_another_org_books_nothing(fake_leads, session, calendar, monkeypatch):
    fake_leads.add(make_lead(1))

    async def get_action(db, action_id, user_id, organization_id):
        return None  # scoped lookup finds nothing for another organisation

    monkeypatch.setattr(actions.repository, "get_action", get_action)
    with pytest.raises(HTTPException) as error:
        await actions.confirm_action(make_deps(ORG_B, db=session), action_id="cal1")
    assert error.value.status_code == 404
    assert calendar["create"] == []


def test_prompt_knows_today_and_supports_calendar():
    from app.crm.assistant.agent import _system_prompt

    prompt = _system_prompt(SimpleNamespace(deps=make_deps()))
    assert date.today().isoformat() in prompt
    assert "Calendar" in prompt.split("Currently you support")[1].split(".")[0]
