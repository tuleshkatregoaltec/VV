"""Agent lead analytics for managers (agreed 17 Nov 2026), against the migrated schema.

A manager sees, per person in the teams they supervise: first-response and pool claim times,
leads contacted in the last day, stages and sources. Never another team's people.
"""

from datetime import timedelta

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from test_crm_lead_visibility import _lead, _world

from app.crm import agent_analytics, assignment, inbound
from app.crm.inbound_models import CrmInboundActivity, CrmInboundAssignmentEvent, CrmInboundEnquiry
from app.crm.inbound_policy import _utcnow
from app.crm.routing_models import PoolReleaseRequest
from app.organization.models import OrganizationTeamMember


async def _log_contact(db, ids, who, enquiry_id, kind, at):
    db.add(
        CrmInboundActivity(
            enquiry_id=enquiry_id,
            organization_id=ids["org"],
            user_id=ids[who],
            activity_type=kind,
            created_at=at,
        )
    )
    await db.commit()


async def test_team_analytics_lists_only_managed_people_with_recorded_metrics(pg_session):
    ids, _ = await _world(pg_session)
    now = _utcnow()
    lead = await _lead(
        pg_session, ids, "omar", "Fast reply",
        assigned_user_id=ids["omar"], team_id=ids["north"], status="qualified",
        assigned_at=now - timedelta(minutes=20), first_contact_at=now - timedelta(minutes=6),
    )  # fmt: skip
    await _log_contact(pg_session, ids, "omar", lead, "call", now - timedelta(hours=2))
    await _log_contact(pg_session, ids, "omar", lead, "whatsapp", now - timedelta(hours=1))
    await _log_contact(pg_session, ids, "omar", lead, "note", now - timedelta(hours=1))

    view = await agent_analytics.team_analytics(pg_session, ids["org"], ids["nadia"], days=30)

    assert view.days == 30
    people = {a.user_id: a for a in view.agents}
    assert set(people) == {ids["nadia"], ids["omar"], ids["sara"], ids["maya"]}  # never South
    omar = people[ids["omar"]]
    assert omar.avg_first_response_minutes == 14
    assert omar.contacted_24h == 1  # one lead, however many contacts; a note is not a contact
    assert omar.qualified_or_better == 1
    assert ids["north"] in omar.team_ids
    assert people[ids["maya"]].avg_first_response_minutes is None
    assert people[ids["maya"]].contacted_24h == 0


async def test_contact_before_assignment_is_not_a_negative_response(pg_session):
    ids, _ = await _world(pg_session)
    now = _utcnow()
    await _lead(
        pg_session, ids, "sara", "Reassigned",
        assigned_user_id=ids["sara"], team_id=ids["north"],
        assigned_at=now - timedelta(minutes=5), first_contact_at=now - timedelta(minutes=15),
    )  # fmt: skip

    view = await agent_analytics.team_analytics(pg_session, ids["org"], ids["nadia"])

    sara = next(a for a in view.agents if a.user_id == ids["sara"])
    assert sara.avg_first_response_minutes is None
    assert sara.assigned_in_window == 1


async def test_former_member_holding_a_lead_is_still_listed(pg_session):
    ids, _ = await _world(pg_session)
    await _lead(
        pg_session, ids, "maya", "Maya's North lead",
        assigned_user_id=ids["maya"], team_id=ids["north"],
    )  # fmt: skip
    await pg_session.exec(
        sa.delete(OrganizationTeamMember).where(
            OrganizationTeamMember.team_id == ids["north"],
            OrganizationTeamMember.user_id == ids["maya"],
        )
    )
    await pg_session.commit()

    view = await agent_analytics.team_analytics(pg_session, ids["org"], ids["nadia"])

    maya = next(a for a in view.agents if a.user_id == ids["maya"])
    assert maya.open_leads >= 1


async def test_agent_detail_is_scoped_to_the_managers_teams(pg_session):
    ids, _ = await _world(pg_session)

    detail = await agent_analytics.agent_analytics(
        pg_session, ids["org"], ids["nadia"], ids["omar"]
    )
    assert detail.metrics.user_id == ids["omar"]
    assert len(detail.activity) == 7
    assert detail.activity[0].date < detail.activity[-1].date
    assert any(row.name == "North held" for row in detail.leads)

    with pytest.raises(HTTPException) as outside:  # Lina is in South only
        await agent_analytics.agent_analytics(pg_session, ids["org"], ids["nadia"], ids["lina"])
    assert outside.value.status_code == 404
    with pytest.raises(HTTPException) as agent:
        await agent_analytics.team_analytics(pg_session, ids["org"], ids["omar"])
    assert agent.value.status_code == 403


async def test_claim_time_runs_from_release_to_the_claiming_contact(pg_session):
    ids, _ = await _world(pg_session)
    lead_id = await _lead(pg_session, ids, "nadia", "To share", assigned_user_id=None)
    revision = (await pg_session.get(CrmInboundEnquiry, lead_id)).assignment_revision
    await assignment.release_to_pool(
        pg_session,
        ids["org"],
        ids["nadia"],
        PoolReleaseRequest(
            enquiry_ids=[lead_id], team_id=ids["north"], expected_revisions={lead_id: revision}
        ),
    )
    await inbound.add_inbound_activity(
        pg_session,
        enquiry_id=lead_id,
        organization_id=ids["org"],
        user_id=ids["sara"],
        activity_type="call",
        body=None,
    )
    # Released 9 minutes before the claim.
    event = CrmInboundAssignmentEvent
    await pg_session.exec(
        sa.update(event)
        .where(event.enquiry_id == lead_id, event.reason == "released")
        .values(created_at=_utcnow() - timedelta(minutes=9))
    )
    await pg_session.commit()

    view = await agent_analytics.team_analytics(pg_session, ids["org"], ids["nadia"], days=7)

    sara = next(a for a in view.agents if a.user_id == ids["sara"])
    assert sara.avg_claim_minutes == 9
