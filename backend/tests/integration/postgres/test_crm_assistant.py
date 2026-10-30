"""CRM Assistant: conversations, pending actions and organisation isolation on real commits."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.crm.assistant import repository
from app.crm.assistant.models import (
    CrmAssistantAction,
    CrmAssistantConversation,
    CrmAssistantMessage,
)


def _now():
    return datetime.now(timezone.utc)


async def _conversation(db, user_id, organization_id, title="Leads chat"):
    conversation = CrmAssistantConversation(
        user_id=user_id,
        organization_id=organization_id,
        title=title,
        created_at=_now(),
        updated_at=_now(),
    )
    repository.save(db, conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def test_conversations_scoped_by_user_and_org(pg_session):
    """A colleague, or the same user after moving organisation, cannot see the chat."""
    owner, colleague = str(uuid4()), str(uuid4())
    org, other_org = str(uuid4()), str(uuid4())
    conversation = await _conversation(pg_session, owner, org)

    for user_id, organization_id in [(colleague, org), (owner, other_org)]:
        assert (
            await repository.get_conversation(pg_session, conversation.id, user_id, organization_id)
            is None
        )
        assert await repository.list_conversations(pg_session, user_id, organization_id) == []

    listed = await repository.list_conversations(pg_session, owner, org)
    assert [item.id for item in listed] == [conversation.id]


async def test_delete_removes_messages_only_for_owner(pg_session):
    owner, colleague, org = str(uuid4()), str(uuid4()), str(uuid4())
    conversation = await _conversation(pg_session, owner, org)
    repository.save(
        pg_session,
        CrmAssistantMessage(
            conversation_id=conversation.id, role="user", content="hi", created_at=_now()
        ),
    )
    await pg_session.commit()

    await repository.delete_conversation_records(pg_session, conversation.id, colleague, org)
    await pg_session.commit()
    assert len(await repository.list_messages(pg_session, conversation.id, owner, org)) == 1

    await repository.delete_conversation_records(pg_session, conversation.id, owner, org)
    await pg_session.commit()
    assert await repository.list_messages(pg_session, conversation.id, owner, org) == []
    assert await repository.get_conversation(pg_session, conversation.id, owner, org) is None


async def _action(db, user_id, organization_id, **overrides):
    action = CrmAssistantAction(
        id=uuid4().hex,
        organization_id=organization_id,
        user_id=user_id,
        enquiry_id=1,
        action_type="status",
        payload={"status": "qualified"},
        summary="Move lead to qualified",
        before={"status": "contacted"},
        after={"status": "qualified"},
        expires_at=_now() + timedelta(minutes=10),
        created_at=_now(),
        **overrides,
    )
    repository.save(db, action)
    await db.commit()
    return action


async def test_action_round_trips(pg_session):
    user, org = str(uuid4()), str(uuid4())
    action = await _action(pg_session, user, org)
    action_id = action.id
    pg_session.expire_all()

    loaded = await repository.get_action(pg_session, action_id, user, org)
    assert loaded.status == "pending"
    assert loaded.payload == {"status": "qualified"}
    assert loaded.expires_at.tzinfo is not None
    # Another user or organisation cannot load it by id.
    assert await repository.get_action(pg_session, action_id, str(uuid4()), org) is None
    assert await repository.get_action(pg_session, action_id, user, str(uuid4())) is None


async def test_claim_action_succeeds_once(pg_session):
    """Two Confirm clicks must not both run the change."""
    user, org = str(uuid4()), str(uuid4())
    action = await _action(pg_session, user, org)

    assert await repository.claim_action(pg_session, action.id) is True
    await pg_session.commit()
    assert await repository.claim_action(pg_session, action.id) is False


# Full flow on real commits: propose → confirm through the existing Leads services.


async def _lead(db, organization_id, name="Ahmed Khan"):
    from app.crm import inbound
    from app.crm.inbound_models import InboundEnquiryCreate

    return await inbound.create_inbound_enquiry(
        db,
        payload=InboundEnquiryCreate(
            full_name=name,
            intent="buy",
            record_kind="opportunity",
            phone="+971501234567",
            criteria={"locations": ["JVC"], "budget_max_aed": 2_000_000},
        ),
        user_id=str(uuid4()),
        organization_id=organization_id,
    )


def _deps(db, organization_id, user_id):
    from types import SimpleNamespace

    from app.crm.assistant.deps import AssistantDeps

    return AssistantDeps(
        db=db,
        user_id=user_id,
        organization_id=organization_id,
        organization_name="Test org",
        role="member",
        organization=SimpleNamespace(id=organization_id, name="Test org"),
    )


def _ctx(deps):
    from types import SimpleNamespace

    return SimpleNamespace(deps=deps)


async def test_status_confirm_changes_the_lead_with_both_activities(pg_session):
    from app.crm.assistant.actions import confirm_action
    from app.crm.assistant.tools import leads as tools
    from app.crm.inbound import get_inbound_enquiry

    org, user = str(uuid4()), str(uuid4())
    lead = await _lead(pg_session, org)
    deps = _deps(pg_session, org, user)

    proposed = await tools.propose_status_change(
        _ctx(deps), lead_id=lead.id, new_status="qualified"
    )
    unchanged = await get_inbound_enquiry(pg_session, lead.id, org)
    assert unchanged.status == lead.status

    result = await confirm_action(deps, action_id=proposed["action_id"])
    assert result.status == "confirmed"
    pg_session.expire_all()
    changed = await get_inbound_enquiry(pg_session, lead.id, org)
    assert changed.status == "qualified"
    kinds = [activity.activity_type for activity in changed.activities]
    assert "status_changed" in kinds and "assistant" in kinds
    stored = await repository.get_action(pg_session, proposed["action_id"], user, org)
    assert stored.status == "confirmed"


async def test_cross_org_full_flow_leaves_org_b_untouched(pg_session):
    import pytest
    from fastapi import HTTPException

    from app.crm.assistant.actions import confirm_action
    from app.crm.assistant.tools import leads as tools
    from app.crm.inbound_models import CrmInboundEnquiry

    org_a, org_b, user_a, user_b = (str(uuid4()) for _ in range(4))
    lead_b = await _lead(pg_session, org_b, name="Org B Buyer")
    before = (await pg_session.get(CrmInboundEnquiry, lead_b.id)).model_dump()
    deps_a = _deps(pg_session, org_a, user_a)

    assert await tools.get_lead(_ctx(deps_a), lead_id=lead_b.id) == {"error": "Lead not found"}
    assert (await tools.search_leads(_ctx(deps_a), query="Org B Buyer"))["total"] == 0
    assert await tools.propose_status_change(_ctx(deps_a), lead_id=lead_b.id, new_status="won") == {
        "error": "Lead not found"
    }

    # An action org B's user proposed cannot be confirmed from org A, even with its id.
    proposed_b = await tools.propose_status_change(
        _ctx(_deps(pg_session, org_b, user_b)), lead_id=lead_b.id, new_status="won"
    )
    for deps in (deps_a, _deps(pg_session, org_a, user_b)):
        with pytest.raises(HTTPException) as error:
            await confirm_action(deps, action_id=proposed_b["action_id"])
        assert error.value.status_code == 404

    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, lead_b.id)).model_dump() == before
