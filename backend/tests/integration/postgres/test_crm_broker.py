"""Real disposable PostgreSQL tests for CRM ownership and human-confirmed side effects."""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import select

from app.crm import broker
from app.crm.broker_models import (
    BrokerActionConfirmation,
    BrokerActionRequest,
    BrokerFollowUpRequest,
    BrokerListRequest,
    BrokerMatchRequest,
    BrokerRequirements,
    CrmBrokerAction,
)
from app.crm.inbound_models import (
    CrmInboundContact,
    CrmInboundEnquiry,
    CrmInboundMatch,
    CrmInboundNote,
)
from app.market.evidence import MarketAccessContext
from app.organization.models import Organization, OrganizationMembership


@pytest.fixture
async def broker_fixture(pg_session):
    await pg_session.run_sync(
        lambda session: CrmBrokerAction.__table__.create(session.get_bind(), checkfirst=True)
    )
    org, other_org, member, colleague, owner = (str(uuid4()) for _ in range(5))
    now = datetime(2026, 10, 3, 10, tzinfo=timezone.utc)
    pg_session.add_all(
        [Organization(id=org, name="Broker test"), Organization(id=other_org, name="Other test")]
    )
    await pg_session.flush()
    pg_session.add_all(
        [
            OrganizationMembership(organization_id=org, user_id=member),
            OrganizationMembership(organization_id=org, user_id=colleague),
            OrganizationMembership(organization_id=org, user_id=owner, role="owner"),
        ]
    )
    contacts = [
        CrmInboundContact(
            organization_id=org,
            full_name=f"Fixture {i}",
            phone=f"private-{i}",
            consent_status="provided",
            created_at=now,
            updated_at=now,
        )
        for i in range(3)
    ]
    pg_session.add_all(contacts)
    await pg_session.flush()
    criteria = {
        "locations": ["JVC"],
        "property_type": "Apartment",
        "bedrooms_min": 1,
        "bedrooms_max": 1,
        "budget_max_aed": 1_200_000,
        "budget_max_inclusive": False,
    }
    rows = []
    for contact, creator, assigned in [
        (contacts[0], colleague, member),
        (contacts[0], member, None),
        (contacts[1], member, colleague),
        (contacts[2], colleague, None),
    ]:
        row = CrmInboundEnquiry(
            organization_id=org,
            contact_id=contact.id,
            created_by_user_id=creator,
            assigned_user_id=assigned,
            record_kind="opportunity",
            intent="buy",
            status="qualified",
            criteria=criteria,
            next_follow_up=date(2026, 10, 3),
            enquiry_date=now,
            created_at=now,
            updated_at=now,
        )
        pg_session.add(row)
        rows.append(row)
    await pg_session.commit()
    actor = MarketAccessContext(member, org, date(2026, 10, 3), "fixture-turn")
    admin = MarketAccessContext(owner, org, date(2026, 10, 3), "fixture-owner")
    return actor, admin, colleague, contacts, rows


async def test_broker_ownership_counts_paging_and_reassignment_revoke_creator(
    pg_session, broker_fixture
):
    actor, owner, colleague, contacts, rows = broker_fixture
    listed = await broker._list(pg_session, actor, BrokerListRequest(limit=1))
    assert (listed["enquiry_count"], listed["unique_contact_count"], listed["returned_count"]) == (
        2,
        1,
        1,
    )
    assert listed["has_more"] is True
    assert "private-" not in str(listed)
    all_org = await broker._list(pg_session, owner, BrokerListRequest(scope="organization"))
    assert (all_org["enquiry_count"], all_org["unique_contact_count"]) == (4, 3)
    for action in [
        broker.require_enquiry(pg_session, actor, rows[2].id),
        broker.require_enquiry(pg_session, actor, rows[3].id),
        broker._list(pg_session, actor, BrokerListRequest(scope="organization")),
        broker.require_enquiry(
            pg_session,
            MarketAccessContext(actor.user_id, str(uuid4()), actor.reference_date, "wrong"),
            rows[0].id,
        ),
    ]:
        with pytest.raises(HTTPException):
            await action
    rows[1].assigned_user_id = colleague
    await pg_session.commit()
    with pytest.raises(HTTPException, match="404"):
        await broker.require_enquiry(pg_session, actor, rows[1].id)


async def test_broker_action_proposal_is_inert_and_confirmation_is_atomic_idempotent(
    pg_session, broker_fixture
):
    actor, _, colleague, _, rows = broker_fixture
    target = rows[0]
    proposed = await broker.prepare_broker_action(
        pg_session,
        actor,
        BrokerActionRequest(
            enquiry_id=target.id,
            action="follow_up",
            due_date=date(2026, 10, 8),
            body="Confirm preferred viewing time",
        ),
    )
    count = (
        select(func.count())
        .select_from(CrmInboundNote)
        .where(CrmInboundNote.enquiry_id == target.id)
    )
    assert (await pg_session.exec(count)).one() == 0
    assert target.next_follow_up == date(2026, 10, 3)
    confirm = BrokerActionConfirmation(proposal_id=proposed["proposal"]["proposal_id"])
    unauthorized = MarketAccessContext(
        colleague, actor.organization_id, actor.reference_date, "other"
    )
    with pytest.raises(HTTPException):
        await broker.confirm_broker_action(pg_session, unauthorized, confirm)
    result = await broker.confirm_broker_action(pg_session, actor, confirm)
    assert result["status"] == "completed" and result["already_completed"] is False
    replay = await broker.confirm_broker_action(pg_session, actor, confirm)
    assert replay["already_completed"] is True
    assert (await pg_session.exec(count)).one() == 1
    await pg_session.refresh(target)
    assert target.next_follow_up == date(2026, 10, 8)
    assert target.status == "qualified" and target.contact_attempt_count == 0
    assert target.first_contact_at is None and target.last_contact_at is None
    detail = await broker._enquiry_projection(pg_session, target, actor, history=True)
    assert detail["activities"][0]["type"] == "note"
    assert detail["notes"][0]["body"] == "Confirm preferred viewing time"
    assert detail["qualification_gaps"] == []
    assert detail["match_summary"]["stored_count"] == 0


async def test_broker_confirmation_rejects_stale_or_reassigned_proposals(
    pg_session, broker_fixture
):
    actor, _, colleague, _, rows = broker_fixture
    for reassigned in (False, True):
        target = rows[0 if not reassigned else 1]
        proposed = await broker.prepare_broker_action(
            pg_session,
            actor,
            BrokerActionRequest(
                enquiry_id=target.id,
                action="note",
                body="Proposed only",
            ),
        )
        if reassigned:
            target.assigned_user_id = colleague
        else:
            target.updated_at += timedelta(seconds=1)
        await pg_session.commit()
        with pytest.raises(HTTPException) as error:
            await broker.confirm_broker_action(
                pg_session,
                actor,
                BrokerActionConfirmation(
                    proposal_id=proposed["proposal"]["proposal_id"],
                ),
            )
        assert error.value.status_code == (404 if reassigned else 409)
        assert (
            await pg_session.exec(
                select(func.count())
                .select_from(CrmInboundNote)
                .where(CrmInboundNote.enquiry_id == target.id)
            )
        ).one() == 0


async def add_matches(db, enquiry):
    rows = []
    for price, state in [
        (1_199_999.99, "suggested"),
        (1_200_000, "suggested"),
        (1_100_000, "stale"),
    ]:
        row = CrmInboundMatch(
            enquiry_id=enquiry.id,
            organization_id=enquiry.organization_id,
            target_type="listing",
            target_key=str(uuid4()),
            score=85,
            fit="near",
            state=state,
            title="Property",
            subtitle="",
            reasons=[],
            score_breakdown={},
            snapshot={
                "area_name": "Jumeirah Village Circle",
                "tower_name": "Fixture Tower",
                "property_type": "Apartment",
                "bedrooms": "1",
                "price_value": price,
                "price_currency": "AED",
                "phone": "must-not-leak",
                "agent_name": "must-not-leak",
            },
            generated_at=enquiry.updated_at,
            updated_at=enquiry.updated_at,
        )
        db.add(row)
        rows.append(row)
    await db.commit()
    return rows


async def test_broker_matching_preserves_strict_budgets_and_safe_document_selection(
    pg_session, broker_fixture
):
    actor, _, _, _, enquiries = broker_fixture
    matches = await add_matches(pg_session, enquiries[0])
    result = await broker.client_matches(pg_session, actor, enquiries[0].id)
    assert [row["match_id"] for row in result["matches"]] == [matches[0].id]
    assert result["review_candidates"][0]["fit"] == "outside"
    assert "must-not-leak" not in str(result)
    narrowed = await broker.client_matches(
        pg_session,
        actor,
        enquiries[0].id,
        requirements=BrokerRequirements(budget_max_aed=1_100_000),
    )
    assert narrowed["matches"] == []  # Additional constraints intersect rather than overwrite.
    selected = await broker.require_matches(pg_session, actor, enquiries[0].id, [matches[0].id])
    assert selected[0]["property"]["price_aed"] == 1_199_999.99
    with pytest.raises(HTTPException):
        await broker.require_matches(
            pg_session,
            actor,
            enquiries[0].id,
            [matches[0].id],
            requirements=BrokerRequirements(budget_max_aed=1_100_000),
        )
    for bad in (matches[1].id, matches[2].id):
        with pytest.raises(HTTPException):
            await broker.require_matches(pg_session, actor, enquiries[0].id, [bad])
    with pytest.raises(HTTPException):
        await broker.require_matches(pg_session, actor, enquiries[1].id, [matches[0].id])


async def test_broker_draft_respects_contact_restrictions_and_viewing_requires_match(
    pg_session, broker_fixture
):
    actor, _, _, contacts, enquiries = broker_fixture
    contact = contacts[0]
    draft = BrokerFollowUpRequest(mode="draft_message", enquiry_id=enquiries[0].id)
    result = await broker._follow_up(pg_session, actor, draft)
    assert result["message_sent"] is False and result["review_required"] is True
    assert result["recorded_requirements"] == enquiries[0].criteria
    for field, value in (("do_not_contact", True), ("consent_status", "withdrawn")):
        contact.do_not_contact = False
        setattr(contact, field, value)
        await pg_session.commit()
        result = await broker._follow_up(pg_session, actor, draft)
        assert result["status"] == "unavailable" and result["reason"] == "contact_restricted"
    brief = await broker._follow_up(
        pg_session,
        actor,
        BrokerFollowUpRequest(
            mode="viewing_brief",
            enquiry_id=enquiries[0].id,
        ),
    )
    assert brief["status"] == "clarification_required"
    await pg_session.refresh(enquiries[0])
    assert enquiries[0].contact_attempt_count == 0


async def test_broker_reverse_matching_cannot_disclose_a_colleagues_demand(
    pg_session, broker_fixture
):
    actor, _, _, _, rows = broker_fixture
    property_enquiry = rows[1]
    property_enquiry.intent = "sell"
    property_enquiry.criteria = {
        "locations": ["JVC"],
        "building": "Fixture Tower",
        "unit_number": "101",
        "property_type": "Apartment",
        "bedrooms_min": 1,
        "expected_price_aed": 1_000_000,
    }
    for demand in (rows[0], rows[2]):
        pg_session.add(
            CrmInboundMatch(
                enquiry_id=property_enquiry.id,
                organization_id=actor.organization_id,
                target_type="demand",
                target_key=str(demand.id),
                score=90,
                fit="exact",
                title="Private name",
                subtitle="",
                snapshot={"phone": "secret", "enquiry_id": demand.id},
                generated_at=property_enquiry.updated_at,
                updated_at=property_enquiry.updated_at,
            )
        )
    await pg_session.commit()
    result = await broker._reverse(
        pg_session, actor, BrokerMatchRequest(enquiry_id=property_enquiry.id)
    )
    assert result["matched_enquiry_count"] == result["matched_unique_contact_count"] == 1
    assert result["clients"][0]["enquiry"]["enquiry_id"] == rows[0].id
    assert result["clients"][0]["enquiry"]["interest"]["status"] == "recorded_open"
    assert "secret" not in str(result)
