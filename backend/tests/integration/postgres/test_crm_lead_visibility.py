"""Who sees which lead, the shared team pool and timed rotation, against the migrated schema.

Agreed in the meeting of 13 Nov 2026: a manager sees only their own team's leads (28:20, 28:40);
leads released to a team go to whoever makes first contact and disappear for the others
(29:29-31:52); a lead given to one agent moves on when they do not act in time (32:17); the
Assistant must not expose another organisation's, manager's or agent's data (42:28).
"""

import asyncio
import importlib.util
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.crm.assistant.scope import load_lead
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from test_crm_lead_assignment import CSV, _agency, _events, _import, _imported, _org, _team

from app.crm import assignment, inbound, rotation, routing
from app.crm.inbound_models import (
    CrmInboundEnquiry,
    InboundEnquiryCreate,
    InboundEnquiryUpdate,
)
from app.crm.inbound_policy import _utcnow
from app.crm.routing_models import (
    CrmLeadRotation,
    ImportAssignmentPolicy,
    LeadAssignmentRequest,
    PoolReleaseRequest,
    RoutingCondition,
    RoutingRuleWrite,
)
from app.organization.models import OrganizationTeamMember


async def _lead(db, ids, creator, name, **fields):
    response = await inbound.create_inbound_enquiry(
        db,
        payload=InboundEnquiryCreate(full_name=name, intent="buy", record_kind="opportunity"),
        user_id=ids[creator],
        organization_id=ids["org"],
    )
    if fields:
        row = await db.get(CrmInboundEnquiry, response.id)
        for key, value in fields.items():
            setattr(row, key, value)
        db.add(row)
        await db.commit()
    return response.id


async def _world(db):
    """The agency of test_crm_lead_assignment plus Maya, an agent in both North and South, and
    one lead of each kind. Another organization holds a lead too."""
    ids = await _agency(db)
    maya = f"maya-{uuid4().hex[:6]}"
    ids["maya"] = maya
    from app.organization.models import OrganizationMembership

    db.add(OrganizationMembership(organization_id=ids["org"], user_id=maya, role="member"))
    await db.flush()
    for team in ("north", "south"):
        db.add(
            OrganizationTeamMember(
                team_id=ids[team], organization_id=ids["org"], user_id=maya, role="agent"
            )
        )
    await db.commit()
    now = _utcnow()
    leads = {
        "north_held": await _lead(db, ids, "omar", "North held"),
        "south_held": await _lead(db, ids, "lina", "South held"),
        "adam_own": await _lead(db, ids, "adam", "Adam own"),
        "legacy": await _lead(db, ids, "omar", "Legacy", team_id=None),
        "north_waiting": await _lead(
            db, ids, "nadia", "North waiting", assigned_user_id=None, team_id=ids["north"]
        ),
        "north_pool": await _lead(
            db,
            ids,
            "nadia",
            "North pool",
            assigned_user_id=None,
            team_id=ids["north"],
            pool_released_at=now,
        ),
    }
    other = await _org(db, stranger="owner")
    leads["other_org"] = await _lead(db, other, "stranger", "Other agency")
    return ids, leads


EXPECTED = {
    # user: the leads they see (the permission table in app/crm/assignment.py)
    "owner": {"north_held", "south_held", "adam_own", "legacy", "north_waiting", "north_pool"},
    "nadia": {"north_held", "north_waiting", "north_pool"},
    "karim": {"south_held"},
    "omar": {"north_held", "legacy", "north_pool"},
    "sara": {"north_pool"},
    "lina": {"south_held"},
    "maya": {"north_pool"},
    "adam": {"adam_own"},
}


async def test_every_lead_path_shows_each_person_only_the_leads_they_may_see(pg_session):
    ids, leads = await _world(pg_session)
    names = {lead_id: name for name, lead_id in leads.items()}

    for person, expected in EXPECTED.items():
        listed = await inbound.list_inbound_enquiries(
            pg_session,
            organization_id=ids["org"],
            user_id=ids[person],
            intent_group=None,
            workspace=None,
            status=None,
            search=None,
            limit=100,
            offset=0,
        )
        assert {names[e.id] for e in listed.enquiries} == expected, person
        assert listed.total == len(expected), person  # counts leak nothing either
        # Search runs over the same visible set.
        found = await inbound.list_inbound_enquiries(
            pg_session,
            organization_id=ids["org"],
            user_id=ids[person],
            intent_group=None,
            workspace=None,
            status=None,
            search="South held",
            limit=100,
            offset=0,
        )
        assert bool(found.enquiries) == ("south_held" in expected), person

        scope = await assignment.load_scope(pg_session, ids["org"], ids[person])
        sql_seen = await assignment.visible_ids(pg_session, scope, leads.values())
        for name, lead_id in leads.items():
            allowed = name in expected
            # The SQL condition and its Python twin agree on every lead.
            assert (lead_id in sql_seen) == allowed, (person, name)
            row = await pg_session.get(CrmInboundEnquiry, lead_id)
            assert scope.can_view(row) == allowed, (person, name)
            # A direct id answers 404 like a missing lead, on every read and write path.
            calls = [
                lambda lead_id=lead_id: inbound.get_inbound_enquiry(
                    pg_session, lead_id, ids["org"], user_id=ids[person]
                ),
                lambda lead_id=lead_id: assignment.assignment_history(
                    pg_session, ids["org"], ids[person], lead_id
                ),
                lambda lead_id=lead_id: load_lead(
                    pg_session, ids["org"], lead_id, user_id=ids[person]
                ),
                lambda lead_id=lead_id: inbound.add_inbound_note(
                    pg_session,
                    enquiry_id=lead_id,
                    organization_id=ids["org"],
                    user_id=ids[person],
                    body="hi",
                ),
                lambda lead_id=lead_id: inbound.update_inbound_enquiry(
                    pg_session,
                    enquiry_id=lead_id,
                    organization_id=ids["org"],
                    user_id=ids[person],
                    payload=InboundEnquiryUpdate(notes="edited"),
                ),
            ]
            if not allowed:
                for call in calls:
                    with pytest.raises(HTTPException) as hidden:
                        await call()
                    assert hidden.value.status_code == 404, (person, name)
                    await pg_session.rollback()


async def test_agents_cannot_work_a_pooled_lead_until_they_take_it(pg_session):
    ids, leads = await _world(pg_session)
    for change in (
        lambda: inbound.add_inbound_note(
            pg_session,
            enquiry_id=leads["north_pool"],
            organization_id=ids["org"],
            user_id=ids["sara"],
            body="mine?",
        ),
        lambda: inbound.update_inbound_enquiry(
            pg_session,
            enquiry_id=leads["north_pool"],
            organization_id=ids["org"],
            user_id=ids["sara"],
            payload=InboundEnquiryUpdate(status="qualified"),
        ),
    ):
        with pytest.raises(HTTPException) as refused:
            await change()
        assert refused.value.status_code == 409
        assert refused.value.detail["code"] == "LEAD_IN_POOL"
        await pg_session.rollback()


async def test_first_logged_contact_claims_a_pooled_lead_and_hides_it_from_the_others(pg_session):
    ids, _ = await _world(pg_session)
    lead_id = await _lead(pg_session, ids, "nadia", "Released", assigned_user_id=None)
    revision = (await pg_session.get(CrmInboundEnquiry, lead_id)).assignment_revision
    # South's manager cannot release into North; North's manager can.
    with pytest.raises(HTTPException) as foreign:
        await assignment.release_to_pool(
            pg_session,
            ids["org"],
            ids["karim"],
            PoolReleaseRequest(
                enquiry_ids=[lead_id], team_id=ids["north"], expected_revisions={lead_id: revision}
            ),
        )
    assert foreign.value.status_code == 403
    await pg_session.rollback()
    released = await assignment.release_to_pool(
        pg_session,
        ids["org"],
        ids["nadia"],
        PoolReleaseRequest(
            enquiry_ids=[lead_id], team_id=ids["north"], expected_revisions={lead_id: revision}
        ),
    )
    assert released.results[0].shared and released.results[0].assigned_user_id is None

    # Opening the lead does not take it: only logged contact does.
    await inbound.get_inbound_enquiry(pg_session, lead_id, ids["org"], user_id=ids["omar"])
    assert (await pg_session.get(CrmInboundEnquiry, lead_id)).assigned_user_id is None

    taken = await inbound.add_inbound_activity(
        pg_session,
        enquiry_id=lead_id,
        organization_id=ids["org"],
        user_id=ids["omar"],
        activity_type="call",
        body=None,
    )
    assert (taken.assigned_user_id, taken.team_id, taken.shared) == (
        ids["omar"],
        ids["north"],
        False,
    )
    for other in ("sara", "maya"):
        with pytest.raises(HTTPException) as gone:
            await inbound.get_inbound_enquiry(pg_session, lead_id, ids["org"], user_id=ids[other])
        assert gone.value.status_code == 404
    with pytest.raises(HTTPException) as late:
        await inbound.add_inbound_activity(
            pg_session,
            enquiry_id=lead_id,
            organization_id=ids["org"],
            user_id=ids["sara"],
            activity_type="call",
            body=None,
        )
    assert (late.value.status_code, late.value.detail["code"]) == (409, "LEAD_CLAIMED")
    await pg_session.rollback()
    claims = [e for e in await _events(pg_session, lead_id) if e.reason == "claimed"]
    assert [(e.actor_user_id, e.assigned_user_id, e.team_id) for e in claims] == [
        (ids["omar"], ids["omar"], ids["north"])
    ]


async def test_two_agents_claiming_at_once_cannot_both_win(postgres_test_url):
    engine = create_async_engine(postgres_test_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as setup:
            ids, _ = await _world(setup)
            lead_id = await _lead(
                setup,
                ids,
                "nadia",
                "Race",
                assigned_user_id=None,
                team_id=ids["north"],
                pool_released_at=_utcnow(),
            )

        async def claim(person):
            async with AsyncSession(engine, expire_on_commit=False) as db:
                try:
                    await inbound.add_inbound_activity(
                        db,
                        enquiry_id=lead_id,
                        organization_id=ids["org"],
                        user_id=ids[person],
                        activity_type="whatsapp",
                        body=None,
                    )
                    return "won"
                except HTTPException as error:
                    return error.status_code

        results = await asyncio.gather(claim("omar"), claim("sara"), claim("maya"))
        assert sorted(results, key=str) == [409, 409, "won"]
        async with AsyncSession(engine) as check:
            stored = await check.get(CrmInboundEnquiry, lead_id)
            claims = [e for e in await _events(check, lead_id) if e.reason == "claimed"]
        assert stored.pool_released_at is None and stored.assigned_user_id is not None
        assert [e.assigned_user_id for e in claims] == [stored.assigned_user_id]
    finally:
        await engine.dispose()


async def test_a_multi_team_agent_is_given_to_one_explicit_team(pg_session):
    ids, _ = await _world(pg_session)
    lead_id = await _lead(pg_session, ids, "owner", "Owner lead")
    revision = (await pg_session.get(CrmInboundEnquiry, lead_id)).assignment_revision

    def give(team=None):
        return LeadAssignmentRequest(
            enquiry_ids=[lead_id],
            assignee_user_id=ids["maya"],
            team_id=team,
            expected_revisions={lead_id: revision},
        )

    # The owner manages both of Maya's teams: nothing is guessed.
    with pytest.raises(HTTPException) as ambiguous:
        await assignment.assign_leads(pg_session, ids["org"], ids["owner"], give())
    assert ambiguous.value.detail["code"] == "TEAM_REQUIRED"
    await pg_session.rollback()
    done = await assignment.assign_leads(pg_session, ids["org"], ids["owner"], give(ids["south"]))
    assert done.results[0].team_id == ids["south"]
    # So South's manager sees it and North's does not, though Maya is in both.
    for manager, sees in (("karim", True), ("nadia", False)):
        scope = await assignment.load_scope(pg_session, ids["org"], ids[manager])
        assert scope.can_view(await pg_session.get(CrmInboundEnquiry, lead_id)) is sees


async def test_imports_give_unclaimed_leads_an_owning_team(pg_session):
    ids = await _agency(pg_session)
    shared = await _import(
        pg_session, ids, "nadia", ImportAssignmentPolicy(mode="team"), name="To the team"
    )
    assert (shared.summary.assignment.shared, shared.summary.assignment.team_id) == (
        3,
        ids["north"],
    )
    rows = (await _imported(pg_session, shared.id)).values()
    assert {(r.assigned_user_id, r.team_id, r.pool_released_at is not None) for r in rows} == {
        (None, ids["north"], True)
    }
    assert {e.reason for e in await _events(pg_session, org=ids["org"])} == {"released"}

    waiting = await _import(
        pg_session,
        ids,
        "karim",
        ImportAssignmentPolicy(mode="unassigned"),
        data=CSV.replace("+97150111", "+97150222"),
        name="For later",
    )
    rows = (await _imported(pg_session, waiting.id)).values()
    assert {(r.assigned_user_id, r.team_id, r.pool_released_at) for r in rows} == {
        (None, ids["south"], None)
    }
    # A manager of two teams must say which team owns the leads.
    await _team(pg_session, ids, "East", nadia="supervisor", sara="agent")
    with pytest.raises(HTTPException) as unclear:
        await _import(
            pg_session,
            ids,
            "nadia",
            ImportAssignmentPolicy(mode="team"),
            data=CSV.replace("+97150111", "+97150333"),
        )
    assert unclear.value.detail["code"] == "TEAM_REQUIRED"
    await pg_session.rollback()
    with pytest.raises(HTTPException) as foreign:
        await _import(
            pg_session,
            ids,
            "nadia",
            ImportAssignmentPolicy(mode="team", team_id=ids["south"]),
            data=CSV.replace("+97150111", "+97150444"),
        )
    assert foreign.value.status_code == 403


async def _rotating_rule(db, ids, minutes=10):
    scope = await assignment.load_scope(db, ids["org"], ids["nadia"])
    return await routing.create_rule(
        db,
        scope,
        RoutingRuleWrite(
            name="JVC rotation",
            team_id=ids["north"],
            destination_user_id=ids["omar"],
            rotation_user_ids=[ids["sara"]],
            rotation_minutes=minutes,
            conditions=[RoutingCondition(field="area", values=["JVC"])],
        ),
    )


async def _jvc_lead(db, ids):
    result = await _import(db, ids, "nadia", ImportAssignmentPolicy(mode="rules"), name="Rot")
    return (await _imported(db, result.id))["Jade Buyer"].id


async def test_an_unanswered_lead_moves_on_then_lands_in_the_team_pool(pg_session):
    ids = await _agency(pg_session)
    rule = await _rotating_rule(pg_session, ids)
    lead_id = await _jvc_lead(pg_session, ids)
    start = (await pg_session.get(CrmInboundEnquiry, lead_id)).assigned_at

    # Not due yet: nothing moves, however often the scheduler runs.
    assert await rotation.advance_due(pg_session, now=start + timedelta(minutes=9)) == {}
    moved = await rotation.advance_due(pg_session, now=start + timedelta(minutes=11))
    assert moved == {"rotated": 1}
    pg_session.expire_all()
    lead = await pg_session.get(CrmInboundEnquiry, lead_id)
    assert (lead.assigned_user_id, lead.team_id) == (ids["sara"], ids["north"])
    # A rerun at the same moment (a retry, a second worker) changes nothing.
    assert await rotation.advance_due(pg_session, now=start + timedelta(minutes=11)) == {}

    done = await rotation.advance_due(pg_session, now=start + timedelta(minutes=22))
    assert done == {"released": 1}
    pg_session.expire_all()
    lead = await pg_session.get(CrmInboundEnquiry, lead_id)
    assert (lead.assigned_user_id, lead.team_id) == (None, ids["north"])
    assert lead.pool_released_at is not None
    history = [
        (e.reason, e.actor_user_id, e.assigned_user_id, e.rule_id)
        for e in await _events(pg_session, lead_id)
    ]
    assert history == [
        ("import_rule", ids["nadia"], ids["omar"], rule.id),
        ("rotation", "system", ids["sara"], rule.id),
        ("released", "system", None, rule.id),
    ]
    stored = (
        await pg_session.exec(select(CrmLeadRotation).where(CrmLeadRotation.enquiry_id == lead_id))
    ).one()
    assert (stored.status, stored.stop_reason) == ("finished", "released_to_pool")


@pytest.mark.parametrize("action", ["contact", "stage"])
async def test_the_rotation_stops_when_the_holder_acts(pg_session, action):
    ids = await _agency(pg_session)
    await _rotating_rule(pg_session, ids)
    lead_id = await _jvc_lead(pg_session, ids)
    start = (await pg_session.get(CrmInboundEnquiry, lead_id)).assigned_at
    if action == "contact":
        await inbound.add_inbound_activity(
            pg_session,
            enquiry_id=lead_id,
            organization_id=ids["org"],
            user_id=ids["omar"],
            activity_type="call",
            body=None,
        )
    else:
        await inbound.update_inbound_enquiry(
            pg_session,
            enquiry_id=lead_id,
            organization_id=ids["org"],
            user_id=ids["omar"],
            payload=InboundEnquiryUpdate(status="contacted"),
        )
    assert await rotation.advance_due(pg_session, now=start + timedelta(minutes=30)) == {}
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, lead_id)).assigned_user_id == ids["omar"]


async def test_reassignment_restarts_the_timeout_and_skips_tried_agents(pg_session, monkeypatch):
    ids = await _agency(pg_session)
    await _rotating_rule(pg_session, ids)
    first = await _jvc_lead(pg_session, ids)
    start = (await pg_session.get(CrmInboundEnquiry, first)).assigned_at
    revision = (await pg_session.get(CrmInboundEnquiry, first)).assignment_revision
    reassigned_at = start + timedelta(minutes=8)
    monkeypatch.setattr(assignment, "_utcnow", lambda: reassigned_at)
    await assignment.assign_leads(
        pg_session,
        ids["org"],
        ids["nadia"],
        LeadAssignmentRequest(
            enquiry_ids=[first], assignee_user_id=ids["sara"], expected_revisions={first: revision}
        ),
    )
    # A worker that selected the old timer must re-read it under the lead lock.
    assert await rotation.advance_due(pg_session, now=start + timedelta(minutes=11)) == {}
    assert (
        await rotation._advance_one(pg_session, first, start + timedelta(minutes=11)) == "not_due"
    )
    await pg_session.commit()
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, first)).assigned_user_id == ids["sara"]
    # Reassignment is not contact. Both people have now held it, so it returns to North's pool.
    assert await rotation.advance_due(pg_session, now=reassigned_at + timedelta(minutes=11)) == {
        "released": 1
    }
    pg_session.expire_all()
    pooled = await pg_session.get(CrmInboundEnquiry, first)
    assert pooled.assigned_user_id is None and pooled.team_id == ids["north"]

    # Sara leaves North before her turn: she is skipped, never assigned; the lead goes to the pool.
    second = (
        await _imported(
            pg_session,
            (
                await _import(
                    pg_session,
                    ids,
                    "nadia",
                    ImportAssignmentPolicy(mode="rules"),
                    data=CSV.replace("+97150111", "+97150555"),
                    name="Second",
                )
            ).id,
        )
    )["Jade Buyer"].id
    await pg_session.exec(
        sa.delete(OrganizationTeamMember).where(
            OrganizationTeamMember.team_id == ids["north"],
            OrganizationTeamMember.user_id == ids["sara"],
        )
    )
    await pg_session.commit()
    start = (await pg_session.get(CrmInboundEnquiry, second)).assigned_at
    assert await rotation.advance_due(pg_session, now=start + timedelta(minutes=11)) == {
        "released": 1
    }
    assert ids["sara"] not in {e.assigned_user_id for e in await _events(pg_session, second)}


async def test_concurrent_schedulers_move_each_lead_once(postgres_test_url):
    engine = create_async_engine(postgres_test_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as setup:
            ids = await _agency(setup)
            await _rotating_rule(setup, ids)
            lead_id = await _jvc_lead(setup, ids)
            due = (await setup.get(CrmInboundEnquiry, lead_id)).assigned_at + timedelta(minutes=11)

        async def run():
            async with AsyncSession(engine, expire_on_commit=False) as db:
                return await rotation.advance_due(db, now=due)

        outcomes = await asyncio.gather(*(run() for _ in range(4)))
        assert sum(o.get("rotated", 0) for o in outcomes) == 1
        async with AsyncSession(engine) as check:
            moves = [e for e in await _events(check, lead_id) if e.reason == "rotation"]
        assert len(moves) == 1
    finally:
        await engine.dispose()


async def test_a_language_rule_routes_on_the_imported_language_column(pg_session):
    ids = await _agency(pg_session)
    scope = await assignment.load_scope(pg_session, ids["org"], ids["nadia"])
    await routing.create_rule(
        pg_session,
        scope,
        RoutingRuleWrite(
            name="Hindi speakers",
            team_id=ids["north"],
            destination_user_id=ids["sara"],
            conditions=[RoutingCondition(field="language", values=["Hindi"])],
        ),
    )
    data = (
        "Name,Phone,Intent,Area,Language\n"
        "Ravi Buyer,+971501119001,Buyer,JVC,hindi\n"
        "Omid Buyer,+971501119002,Buyer,JVC,Farsi\n"
        "Nora Buyer,+971501119003,Buyer,JVC,\n"
    )
    result = await _import(
        pg_session, ids, "nadia", ImportAssignmentPolicy(mode="rules"), data=data, name="Lang"
    )
    leads = await _imported(pg_session, result.id)
    assert {name: lead.assigned_user_id for name, lead in leads.items()} == {
        "Ravi Buyer": ids["sara"],
        "Omid Buyer": None,
        "Nora Buyer": None,
    }


def _migration():
    path = (
        Path(__file__).parents[3]
        / "migrations/versions/e8b4d2f6a1c3_add_lead_team_pool_rotation.py"
    )
    spec = importlib.util.spec_from_file_location("lead_team_pool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_backfill_gives_a_team_only_where_ownership_is_certain(pg_session):
    """Existing leads: a team only when the assignee is in exactly one team; nothing shared."""
    ids, leads = await _world(pg_session)
    connection = await pg_session.connection()

    def verify(sync):
        module = _migration()
        module.op = Operations(MigrationContext.configure(sync))
        module.downgrade()
        module.upgrade()
        rows = dict(
            sync.execute(
                sa.text("SELECT id, team_id FROM crm_inbound_enquiries WHERE id = ANY(:ids)"),
                {"ids": list(leads.values())},
            ).all()
        )
        shared = sync.execute(
            sa.text("SELECT count(*) FROM crm_inbound_enquiries WHERE pool_released_at IS NOT NULL")
        ).scalar()
        return rows, shared

    try:
        rows, shared = await connection.run_sync(verify)
    finally:
        await pg_session.rollback()  # PostgreSQL restores the test-only DDL too.
    assert shared == 0
    assert rows[leads["north_held"]] == ids["north"]  # Omar: North only
    assert rows[leads["south_held"]] == ids["south"]  # Lina: South only
    assert rows[leads["legacy"]] == ids["north"]  # assigned to Omar: certain
    assert rows[leads["adam_own"]] is None  # Adam: no team
    assert rows[leads["north_waiting"]] is None  # unassigned: not guessed
    assert rows[leads["other_org"]] is None


async def test_a_team_that_owns_leads_cannot_be_deleted(pg_session):
    from app.organization import teams

    ids, _ = await _world(pg_session)
    with pytest.raises(HTTPException) as blocked:
        await teams.delete_team(pg_session, ids["org"], ids["south"])
    assert blocked.value.status_code == 409


async def test_the_claim_statement_alone_lets_only_one_of_two_stale_readers_win(postgres_test_url):
    """Even without the request's row lock, the conditional UPDATE decides a claim: a second
    claimer holding an out-of-date copy of the lead must not take it from the first."""
    engine = create_async_engine(postgres_test_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as setup:
            ids, _ = await _world(setup)
            lead_id = await _lead(
                setup,
                ids,
                "nadia",
                "Stale race",
                assigned_user_id=None,
                team_id=ids["north"],
                pool_released_at=_utcnow(),
            )
        async with (
            AsyncSession(engine, expire_on_commit=False) as first,
            AsyncSession(engine, expire_on_commit=False) as second,
        ):
            scopes, copies = [], []
            for db, person in ((first, "omar"), (second, "sara")):
                scopes.append(await assignment.load_scope(db, ids["org"], ids[person]))
                copies.append(await db.get(CrmInboundEnquiry, lead_id))  # both see it pooled
            assert await assignment.claim(first, scopes[0], copies[0], now=_utcnow())
            racing = asyncio.create_task(
                assignment.claim(second, scopes[1], copies[1], now=_utcnow())
            )
            await asyncio.sleep(0.3)
            assert not racing.done()  # waits on the first claim's row
            await first.commit()
            assert await racing is False
            await second.rollback()
        async with AsyncSession(engine) as check:
            assert (await check.get(CrmInboundEnquiry, lead_id)).assigned_user_id == ids["omar"]
    finally:
        await engine.dispose()


async def test_a_manager_sees_only_their_teams_recorded_workload(pg_session):
    from app.crm import oversight

    ids, leads = await _world(pg_session)
    closed = await _lead(pg_session, ids, "omar", "Won already", status="won")
    overdue = await _lead(pg_session, ids, "sara", "Overdue")
    row = await pg_session.get(CrmInboundEnquiry, overdue)
    row.first_response_due_at = _utcnow() - timedelta(hours=1)
    pg_session.add(row)
    await pg_session.commit()

    view = await oversight.team_workload(pg_session, ids["org"], ids["nadia"])
    assert [t.name for t in view.teams] == ["North"]  # never South
    north = view.teams[0]
    assert (north.unassigned, north.shared) == (2, 1)  # North waiting + North pool
    people = {m.user_id: m for m in north.members}
    assert set(people) == {ids["nadia"], ids["omar"], ids["sara"], ids["maya"]}
    assert people[ids["omar"]].open_leads == 1  # the won lead is not open work
    assert people[ids["sara"]].overdue_first_contact == 1
    assert closed not in leads.values()
    with pytest.raises(HTTPException) as agent:
        await oversight.team_workload(pg_session, ids["org"], ids["omar"])
    assert agent.value.status_code == 403


# ---- Agents' languages: a "speakers only" rule routes a lead to people who speak its language --


async def _speaks(db, ids, manager, person, *languages):
    from app.crm import agent_languages
    from app.crm.routing_models import AgentLanguagesWrite

    scope = await assignment.load_scope(db, ids["org"], ids[manager])
    return await agent_languages.set_languages(
        db, scope, ids[person], AgentLanguagesWrite(languages=list(languages))
    )


async def _speakers_rule(db, ids, minutes=10):
    scope = await assignment.load_scope(db, ids["org"], ids["nadia"])
    return await routing.create_rule(
        db,
        scope,
        RoutingRuleWrite(
            name="JVC, in the client's language",
            team_id=ids["north"],
            destination_user_id=ids["omar"],
            rotation_user_ids=[ids["sara"]],
            rotation_minutes=minutes,
            speakers_only=True,
            conditions=[RoutingCondition(field="area", values=["JVC"])],
        ),
    )


LANG_CSV = (
    "Name,Phone,Intent,Area,Language\n"
    "Ravi Buyer,+971501119001,Buyer,JVC,Hindi\n"
    "Omid Buyer,+971501119002,Buyer,JVC,Farsi\n"
    "Nora Buyer,+971501119003,Buyer,JVC,\n"
)


async def test_only_managers_record_languages_and_only_for_their_own_people(pg_session):
    from app.crm.routing_models import AgentLanguagesWrite

    ids = await _agency(pg_session)
    # Spacing and case are normalized; duplicates collapse; nothing is inferred from the names.
    saved = await _speaks(pg_session, ids, "nadia", "omar", " hindi ", "Hindi", "English")
    assert saved.languages == ["hindi", "English"]
    saved = await _speaks(pg_session, ids, "owner", "omar", "Arabic")
    assert saved.languages == ["Arabic"]  # the last write wins, as one row

    with pytest.raises(HTTPException) as other_team:
        await _speaks(pg_session, ids, "nadia", "lina", "Hindi")
    assert other_team.value.status_code == 404  # Lina is South's; Nadia does not learn she exists
    with pytest.raises(HTTPException) as agent:
        await _speaks(pg_session, ids, "omar", "sara", "Hindi")
    assert agent.value.status_code == 403
    with pytest.raises(HTTPException) as stranger:
        scope = await assignment.load_scope(pg_session, ids["org"], ids["owner"])
        await assignment.scope_response(pg_session, scope)
        from app.crm import agent_languages

        await agent_languages.set_languages(
            pg_session, scope, "nobody-here", AgentLanguagesWrite(languages=["Hindi"])
        )
    assert stranger.value.status_code == 404
    # Managers see the recorded languages beside each person they may assign to.
    response = await assignment.scope_response(
        pg_session, await assignment.load_scope(pg_session, ids["org"], ids["nadia"])
    )
    people = {p.user_id: p.languages for team in response.teams for p in team.members}
    assert people[ids["omar"]] == ["Arabic"] and people[ids["sara"]] == []


async def test_a_speakers_only_rule_gives_the_lead_to_someone_who_speaks_its_language(pg_session):
    ids = await _agency(pg_session)
    await _speaks(pg_session, ids, "nadia", "sara", "Hindi")  # Omar, the destination, does not
    await _speakers_rule(pg_session, ids)
    result = await _import(
        pg_session, ids, "nadia", ImportAssignmentPolicy(mode="rules"), data=LANG_CSV, name="L"
    )
    assert result.status == "completed", result.error_message
    leads = await _imported(pg_session, result.id)
    assert {name: lead.assigned_user_id for name, lead in leads.items()} == {
        "Ravi Buyer": ids["sara"],  # Hindi: skips Omar, who is not recorded as speaking it
        "Omid Buyer": None,  # Farsi: nobody in the rule speaks it; left for the manager
        "Nora Buyer": ids["omar"],  # no language known: routed as usual, never guessed
    }
    assert result.summary.assignment.unassigned_reasons == {"no_language_speaker": 1}
    assert leads["Omid Buyer"].team_id == ids["north"]
    # Ravi's rotation starts at Sara's slot, with nobody left after her who speaks Hindi.
    stored = (
        await pg_session.exec(
            select(CrmLeadRotation).where(CrmLeadRotation.enquiry_id == leads["Ravi Buyer"].id)
        )
    ).one()
    assert (stored.position, stored.required_language) == (1, "hindi")
    # Ravi: nobody after Sara speaks Hindi, so the pool. Nora (no language): Omar -> Sara as usual.
    start = leads["Ravi Buyer"].assigned_at
    assert await rotation.advance_due(pg_session, now=start + timedelta(minutes=11)) == {
        "released": 1,
        "rotated": 1,
    }
    ravi, nora = leads["Ravi Buyer"].id, leads["Nora Buyer"].id
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, ravi)).assigned_user_id is None
    assert (await pg_session.get(CrmInboundEnquiry, nora)).assigned_user_id == ids["sara"]


async def test_rotation_under_a_speakers_only_rule_skips_people_without_the_language(pg_session):
    ids = await _agency(pg_session)
    await _speaks(pg_session, ids, "nadia", "omar", "Hindi")
    await _speakers_rule(pg_session, ids)  # Omar then Sara; Sara does not speak Hindi
    result = await _import(
        pg_session, ids, "nadia", ImportAssignmentPolicy(mode="rules"), data=LANG_CSV, name="L"
    )
    ravi = (await _imported(pg_session, result.id))["Ravi Buyer"]
    assert ravi.assigned_user_id == ids["omar"]
    # Omar does not act: Sara is skipped (no Hindi), so Ravi goes to North's pool, while Nora's
    # lead (no language) rotates to Sara as usual.
    assert await rotation.advance_due(pg_session, now=ravi.assigned_at + timedelta(minutes=11)) == {
        "released": 1,
        "rotated": 1,
    }
    assert ids["sara"] not in {e.assigned_user_id for e in await _events(pg_session, ravi.id)}

    # A language recorded later counts: the manager adds Hindi for Sara before the next lead.
    await _speaks(pg_session, ids, "nadia", "sara", "Hindi")
    second = await _import(
        pg_session,
        ids,
        "nadia",
        ImportAssignmentPolicy(mode="rules"),
        data=LANG_CSV.replace("+97150111", "+97150555"),
        name="L2",
    )
    ravi2 = (await _imported(pg_session, second.id))["Ravi Buyer"]
    assert await rotation.advance_due(
        pg_session, now=ravi2.assigned_at + timedelta(minutes=11)
    ) == {"rotated": 2}
    ravi2_id = ravi2.id
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, ravi2_id)).assigned_user_id == ids["sara"]


async def test_languages_vanish_with_the_membership(pg_session):
    from app.organization.models import OrganizationMembership

    ids = await _agency(pg_session)
    await _speaks(pg_session, ids, "nadia", "sara", "Hindi")
    await pg_session.exec(
        sa.delete(OrganizationTeamMember).where(OrganizationTeamMember.user_id == ids["sara"])
    )
    await pg_session.exec(
        sa.delete(OrganizationMembership).where(OrganizationMembership.user_id == ids["sara"])
    )
    await pg_session.commit()
    from app.crm import agent_languages

    assert await agent_languages.languages_by_user(pg_session, ids["org"], [ids["sara"]]) == {}


async def test_reassignment_continues_original_order_without_repeating_people(
    pg_session, monkeypatch
):
    ids = await _agency(pg_session)
    pg_session.add(
        OrganizationTeamMember(
            team_id=ids["north"], organization_id=ids["org"], user_id=ids["adam"], role="agent"
        )
    )
    await pg_session.commit()
    scope = await assignment.load_scope(pg_session, ids["org"], ids["nadia"])
    await routing.create_rule(
        pg_session,
        scope,
        RoutingRuleWrite(
            name="Three people",
            team_id=ids["north"],
            destination_user_id=ids["omar"],
            rotation_user_ids=[ids["sara"], ids["adam"]],
            rotation_minutes=10,
            conditions=[RoutingCondition(field="area", values=["JVC"])],
        ),
    )
    lead_id = await _jvc_lead(pg_session, ids)
    lead = await pg_session.get(CrmInboundEnquiry, lead_id)
    start = lead.assigned_at
    monkeypatch.setattr(assignment, "_utcnow", lambda: start + timedelta(minutes=8))
    await assignment.assign_leads(
        pg_session,
        ids["org"],
        ids["nadia"],
        LeadAssignmentRequest(
            enquiry_ids=[lead_id],
            assignee_user_id=ids["adam"],
            expected_revisions={lead_id: lead.assignment_revision},
        ),
    )
    assert (
        await rotation._advance_one(pg_session, lead_id, start + timedelta(minutes=19)) == "rotated"
    )
    await pg_session.commit()
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, lead_id)).assigned_user_id == ids["sara"]
    assert (
        await rotation._advance_one(pg_session, lead_id, start + timedelta(minutes=30))
        == "released"
    )
    await pg_session.commit()
    assert [e.assigned_user_id for e in await _events(pg_session, lead_id)] == [
        ids["omar"],
        ids["adam"],
        ids["sara"],
        None,
    ]


@pytest.mark.parametrize("same_assignee", [False, True])
async def test_cross_team_reassignment_ends_the_old_rotation(pg_session, same_assignee):
    ids = await _agency(pg_session)
    target = ids["omar"] if same_assignee else ids["lina"]
    if same_assignee:
        pg_session.add(
            OrganizationTeamMember(
                team_id=ids["south"], organization_id=ids["org"], user_id=target, role="agent"
            )
        )
        await pg_session.commit()
    await _rotating_rule(pg_session, ids)
    lead_id = await _jvc_lead(pg_session, ids)
    lead = await pg_session.get(CrmInboundEnquiry, lead_id)
    start = lead.assigned_at
    await assignment.assign_leads(
        pg_session,
        ids["org"],
        ids["owner"],
        LeadAssignmentRequest(
            enquiry_ids=[lead_id],
            assignee_user_id=target,
            team_id=ids["south"],
            expected_revisions={lead_id: lead.assignment_revision},
        ),
    )
    assert (
        await rotation._advance_one(pg_session, lead_id, start + timedelta(minutes=30)) == "not_due"
    )
    await pg_session.commit()
    pg_session.expire_all()
    lead = await pg_session.get(CrmInboundEnquiry, lead_id)
    assert (lead.assigned_user_id, lead.team_id) == (target, ids["south"])
    state = (
        await pg_session.exec(select(CrmLeadRotation).where(CrmLeadRotation.enquiry_id == lead_id))
    ).one()
    assert (state.status, state.stop_reason) == ("stopped", "team_changed")


async def test_notes_and_background_updates_do_not_stop_rotation(pg_session):
    ids = await _agency(pg_session)
    await _rotating_rule(pg_session, ids)
    lead_id = await _jvc_lead(pg_session, ids)
    start = (await pg_session.get(CrmInboundEnquiry, lead_id)).assigned_at
    await inbound.add_inbound_note(
        pg_session,
        enquiry_id=lead_id,
        organization_id=ids["org"],
        user_id=ids["omar"],
        body="Preparing a call",
    )
    assert (
        await rotation._advance_one(pg_session, lead_id, start + timedelta(minutes=11)) == "rotated"
    )
    await pg_session.commit()
