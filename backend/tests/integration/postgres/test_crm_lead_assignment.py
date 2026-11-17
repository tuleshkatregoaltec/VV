"""Lead assignment and routing against the migrated schema: authority, history, races."""

import asyncio
import io
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import assignment, inbound, inbound_imports, recently_sold, routing
from app.crm.inbound_models import (
    SOLD_OWNER_SOURCE,
    CrmInboundAssignmentEvent,
    CrmInboundContact,
    CrmInboundEnquiry,
    InboundEnquiryCreate,
    InboundEnquiryUpdate,
)
from app.crm.inbound_policy import _utcnow
from app.crm.routing_models import (
    ImportAssignmentPolicy,
    LeadAssignmentRequest,
    RoutingCondition,
    RoutingRuleUpdate,
    RoutingRuleWrite,
)
from app.organization.models import (
    Organization,
    OrganizationMembership,
    OrganizationTeam,
    OrganizationTeamMember,
)

CSV = (
    "Name,Phone,Intent,Area,Budget,Bedrooms\n"
    "Jade Buyer,+971501110001,Buyer,JVC,1500000,2\n"
    "Mara Buyer,+971501110002,Buyer,Dubai Marina,2500000,2\n"
    "Dora Buyer,+971501110003,Buyer,Downtown Dubai,3500000,3\n"
)


async def _org(db, **people):
    """An organization; `people` maps a name to its membership role. Returns ids by name."""
    org = str(uuid4())
    db.add(Organization(id=org, name="Agency", subscription_status="active"))
    await db.flush()
    ids = {"org": org}
    for name, role in people.items():
        ids[name] = f"{name}-{uuid4().hex[:6]}"
        db.add(OrganizationMembership(organization_id=org, user_id=ids[name], role=role))
    await db.commit()
    return ids


async def _team(db, ids, name, **members):
    team = OrganizationTeam(organization_id=ids["org"], name=name)
    db.add(team)
    await db.flush()
    for person, role in members.items():
        db.add(
            OrganizationTeamMember(
                team_id=team.id, organization_id=ids["org"], user_id=ids[person], role=role
            )
        )
    await db.commit()
    return team.id


async def _agency(db):
    """Owner; Nadia supervises North (Omar, Sara); Karim supervises South (Lina); Adam is in
    no team."""
    ids = await _org(
        db, owner="owner", nadia="member", omar="member", sara="member", karim="member",
        lina="member", adam="member",
    )  # fmt: skip
    ids["north"] = await _team(db, ids, "North", nadia="supervisor", omar="agent", sara="agent")
    ids["south"] = await _team(db, ids, "South", karim="supervisor", lina="agent")
    return ids


async def _import(db, ids, importer, policy, data=CSV, name="Campaign"):
    upload = UploadFile(file=io.BytesIO(data.encode()), filename="leads.csv")
    return await inbound_imports.process_inbound_import(
        db,
        upload=upload,
        name=name,
        user_id=ids[importer],
        organization_id=ids["org"],
        assignment_policy=policy,
    )


async def _imported(db, import_id):
    rows = (
        await db.exec(
            select(CrmInboundEnquiry)
            .where(CrmInboundEnquiry.source_import_id == import_id)
            .order_by(CrmInboundEnquiry.id)
        )
    ).all()
    contacts = {
        c.id: c.full_name
        for c in (
            await db.exec(
                select(CrmInboundContact).where(
                    CrmInboundContact.id.in_([r.contact_id for r in rows])
                )
            )
        ).all()
    }
    return {contacts[r.contact_id]: r for r in rows}


async def _events(db, enquiry_id=None, org=None):
    query = select(CrmInboundAssignmentEvent)
    if enquiry_id is not None:
        query = query.where(CrmInboundAssignmentEvent.enquiry_id == enquiry_id)
    if org is not None:
        query = query.where(CrmInboundAssignmentEvent.organization_id == org)
    return (await db.exec(query.order_by(CrmInboundAssignmentEvent.id))).all()


async def _rule(db, ids, name, team, destination, *conditions):
    scope = await assignment.load_scope(db, ids["org"], ids["owner"])
    return await routing.create_rule(
        db,
        scope,
        RoutingRuleWrite(
            name=name,
            team_id=ids[team],
            destination_user_id=ids[destination],
            conditions=[RoutingCondition(field=f, values=v) for f, v in conditions],
        ),
    )


async def test_manager_imports_to_a_supervised_agent_who_then_handles_every_new_lead(pg_session):
    ids = await _agency(pg_session)
    result = await _import(
        pg_session, ids, "nadia", ImportAssignmentPolicy(mode="agent", assignee_user_id=ids["omar"])
    )
    assert result.status == "completed"
    assert result.summary.assignment.assigned == 3
    assert result.summary.assignment.by_assignee == {ids["omar"]: 3}
    leads = await _imported(pg_session, result.id)
    # The importer created them; the chosen agent handles them.
    assert {(r.created_by_user_id, r.assigned_user_id) for r in leads.values()} == {
        (ids["nadia"], ids["omar"])
    }
    events = await _events(pg_session, org=ids["org"])
    assert [(e.reason, e.actor_user_id, e.import_id, e.revision) for e in events] == [
        ("import_agent", ids["nadia"], result.id, 1)
    ] * 3


async def test_rules_send_jvc_to_omar_and_marina_to_sara_and_report_the_rest(pg_session):
    ids = await _agency(pg_session)
    jvc = await _rule(pg_session, ids, "JVC", "north", "omar", ("area", ["JVC"]))
    await _rule(pg_session, ids, "Marina", "north", "sara", ("area", ["Dubai Marina"]))

    result = await _import(pg_session, ids, "nadia", ImportAssignmentPolicy(mode="rules"))
    outcome = result.summary.assignment
    assert (outcome.assigned, outcome.unassigned) == (2, 1)
    assert outcome.unassigned_reasons == {"no_matching_rule": 1}
    leads = await _imported(pg_session, result.id)
    assert leads["Jade Buyer"].assigned_user_id == ids["omar"]
    assert leads["Mara Buyer"].assigned_user_id == ids["sara"]
    # Not silently given to the importer: it waits, reported, in the pool.
    assert leads["Dora Buyer"].assigned_user_id is None
    jade_events = await _events(pg_session, leads["Jade Buyer"].id)
    assert [(e.reason, e.rule_id, e.rule_revision) for e in jade_events] == [
        ("import_rule", jvc.id, jvc.revision)
    ]


async def test_a_matching_rule_with_a_departed_destination_does_not_fall_through(pg_session):
    ids = await _agency(pg_session)
    await _rule(pg_session, ids, "JVC", "north", "omar", ("area", ["JVC"]))
    await _rule(pg_session, ids, "Buyers", "north", "sara", ("intent", ["buy"]))
    # Omar leaves the team after the rule was written.
    await pg_session.exec(
        sa.delete(OrganizationTeamMember).where(OrganizationTeamMember.user_id == ids["omar"])
    )
    await pg_session.commit()

    result = await _import(pg_session, ids, "owner", ImportAssignmentPolicy(mode="rules"))
    leads = await _imported(pg_session, result.id)
    assert leads["Jade Buyer"].assigned_user_id is None  # not passed on to the buyers rule
    assert leads["Mara Buyer"].assigned_user_id == ids["sara"]
    assert result.summary.assignment.unassigned_reasons == {"destination_ineligible": 1}


async def test_reimporting_the_same_file_neither_creates_nor_reassigns_leads(pg_session):
    ids = await _agency(pg_session)
    first = await _import(
        pg_session, ids, "nadia", ImportAssignmentPolicy(mode="agent", assignee_user_id=ids["omar"])
    )
    again = await _import(
        pg_session, ids, "nadia", ImportAssignmentPolicy(mode="agent", assignee_user_id=ids["sara"])
    )
    assert again.id == first.id
    leads = await _imported(pg_session, first.id)
    assert {r.assigned_user_id for r in leads.values()} == {ids["omar"]}
    assert len(await _events(pg_session, org=ids["org"])) == 3


async def test_unassigned_import_keeps_review_status_and_assigns_no_one(pg_session):
    ids = await _agency(pg_session)
    data = "Name,Phone\nNo Intent,+971501110009\n"
    result = await _import(
        pg_session, ids, "owner", ImportAssignmentPolicy(mode="unassigned"), data
    )
    lead = (await _imported(pg_session, result.id))["No Intent"]
    assert (lead.assigned_user_id, lead.status) == (None, "needs_review")
    assert result.summary.assignment.unassigned_reasons == {"chosen_unassigned": 1}
    assert await _events(pg_session, lead.id) == []


@pytest.mark.parametrize(
    ("importer", "assignee"),
    [
        ("omar", "sara"),  # an agent cannot import or assign
        ("nadia", "lina"),  # another manager's team
        ("nadia", "adam"),  # an organization member in no team
        ("nadia", "stranger"),  # not in the organization
    ],
)
async def test_import_to_an_ineligible_agent_is_refused_before_anything_is_stored(
    pg_session, importer, assignee
):
    ids = await _agency(pg_session)
    ids["stranger"] = "stranger-" + uuid4().hex
    with pytest.raises(HTTPException) as refused:
        await _import(
            pg_session,
            ids,
            importer,
            ImportAssignmentPolicy(mode="agent", assignee_user_id=ids[assignee]),
        )
    assert refused.value.status_code == 403
    count = await pg_session.exec(
        select(sa.func.count(CrmInboundEnquiry.id)).where(
            CrmInboundEnquiry.organization_id == ids["org"]
        )
    )
    assert count.one() == 0


async def test_an_agent_in_no_team_imports_leads_that_are_assigned_to_them(pg_session):
    # Adam is a plain member in no team: his own import still lands in his queue, never the pool.
    ids = await _agency(pg_session)
    data = CSV + "Jade Buyer,+971501110001,Buyer,JVC,1500000,2\n"  # the same row again
    result = await _import(pg_session, ids, "adam", ImportAssignmentPolicy(mode="self"), data)

    assert result.status == "completed"
    assert (result.summary.imported, result.summary.duplicates) == (3, 1)
    assert result.summary.assignment.model_dump() == {
        "mode": "self",
        "assignee_user_id": None,
        "team_id": None,
        "assigned": 3,
        "unassigned": 0,
        "by_assignee": {ids["adam"]: 3},
        "by_rule": {},
        "shared": 0,
        "unassigned_reasons": {},
    }
    leads = await _imported(pg_session, result.id)
    # No team owns them (Adam has none): only Adam and the administrators see them.
    assert {(r.created_by_user_id, r.assigned_user_id, r.team_id) for r in leads.values()} == {
        (ids["adam"], ids["adam"], None)
    }
    events = await _events(pg_session, org=ids["org"])
    assert {(e.reason, e.actor_user_id, e.assigned_user_id) for e in events} == {
        ("import_agent", ids["adam"], ids["adam"])
    }

    # A retry of the same file returns the first import; nothing is created or assigned again.
    again = await _import(pg_session, ids, "adam", ImportAssignmentPolicy(mode="self"), data)
    assert again.id == result.id
    assert len(await _events(pg_session, org=ids["org"])) == 3


@pytest.mark.parametrize(
    "policy",
    [
        ImportAssignmentPolicy(mode="rules"),
        ImportAssignmentPolicy(mode="unassigned"),
    ],
)
async def test_an_agent_cannot_route_or_pool_an_import_with_a_forged_mode(pg_session, policy):
    # The UI never offers these to an agent; a hand-made request must be refused the same way.
    ids = await _agency(pg_session)
    await _rule(pg_session, ids, "JVC", "north", "omar", ("area", ["JVC"]))
    with pytest.raises(HTTPException) as refused:
        await _import(pg_session, ids, "omar", policy)
    assert refused.value.status_code == 403
    count = await pg_session.exec(
        select(sa.func.count(CrmInboundEnquiry.id)).where(
            CrmInboundEnquiry.organization_id == ids["org"]
        )
    )
    assert count.one() == 0


async def test_a_manager_keeps_distributing_and_may_also_import_for_themselves(pg_session):
    ids = await _agency(pg_session)
    mine = await _import(pg_session, ids, "nadia", ImportAssignmentPolicy(mode="self"))
    assert mine.summary.assignment.by_assignee == {ids["nadia"]: 3}
    data = CSV.replace("+97150111", "+97150222")  # different people, so a new file
    theirs = await _import(
        pg_session,
        ids,
        "nadia",
        ImportAssignmentPolicy(mode="agent", assignee_user_id=ids["sara"]),
        data,
        name="For Sara",
    )
    assert theirs.summary.assignment.by_assignee == {ids["sara"]: 3}


async def test_a_lead_edit_cannot_bypass_assignment_authority(pg_session):
    ids = await _agency(pg_session)
    lead = await inbound.create_inbound_enquiry(
        pg_session,
        payload=InboundEnquiryCreate(full_name="Patch Target"),
        user_id=ids["omar"],
        organization_id=ids["org"],
    )
    assert lead.assigned_user_id == ids["omar"]  # creating a lead still makes it yours

    async def patch(actor, assignee):
        return await inbound.update_inbound_enquiry(
            pg_session,
            enquiry_id=lead.id,
            organization_id=ids["org"],
            user_id=ids[actor],
            payload=InboundEnquiryUpdate(assigned_user_id=ids[assignee] if assignee else None),
        )

    # Omar's lead belongs to his only team, North. Karim manages South: he cannot even see it
    # (404, like a missing lead), let alone move it. The others see it but may not move it so.
    for actor, assignee, status in (
        ("omar", "sara", 403),
        ("omar", None, 403),
        ("karim", "lina", 404),
        ("nadia", "adam", 403),
    ):
        with pytest.raises(HTTPException) as refused:
            await patch(actor, assignee)
        assert refused.value.status_code == status
        await pg_session.rollback()
    moved = await patch("nadia", "sara")
    assert (moved.assigned_user_id, moved.assignment_revision) == (ids["sara"], 2)
    events = await _events(pg_session, lead.id)
    assert [(e.reason, e.previous_user_id, e.assigned_user_id) for e in events] == [
        ("created", None, ids["omar"]),
        ("manual", ids["omar"], ids["sara"]),
    ]


async def test_a_stale_bulk_assignment_changes_no_lead(pg_session):
    ids = await _agency(pg_session)
    made = [
        await inbound.create_inbound_enquiry(
            pg_session,
            payload=InboundEnquiryCreate(full_name=f"Lead {n}"),
            user_id=ids["nadia"],
            organization_id=ids["org"],
        )
        for n in range(2)
    ]
    first, second = (lead.id for lead in made)
    await assignment.assign_leads(
        pg_session,
        ids["org"],
        ids["nadia"],
        LeadAssignmentRequest(
            enquiry_ids=[second], assignee_user_id=ids["omar"], expected_revisions={second: 1}
        ),
    )
    with pytest.raises(HTTPException) as conflict:
        await assignment.assign_leads(
            pg_session,
            ids["org"],
            ids["nadia"],
            LeadAssignmentRequest(
                enquiry_ids=[first, second],
                assignee_user_id=ids["sara"],
                expected_revisions={first: 1, second: 1},  # second moved since it was read
            ),
        )
    assert conflict.value.status_code == 409
    assert conflict.value.detail["enquiry_ids"] == [second]
    await pg_session.rollback()
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, first)).assigned_user_id == ids["nadia"]
    assert len(await _events(pg_session, first)) == 1


async def test_two_managers_assigning_the_same_revision_cannot_both_win(postgres_test_url):
    engine = create_async_engine(postgres_test_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as setup:
            ids = await _agency(setup)
            # Both managers supervise the team that owns the lead, so both may move it.
            shared = await _team(
                setup,
                ids,
                "Shared",
                karim="supervisor",
                nadia="supervisor",
                omar="agent",
                lina="agent",
                sara="agent",
            )
            lead = await inbound.create_inbound_enquiry(
                setup,
                payload=InboundEnquiryCreate(
                    full_name="Contested", assigned_user_id=ids["omar"], team_id=shared
                ),
                user_id=ids["owner"],
                organization_id=ids["org"],
            )
        seen = {lead.id: lead.assignment_revision}  # both managers loaded the same revision

        async def karim_assigns():
            async with AsyncSession(engine, expire_on_commit=False) as db:
                try:
                    await assignment.assign_leads(
                        db,
                        ids["org"],
                        ids["karim"],
                        LeadAssignmentRequest(
                            enquiry_ids=[lead.id],
                            assignee_user_id=ids["lina"],
                            expected_revisions=seen,
                        ),
                    )
                    return "assigned"
                except HTTPException as error:
                    return error.status_code

        async with AsyncSession(engine, expire_on_commit=False) as nadia:
            scope = await assignment.load_scope(nadia, ids["org"], ids["nadia"])
            await assignment.reassign(nadia, scope, [lead.id], ids["sara"], expected_revisions=seen)
            # Nadia has not committed yet; Karim's request must wait instead of reading the
            # old revision and overwriting her change afterwards.
            karim = asyncio.create_task(karim_assigns())
            await asyncio.sleep(0.5)
            assert not karim.done()
            await nadia.commit()
        assert await karim == 409

        async with AsyncSession(engine) as check:
            stored = await check.get(CrmInboundEnquiry, lead.id)
            history = await _events(check, lead.id)
        assert stored.assigned_user_id == ids["sara"]
        # History matches committed state: the creation and Nadia's reassignment only.
        assert [e.assigned_user_id for e in history] == [ids["omar"], ids["sara"]]
    finally:
        await engine.dispose()


async def test_the_database_keeps_teams_inside_one_organization(pg_session):
    ids = await _agency(pg_session)
    other = await _org(pg_session, outsider="member")
    pg_session.add(
        OrganizationTeamMember(
            team_id=ids["north"], organization_id=other["org"], user_id=other["outsider"]
        )
    )
    with pytest.raises(IntegrityError):
        await pg_session.commit()
    await pg_session.rollback()

    # Leaving the organization leaves every team, so they stop being an eligible destination.
    await pg_session.exec(
        sa.delete(OrganizationMembership).where(OrganizationMembership.user_id == ids["omar"])
    )
    await pg_session.commit()
    scope = await assignment.load_scope(pg_session, ids["org"], ids["nadia"])
    assert ids["omar"] not in scope.eligible_user_ids


async def test_rule_edits_need_the_revision_the_editor_saw(pg_session):
    ids = await _agency(pg_session)
    rule = await _rule(pg_session, ids, "JVC", "north", "omar", ("area", ["JVC"]))
    scope = await assignment.load_scope(pg_session, ids["org"], ids["owner"])
    change = dict(
        name="JVC",
        team_id=ids["north"],
        destination_user_id=ids["sara"],
        conditions=[RoutingCondition(field="area", values=["JVC"])],
    )
    updated = await routing.update_rule(
        pg_session, scope, rule.id, RoutingRuleUpdate(**change, expected_revision=1)
    )
    assert updated.revision == 2
    with pytest.raises(HTTPException) as conflict:
        await routing.update_rule(
            pg_session, scope, rule.id, RoutingRuleUpdate(**change, expected_revision=1)
        )
    assert conflict.value.status_code == 409
    # North's manager edits North's rules (agreed: the manager sets the assignment rules), at the
    # revision she saw like anyone else.
    nadia = await assignment.load_scope(pg_session, ids["org"], ids["nadia"])
    edited = await routing.update_rule(
        pg_session, nadia, rule.id, RoutingRuleUpdate(**change, expected_revision=2)
    )
    assert (edited.revision, edited.updated_by_user_id) == (3, ids["nadia"])
    # She cannot move it into a team she does not manage.
    with pytest.raises(HTTPException) as foreign_team:
        await routing.update_rule(
            pg_session,
            nadia,
            rule.id,
            RoutingRuleUpdate(
                **{**change, "team_id": ids["south"], "destination_user_id": ids["lina"]},
                expected_revision=3,
            ),
        )
    assert foreign_team.value.status_code == 403
    # South's manager does not see North's rule at all; an agent cannot change rules.
    karim = await assignment.load_scope(pg_session, ids["org"], ids["karim"])
    with pytest.raises(HTTPException) as hidden:
        await routing.update_rule(
            pg_session, karim, rule.id, RoutingRuleUpdate(**change, expected_revision=3)
        )
    assert hidden.value.status_code == 404
    assert [r.id for r in await routing.list_rules(pg_session, karim)] == []
    omar = await assignment.load_scope(pg_session, ids["org"], ids["omar"])
    with pytest.raises(HTTPException) as agent:
        await routing.update_rule(
            pg_session, omar, rule.id, RoutingRuleUpdate(**change, expected_revision=3)
        )
    assert agent.value.status_code == 403


async def test_a_failed_import_leaves_no_assignment_history(pg_session, monkeypatch):
    ids = await _agency(pg_session)

    async def broken(*args, **kwargs):
        raise RuntimeError("enrichment failed")

    monkeypatch.setattr(inbound_imports, "_bulk_ownership_enrichments", broken)
    result = await _import(
        pg_session, ids, "nadia", ImportAssignmentPolicy(mode="agent", assignee_user_id=ids["omar"])
    )
    assert result.status == "failed"
    assert result.summary.assignment.assigned == 0
    assert await _events(pg_session, org=ids["org"]) == []
    assert await _imported(pg_session, result.id) == {}


async def test_approving_an_inbox_item_assigns_the_approver_but_never_takes_anothers_lead(
    pg_session,
):
    ids = await _agency(pg_session)
    now = _utcnow()

    async def sold_item():
        contact = CrmInboundContact(
            organization_id=ids["org"], full_name="Seller", created_at=now, updated_at=now
        )
        pg_session.add(contact)
        await pg_session.flush()
        item = CrmInboundEnquiry(
            organization_id=ids["org"],
            contact_id=contact.id,
            created_by_user_id="system",
            intent="unknown",
            source=SOLD_OWNER_SOURCE,
            source_lead_id=uuid4().hex,
            enquiry_date=now,
            created_at=now,
            updated_at=now,
        )
        pg_session.add(item)
        await pg_session.commit()
        return item.id

    waiting, held = await sold_item(), await sold_item()
    await assignment.assign_leads(
        pg_session,
        ids["org"],
        ids["nadia"],
        LeadAssignmentRequest(
            enquiry_ids=[held], assignee_user_id=ids["sara"], expected_revisions={held: 0}
        ),
    )
    await recently_sold.approve_recent_seller(
        pg_session, enquiry_id=waiting, organization_id=ids["org"], user_id=ids["adam"]
    )
    # Once Sara holds it, it is her lead: Adam no longer sees it, so he cannot approve it.
    with pytest.raises(HTTPException) as hidden:
        await recently_sold.approve_recent_seller(
            pg_session, enquiry_id=held, organization_id=ids["org"], user_id=ids["adam"]
        )
    assert hidden.value.status_code == 404
    await pg_session.rollback()
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, waiting)).assigned_user_id == ids["adam"]
    assert (await pg_session.get(CrmInboundEnquiry, held)).assigned_user_id == ids["sara"]
    assert [e.reason for e in await _events(pg_session, waiting)] == ["approved_from_inbox"]
