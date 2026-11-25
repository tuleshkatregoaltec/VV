"""Qualifying an Inbox contact: the Inbox's "Qualify lead" saves through the ordinary lead edit
(PATCH /crm/inbound/enquiries/{id} → `update_inbound_enquiry`), so the same enquiry becomes a lead
under the same authority as any edit.

Agency (crm_role_support): Nadia manages North (Omar, Sara); Karim manages South (Lina).
"""

from datetime import UTC, datetime

import pytest
from crm_role_support import agency, lead
from fastapi import HTTPException
from sqlmodel import func, select

from app.crm import inbound
from app.crm.inbound_models import (
    CrmInboundAssignmentEvent,
    CrmInboundEnquiry,
    CrmInboundNote,
    InboundEnquiryCreate,
    InboundEnquiryUpdate,
)

BRIEFS = {
    "buy": {"locations": ["JVC"], "budget_max_aed": 1_500_000},
    "rent": {"locations": ["JVC"], "budget_max_aed": 120_000},
    "sell": {"building": "Marina Gate", "unit_number": "1204"},
    "let": {"building": "Bloom Towers", "unit_number": "305"},
}


async def _contact(db, ids, holder="omar"):
    """An unqualified Inbox contact Omar created: his, in North, with history and a note."""
    created = await inbound.create_inbound_enquiry(
        db,
        payload=InboundEnquiryCreate(full_name="Hana Unqualified"),
        user_id=ids[holder],
        organization_id=ids["org"],
    )
    db.add(
        CrmInboundNote(
            enquiry_id=created.id,
            organization_id=ids["org"],
            user_id=ids["nadia"],
            body="Called about a 2BR",
            created_at=datetime.now(UTC),
        )
    )
    await db.commit()
    return created.id


async def _qualify(db, ids, actor, enquiry_id, intent):
    return await inbound.update_inbound_enquiry(
        db,
        enquiry_id=enquiry_id,
        organization_id=ids["org"],
        user_id=ids[actor],
        payload=InboundEnquiryUpdate(intent=intent, criteria=BRIEFS[intent]),
    )


async def _history(db, enquiry_id):
    events = (
        await db.exec(
            select(CrmInboundAssignmentEvent).where(
                CrmInboundAssignmentEvent.enquiry_id == enquiry_id
            )
        )
    ).all()
    notes = (
        await db.exec(
            select(func.count())
            .select_from(CrmInboundNote)
            .where(CrmInboundNote.enquiry_id == enquiry_id)
        )
    ).one()
    return [(e.assigned_user_id, e.reason, e.revision) for e in events], notes


@pytest.mark.parametrize("intent", list(BRIEFS))
async def test_qualifying_turns_the_same_enquiry_into_a_lead(pg_session, intent):
    ids = await agency(pg_session)
    enquiry_id = await _contact(pg_session, ids)
    before = await pg_session.get(CrmInboundEnquiry, enquiry_id)
    holder, team, revision = before.assigned_user_id, before.team_id, before.assignment_revision
    history = await _history(pg_session, enquiry_id)
    assert before.intent == "unknown" and before.record_kind == "unqualified_contact"

    response = await _qualify(pg_session, ids, "omar", enquiry_id, intent)

    assert response.id == enquiry_id
    pg_session.expire_all()
    after = await pg_session.get(CrmInboundEnquiry, enquiry_id)
    # Classified as the CRM's own lead edit does it.
    assert after.intent == intent and after.record_kind == "opportunity"
    assert after.confirmed_data == {"intent": intent, "criteria": BRIEFS[intent]}
    assert after.criteria == BRIEFS[intent]
    # Same holder, team and assignment history; the note is still there.
    assert (after.assigned_user_id, after.team_id) == (holder, team)
    assert after.assignment_revision == revision
    assert await _history(pg_session, enquiry_id) == history
    # Still one enquiry for the contact: nothing was duplicated.
    assert (
        await pg_session.exec(
            select(func.count())
            .select_from(CrmInboundEnquiry)
            .where(CrmInboundEnquiry.contact_id == after.contact_id)
        )
    ).one() == 1

    # It leaves the Inbox's unqualified list and appears in Leads.
    async def ids_in(**filters):
        listed = await inbound.list_inbound_enquiries(
            pg_session,
            organization_id=ids["org"],
            user_id=ids["omar"],
            intent_group=None,
            workspace=filters.get("workspace"),
            status=None,
            search=None,
            limit=50,
            offset=0,
            leads_only=filters.get("leads_only", False),
        )
        return {item.id for item in listed.enquiries}

    assert enquiry_id in await ids_in(leads_only=True)
    assert enquiry_id not in await ids_in(workspace="unqualified")


async def test_qualifying_follows_who_may_edit_the_enquiry(pg_session):
    ids = await agency(pg_session)
    enquiry_id = await _contact(pg_session, ids)
    # A teammate and another team's agent cannot see Omar's contact: refused like a missing one.
    for actor in ("sara", "lina", "karim"):
        with pytest.raises(HTTPException) as error:
            await _qualify(pg_session, ids, actor, enquiry_id, "buy")
        assert error.value.status_code == 404, actor
        await pg_session.rollback()
    # A contact waiting in North's pool is read only for North's agents until claimed.
    pooled = await lead(
        pg_session, ids, "Pooled", team="north", assignee=None, pooled=True, intent="unknown"
    )
    with pytest.raises(HTTPException) as error:
        await _qualify(pg_session, ids, "sara", pooled.id, "rent")
    assert error.value.status_code == 409
    await pg_session.rollback()
    pg_session.expire_all()
    untouched = await pg_session.get(CrmInboundEnquiry, enquiry_id)
    assert untouched.intent == "unknown" and untouched.record_kind == "unqualified_contact"
    assert (await pg_session.get(CrmInboundEnquiry, pooled.id)).intent == "unknown"
    # North's manager and the owner may qualify what they can edit; the pool keeps its state.
    await _qualify(pg_session, ids, "nadia", pooled.id, "rent")
    await _qualify(pg_session, ids, "owner", enquiry_id, "sell")
    pg_session.expire_all()
    still_pooled = await pg_session.get(CrmInboundEnquiry, pooled.id)
    assert still_pooled.assigned_user_id is None and still_pooled.pool_released_at is not None


async def test_another_organization_cannot_qualify_the_contact(pg_session):
    ids = await agency(pg_session)
    other = await agency(pg_session)
    enquiry_id = await _contact(pg_session, ids)
    with pytest.raises(HTTPException) as error:
        await inbound.update_inbound_enquiry(
            pg_session,
            enquiry_id=enquiry_id,
            organization_id=other["org"],
            user_id=other["owner"],
            payload=InboundEnquiryUpdate(intent="buy", criteria=BRIEFS["buy"]),
        )
    assert error.value.status_code == 404
