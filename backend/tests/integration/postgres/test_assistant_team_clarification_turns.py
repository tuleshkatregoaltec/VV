"""A "yes" to a team clarification continues the team request, not an older lead topic.

Reported conversation (an organization owner):
1. "give me latest 5 leads"                     -> a private answer listing Mariam Ali first
2. "Create new team jvt sales manager is Track 3 agent is Track 8,1,2"
                                                -> the empty jvt sales team is created
3. "Add in jvt sales team manager is Track 3 agent is Track 8,1,2"
                                                -> "Do you mean jvt sales rather than JVC sales?"
4. "yes"                                        -> was: "Do you mean Mariam Ali, or another lead?"

Private answers are never replayed to the model, so the reply "yes" depends on what the server
carries over. It carried the lead handles of turn 1, because the team turns in between hold no
record handles and the search went past them. A follow-up's subject is the latest answer that
used CRM evidence; and the held request carries the team, its manager and agents as the user
gave them, so the confirmation-required proposals use fresh lookups of exactly those.

Models are scripted; routing, history loading, lookups, proposals and confirmation are real.
"""

import re
from types import SimpleNamespace

import pytest
from crm_role_support import lead
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import update
from sqlmodel import select
from test_assistant_lead_contact_turns import (
    Chat,
    call,
    delegate,
    last_return,
    leads,
    say,
    script,
    setup_office,
)
from test_assistant_team_management import roster, team_named

from app.assistant_actions import service as actions
from app.assistant_actions.models import AssistantAction
from app.crm.assistant import routing, service
from app.crm.inbound_models import CrmInboundEnquiry
from app.organization.models import OrganizationTeam

NAMES = {
    "owner": ("Agency", "Owner"),
    "nadia": ("Track", "3"),
    "omar": ("Track", "8"),
    "sara": ("Track", "1"),
    "karim": ("Track", "10"),  # Begins with "Track 1" but is not that person.
    "lina": ("Track", "2"),
}
TEAM_REQUEST = "Add in jvt sales team\nmanager  is Track 3\nagent is Track 8,1,2"
STALE_LEAD_CONTEXT = "Server-reauthorized record handles"


def carries_lead_handles(replay: str) -> bool:
    """Whether the model was given record handles (an earlier answer's leads) to resolve to."""
    return STALE_LEAD_CONTEXT in replay or bool(re.search(r'record_id\\?": \d', replay))


@pytest.fixture
async def office(pg_session, monkeypatch):
    return await setup_track_office(pg_session, monkeypatch)


async def setup_track_office(pg_session, monkeypatch):
    """The agency with members named Track 1, 2, 3, 8 and 10, and the lead Mariam Ali."""
    from app.organization import service as organizations
    from app.organization import teams

    office = await setup_office(pg_session, monkeypatch)
    ids = office.ids
    people = {ids[person]: name for person, name in NAMES.items()}

    async def profile(user_id):
        first, last = people.get(user_id, ("Former", "Member"))
        return SimpleNamespace(first_name=first, last_name=last, email=f"{user_id}@example.test")

    for module in (organizations, actions, teams):
        monkeypatch.setattr(module, "get_user_by_id", profile)
    # "JVC sales" is the existing team one letter away from the new "jvt sales".
    for team, name in (("north", "JVC sales"), ("south", "Dubai Marina")):
        await pg_session.exec(
            update(OrganizationTeam).where(OrganizationTeam.id == ids[team]).values(name=name)
        )
    await pg_session.commit()
    office.mariam = await lead(pg_session, ids, "Mariam Ali", team="north", assignee="nadia")
    return office


async def up_to_the_team_question(pg_session, office, *, held: bool):
    """Turns 1-3 of the reported conversation; returns the chat and the new team."""
    chat = await Chat(pg_session, office, "owner").start()

    # 1. A private lead answer: its record handles are what the "yes" wrongly resolved to.
    await chat.turn(
        "give me latest 5 leads",
        coordinator=delegate("retrieve_personal_crm", "The latest 5 leads"),
        crm=script(leads(), say("The latest leads are Mariam Ali and Bilal Hameed.")),
    )

    # 2. The team is created only once the owner confirms it.
    await chat.turn(
        "Create new team jvt sales\nmanager  is Track 3\nagent is Track 8,1,2",
        coordinator=delegate("prepare_action", "Create team jvt sales"),
        action=script(
            call("propose_crm_action", kind="create_team", payload={"name": "jvt sales"}),
            say("Please confirm creating jvt sales; I can then add its members."),
        ),
    )
    assert await team_named(pg_session, office.ids["org"], "jvt sales") is None
    [create] = await actions.list_actions(
        pg_session, **chat.scope, conversation_id=chat.conversation_id
    )
    confirmed = await actions.confirm_action(pg_session, **chat.scope, action_id=create.id)
    assert confirmed.status == "succeeded", confirmed.result
    jvt = await team_named(pg_session, office.ids["org"], "jvt sales")
    assert await roster(pg_session, jvt.id) == set()

    # 3. The assistant asks which team is meant (the request held, or, as reported, not).
    steps = [call("find_teams", search="jvt sales")]
    if held:
        steps.append(
            call(
                "hold_pending_request",
                kind="add_team_agent",
                details={
                    "team": "jvt sales",
                    "managers": ["Track 3"],
                    "people": ["Track 8", "Track 1", "Track 2"],
                    "missing": ["confirm the team is jvt sales, not JVC sales"],
                },
            )
        )
    steps.append(say("Do you mean the exact jvt sales team rather than JVC sales?"))
    await chat.turn(
        TEAM_REQUEST,
        coordinator=delegate("prepare_action", TEAM_REQUEST),
        action=script(*steps),
    )
    assert (
        await actions.list_actions(pg_session, **chat.scope, conversation_id=chat.conversation_id)
    )[1:] == []  # Only the confirmed create: a question proposes nothing.
    # Plain values: service commits expire ORM rows the test still holds.
    return chat, SimpleNamespace(id=jvt.id)


async def test_yes_continues_the_held_team_request_with_fresh_lookups(pg_session, office):
    ids = office.ids
    chat, jvt = await up_to_the_team_question(pg_session, office, held=True)
    found: dict = {}

    def continues(messages):
        replay = str(messages)
        # The older lead answer is not this follow-up's subject...
        assert not carries_lead_handles(replay)
        # ...the held team request is, with the user's own names and roles.
        for given in (
            '"kind": "add_team_agent"',
            '"team": "jvt sales"',
            '"managers": ["Track 3"]',
            '"people": ["Track 8", "Track 1", "Track 2"]',
        ):
            assert given in replay, given
        return call("prepare_action", question="Continue the pending jvt sales team request")

    def task_names_the_team(messages):
        replay = str(messages)
        assert not carries_lead_handles(replay)
        # The specialist's own task carries the held request (pending_note).
        task = replay[replay.index("Pending request this message may answer") :]
        assert '"team": "jvt sales"' in task and '"managers": ["Track 3"]' in task
        return call("find_teams", search="jvt sales")

    def look_up(name, previous=None):
        def step(messages):
            result = last_return(messages)
            if previous == "team":
                assert result["clarification_required"] is False
                [team] = result["matches"]
                assert team == {"id": jvt.id, "name": "jvt sales"}  # Not JVC sales.
                found["team"] = team["id"]
            elif previous:
                assert result["clarification_required"] is False, result
                [person] = result["matches"]
                assert person["display_name"] == previous  # "Track 1", never "Track 10".
                found[previous] = person["id"]
            return call("find_team_people", search=name)

        return step

    def propose_all(messages):
        # One change for the whole roster request: separate ones would each preview the same
        # team, and confirming one would leave the others stale.
        [match] = last_return(messages)["matches"]
        found["Track 2"] = match["id"]
        roles = {
            "Track 3": "supervisor",
            "Track 8": "agent",
            "Track 1": "agent",
            "Track 2": "agent",
        }
        return call(
            "propose_crm_action",
            kind="update_team_members",
            payload={
                "team_id": found["team"],
                "members": [{"member_id": found[p], "role": r} for p, r in roles.items()],
            },
        )

    action = script(
        task_names_the_team,
        look_up("Track 3", "team"),
        look_up("Track 8", "Track 3"),
        look_up("Track 1", "Track 8"),
        look_up("Track 2", "Track 1"),
        propose_all,
        say("Done! Track 3 now manages jvt sales with Track 8, Track 1 and Track 2."),
    )
    shown = await chat.turn(
        "yes", coordinator=script(continues, lambda m: say(last_return(m))), action=action
    )

    assert found["Track 3"] == ids["nadia"] and found["Track 1"] == ids["sara"]
    assert "Mariam" not in shown and "Done" not in shown
    assert "awaiting your confirmation" in shown
    # The stored proposal targets the looked-up team and people, and is not confirmed.
    pg_session.expire_all()
    [proposal] = (
        await pg_session.exec(
            select(AssistantAction).where(
                AssistantAction.conversation_id == chat.conversation_id,
                AssistantAction.kind != "create_team",
            )
        )
    ).all()
    expected = {
        (ids["nadia"], "supervisor"),
        (ids["omar"], "agent"),
        (ids["sara"], "agent"),
        (ids["lina"], "agent"),
    }
    assert (proposal.kind, proposal.status, proposal.payload["team_id"]) == (
        "update_team_members",
        "awaiting_confirmation",
        jvt.id,
    )
    assert {(m["member_id"], m["role"]) for m in proposal.payload["members"]} == expected
    proposal_id = proposal.id
    # Proposed is not done: no team or lead changed before confirmation.
    assert await roster(pg_session, jvt.id) == set()
    pg_session.expire_all()
    mariam = await pg_session.get(CrmInboundEnquiry, office.mariam.id)
    assert mariam.assigned_user_id == ids["nadia"]

    # Confirmation rechecks permission and the team as previewed, then writes every member.
    done = await actions.confirm_action(pg_session, **chat.scope, action_id=proposal_id)
    assert done.status == "succeeded", done.result
    assert await roster(pg_session, jvt.id) == expected


async def test_yes_after_an_unheld_team_question_never_resurrects_the_lead_list(
    pg_session, office, monkeypatch
):
    """The reported state exactly: the question held nothing. The reply cannot be resolved
    to an earlier lead answer; the router and specialist see no lead handles."""
    from app.crm.assistant.routing import IntentDecision

    chat, jvt = await up_to_the_team_question(pg_session, office, held=False)
    monkeypatch.setattr(service.settings, "ASSISTANT_TYPED_ROUTING_ENABLED", True)
    routed: list[str] = []

    def route(messages, info):
        routed.append(str(messages))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    IntentDecision(decision="route", workflows=["action"]).model_dump(),
                )
            ]
        )

    def specialist(messages):
        assert not carries_lead_handles(str(messages))
        return say("Which change should I prepare for the jvt sales team?")

    with routing.router_agent.override(model=FunctionModel(route)):
        shown = await chat.turn("yes", action=script(specialist))
    assert routed and not any(carries_lead_handles(seen) for seen in routed)
    assert "Mariam" not in shown
    assert await roster(pg_session, jvt.id) == set()
