from datetime import UTC, datetime
from uuid import uuid4

from app.chat import repository, service
from app.chat.agent import _convert_to_pydantic_messages
from app.chat.models import Message
from app.chat.security import RESTRICTED_HISTORY, fingerprint, safe_data
from app.crm.assistant import query_my_records
from app.crm.assistant_models import CrmAssistantQuery
from app.crm.inbound_models import (
    CrmInboundActivity,
    CrmInboundContact,
    CrmInboundEnquiry,
    CrmInboundNote,
)
from app.organization.models import Organization, OrganizationMembership


async def test_notes_and_history_disappear_after_assignment_revocation(pg_session):
    user, other, org = [str(uuid4()) for _ in range(3)]
    pg_session.add(Organization(id=org, name="Workflow test", subscription_status="active"))
    await pg_session.flush()
    pg_session.add(OrganizationMembership(user_id=user, organization_id=org))
    await pg_session.commit()
    now = datetime.now(UTC)
    scope = {"user_id": user, "organization_id": org}
    contact = CrmInboundContact(
        organization_id=org, full_name="Private customer", created_at=now, updated_at=now
    )
    pg_session.add(contact)
    await pg_session.flush()
    lead = CrmInboundEnquiry(
        organization_id=org,
        contact_id=contact.id,
        created_by_user_id=user,
        assigned_user_id=user,
        intent="buy",
        status="new",
        enquiry_date=now,
        created_at=now,
        updated_at=now,
    )
    pg_session.add(lead)
    await pg_session.flush()
    for author in (user, other):
        pg_session.add(
            CrmInboundNote(
                organization_id=org,
                user_id=author,
                enquiry_id=lead.id,
                body=f"Private note {author}",
                created_at=now,
            )
        )
        pg_session.add(
            CrmInboundActivity(
                organization_id=org,
                user_id=author,
                enquiry_id=lead.id,
                activity_type="call",
                body=f"Private activity {author}",
                created_at=now,
            )
        )
    await pg_session.commit()
    for resource in ("lead_notes", "lead_activities"):
        data = await query_my_records(pg_session, CrmAssistantQuery(resource=resource), **scope)
        # Every author's entries on a lead the user holds, as on the CRM lead page.
        assert data.total == 2
        assert {row["author"] for row in data.records} == {"you", "colleague"}
    request = CrmAssistantQuery(resource="leads", record_id=lead.id)
    data = await query_my_records(pg_session, request, **scope)
    payload = safe_data(data.model_dump(mode="json"))
    payload["source"] = "Your CRM records"
    conversation = await service.create_conversation(pg_session, user, org)
    await service.add_message(
        pg_session,
        conversation.id,
        "assistant",
        "Private customer is new",
        {
            "guardrail_version": 1,
            "private": True,
            "evidence": [
                {"query": request.model_dump(mode="json"), "fingerprint": fingerprint(payload)}
            ],
            "artifacts": [{"type": "chart", "data": "Private customer"}],
        },
        **scope,
    )
    visible = await service.get_conversation_messages(pg_session, conversation.id, **scope)
    assert visible[0].content == "Private customer is new"
    assert "evidence" not in visible[0].meta_data
    assert _convert_to_pydantic_messages(visible) == []
    lead.assigned_user_id = other
    pg_session.add(lead)
    await pg_session.commit()
    visible = await service.get_conversation_messages(pg_session, conversation.id, **scope)
    assert visible[0].content == RESTRICTED_HISTORY
    assert "artifacts" not in visible[0].meta_data
    for resource in ("lead_notes", "lead_activities"):
        assert (
            await query_my_records(pg_session, CrmAssistantQuery(resource=resource), **scope)
        ).records == []
    # Redaction must never overwrite the historical stored record.
    stored = await repository.get_conversation_messages(pg_session, conversation.id, **scope)
    assert stored[0].content == "Private customer is new"


async def test_latest_history_is_chronological_and_before_id_pages_without_overlap(pg_session):
    user, org = str(uuid4()), str(uuid4())
    conversation = await service.create_conversation(pg_session, user, org)
    for number in range(105):
        pg_session.add(Message(conversation_id=conversation.id, role="user", content=str(number)))
    await pg_session.commit()
    latest = await service.get_conversation_messages(pg_session, conversation.id, user, org)
    assert [int(row.content) for row in latest] == list(range(5, 105))
    previous = await service.get_conversation_messages(
        pg_session, conversation.id, user, org, before_id=latest[0].id
    )
    assert [int(row.content) for row in previous] == list(range(5))
    legacy = await service.add_message(
        pg_session,
        conversation.id,
        "assistant",
        "Old private answer without evidence",
        user_id=user,
        organization_id=org,
    )
    visible = await service.get_conversation_messages(pg_session, conversation.id, user, org)
    assert visible[-1].id == legacy.id and visible[-1].content == RESTRICTED_HISTORY


async def test_membership_revocation_and_subscription_change_block_private_retrieval(pg_session):
    import pytest
    from sqlalchemy import delete, update

    user, org = str(uuid4()), str(uuid4())
    organization = Organization(id=org, name="Revocation", subscription_status="active")
    member = OrganizationMembership(user_id=user, organization_id=org)
    pg_session.add(organization)
    await pg_session.flush()
    pg_session.add(member)
    await pg_session.commit()
    scope = {"user_id": user, "organization_id": org}
    request = CrmAssistantQuery(resource="leads")
    assert (await query_my_records(pg_session, request, **scope)).total == 0
    # Raw update leaves the previously loaded organization stale in the identity map.
    await pg_session.execute(
        update(Organization)
        .where(Organization.id == org)
        .values(subscription_status="past_due")
        .execution_options(synchronize_session=False)
    )
    await pg_session.commit()
    assert organization.subscription_status == "active"
    with pytest.raises(PermissionError):
        await query_my_records(pg_session, request, **scope)
    await pg_session.execute(
        update(Organization).where(Organization.id == org).values(subscription_status="active")
    )
    await pg_session.execute(
        delete(OrganizationMembership)
        .where(OrganizationMembership.id == member.id)
        .execution_options(synchronize_session=False)
    )
    await pg_session.commit()
    with pytest.raises(PermissionError):
        await query_my_records(pg_session, request, **scope)


async def test_renewal_research_only_reads_currently_owned_opened_lead(pg_session, monkeypatch):
    from unittest.mock import AsyncMock

    from pydantic import BaseModel

    from app.crm import opportunities
    from app.crm.inbound_models import VITEVUE_LEASE_SOURCE

    class Evidence(BaseModel):
        building_name: str = "Own building"
        annual_rent_aed: int = 90000
        secret_party: str = "Never disclose"

    from types import SimpleNamespace

    read = AsyncMock(return_value=SimpleNamespace(lead=Evidence()))
    monkeypatch.setattr(opportunities, "get_lead_detail", read)
    user, other, org = [str(uuid4()) for _ in range(3)]
    now = datetime.now(UTC)
    pg_session.add(Organization(id=org, name="Renewals", subscription_status="active"))
    await pg_session.flush()
    pg_session.add(OrganizationMembership(user_id=user, organization_id=org))
    contact = CrmInboundContact(
        organization_id=org, full_name="Own renewal", created_at=now, updated_at=now
    )
    pg_session.add(contact)
    await pg_session.flush()
    lead = CrmInboundEnquiry(
        organization_id=org,
        contact_id=contact.id,
        created_by_user_id=user,
        assigned_user_id=user,
        intent="rent",
        status="new",
        source=VITEVUE_LEASE_SOURCE,
        source_lead_id="private-unit-key",
        enquiry_date=now,
        created_at=now,
        updated_at=now,
    )
    pg_session.add(lead)
    await pg_session.commit()
    request = CrmAssistantQuery(resource="renewals", record_id=lead.id)
    scope = {"user_id": user, "organization_id": org}
    data = await query_my_records(pg_session, request, **scope)
    assert data.records[0]["renewal_evidence"] == {
        "building_name": "Own building",
        "annual_rent_aed": 90000,
    }
    assert "source_lead_id" not in data.records[0]
    read.assert_awaited_once_with("private-unit-key")
    lead.assigned_user_id = other
    pg_session.add(lead)
    await pg_session.commit()
    read.reset_mock()
    assert (await query_my_records(pg_session, request, **scope)).records == []
    read.assert_not_awaited()


async def test_confirmed_update_keeps_only_reauthorized_followup_handle(pg_session):
    from app.assistant_actions import service as actions
    from app.assistant_actions.models import ActionProposalRequest

    user, other, org = [str(uuid4()) for _ in range(3)]
    now = datetime.now(UTC)
    pg_session.add(Organization(id=org, name="Follow-up test", subscription_status="active"))
    await pg_session.flush()
    pg_session.add(OrganizationMembership(user_id=user, organization_id=org))
    contact = CrmInboundContact(
        organization_id=org, full_name="Private Alice", created_at=now, updated_at=now
    )
    pg_session.add(contact)
    await pg_session.flush()
    lead = CrmInboundEnquiry(
        organization_id=org,
        contact_id=contact.id,
        created_by_user_id=user,
        assigned_user_id=user,
        intent="buy",
        status="new",
        enquiry_date=now,
        created_at=now,
        updated_at=now,
    )
    pg_session.add(lead)
    await pg_session.commit()
    scope = {"user_id": user, "organization_id": org}
    conversation = await service.create_conversation(pg_session, **scope)
    query = CrmAssistantQuery(resource="leads", record_id=lead.id)
    evidence = safe_data(
        (await query_my_records(pg_session, query, **scope)).model_dump(mode="json")
    )
    evidence["source"] = "Your CRM records"
    handles = [{"resource": "leads", "record_id": lead.id}]
    await service.add_message(
        pg_session,
        conversation.id,
        "assistant",
        "Private Alice is new",
        {
            "guardrail_version": 1,
            "private": True,
            "evidence": [
                {
                    "query": query.model_dump(mode="json"),
                    "fingerprint": fingerprint(evidence),
                    "resource_refs": handles,
                }
            ],
        },
        **scope,
    )
    action = await actions.propose_action(
        pg_session,
        **scope,
        request=ActionProposalRequest(
            kind="update_lead",
            conversation_id=conversation.id,
            payload={"lead_id": lead.id, "status": "contacted"},
            idempotency_key=uuid4().hex,
        ),
    )
    assert (
        await actions.confirm_action(pg_session, **scope, action_id=action.id)
    ).status == "succeeded"
    messages = await service.get_conversation_messages(
        pg_session, conversation.id, **scope, include_retrieval_context=True
    )
    assert messages[0].content == RESTRICTED_HISTORY
    assert messages[0].meta_data["_retrieval_context"] == handles
    history = _convert_to_pydantic_messages(messages)
    assert history and "Private Alice" not in str(history)
    public = await service.get_conversation_messages(pg_session, conversation.id, **scope)
    assert "_retrieval_context" not in public[0].meta_data
    lead.assigned_user_id = other
    pg_session.add(lead)
    await pg_session.commit()
    revoked = await service.get_conversation_messages(
        pg_session, conversation.id, **scope, include_retrieval_context=True
    )
    assert "_retrieval_context" not in revoked[0].meta_data
    assert _convert_to_pydantic_messages(revoked) == []


async def test_manager_answer_withheld_after_losing_supervisor_role(pg_session):
    """A team answer given to a manager is private evidence of that role: once they are an
    agent again, history must not keep showing it."""
    import sqlalchemy as sa
    from crm_role_support import agency, lead

    from app.organization.models import OrganizationTeamMember

    ids = await agency(pg_session)
    await lead(pg_session, ids, "OmarLead", team="north", assignee="omar")
    scope = {"user_id": ids["nadia"], "organization_id": ids["org"]}
    request = CrmAssistantQuery(resource="leads", summary_only=True)
    data = await query_my_records(pg_session, request, **scope)
    assert data.total == 1
    payload = safe_data(data.model_dump(mode="json"))
    payload["source"] = "Your CRM records"
    conversation = await service.create_conversation(pg_session, **scope)
    await service.add_message(
        pg_session,
        conversation.id,
        "assistant",
        "Your team has 1 lead",
        {
            "guardrail_version": 1,
            "private": True,
            "evidence": [
                {"query": request.model_dump(mode="json"), "fingerprint": fingerprint(payload)}
            ],
        },
        **scope,
    )
    visible = await service.get_conversation_messages(pg_session, conversation.id, **scope)
    assert visible[0].content == "Your team has 1 lead"
    await pg_session.execute(
        sa.update(OrganizationTeamMember)
        .where(OrganizationTeamMember.user_id == ids["nadia"])
        .values(role="agent")
    )
    await pg_session.commit()
    visible = await service.get_conversation_messages(pg_session, conversation.id, **scope)
    assert visible[0].content == RESTRICTED_HISTORY
