"""Whose calendar events a viewer may read, and what a colleague's event reveals."""

from types import SimpleNamespace

import pytest

from app.crm import calendar_visibility
from app.crm.assignment import AssignmentScope

ME = "me"


def _scope(*, admin=False, supervised=(), team_members=None, member_teams=()) -> AssignmentScope:
    return AssignmentScope(
        organization_id="1",
        user_id=ME,
        organization_admin=admin,
        supervised_team_ids=frozenset(supervised),
        team_members={t: frozenset(u) for t, u in (team_members or {}).items()},
        member_team_ids=frozenset(member_teams),
    )


@pytest.fixture
def memberships(monkeypatch):
    calls: list[str] = []

    async def list_memberships(db, org_id):
        calls.append(org_id)
        return [SimpleNamespace(user_id=u) for u in ("me", "a1", "loner")]

    monkeypatch.setattr(calendar_visibility.org_repository, "list_memberships", list_memberships)
    return calls


async def test_admin_reads_members_outside_teams(memberships):
    scope = _scope(admin=True, team_members={"t1": {"me", "a1"}})
    assert await calendar_visibility.readable_user_ids(None, scope) == {"me", "a1", "loner"}
    assert memberships == ["1"]


async def test_manager_reads_own_and_supervised_teams(memberships):
    scope = _scope(supervised={"t1", "t2"}, team_members={"t1": {"me", "a1"}, "t2": {"me", "a2"}})
    assert await calendar_visibility.readable_user_ids(None, scope) == {"me", "a1", "a2"}
    assert memberships == []


async def test_agent_team_of_a_manager_is_not_added(memberships):
    scope = _scope(supervised={"t1"}, team_members={"t1": {"me", "a1"}}, member_teams={"t1", "t3"})
    assert await calendar_visibility.readable_user_ids(None, scope) == {"me", "a1"}


async def test_agent_reads_only_self(memberships):
    scope = _scope(member_teams={"t1"})
    assert await calendar_visibility.readable_user_ids(None, scope) == {"me"}


# ── What a colleague's event reveals ──


def _event(visibility: str = "default"):
    from datetime import date, datetime, timezone

    from app.crm.calendar_models import CrmCalendarEvent

    return CrmCalendarEvent(
        id=5,
        organization_id="1",
        user_id="a1",
        title="Viewing · Sara",
        detail="gate code 4411",
        location="Marina",
        guests=["c@x.com"],
        meet=True,
        meet_link="https://meet/x",
        reminders=[30],
        lead_id=7,
        listing_id="L1",
        rescheduled_from=[{"date": "2026-11-18", "time": "09:00"}],
        visibility=visibility,
        kind="viewing",
        repeat="weekly",
        event_date=date(2026, 11, 20),
        event_time="10:00",
        event_end_time="11:00",
        updated_at=datetime.now(timezone.utc),
    )


def _for(viewer: str, event, *, lead_visible: bool = True) -> dict:
    return calendar_visibility.serialize_for_viewer(
        event, viewer_id=viewer, owner_name="Aisha K", lead_visible=lead_visible
    )


def test_owner_gets_full_event():
    from app.crm.calendar_service import serialize_event

    event = _event()
    result = _for("a1", event)
    assert result == serialize_event(event)
    assert result["can_edit"] is True
    assert result["redacted"] is False
    assert result["owner_id"] == "a1"
    assert result["agent"] == "You"


def test_shared_default_event_is_read_only_with_owner_name():
    result = _for(ME, _event("default"))
    assert result["title"] == "Viewing · Sara"
    assert result["agent"] == "Aisha K"
    assert result["can_edit"] is False
    assert result["redacted"] is False
    assert result["lead_id"] == 7


def test_hidden_lead_is_dropped_from_shared_event():
    result = _for(ME, _event("default"), lead_visible=False)
    assert result["lead_id"] is None
    assert result["record"] is None
    assert result["context"] is None
    # The title, note, listing, place and guests name the client the viewer may not see.
    assert result["title"] == "Viewing"
    assert result["detail"] == ""
    assert result["listing_id"] is None
    assert result["location"] == ""
    assert result["guests"] == []
    assert "Sara" not in str(result)


@pytest.mark.parametrize("visibility", ["private", "confidential"])
def test_redacted_block_keeps_only_busy_fields(visibility):
    import json

    from app.crm.calendar_service import serialize_event

    event = _event(visibility)
    full = serialize_event(event)
    result = _for(ME, event)
    assert result["title"] == "Busy"
    assert result["detail"] == ""
    assert result["location"] == ""
    assert result["guests"] == []
    assert result["meet"] is False
    assert result["meet_link"] is None
    assert result["reminders"] == []
    for key in ("lead_id", "listing_id", "record", "context", "outcome"):
        assert result[key] is None, key
    assert result["rescheduled_from"] == []
    assert result["kind"] == "follow_up"
    assert result["redacted"] is True
    assert result["can_edit"] is False
    assert result["agent"] == "Aisha K"
    for key in ("date", "time", "end_date", "end_time", "all_day", "show_as", "repeat", "owner_id"):
        assert result[key] == full[key], key
    dumped = json.dumps(result)
    for secret in ("gate code", "Sara", "Marina", "c@x.com", "meet/x", "L1"):
        assert secret not in dumped, secret


def test_owner_private_event_not_redacted():
    result = _for("a1", _event("private"))
    assert result["title"] == "Viewing · Sara"
    assert result["redacted"] is False


async def test_owner_names_looks_up_only_these_owners_and_survives_failures(monkeypatch):
    looked_up: list[str] = []

    async def get_user_by_id(user_id):
        looked_up.append(user_id)
        if user_id == "boom":
            raise RuntimeError("identity provider down")
        if user_id == "gone":
            return None
        return SimpleNamespace(first_name="Aisha", last_name="K", email="a1@example.com")

    monkeypatch.setattr(calendar_visibility, "get_user_by_id", get_user_by_id)

    names = await calendar_visibility.owner_names(None, "1", {"a1", "gone", "boom"})

    assert names == {"a1": "Aisha K", "gone": "Former member", "boom": "Former member"}
    assert sorted(looked_up) == ["a1", "boom", "gone"]


# ── Whose event it is: the owner's role label ──


async def test_owner_roles_label_each_owner_by_their_highest_role(monkeypatch):
    async def list_memberships(db, org_id):
        return [
            SimpleNamespace(user_id="boss", role="owner", organization_admin=False),
            SimpleNamespace(user_id="ops", role="member", organization_admin=True),
            SimpleNamespace(user_id="lead", role="member", organization_admin=False),
            SimpleNamespace(user_id="a1", role="member", organization_admin=False),
            SimpleNamespace(user_id="solo", role="member", organization_admin=False),
        ]

    async def list_team_memberships(db, org_id):
        return [
            SimpleNamespace(user_id="lead", role="supervisor"),
            SimpleNamespace(user_id="lead", role="agent"),
            SimpleNamespace(user_id="a1", role="agent"),
            SimpleNamespace(user_id="ops", role="supervisor"),
        ]

    monkeypatch.setattr(calendar_visibility.org_repository, "list_memberships", list_memberships)
    monkeypatch.setattr(
        calendar_visibility.org_teams, "list_team_memberships", list_team_memberships
    )

    roles = await calendar_visibility.owner_roles(
        None, "1", {"boss", "ops", "lead", "a1", "solo", "gone"}
    )

    assert roles == {
        "boss": "Owner",
        "ops": "Admin",
        "lead": "Manager",
        "a1": "Agent",
        "solo": "Agent",
        "gone": "Former member",
    }


def test_every_event_carries_its_owner_role():
    from app.crm.calendar_service import serialize_event

    event = _event()
    assert serialize_event(event)["owner_role"] is None
    for viewer in ("a1", ME):
        result = calendar_visibility.serialize_for_viewer(
            event, viewer_id=viewer, owner_name="Aisha K", lead_visible=True, owner_role="Agent"
        )
        assert result["owner_role"] == "Agent", viewer
