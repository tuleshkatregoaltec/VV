"""Deals end to end on a real (SQLite) session: open from a lead, move through the steps, close,
and the manager's oversight reflecting what agents actually did (Kian, 18 Nov: "create five new
deals on another agent's account and see that the manager's deal overview shows them")."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import app.postgres.models  # noqa: F401 - registers every table
from app.crm import assignment
from app.crm.assignment import AssignmentScope
from app.crm.inbound_models import (
    SOLD_OWNER_SOURCE,
    VITEVUE_LEASE_SOURCE,
    CrmInboundContact,
    CrmInboundEnquiry,
)
from app.organization.models import Organization
from app.postgres import get_db_session

ORG = "1"  # the mocked signed-in organization (tests/conftest.py)
BASE = "/api/v1/crm/deals"

SCOPES = {
    "omar": AssignmentScope(ORG, "omar", False, frozenset(), {}, frozenset({"north"})),
    "lina": AssignmentScope(ORG, "lina", False, frozenset(), {}, frozenset({"north"})),
    "noor": AssignmentScope(ORG, "noor", False, frozenset(), {}, frozenset({"south"})),
    "sara": AssignmentScope(
        ORG,
        "sara",
        False,
        frozenset({"north"}),
        {"north": frozenset({"omar", "lina", "sara"})},
        frozenset({"north"}),
    ),
    "admin": AssignmentScope(
        ORG,
        "admin",
        True,
        frozenset(),
        {"north": frozenset({"omar", "lina", "sara"}), "south": frozenset({"noor"})},
        frozenset(),
    ),
}


@pytest.fixture(autouse=True)
def no_postgres_actor_context(monkeypatch):
    async def skip(db):
        return None

    monkeypatch.setattr("app.crm.router.apply_actor_context", skip)


@pytest.fixture
def act_as(monkeypatch):
    """Which user the requests run as (their lead-assignment scope)."""
    who = {"user": "omar"}

    async def load_scope(db, organization_id, user_id):
        return SCOPES[who["user"]]

    monkeypatch.setattr(assignment, "load_scope", load_scope)

    def switch(user):
        who["user"] = user

    return switch


@pytest.fixture
async def db(client):
    from app.main import app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Organization(id=ORG, name="Agency"))
        await session.commit()

        async def override():
            yield session

        app.dependency_overrides[get_db_session] = override
        yield session
    await engine.dispose()


async def lead(db, *, holder, team, intent="buy", source="Property Finder", name="Client"):
    now = datetime(2026, 11, 18, tzinfo=timezone.utc)
    contact = CrmInboundContact(organization_id=ORG, full_name=name, created_at=now, updated_at=now)
    db.add(contact)
    await db.flush()
    enquiry = CrmInboundEnquiry(
        organization_id=ORG,
        contact_id=contact.id,
        created_by_user_id=holder or "system",
        assigned_user_id=holder,
        team_id=team,
        record_kind="opportunity",
        intent=intent,
        status="qualified",
        source=source,
        source_lead_id=f"{source}-{name}",
        enquiry_date=now,
        criteria={"locations": ["JVC"], "property_type": "Apartment"},
        created_at=now,
        updated_at=now,
    )
    db.add(enquiry)
    await db.commit()
    return enquiry.id


async def test_an_agents_five_new_deals_show_on_their_managers_oversight(client, db, act_as):
    act_as("omar")
    for i in range(5):
        lead_id = await lead(db, holder="omar", team="north", name=f"Buyer {i}")
        r = await client.post(BASE, json={"lead_id": lead_id, "value_aed": 1_000_000 + i * 100_000})
        assert r.status_code == 201, r.text

    act_as("sara")
    view = (await client.get(f"{BASE}/oversight")).json()
    assert view["scope"] == "teams"
    omar = next(a for a in view["agents"] if a["user_id"] == "omar")
    assert omar["open"] == 5
    assert omar["open_value_aed"] == 6_000_000 and omar["average_value_aed"] == 1_200_000
    assert omar["by_stage"] == {"Offer accepted": 5}
    assert omar["by_origin"] == {"portal": 5}
    assert omar["last_activity_at"] is not None
    # Team members with no deals still appear, at zero.
    lina = next(a for a in view["agents"] if a["user_id"] == "lina")
    assert lina["open"] == 0
    assert view["totals"]["open"] == 5


async def test_origin_breaks_down_where_deals_came_from(client, db, act_as):
    act_as("omar")
    sources = [
        ("Meta", None, "ads"),
        (SOLD_OWNER_SOURCE, None, "owner_outreach"),
        (VITEVUE_LEASE_SOURCE, None, "renewal"),
        ("Own contact", None, "own_contact"),
        ("Bayut", "PF-123", "listing"),  # a deal on a listing counts as the listing's
        ("WhatsApp", None, "inbound"),
    ]
    for i, (source, listing, origin) in enumerate(sources):
        lead_id = await lead(db, holder="omar", team="north", source=source, name=f"O{i}")
        deal = (await client.post(BASE, json={"lead_id": lead_id, "listing_id": listing})).json()
        assert deal["origin"] == origin, source
    by_origin = (await client.get(f"{BASE}/oversight")).json()["totals"]["by_origin"]
    assert by_origin == {
        "ads": 1,
        "owner_outreach": 1,
        "renewal": 1,
        "own_contact": 1,
        "listing": 1,
        "inbound": 1,
    }


async def test_agents_only_see_their_own_deals_and_admins_see_all(client, db, act_as):
    act_as("omar")
    mine = (
        await client.post(BASE, json={"lead_id": await lead(db, holder="omar", team="north")})
    ).json()

    act_as("noor")  # another team's agent
    assert (await client.get(f"{BASE}/{mine['id']}")).status_code == 404
    assert (await client.get(BASE)).json()["items"] == []
    own = (await client.get(f"{BASE}/oversight")).json()
    assert own["scope"] == "own" and [a["user_id"] for a in own["agents"]] == ["noor"]

    act_as("lina")  # same team, but not a manager: still only her own
    assert (await client.get(f"{BASE}/{mine['id']}")).status_code == 404

    act_as("admin")
    assert [d["id"] for d in (await client.get(BASE)).json()["items"]] == [mine["id"]]
    assert (await client.get(f"{BASE}/oversight")).json()["scope"] == "organization"


async def test_a_deal_cannot_be_opened_on_another_agents_lead(client, db, act_as):
    act_as("noor")
    response = await client.post(
        BASE, json={"lead_id": await lead(db, holder="omar", team="north")}
    )
    assert response.status_code == 404


async def test_a_lead_without_a_type_cannot_become_a_deal(client, db, act_as):
    act_as("omar")
    lead_id = await lead(db, holder="omar", team="north", intent="unknown")
    response = await client.post(BASE, json={"lead_id": lead_id})
    assert response.status_code == 422 and "type" in response.json()["detail"]


async def test_a_rent_deal_moves_through_its_steps_and_closes_as_won(client, db, act_as):
    act_as("omar")
    lead_id = await lead(db, holder="omar", team="north", intent="rent", name="Tenant")
    deal = (await client.post(BASE, json={"lead_id": lead_id, "value_aed": 120_000})).json()
    assert deal["deal_type"] == "rent" and deal["stage"] == "Contract"
    assert deal["next_stage"] == "Deposit and cheques" and deal["reference"] == f"D-{deal['id']}"

    for expected in (0, 1, 2):
        deal = (
            await client.post(
                f"{BASE}/{deal['id']}/move",
                json={"direction": "next", "expected_stage_index": expected},
            )
        ).json()
    assert deal["stage"] == "Keys" and deal["status"] == "open" and deal["next_stage"] is None
    deal = (
        await client.post(
            f"{BASE}/{deal['id']}/move", json={"direction": "next", "expected_stage_index": 3}
        )
    ).json()
    assert deal["status"] == "won" and deal["closed_at"]

    listed = (await client.get(BASE, params={"tab": "closed"})).json()
    assert [d["id"] for d in listed["items"]] == [deal["id"]]
    assert listed["counts"]["open"] == 0 and listed["counts"]["closed"] == 1
    history = (await client.get(f"{BASE}/{deal['id']}/history")).json()
    assert [h["kind"] for h in history] == ["created", "stage", "stage", "stage", "closed"]
    assert (
        history[1]["from_stage"] == "Contract" and history[1]["to_stage"] == "Deposit and cheques"
    )
    won = (await client.get(f"{BASE}/oversight")).json()["agents"][0]
    assert won["won_30d"] == 1 and won["open"] == 0


async def test_a_stale_move_and_moving_back_past_the_start_are_refused(client, db, act_as):
    act_as("omar")
    deal = (
        await client.post(BASE, json={"lead_id": await lead(db, holder="omar", team="north")})
    ).json()
    url = f"{BASE}/{deal['id']}/move"
    assert (
        await client.post(url, json={"direction": "back", "expected_stage_index": 0})
    ).status_code == 409
    await client.post(url, json={"direction": "next", "expected_stage_index": 0})
    stale = await client.post(url, json={"direction": "next", "expected_stage_index": 0})
    assert stale.status_code == 409 and "moved meanwhile" in stale.json()["detail"]
    back = await client.post(url, json={"direction": "back", "expected_stage_index": 1})
    assert back.json()["stage"] == "Offer accepted"


async def test_a_lost_deal_leaves_the_pipeline_and_can_be_reopened(client, db, act_as):
    act_as("omar")
    deal = (
        await client.post(BASE, json={"lead_id": await lead(db, holder="omar", team="north")})
    ).json()
    lost = (
        await client.post(
            f"{BASE}/{deal['id']}/close", json={"outcome": "lost", "reason": "Buyer withdrew"}
        )
    ).json()
    assert lost["status"] == "lost"
    assert (await client.get(BASE)).json()["items"] == []
    assert (await client.get(f"{BASE}/oversight")).json()["agents"][0]["lost_30d"] == 1
    blocked = await client.post(
        f"{BASE}/{deal['id']}/move", json={"direction": "next", "expected_stage_index": 0}
    )
    assert blocked.status_code == 409
    reopened = (await client.post(f"{BASE}/{deal['id']}/close", json={"outcome": "reopen"})).json()
    assert reopened["status"] == "open"


async def test_editing_a_deal_records_what_changed(client, db, act_as):
    act_as("omar")
    deal = (
        await client.post(BASE, json={"lead_id": await lead(db, holder="omar", team="north")})
    ).json()
    edited = (
        await client.patch(
            f"{BASE}/{deal['id']}",
            json={
                "value_aed": 2_500_000,
                "counterparty": "  Seller LLC ",
                "dld_transaction_id": "T-1",
            },
        )
    ).json()
    assert edited["value_aed"] == 2_500_000 and edited["counterparty"] == "Seller LLC"
    assert edited["dld_transaction_id"] == "T-1"
    history = (await client.get(f"{BASE}/{deal['id']}/history")).json()
    assert history[-1] == {
        **history[-1],
        "kind": "edited",
        "detail": {"fields": ["counterparty", "dld_transaction_id", "value_aed"]},
    }


async def test_deals_require_sign_in(client_no_auth):
    for method, path in [("GET", BASE), ("POST", BASE), ("GET", f"{BASE}/oversight")]:
        assert (await client_no_auth.request(method, path, json={})).status_code in {401, 403}
