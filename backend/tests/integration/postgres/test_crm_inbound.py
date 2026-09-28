from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.crm import inbound, matching
from app.crm.inbound_models import CrmInboundEnquiry, CrmInboundMatch, InboundEnquiryCreate


async def test_manual_enquiry_scope_history_and_match_state_survive_refresh(pg_session):
    org, user = str(uuid4()), str(uuid4())
    response = await inbound.create_inbound_enquiry(
        pg_session,
        payload=InboundEnquiryCreate(
            full_name="Migration buyer",
            intent="buy",
            record_kind="opportunity",
            criteria={"locations": ["JBR"], "budget_max_aed": 3000000, "bedrooms_min": 2},
        ),
        user_id=user,
        organization_id=org,
    )
    with pytest.raises(HTTPException) as error:
        await inbound.get_inbound_enquiry(pg_session, response.id, str(uuid4()))
    assert error.value.status_code == 404
    enquiry = await pg_session.get(CrmInboundEnquiry, response.id)
    arguments = dict(
        enquiry=enquiry,
        target_type="unit",
        target_key="test-unit",
        title="Unit",
        subtitle="Evidence",
        reasons=["Location"],
        breakdown={"requirements": 85},
        snapshot={"source": "registry"},
    )
    assert await matching._upsert_match(pg_session, score=49, **arguments) is None
    item = await matching._upsert_match(pg_session, score=85, **arguments)
    assert item.fit == "exact"
    await pg_session.commit()
    await matching.update_inbound_match_state(
        pg_session, match_id=item.id, organization_id=org, state="saved"
    )
    refreshed = await matching._upsert_match(pg_session, score=65, **arguments)
    assert refreshed.state == "saved"
    assert (refreshed.score, refreshed.fit) == (65, "near")
    await matching.update_inbound_match_state(
        pg_session, match_id=item.id, organization_id=org, state="dismissed"
    )
    dismissed = await matching._upsert_match(
        pg_session, score=99, **{**arguments, "title": "Changed"}
    )
    assert (dismissed.title, dismissed.score, dismissed.state) == ("Unit", 65, "dismissed")
    await pg_session.commit()
    item_id, criteria = item.id, dict(enquiry.criteria)
    pg_session.expire_all()
    persisted = await pg_session.get(CrmInboundMatch, item_id)
    assert persisted.snapshot == {"source": "registry"}
    loaded = await inbound.get_inbound_enquiry(pg_session, response.id, org)
    assert loaded.criteria == criteria
    assert loaded.activities[0].activity_type == "created"


async def test_high_score_without_requirements_cannot_be_exact(pg_session):
    org, user = str(uuid4()), str(uuid4())
    response = await inbound.create_inbound_enquiry(
        pg_session,
        payload=InboundEnquiryCreate(full_name="Unqualified contact"),
        user_id=user,
        organization_id=org,
    )
    enquiry = await pg_session.get(CrmInboundEnquiry, response.id)
    item = await matching._upsert_match(
        pg_session,
        enquiry=enquiry,
        target_type="unit",
        target_key="test",
        score=99,
        title="Unit",
        subtitle="",
        reasons=[],
        breakdown={},
        snapshot={},
    )
    assert item.fit == "near"
    assert item.missing_fields == ["location", "budget", "property details"]
    item.state = "stale"
    await pg_session.commit()
    refreshed = await matching._upsert_match(
        pg_session,
        enquiry=enquiry,
        target_type="unit",
        target_key="test",
        score=50,
        title="Unit",
        subtitle="",
        reasons=[],
        breakdown={},
        snapshot={},
    )
    assert (refreshed.state, refreshed.fit) == ("suggested", "review")
