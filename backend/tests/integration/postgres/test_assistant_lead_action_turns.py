"""Multi-turn lead actions through the real chat turn (`stream_chat_response`).

Only admission and the language model are replaced. The scripted "model" calls the real tools
(CRM search, hold_pending_request, colleague lookup, proposals), so history loading, privacy
checks, pending-request carry-over, evidence rechecks, persistence and proposals all run for
real against the database.

Agency (crm_role_support): Nadia manages North (Omar, Sara); Karim manages South (Lina).
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from crm_role_support import agency, lead
from sqlalchemy import delete, update
from sqlmodel import select

from app.assistant_actions import service as actions
from app.assistant_actions.models import ActionKind, AssignLead, LeadTarget
from app.chat import conversations
from app.chat.security import RESTRICTED_HISTORY
from app.crm import assignment
from app.crm.assistant import crm_tools, service, workflows
from app.crm.assistant.models import CrmAssistantQuery
from app.crm.inbound_models import CrmInboundAssignmentEvent, CrmInboundEnquiry
from app.organization.models import OrganizationTeamMember

NAMES = {
    "owner": ("Agency", "Owner"),
    "nadia": ("Nadia", "Manager"),
    "omar": ("User", "1"),
    "sara": ("User", "10"),
    "karim": ("Karim", "South"),
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
    monkeypatch.setattr(actions, "get_user_by_id", profile)

    async def session():
        yield pg_session

    for module in (workflows, crm_tools):
        monkeypatch.setattr(module, "get_db_session", session)
    monkeypatch.setattr(service.settings, "ASSISTANT_ENABLED", True)
    monkeypatch.setattr(service.settings, "ASSISTANT_TYPED_ROUTING_ENABLED", False)
    monkeypatch.setattr(
        service.admission, "acquire", AsyncMock(return_value=service.admission.TurnLease("l", 1))
    )
    monkeypatch.setattr(service.admission, "finish", AsyncMock())
    jvc = {"locations": ["JVC"]}
    priya = await lead(pg_session, ids, "Priya Rossi", team="north", assignee="sara", criteria=jvc)
    other = await lead(pg_session, ids, "Omar Buyer", team="north", assignee="omar", criteria=jvc)
    return SimpleNamespace(ids=ids, priya=priya, other=other, monkeypatch=monkeypatch)


class Chat:
    """One user's conversation; each `turn` runs the real chat turn with a scripted model."""

    def __init__(self, db, office, person):
        self.db, self.office, self.person = db, office, person
        self.scope = dict(user_id=office.ids[person], organization_id=office.ids["org"])
        self.seen: list[str] = []
        self.deps = None

    async def start(self):
        conversation = await conversations.create_conversation(self.db, **self.scope)
        self.conversation_id = conversation.id
        return self

    def ctx(self, name="call"):
        return SimpleNamespace(deps=self.deps, tool_call_id=name)

    async def turn(self, message, script):
        failure = []

        async def run(user_message, *, deps, message_history, **_):
            self.deps = deps
            # Everything the model is given about earlier turns.
            self.seen.append(json.dumps([str(m) for m in message_history]))
            try:
                return SimpleNamespace(output=await script())
            except AssertionError as error:  # The turn hides errors; the test must not.
                failure.append(error)
                raise

        self.office.monkeypatch.setattr(service, "agent", SimpleNamespace(run=run))
        events = [
            json.loads(event.removeprefix("data: "))
            async for event in service.stream_chat_response(
                self.db, self.conversation_id, message, **self.scope
            )
            if event.startswith("data: ")
        ]
        if failure:
            raise failure[0]
        content = [event["content"] for event in events if event["type"] == "content"]
        assert content, events
        return content[-1]

    @property
    def history(self) -> str:
        """What the model was given about earlier turns, as plain text."""
        return self.seen[-1].replace('\\"', '"')

    async def search(self, text):
        return await crm_tools.query_my_crm_records(
            self.ctx("search"), CrmAssistantQuery(resource="leads", search=text, limit=5)
        )

    async def hold(self, lead_id, kind=None):
        return await workflows.hold_pending_request(self.ctx("hold"), lead_id=lead_id, kind=kind)

    async def propose(self, kind, payload):
        return await workflows.propose_crm_action(self.ctx(f"propose-{kind}"), kind, payload)

    async def visible(self):
        return await service.get_conversation_messages(self.db, self.conversation_id, **self.scope)


def pending(lead_id, kind, details=None):
    return json.dumps({"details": details or {}, "kind": kind, "lead_id": lead_id}, sort_keys=True)


async def current(db, lead_id):
    db.expire_all()
    return await db.get(CrmInboundEnquiry, lead_id)


# --- Assign and unassign over several turns -----------------------------------------------


async def test_assign_over_several_turns_keeps_the_lead_and_writes_only_on_confirm(
    pg_session, office
):
    ids, priya = office.ids, office.priya
    chat = await Chat(pg_session, office, "nadia").start()

    async def find_jvc():
        found = await chat.search("JVC")
        assert {row["contact_name"] for row in found["records"]} == {"Priya Rossi", "Omar Buyer"}
        return "Two JVC leads: Priya Rossi and Omar Buyer."

    await chat.turn("Find JVC leads", find_jvc)

    async def select_priya():
        # Private answers are not replayed: only reauthorized handles reach the model.
        assert "Priya" not in chat.history and f'"record_id": {priya.id}' in chat.history
        found = await chat.search("Priya Rossi")
        assert [row["id"] for row in found["records"]] == [priya.id]
        assert (await chat.hold(priya.id, ActionKind.ASSIGN_LEAD))["available"] is True
        return "Who should Priya Rossi's lead be assigned to?"

    await chat.turn("Assign Priya's lead", select_priya)

    async def name_assignee():
        assert pending(priya.id, "assign_lead") in chat.history
        assert "Priya" not in chat.history
        found = await workflows.find_assignment_colleagues(chat.ctx("lookup"), "User 1")
        assert found["matches"] == [{"id": ids["omar"], "display_name": "User 1"}]
        proposal = await chat.propose(
            ActionKind.ASSIGN_LEAD, AssignLead(lead_id=priya.id, assignee_id=ids["omar"])
        )
        assert proposal["confirmation_required"] is True
        return "Please review and confirm the assignment."

    await chat.turn("User 1", name_assignee)
    action = chat.deps.proposals[0]
    assert action["preview"]["lead"] == f"Priya Rossi (lead #{priya.id})"
    assert action["preview"]["current_assignee"] == "User 10"
    assert action["preview"]["new_assignee"] == "User 1"
    assert "assignment history" in action["preview"]["consequence"]
    # Nothing changes before confirmation.
    assert (await current(pg_session, priya.id)).assigned_user_id == ids["sara"]

    # The proposal settled the request: it is not carried into the next turn.
    async def after():
        assert "pending request" not in chat.history
        return "Waiting for your confirmation."

    await chat.turn("Thanks", after)
    confirmed = await actions.confirm_action(pg_session, **chat.scope, action_id=action["id"])
    assert confirmed.status == "succeeded"
    assert (await current(pg_session, priya.id)).assigned_user_id == ids["omar"]


async def test_remove_is_clarified_then_unassigns_without_deleting(pg_session, office):
    ids, priya = office.ids, office.priya
    chat = await Chat(pg_session, office, "nadia").start()

    async def ambiguous_remove():
        found = await chat.search("Priya Rossi")
        assert [row["id"] for row in found["records"]] == [priya.id]
        # Lead chosen, action not: "remove" may mean unassign or delete.
        assert (await chat.hold(priya.id))["available"] is True
        return "Do you want to unassign Priya Rossi's lead, or delete the lead entirely?"

    await chat.turn("Remove Priya Rossi", ambiguous_remove)

    async def follow_up_question():
        assert pending(priya.id, None) in chat.history
        return "Unassigning keeps the lead; deleting removes it permanently. Which one?"

    # A turn that neither settles nor replaces the request keeps it (no tool calls here).
    await chat.turn("What is the difference?", follow_up_question)

    async def unassign():
        assert pending(priya.id, None) in chat.history
        proposal = await chat.propose(ActionKind.UNASSIGN_LEAD, LeadTarget(lead_id=priya.id))
        assert proposal["confirmation_required"] is True
        return "Please confirm unassigning the lead."

    await chat.turn("Just remove the assignment", unassign)
    action = chat.deps.proposals[0]
    assert action["preview"]["current_assignee"] == "User 10"
    assert action["preview"]["new_assignee"] == "Unassigned"
    assert "Nothing is deleted" in action["preview"]["consequence"]
    assert (await current(pg_session, priya.id)).assigned_user_id == ids["sara"]

    confirmed = await actions.confirm_action(pg_session, **chat.scope, action_id=action["id"])
    assert confirmed.status == "succeeded"
    after = await current(pg_session, priya.id)
    # Unassigned, still in North (managers keep seeing it), not deleted, and on the record.
    assert after is not None and after.assigned_user_id is None
    assert after.team_id == ids["north"]
    events = (
        await pg_session.exec(
            select(CrmInboundAssignmentEvent).where(
                CrmInboundAssignmentEvent.enquiry_id == priya.id
            )
        )
    ).all()
    assert [(e.previous_user_id, e.assigned_user_id, e.actor_user_id) for e in events] == [
        (ids["sara"], None, ids["nadia"])
    ]


async def test_a_pending_request_lapses_after_unrelated_turns(pg_session, office):
    priya = office.priya
    chat = await Chat(pg_session, office, "nadia").start()

    async def hold():
        await chat.hold(priya.id, ActionKind.ASSIGN_LEAD)
        return "Who should take it?"

    async def chat_only():
        return "Sure."

    await chat.turn("Assign Priya's lead", hold)
    for _ in range(service.PENDING_MAX_CARRIES):
        await chat.turn("Something else", chat_only)
        assert "pending request" in chat.history
    await chat.turn("Something else", chat_only)
    await chat.turn("User 1", chat_only)
    assert "pending request" not in chat.history


# --- Stale evidence and access changes ----------------------------------------------------


async def test_stale_private_answer_keeps_the_rechecked_pending_request(pg_session, office):
    priya = office.priya
    chat = await Chat(pg_session, office, "nadia").start()

    async def select_priya():
        # Both JVC leads are listed: Priya's and Omar Buyer's.
        await chat.search("JVC")
        await chat.hold(priya.id, ActionKind.ASSIGN_LEAD)
        return "Who should Priya Rossi's lead be assigned to?"

    await chat.turn("Assign Priya's lead", select_priya)
    # A change to the lead itself leaves the answer shown: Nadia still sees it.
    await pg_session.execute(
        update(CrmInboundEnquiry).where(CrmInboundEnquiry.id == priya.id).values(status="contacted")
    )
    await pg_session.commit()
    assert (await chat.visible())[-1].content != RESTRICTED_HISTORY
    # Omar Buyer's lead moves to South, out of Nadia's reach: the answer listing it is withheld.
    owner = await assignment.load_scope(pg_session, office.ids["org"], office.ids["owner"])
    await assignment.reassign(
        pg_session, owner, [office.other.id], office.ids["lina"], team_id=office.ids["south"]
    )
    await pg_session.commit()
    messages = await chat.visible()
    assert messages[-1].content == RESTRICTED_HISTORY

    async def still_pending():
        # The unavailable answer does not erase the still-permitted request and lead.
        assert pending(priya.id, "assign_lead") in chat.history
        assert "Priya" not in chat.history
        return "Who should it go to?"

    await chat.turn("Sorry, what was that?", still_pending)


async def test_losing_access_drops_the_request_and_blocks_the_proposal(pg_session, office):
    ids, priya = office.ids, office.priya
    chat = await Chat(pg_session, office, "nadia").start()

    async def select_priya():
        await chat.hold(priya.id, ActionKind.ASSIGN_LEAD)
        return "Who should take it?"

    await chat.turn("Assign Priya's lead", select_priya)
    owner = await assignment.load_scope(pg_session, ids["org"], ids["owner"])
    await assignment.reassign(pg_session, owner, [priya.id], ids["lina"], team_id=ids["south"])
    await pg_session.commit()

    async def gone():
        assert "pending request" not in chat.history and str(priya.id) not in chat.history
        # A stale ID from anywhere is refused the same way a missing lead is.
        refused = await chat.propose(
            ActionKind.ASSIGN_LEAD, AssignLead(lead_id=priya.id, assignee_id=ids["omar"])
        )
        assert refused["available"] is False
        found = await chat.search("Priya Rossi")
        assert found["total"] == 0
        return "I can no longer find that lead in the CRM you can access."

    await chat.turn("User 1", gone)
    assert chat.deps.proposals == []
    assert (await current(pg_session, priya.id)).assigned_user_id == ids["lina"]


async def test_confirmation_rechecks_the_assignee_and_the_lead(pg_session, office):
    ids, priya = office.ids, office.priya
    chat = await Chat(pg_session, office, "nadia").start()

    async def propose_both():
        await workflows.find_assignment_colleagues(chat.ctx("lookup"), "User 1")
        await chat.propose(
            ActionKind.ASSIGN_LEAD, AssignLead(lead_id=priya.id, assignee_id=ids["omar"])
        )
        await chat.propose(ActionKind.UNASSIGN_LEAD, LeadTarget(lead_id=office.other.id))
        return "Please confirm both."

    await chat.turn("Give Priya's lead to User 1 and unassign Omar Buyer", propose_both)
    assign, unassign = chat.deps.proposals
    # The assignee leaves North after the preview: the assignment must not happen.
    await pg_session.execute(
        delete(OrganizationTeamMember).where(OrganizationTeamMember.user_id == ids["omar"])
    )
    await pg_session.commit()
    assert (
        await actions.confirm_action(pg_session, **chat.scope, action_id=assign["id"])
    ).status == "failed"
    assert (await current(pg_session, priya.id)).assigned_user_id == ids["sara"]
    # Nadia stops managing North after the preview: no unassignment either.
    await pg_session.execute(
        delete(OrganizationTeamMember).where(OrganizationTeamMember.user_id == ids["nadia"])
    )
    await pg_session.commit()
    result = await actions.confirm_action(pg_session, **chat.scope, action_id=unassign["id"])
    assert result.status == "failed"
    assert (await current(pg_session, office.other.id)).assigned_user_id == ids["omar"]


# --- Ambiguity ----------------------------------------------------------------------------


async def test_two_matching_leads_are_both_shown_and_the_held_one_is_kept(pg_session, office):
    ids, priya = office.ids, office.priya
    twin = await lead(pg_session, ids, "Priya Rossi", team="north", assignee="omar")
    chat = await Chat(pg_session, office, "nadia").start()

    async def two():
        found = await chat.search("Priya Rossi")
        # The server returns both; nothing is chosen for the user.
        assert found["total"] == 2 and {r["id"] for r in found["records"]} == {priya.id, twin.id}
        return "There are two Priya Rossi leads. Which one do you mean?"

    await chat.turn("Assign Priya Rossi", two)

    async def chosen():
        await chat.hold(twin.id, ActionKind.ASSIGN_LEAD)
        return "Who should take it?"

    await chat.turn("The one assigned to User 1", chosen)

    async def exactly_that_one():
        replay = chat.history
        assert pending(twin.id, "assign_lead") in replay
        assert f'"lead_id": {priya.id}' not in replay
        return "Who should take it?"

    await chat.turn("Hmm", exactly_that_one)


async def test_ambiguous_assignee_never_reaches_a_proposal(pg_session, office):
    ids, priya = office.ids, office.priya
    chat = await Chat(pg_session, office, "owner").start()

    async def ambiguous():
        found = await workflows.find_assignment_colleagues(chat.ctx("lookup"), "User 1")
        assert {m["id"] for m in found["matches"]} == {ids["omar"], ids["lina"]}
        assert found["clarification_required"] is True
        refused = await chat.propose(
            ActionKind.ASSIGN_LEAD, AssignLead(lead_id=priya.id, assignee_id=ids["omar"])
        )
        assert refused["available"] is False and refused["clarification_required"] is True
        return "Two people are named User 1. Which team's?"

    await chat.turn("Assign Priya's lead to User 1", ambiguous)
    assert chat.deps.proposals == []


# --- Unauthorized targets and assignees ---------------------------------------------------


async def test_unauthorized_targets_and_assignees_are_refused(pg_session, office):
    ids, priya = office.ids, office.priya
    south = await lead(pg_session, ids, "South Lead", team="south", assignee="lina")
    unassigned = await lead(pg_session, ids, "Waiting", team="north", assignee=None)

    agent = await Chat(pg_session, office, "omar").start()

    async def agent_tries():
        # Agents cannot unassign, not even their own lead, nor hold such a request.
        own = office.other.id
        assert (await agent.hold(own, ActionKind.UNASSIGN_LEAD))["available"] is False
        refused = await agent.propose(ActionKind.UNASSIGN_LEAD, LeadTarget(lead_id=own))
        assert refused["available"] is False
        return "Only managers can change who holds a lead."

    await agent.turn("Unassign my lead", agent_tries)
    assert agent.deps.proposals == []

    manager = await Chat(pg_session, office, "nadia").start()

    async def manager_tries():
        # Another team's lead answers like a missing one.
        refused = await manager.propose(ActionKind.UNASSIGN_LEAD, LeadTarget(lead_id=south.id))
        assert refused["available"] is False
        assert (await manager.hold(south.id, ActionKind.UNASSIGN_LEAD))["available"] is False
        # Already unassigned: nothing to remove.
        refused = await manager.propose(ActionKind.UNASSIGN_LEAD, LeadTarget(lead_id=unassigned.id))
        assert refused == {"available": False, "reason": "This lead is already unassigned"}
        # South's "User 1" is not someone Nadia may assign to, even by a supplied ID.
        found = await workflows.find_assignment_colleagues(manager.ctx("lookup"), "User 1")
        assert [m["id"] for m in found["matches"]] == [ids["omar"]]
        refused = await manager.propose(
            ActionKind.ASSIGN_LEAD, AssignLead(lead_id=priya.id, assignee_id=ids["lina"])
        )
        assert refused["available"] is False
        return "Those changes are not available to you."

    await manager.turn("Try these", manager_tries)
    assert manager.deps.proposals == []
    assert (await current(pg_session, south.id)).assigned_user_id == ids["lina"]
    assert (await current(pg_session, priya.id)).assigned_user_id == ids["sara"]
