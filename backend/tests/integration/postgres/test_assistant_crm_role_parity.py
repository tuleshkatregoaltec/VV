"""The assistant reads and changes exactly what the CRM lets each role read and change.

Agency (crm_role_support): Owner is the organization administrator; Nadia manages North (Omar,
Sara); Karim manages South (Lina). A second agency checks that nothing crosses organizations.
Every check goes through the CRM's own rules (crm/assignment.py, crm/deals.py,
crm/oversight.py, crm/inbound.py); these tests fail if the assistant drifts from them.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from crm_role_support import agency, lead
from fastapi import HTTPException
from sqlmodel import select

from app.assistant_actions import service
from app.assistant_actions.models import ActionProposalRequest
from app.chat.models import Conversation
from app.crm import assignment
from app.crm import inbound as crm_inbound
from app.crm.assistant import query_my_records
from app.crm.assistant.models import CrmAssistantQuery
from app.crm.deal_models import CrmDeal
from app.crm.inbound_models import (
    CrmInboundActivity,
    CrmInboundAssignmentEvent,
    CrmInboundEnquiry,
)
from app.organization import teams as org_teams
from app.organization.models import OrganizationTeamMember


@pytest.fixture(autouse=True)
def offline_directory(monkeypatch):
    """Names as the identity provider would hold them: "sara-1a2b3c" is "Sara"."""

    async def person(user_id):
        return SimpleNamespace(
            first_name=user_id.split("-")[0].title(),
            last_name="",
            email=f"{user_id}@example.test",
        )

    monkeypatch.setattr(org_teams, "get_user_by_id", person)
    monkeypatch.setattr(service, "get_user_by_id", person)


async def read(db, ids, person, **query):
    return await query_my_records(
        db, CrmAssistantQuery(**query), user_id=ids[person], organization_id=ids["org"]
    )


async def deal(db, ids, *, team, agent, client):
    now = datetime.now(UTC)
    row = CrmDeal(
        organization_id=ids["org"],
        assigned_user_id=ids[agent],
        team_id=ids[team],
        created_by_user_id=ids[agent],
        deal_type="sale",
        unit="Unit 1",
        client=client,
        origin="portal",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    return row.id


async def actor(db, ids, person):
    conversation = Conversation(user_id=ids[person], organization_id=ids["org"])
    db.add(conversation)
    await db.commit()
    return dict(user_id=ids[person], organization_id=ids["org"]), conversation.id


async def propose(db, ids, person, kind, payload):
    identity, conversation_id = await actor(db, ids, person)
    proposal = await service.propose_action(
        db,
        **identity,
        request=ActionProposalRequest(
            kind=kind, payload=payload, conversation_id=conversation_id, idempotency_key=uuid4().hex
        ),
    )
    return identity, proposal


async def refused(db, ids, person, kind, payload) -> int:
    with pytest.raises(HTTPException) as error:
        await propose(db, ids, person, kind, payload)
    await db.rollback()
    return error.value.status_code


@pytest.fixture
async def agency_leads(pg_session):
    ids = await agency(pg_session)
    leads = {
        "omar": await lead(pg_session, ids, "OmarLead", team="north", assignee="omar"),
        "sara": await lead(pg_session, ids, "SaraLead", team="north", assignee="sara"),
        "pool": await lead(pg_session, ids, "NorthPool", team="north", assignee=None, pooled=True),
        "lina": await lead(pg_session, ids, "LinaLead", team="south", assignee="lina"),
        "south_pool": await lead(
            pg_session, ids, "SouthPool", team="south", assignee=None, pooled=True
        ),
    }
    return ids, leads


# Reads: lead counts by team and handler follow each role's CRM visibility.


async def test_owner_counts_every_team_and_sees_who_handles_each_lead(pg_session, agency_leads):
    ids, _ = agency_leads
    result = await read(pg_session, ids, "owner", resource="leads", summary_only=True)
    assert result.total == 5
    assert result.counts_by_team == {"North": 3, "South": 2}
    assert result.counts_by_handler == {"Omar": 1, "Sara": 1, "Lina": 1, "unassigned": 2}


async def test_manager_counts_only_their_teams_and_names_their_teams_handlers(
    pg_session, agency_leads
):
    ids, _ = agency_leads
    result = await read(pg_session, ids, "nadia", resource="leads", summary_only=True)
    # South's leads and South's people never appear for North's manager.
    assert result.counts_by_team == {"North": 3}
    assert result.counts_by_handler == {"Omar": 1, "Sara": 1, "unassigned": 1}
    rows = (await read(pg_session, ids, "nadia", resource="leads", handled_by="sara")).records
    assert [(row["contact_name"], row["handled_by"], row["team"]) for row in rows] == [
        ("SaraLead", "Sara", "North")
    ]


async def test_manager_cannot_reach_another_teams_leads_by_name_or_team(pg_session, agency_leads):
    ids, _ = agency_leads
    # Filters only narrow the role's own visibility; they never widen it.
    assert (await read(pg_session, ids, "nadia", resource="leads", handled_by="Lina")).total == 0
    assert (await read(pg_session, ids, "nadia", resource="leads", team="South")).total == 0


async def test_agent_sees_own_and_team_pool_and_never_colleagues_names(pg_session, agency_leads):
    ids, leads = agency_leads
    result = await read(pg_session, ids, "omar", resource="leads")
    by_id = {row["id"]: row for row in result.records}
    assert set(by_id) == {leads["omar"].id, leads["pool"].id}
    assert by_id[leads["pool"].id]["in_team_pool"] is True
    assert result.counts_by_handler == {"you": 1, "unassigned": 1}
    assert "Sara" not in result.model_dump_json()
    assert (await read(pg_session, ids, "omar", resource="leads", handled_by="Sara")).total == 0


async def test_team_workload_is_the_crms_manager_view(pg_session, agency_leads):
    ids, _ = agency_leads
    owner = await read(pg_session, ids, "owner", resource="team_workload")
    assert [team["team"] for team in owner.records] == ["North", "South"]
    nadia = await read(pg_session, ids, "nadia", resource="team_workload")
    assert [team["team"] for team in nadia.records] == ["North"]
    north = nadia.records[0]
    assert (north["unassigned"], north["waiting_in_pool"]) == (1, 1)
    assert {m["name"]: m["open_leads"] for m in north["members"]} == {
        "you": 0,
        "Omar": 1,
        "Sara": 1,
    }
    agent = await read(pg_session, ids, "omar", resource="team_workload")
    assert (agent.available, agent.records) == (False, [])


async def test_deals_follow_the_crms_deal_access(pg_session, agency_leads):
    ids, _ = agency_leads
    await deal(pg_session, ids, team="north", agent="omar", client="OmarClient")
    await deal(pg_session, ids, team="north", agent="sara", client="SaraClient")
    await deal(pg_session, ids, team="south", agent="lina", client="LinaClient")

    async def clients(person):
        result = await read(pg_session, ids, person, resource="deals")
        return {row["client"] for row in result.records}

    assert await clients("owner") == {"OmarClient", "SaraClient", "LinaClient"}
    assert await clients("nadia") == {"OmarClient", "SaraClient"}
    assert await clients("omar") == {"OmarClient"}
    row = (await read(pg_session, ids, "nadia", resource="deals", handled_by="Omar")).records[0]
    assert (row["handled_by"], row["team"], row["status"]) == ("Omar", "North", "open")
    assert row["reference"].startswith("D-") and isinstance(row["stage"], str)


async def test_nothing_crosses_organizations(pg_session, agency_leads):
    ids, leads = agency_leads
    other = await agency(pg_session)
    await lead(pg_session, other, "OtherOrgLead", team="north", assignee="omar")
    result = await read(pg_session, other, "owner", resource="leads", summary_only=True)
    assert result.total == 1
    assert (
        await refused(
            pg_session,
            other,
            "owner",
            "log_contact",
            {"lead_id": leads["pool"].id, "activity_type": "call"},
        )
        == 404
    )
    # A member of another organization reading this one has no current membership here.
    with pytest.raises(PermissionError):
        await query_my_records(
            pg_session,
            CrmAssistantQuery(resource="leads"),
            user_id=other["owner"],
            organization_id=ids["org"],
        )


async def test_no_membership_means_no_crm_access_whatever_the_platform_role(
    pg_session, agency_leads
):
    """A platform Super Admin is just an authenticated user here: neither the CRM nor the
    assistant takes a platform role as input, so without membership there is nothing."""
    ids, leads = agency_leads
    outsider = {**ids, "outsider": f"platform-admin-{uuid4().hex[:6]}"}
    with pytest.raises(PermissionError):
        await read(pg_session, outsider, "outsider", resource="leads")
    assert (
        await refused(
            pg_session,
            outsider,
            "outsider",
            "log_contact",
            {"lead_id": leads["pool"].id, "activity_type": "call"},
        )
        == 403
    )


# Actions: the CRM's own writes, re-checked when the user confirms.


async def test_agent_takes_a_lead_from_their_team_pool_by_logging_contact(pg_session, agency_leads):
    ids, leads = agency_leads
    identity, proposal = await propose(
        pg_session,
        ids,
        "omar",
        "log_contact",
        {"lead_id": leads["pool"].id, "activity_type": "call"},
    )
    result = await service.confirm_action(pg_session, **identity, action_id=proposal.id)
    assert result.status == "succeeded"
    assert result.result["message"] == "Contact logged; the lead is now yours"
    pg_session.expire_all()
    taken = await pg_session.get(CrmInboundEnquiry, leads["pool"].id)
    assert (taken.assigned_user_id, taken.pool_released_at, taken.status) == (
        ids["omar"],
        None,
        "attempted",
    )
    events = (
        await pg_session.exec(
            select(CrmInboundAssignmentEvent.reason).where(
                CrmInboundAssignmentEvent.enquiry_id == leads["pool"].id
            )
        )
    ).all()
    assert events == ["claimed"]
    activities = (
        await pg_session.exec(
            select(CrmInboundActivity.activity_type).where(
                CrmInboundActivity.enquiry_id == leads["pool"].id
            )
        )
    ).all()
    assert activities == ["call"]


async def test_agent_cannot_touch_another_teams_pool_or_a_colleagues_lead(pg_session, agency_leads):
    ids, leads = agency_leads
    call = {"activity_type": "call"}
    assert (
        await refused(
            pg_session, ids, "omar", "log_contact", {"lead_id": leads["south_pool"].id, **call}
        )
        == 404
    )
    assert (
        await refused(pg_session, ids, "omar", "log_contact", {"lead_id": leads["sara"].id, **call})
        == 404
    )
    assert (
        await refused(pg_session, ids, "omar", "release_to_pool", {"lead_id": leads["omar"].id})
        == 403
    )


async def test_manager_shares_a_team_lead_in_the_pool_but_not_another_teams(
    pg_session, agency_leads
):
    ids, leads = agency_leads
    identity, proposal = await propose(
        pg_session, ids, "nadia", "release_to_pool", {"lead_id": leads["sara"].id}
    )
    assert (proposal.preview["current_assignee"], proposal.preview["new_assignee"]) == (
        "Sara",
        "Team pool",
    )
    result = await service.confirm_action(pg_session, **identity, action_id=proposal.id)
    assert result.status == "succeeded"
    pg_session.expire_all()
    shared = await pg_session.get(CrmInboundEnquiry, leads["sara"].id)
    assert shared.assigned_user_id is None and shared.pool_released_at is not None
    assert shared.team_id == ids["north"]
    assert (
        await refused(pg_session, ids, "nadia", "release_to_pool", {"lead_id": leads["lina"].id})
        == 404
    )
    owner, proposal = await propose(
        pg_session, ids, "owner", "release_to_pool", {"lead_id": leads["lina"].id}
    )
    assert (await service.confirm_action(pg_session, **owner, action_id=proposal.id)).status == (
        "succeeded"
    )


async def test_confirmation_rechecks_the_managers_role(pg_session, agency_leads):
    ids, leads = agency_leads
    identity, proposal = await propose(
        pg_session, ids, "nadia", "release_to_pool", {"lead_id": leads["omar"].id}
    )
    # Nadia stops managing North before she confirms.
    membership = (
        await pg_session.exec(
            select(OrganizationTeamMember).where(
                OrganizationTeamMember.user_id == ids["nadia"],
                OrganizationTeamMember.team_id == ids["north"],
            )
        )
    ).one()
    membership.role = "agent"
    await pg_session.commit()
    result = await service.confirm_action(pg_session, **identity, action_id=proposal.id)
    assert result.status == "failed"
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, leads["omar"].id)).assigned_user_id == ids[
        "omar"
    ]


async def test_a_pool_lead_taken_by_a_teammate_first_is_not_taken_again(pg_session, agency_leads):
    ids, leads = agency_leads
    identity, proposal = await propose(
        pg_session,
        ids,
        "omar",
        "log_contact",
        {"lead_id": leads["pool"].id, "activity_type": "call"},
    )
    # Sara logs contact in the CRM before Omar confirms: the lead is hers.
    sara = await assignment.load_scope(pg_session, ids["org"], ids["sara"])
    await crm_inbound.log_contact(
        pg_session, sara, enquiry_id=leads["pool"].id, activity_type="whatsapp", body=None
    )
    await pg_session.commit()
    result = await service.confirm_action(pg_session, **identity, action_id=proposal.id)
    assert result.status == "failed"
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, leads["pool"].id)).assigned_user_id == ids[
        "sara"
    ]
