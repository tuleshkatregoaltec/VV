"""Calendar reads by organization role, through the routes.

Owners/administrators read everyone in their organization, managers their supervised teams,
agents themselves; writes stay owner-only and listing never touches a colleague's Google account.
Real `assignment.load_scope` over seeded membership rows; names and lead visibility are stubbed.
"""

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import app.postgres.models  # noqa: F401 - registers every table
from app.core.dependencies import AuthContext, require_active_subscription
from app.crm import assignment, calendar_service, calendar_visibility
from app.crm.calendar_models import CrmCalendarConnection, CrmCalendarEvent
from app.organization.models import (
    Organization,
    OrganizationMembership,
    OrganizationTeam,
    OrganizationTeamMember,
)
from app.postgres import get_db_session

ME, ORG, OTHER_ORG = "test-user-id", "1", "2"
LIST = "/api/v1/crm/calendar/events?start=2026-11-01&end=2026-11-30"
NAMES = {ME: "Me", "a1": "Aisha K", "a2": "Bilal R", "x": "Xavier", "loner": "Lone Wolf"}


@pytest.fixture(autouse=True)
def no_postgres_actor_context(monkeypatch):
    """CRM routes stamp each transaction with set_config, which SQLite lacks."""

    async def skip(db):
        return None

    monkeypatch.setattr("app.crm.router.apply_actor_context", skip)


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    async def person(user_id):
        name = NAMES.get(user_id)
        return SimpleNamespace(first_name=name, last_name="", email="") if name else None

    async def no_leads(db, scope, ids):
        return set()

    monkeypatch.setattr(calendar_visibility, "get_user_by_id", person)
    monkeypatch.setattr(assignment, "visible_ids", no_leads)


def sign_in(user_id: str, org_id: str = ORG) -> None:
    from app.main import app

    user = SimpleNamespace(id=user_id, email=f"{user_id}@example.com", first_name="", last_name="")
    org = SimpleNamespace(id=org_id, subscription_status="active")
    membership = SimpleNamespace(role="member", organization_id=org_id)
    app.dependency_overrides[require_active_subscription] = lambda: AuthContext(
        user=user, organization=org, membership=membership, subscription=None
    )


@pytest.fixture
async def db(client):
    from app.main import app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(
            [Organization(id=ORG, name=ORG), Organization(id=OTHER_ORG, name=OTHER_ORG)]
        )
        for team in ("T1", "T2", "T3"):
            session.add(OrganizationTeam(id=team, organization_id=ORG, name=team))
        await session.commit()

        async def override():
            yield session

        app.dependency_overrides[get_db_session] = override
        sign_in(ME)
        yield session
    await engine.dispose()


async def seed(db, *, me_role="member", me_admin=False, me_teams=()):
    """Org 1: me, a1 (T1 agent), a2 (T2 agent), x (T3 agent), loner (no team). Org 2: z.

    One event each on 20 Nov; returns {owner: event id}.
    """
    now = datetime.now(timezone.utc)
    members = [(ME, ORG, me_role, me_admin)] + [
        (uid, ORG, "member", False) for uid in ("a1", "a2", "x", "loner")
    ]
    members.append(("z", OTHER_ORG, "owner", False))
    for uid, org, role, admin in members:
        db.add(
            OrganizationMembership(
                organization_id=org,
                user_id=uid,
                role=role,
                organization_admin=admin,
                created_at=now,
            )
        )
    teams = [("T1", "a1", "agent"), ("T2", "a2", "agent"), ("T3", "x", "agent"), *me_teams]
    for team, uid, role in teams:
        db.add(OrganizationTeamMember(team_id=team, organization_id=ORG, user_id=uid, role=role))
    ids = {}
    for uid, org, *_ in members:
        event = CrmCalendarEvent(
            organization_id=org,
            user_id=uid,
            title=f"{uid} event",
            detail=f"{uid} secret detail",
            event_date=date(2026, 11, 20),
            event_time="10:00",
            event_end_time="11:00",
            kind="call",
            updated_at=now,
        )
        db.add(event)
        await db.flush()
        ids[uid] = event.id
    await db.commit()
    return ids


def supervises(*teams):
    return tuple((team, ME, "supervisor") for team in teams)


def agent_of(*teams):
    return tuple((team, ME, "agent") for team in teams)


async def owners(client) -> set[str]:
    response = await client.get(LIST)
    assert response.status_code == 200, response.text
    return {item["owner_id"] for item in response.json()}


@pytest.mark.parametrize("role,admin", [("owner", False), ("member", True)])
async def test_owner_and_admin_see_whole_organization(client, db, role, admin):
    await seed(db, me_role=role, me_admin=admin)
    assert await owners(client) == {ME, "a1", "a2", "x", "loner"}


async def test_manager_sees_own_and_supervised_teams(client, db):
    await seed(db, me_teams=supervises("T1", "T2"))
    assert await owners(client) == {ME, "a1", "a2"}


async def test_manager_agent_elsewhere_gains_nothing(client, db):
    await seed(db, me_teams=supervises("T1") + agent_of("T3"))
    assert await owners(client) == {ME, "a1"}


async def test_agent_sees_only_own(client, db):
    await seed(db, me_teams=agent_of("T1"))
    assert await owners(client) == {ME}


async def test_query_params_cannot_widen_scope(client, db):
    await seed(db, me_teams=agent_of("T1"))
    response = await client.get(LIST + "&user_id=a1&team_id=T1&organization_id=2")
    assert {item["owner_id"] for item in response.json()} == {ME}


async def test_shared_events_are_labelled_and_read_only(client, db):
    await seed(db, me_teams=supervises("T1"))
    items = {item["owner_id"]: item for item in (await client.get(LIST)).json()}
    assert items[ME]["can_edit"] is True and items[ME]["agent"] == "You"
    assert items["a1"]["can_edit"] is False and items["a1"]["agent"] == "Aisha K"
    assert items["a1"]["detail"] == "a1 secret detail"


async def test_detail_out_of_scope_is_404(client, db):
    ids = await seed(db, me_teams=agent_of("T1"))
    for owner in ("a1", "z"):
        response = await client.get(f"/api/v1/crm/calendar/events/{ids[owner]}")
        assert response.status_code == 404, owner
        assert response.json()["detail"] == "Calendar event not found"


async def test_manager_reads_supervised_detail_read_only(client, db):
    ids = await seed(db, me_teams=supervises("T1"))
    response = await client.get(f"/api/v1/crm/calendar/events/{ids['a1']}")
    assert response.status_code == 200
    assert response.json()["can_edit"] is False


async def test_admin_never_reads_another_organizations_detail(client, db):
    ids = await seed(db, me_role="owner")
    response = await client.get(f"/api/v1/crm/calendar/events/{ids['z']}")
    assert response.status_code == 404


async def test_private_event_is_busy_block_for_others_full_for_owner(client, db):
    ids = await seed(db, me_teams=supervises("T1"))
    event = await db.get(CrmCalendarEvent, ids["a1"])
    event.visibility = "private"
    await db.commit()

    shared = {item["owner_id"]: item for item in (await client.get(LIST)).json()}["a1"]
    assert shared["title"] == "Busy"
    assert shared["detail"] == ""
    assert shared["redacted"] is True
    detail = (await client.get(f"/api/v1/crm/calendar/events/{ids['a1']}")).json()
    assert detail["title"] == "Busy"
    assert "secret" not in str(detail)

    sign_in("a1")
    mine = {item["owner_id"]: item for item in (await client.get(LIST)).json()}["a1"]
    assert mine["title"] == "a1 event"
    assert mine["redacted"] is False


async def test_writes_to_anothers_event_rejected(client, db):
    ids = await seed(db, me_role="owner")
    target = f"/api/v1/crm/calendar/events/{ids['a1']}"
    body = {"title": "Hijacked", "date": "2026-11-21", "time": "12:00", "kind": "call"}
    attempts = [
        client.put(target, json=body),
        client.patch(target, json={"date": "2026-11-21", "time": "12:00"}),
        client.post(f"{target}/done"),
        client.delete(target),
    ]
    for attempt in attempts:
        assert (await attempt).status_code == 404
    db.expire_all()
    event = await db.get(CrmCalendarEvent, ids["a1"])
    assert (event.title, event.event_date, event.done) == ("a1 event", date(2026, 11, 20), False)


async def test_listing_never_syncs_other_users(client, db, monkeypatch):
    await seed(db, me_teams=supervises("T1"))
    now = datetime.now(timezone.utc)
    for uid in (ME, "a1"):
        db.add(
            CrmCalendarConnection(
                organization_id=ORG,
                user_id=uid,
                google_email=f"{uid}@example.com",
                refresh_token_encrypted="unused",
                updated_at=now,
            )
        )
    await db.commit()
    touched: list[str] = []

    async def sync(db, *, user_id, organization_id):
        touched.append(user_id)

    async def token(connection):
        touched.append(connection.user_id)
        return "token"

    async def pending(db, *, connection, token):
        touched.append(connection.user_id)

    monkeypatch.setattr(calendar_service, "sync_google_events", sync)
    monkeypatch.setattr(calendar_service, "_access_token", token)
    monkeypatch.setattr(calendar_service, "_sync_pending", pending)

    assert await owners(client) == {ME, "a1"}
    assert set(touched) == {ME}


async def test_shared_list_says_whose_event_it_is(client, db):
    await seed(db, me_teams=supervises("T1"))
    items = {item["owner_id"]: item for item in (await client.get(LIST)).json()}
    assert items[ME]["owner_role"] == "Manager"
    assert (items["a1"]["agent"], items["a1"]["owner_role"]) == ("Aisha K", "Agent")


async def test_own_only_list_skips_role_lookup(client, db):
    await seed(db, me_teams=agent_of("T1"))
    items = (await client.get(LIST)).json()
    assert [item["owner_role"] for item in items] == [None]
