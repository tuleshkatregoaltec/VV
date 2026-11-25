"""Assigning a listed lead over several turns: "assign Priya's lead" → "To whom?" → "User 1".

Agency (crm_role_support): Nadia manages North (Omar, Sara); Karim manages South (Lina).
"""

from types import SimpleNamespace

import pytest
from crm_role_support import agency, lead
from fastapi import HTTPException

from app.assistant_actions import service
from app.assistant_actions.models import ActionKind, AssignLead
from app.chat.conversations import add_message
from app.chat.models import Conversation
from app.crm import assignment
from app.crm.assistant import workflows
from app.crm.assistant.agent import _convert_to_pydantic_messages
from app.crm.assistant.dependencies import ChatDependencies
from app.crm.assistant.service import get_conversation_messages
from app.crm.inbound_models import CrmInboundEnquiry

# CRM display names: first and last name, as the member directory stores them.
NAMES = {
    "owner": ("Agency", "Owner"),
    "nadia": ("Nadia", "Manager"),
    "omar": ("User", "1"),
    "sara": ("User", "10"),  # Begins with "User 1": must not make "User 1" ambiguous.
    "karim": ("User 1", "Khan"),  # South's manager: not someone Nadia may assign to.
    "lina": ("User", "1"),  # Same name as Omar, in South.
}


@pytest.fixture
async def office(pg_session, monkeypatch):
    from app.organization import service as organizations

    ids = await agency(pg_session)
    people = {ids[person]: name for person, name in NAMES.items()}

    async def profile(user_id):
        first, last = people.get(user_id, ("Former", "Member"))
        return SimpleNamespace(first_name=first, last_name=last, email=f"{user_id}@example.test")

    monkeypatch.setattr(organizations, "get_user_by_id", profile)
    monkeypatch.setattr(service, "get_user_by_id", profile)

    async def session():
        yield pg_session

    monkeypatch.setattr(workflows, "get_db_session", session)
    priya = await lead(pg_session, ids, "Priya Rossi", team="north", assignee="sara")
    return SimpleNamespace(ids=ids, priya=priya)


async def _context(db, ids, person):
    conversation = Conversation(user_id=ids[person], organization_id=ids["org"])
    db.add(conversation)
    await db.commit()
    deps = ChatDependencies(ids[person], ids["org"], conversation_id=conversation.id)
    return conversation.id, deps


async def _lookup(db, ids, person, search):
    return await service.lookup_assignees(
        db, user_id=ids[person], organization_id=ids["org"], search=search
    )


# --- Display-name resolution -----------------------------------------------------------


async def test_exact_display_name_resolves_to_that_one_member(pg_session, office):
    ids = office.ids
    for typed in ("User 1", "user 1", "  User   1 "):
        result = await _lookup(pg_session, ids, "nadia", typed)
        # Not "User 10" (prefix only), not South's "User 1" or "User 1 Khan" (not assignable).
        assert result["matches"] == [{"id": ids["omar"], "display_name": "User 1"}], typed
        assert result["clarification_required"] is False
    # A partial name still lists everyone it begins, for the user to choose.
    partial = await _lookup(pg_session, ids, "nadia", "User")
    assert {item["id"] for item in partial["matches"]} == {ids["omar"], ids["sara"]}
    assert partial["clarification_required"] is True


async def test_same_exact_name_twice_asks_which_one(pg_session, office):
    ids = office.ids
    # The owner may assign into both teams, where two different people are "User 1".
    result = await _lookup(pg_session, ids, "owner", "User 1")
    assert {item["id"] for item in result["matches"]} == {ids["omar"], ids["lina"]}
    assert result["clarification_required"] is True


async def test_unknown_or_unassignable_names_ask_for_clarification(pg_session, office):
    ids = office.ids
    # Karim exists, but outside Nadia's teams: answered exactly like a name nobody has.
    for typed in ("User 1 Khan", "User 7"):
        result = await _lookup(pg_session, ids, "nadia", typed)
        assert result["matches"] == [] and result["clarification_required"] is True, typed
        assert result["reason"] == "No one you can assign this lead to has that name"


# --- The pending request survives the clarifying turn -----------------------------------


async def test_pending_assignment_survives_the_clarifying_question(pg_session, office):
    ids, priya = office.ids, office.priya
    conversation_id, deps = await _context(pg_session, ids, "nadia")
    ctx = SimpleNamespace(deps=deps, tool_call_id="hold")
    held = await workflows.hold_pending_request(ctx, lead_id=priya.id, kind=ActionKind.ASSIGN_LEAD)
    assert held["available"] is True
    assert held["held"] == {"kind": "assign_lead", "lead_id": priya.id, "details": {}}
    scope = dict(user_id=ids["nadia"], organization_id=ids["org"])
    await add_message(pg_session, conversation_id, "user", "Assign Priya's lead", **scope)
    await add_message(
        pg_session,
        conversation_id,
        "assistant",
        "Who should Priya Rossi's lead be assigned to?",
        {"guardrail_version": 1, "private": True, "evidence": deps.evidence},
        **scope,
    )
    await add_message(pg_session, conversation_id, "user", "User 1", **scope)

    async def history():
        messages = await get_conversation_messages(
            pg_session, conversation_id, **scope, include_retrieval_context=True
        )
        return messages, str(_convert_to_pydantic_messages(messages[:-1]))

    messages, replay = await history()
    # The user still sees the question; the model gets the request and lead, not the prose.
    assert messages[1].content == "Who should Priya Rossi's lead be assigned to?"
    assert '"kind": "assign_lead"' in replay and f'"lead_id": {priya.id}' in replay
    assert "Priya" not in replay and "Assign Priya" not in replay

    # Access is rechecked every turn: once the lead leaves Nadia's team the request is gone.
    owner = await assignment.load_scope(pg_session, ids["org"], ids["owner"])
    await assignment.reassign(pg_session, owner, [priya.id], ids["lina"], team_id=ids["south"])
    await pg_session.commit()
    messages, replay = await history()
    assert "pending request" not in replay and str(priya.id) not in replay
    assert messages[1].meta_data.get("restricted") is True


async def test_a_later_answer_settles_the_pending_request(pg_session, office):
    ids, priya = office.ids, office.priya
    conversation_id, deps = await _context(pg_session, ids, "nadia")
    await workflows.hold_pending_request(
        SimpleNamespace(deps=deps, tool_call_id="hold"),
        lead_id=priya.id,
        kind=ActionKind.ASSIGN_LEAD,
    )
    scope = dict(user_id=ids["nadia"], organization_id=ids["org"])
    private = {"guardrail_version": 1, "private": True, "evidence": deps.evidence}
    await add_message(pg_session, conversation_id, "assistant", "To whom?", private, **scope)
    await add_message(pg_session, conversation_id, "user", "Never mind", **scope)
    await add_message(
        pg_session, conversation_id, "assistant", "Okay.", {"guardrail_version": 1}, **scope
    )
    await add_message(pg_session, conversation_id, "user", "User 1", **scope)
    messages = await get_conversation_messages(
        pg_session, conversation_id, **scope, include_retrieval_context=True
    )
    assert "pending request" not in str(_convert_to_pydantic_messages(messages[:-1]))


async def test_only_someone_who_may_assign_the_lead_can_hold_its_assignment(pg_session, office):
    ids, priya = office.ids, office.priya
    own = await lead(pg_session, ids, "OmarLead", team="north", assignee="omar")
    _, agent_deps = await _context(pg_session, ids, "omar")
    ctx = SimpleNamespace(deps=agent_deps, tool_call_id="hold")
    # An agent cannot reassign, even their own lead; another agent's lead is not visible.
    for target in (own, priya):
        result = await workflows.hold_pending_request(
            ctx, lead_id=target.id, kind=ActionKind.ASSIGN_LEAD
        )
        assert result["available"] is False
    assert agent_deps.evidence == []


# --- Confirmation ----------------------------------------------------------------------


async def test_user_1_is_proposed_with_lead_and_assignee_and_assigned_only_on_confirm(
    pg_session, office
):
    ids, priya = office.ids, office.priya
    _, deps = await _context(pg_session, ids, "nadia")
    ctx = SimpleNamespace(deps=deps, tool_call_id="assign-1")
    found = await workflows.find_assignment_colleagues(ctx, "User 1")
    assert found["matches"] == [{"id": ids["omar"], "display_name": "User 1"}]
    proposal = await workflows.propose_crm_action(
        ctx, ActionKind.ASSIGN_LEAD, AssignLead(lead_id=priya.id, assignee_id=ids["omar"])
    )
    assert proposal["confirmation_required"] is True
    assert proposal["preview"]["lead"].startswith("Priya Rossi")
    assert proposal["preview"]["current_assignee"] == "User 10"
    assert proposal["preview"]["new_assignee"] == "User 1"
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, priya.id)).assigned_user_id == ids["sara"]

    confirmed = await service.confirm_action(
        pg_session,
        user_id=ids["nadia"],
        organization_id=ids["org"],
        action_id=deps.proposals[0]["id"],
    )
    assert confirmed.status == "succeeded"
    pg_session.expire_all()
    assert (await pg_session.get(CrmInboundEnquiry, priya.id)).assigned_user_id == ids["omar"]


async def test_ambiguous_or_unassignable_names_never_reach_a_proposal(pg_session, office):
    ids, priya = office.ids, office.priya
    # The owner's "User 1" is two people: no ID may be chosen for them.
    _, owner_deps = await _context(pg_session, ids, "owner")
    ctx = SimpleNamespace(deps=owner_deps, tool_call_id="ambiguous")
    assert (await workflows.find_assignment_colleagues(ctx, "User 1"))["clarification_required"]
    refused = await workflows.propose_crm_action(
        ctx, ActionKind.ASSIGN_LEAD, AssignLead(lead_id=priya.id, assignee_id=ids["omar"])
    )
    assert refused["available"] is False and refused["clarification_required"] is True
    assert owner_deps.proposals == []
    # Nadia cannot hand North's lead to South's Lina, whatever ID is supplied.
    with pytest.raises(HTTPException) as error:
        await service.propose_action(
            pg_session,
            user_id=ids["nadia"],
            organization_id=ids["org"],
            request=service.ActionProposalRequest(
                kind="assign_lead",
                conversation_id=(await _context(pg_session, ids, "nadia"))[0],
                payload={"lead_id": priya.id, "assignee_id": ids["lina"]},
                idempotency_key="forged-assignee-1",
            ),
        )
    assert error.value.status_code == 403
