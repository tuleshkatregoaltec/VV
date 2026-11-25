"""Team questions and team management through the assistant, with the CRM's own rules.

The CRM's Teams page (organization/router.py) is for organization owners and administrators:
they create and delete teams and set who is in each team as agent or manager. A team still
used by leads or routing rules cannot be deleted, and team names are unique. The assistant
proposes each change, rechecks permission and state on confirmation, applies it through the
CRM's own team writes (organization/teams.py) and reports success only after they succeed.

Agency (crm_role_support), renamed: Nadia manages JVC Sales (agents Track 8 and User 10);
Karim manages Dubai Marina (agent User 2); the owner administers the organization. A rival
organization has its own "JVC Sales" team. Models are scripted; tools and services are real.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import update
from sqlmodel import select
from test_assistant_lead_contact_turns import (
    Chat,
    call,
    delegate,
    last_return,
    say,
    script,
    setup_office,
)

from app.assistant_actions import service as actions
from app.assistant_actions.models import ActionKind, ActionProposalRequest
from app.crm.assistant import workflows
from app.organization.models import (
    Organization,
    OrganizationMembership,
    OrganizationTeam,
    OrganizationTeamMember,
)
from app.organization.teams import TEAM_IN_USE, TEAM_NAME_TAKEN

ADMIN_ONLY = actions.TEAM_ADMIN_ONLY


@pytest.fixture
async def office(pg_session, monkeypatch):
    office = await setup_office(pg_session, monkeypatch)
    ids = office.ids
    for team, name in (("north", "JVC Sales"), ("south", "Dubai Marina")):
        await pg_session.exec(
            update(OrganizationTeam).where(OrganizationTeam.id == ids[team]).values(name=name)
        )
    empty = OrganizationTeam(organization_id=ids["org"], name="Downtown")
    pg_session.add(empty)
    rival_org, stranger = str(uuid4()), f"stranger-{uuid4().hex[:6]}"
    pg_session.add(Organization(id=rival_org, name="Rival", subscription_status="active"))
    await pg_session.flush()
    pg_session.add(
        OrganizationMembership(organization_id=rival_org, user_id=stranger, role="owner")
    )
    rival = OrganizationTeam(organization_id=rival_org, name="JVC Sales")
    pg_session.add(rival)
    await pg_session.commit()
    ids.update(downtown=empty.id, rival_team=rival.id, rival_org=rival_org, stranger=stranger)
    return office


async def roster(db, team_id):
    """The team's current members as (person, role), from the database."""
    db.expire_all()
    rows = (
        await db.exec(
            select(OrganizationTeamMember).where(OrganizationTeamMember.team_id == team_id)
        )
    ).all()
    return {(row.user_id, row.role) for row in rows}


async def team_named(db, org, name):
    db.expire_all()
    return (
        await db.exec(
            select(OrganizationTeam).where(
                OrganizationTeam.organization_id == org, OrganizationTeam.name == name
            )
        )
    ).first()


async def propose(db, ids, person, kind, payload):
    conversation = await actions_conversation(db, ids, person)
    return await actions.propose_action(
        db,
        user_id=ids[person],
        organization_id=ids["org"],
        request=ActionProposalRequest(
            kind=kind,
            conversation_id=conversation,
            payload=payload,
            idempotency_key=uuid4().hex,
        ),
    )


async def actions_conversation(db, ids, person):
    from app.chat.conversations import create_conversation

    return (await create_conversation(db, ids[person], ids["org"])).id


async def confirm(db, ids, person, action_id):
    return await actions.confirm_action(
        db, user_id=ids[person], organization_id=ids["org"], action_id=action_id
    )


# --- Who may manage teams: the CRM's rule --------------------------------------------------


CHANGES = [
    (ActionKind.CREATE_TEAM, lambda ids: {"name": "Palm"}),
    (ActionKind.DELETE_TEAM, lambda ids: {"team_id": ids["downtown"]}),
    (ActionKind.ADD_TEAM_AGENT, lambda ids: {"team_id": ids["north"], "member_id": ids["lina"]}),
    (
        ActionKind.REMOVE_TEAM_MEMBER,
        lambda ids: {"team_id": ids["north"], "member_id": ids["sara"]},
    ),
    (ActionKind.SET_TEAM_MANAGER, lambda ids: {"team_id": ids["north"], "member_id": ids["omar"]}),
]


@pytest.mark.parametrize(("kind", "payload"), CHANGES)
@pytest.mark.parametrize("person", ["nadia", "omar"])  # A team's own manager; an agent.
async def test_only_owners_and_administrators_may_change_teams(
    pg_session, office, person, kind, payload
):
    ids = office.ids
    before = {team: await roster(pg_session, ids[team]) for team in ("north", "south")}
    with pytest.raises(HTTPException) as refused:
        await propose(pg_session, ids, person, kind, payload(ids))
    assert (refused.value.status_code, refused.value.detail) == (403, ADMIN_ONLY)
    assert {team: await roster(pg_session, ids[team]) for team in ("north", "south")} == before
    # Their lookups say so too, without listing anything.
    found = await actions.lookup_teams(
        pg_session, user_id=ids[person], organization_id=ids["org"], search="JVC Sales"
    )
    assert found == {"available": False, "reason": ADMIN_ONLY}


async def test_an_organization_administrator_may_manage_teams_like_the_owner(pg_session, office):
    ids = office.ids
    await pg_session.exec(
        update(OrganizationMembership)
        .where(OrganizationMembership.user_id == ids["nadia"])
        .values(organization_admin=True)
    )
    await pg_session.commit()
    action = await propose(
        pg_session,
        ids,
        "nadia",
        ActionKind.ADD_TEAM_AGENT,
        {"team_id": ids["south"], "member_id": ids["sara"]},
    )
    assert (await confirm(pg_session, ids, "nadia", action.id)).status == "succeeded"
    assert (ids["sara"], "agent") in await roster(pg_session, ids["south"])


async def test_another_organizations_team_or_person_is_never_reachable(pg_session, office):
    ids = office.ids
    with pytest.raises(HTTPException) as refused:
        await propose(
            pg_session, ids, "owner", ActionKind.DELETE_TEAM, {"team_id": ids["rival_team"]}
        )
    assert refused.value.status_code == 404
    with pytest.raises(HTTPException) as refused:
        await propose(
            pg_session,
            ids,
            "owner",
            ActionKind.ADD_TEAM_AGENT,
            {"team_id": ids["north"], "member_id": ids["stranger"]},
        )
    assert refused.value.status_code == 409
    # Lookups see only this organization's teams: one "JVC Sales", not the rival's.
    found = await actions.lookup_teams(
        pg_session, user_id=ids["owner"], organization_id=ids["org"], search="JVC Sales"
    )
    assert found["matches"] == [{"id": ids["north"], "name": "JVC Sales"}]
    assert await roster(pg_session, ids["rival_team"]) == set()


# --- Each change, confirmed, through the CRM's team writes -----------------------------------


async def test_create_and_delete_a_team_only_after_confirmation(pg_session, office):
    ids = office.ids
    action = await propose(pg_session, ids, "owner", ActionKind.CREATE_TEAM, {"name": "Palm"})
    assert action.status == "awaiting_confirmation" and action.preview["team"] == "Palm"
    assert await team_named(pg_session, ids["org"], "Palm") is None  # Proposed is not created.
    done = await confirm(pg_session, ids, "owner", action.id)
    assert (done.status, done.result["message"]) == ("succeeded", "Team Palm created")
    palm = await team_named(pg_session, ids["org"], "Palm")
    assert palm is not None

    action = await propose(pg_session, ids, "owner", ActionKind.DELETE_TEAM, {"team_id": palm.id})
    assert action.preview["team"] == "Palm"
    done = await confirm(pg_session, ids, "owner", action.id)
    assert (done.status, done.result["message"]) == ("succeeded", "Team Palm deleted")
    assert await team_named(pg_session, ids["org"], "Palm") is None
    # The finished action stays visible as completed, though its team is gone.
    shown = await actions.get_action(
        pg_session, user_id=ids["owner"], organization_id=ids["org"], action_id=action.id
    )
    assert shown.status == "succeeded" and shown.preview.get("available") is not False


async def test_the_crm_refuses_a_taken_name_or_a_team_still_in_use_and_nothing_changes(
    pg_session, office
):
    ids = office.ids
    taken = await propose(
        pg_session, ids, "owner", ActionKind.CREATE_TEAM, {"name": "Dubai Marina"}
    )
    done = await confirm(pg_session, ids, "owner", taken.id)
    assert (done.status, done.result["message"]) == ("failed", TEAM_NAME_TAKEN)

    # JVC Sales holds Bilal Hameed's lead: the CRM keeps the team.
    in_use = await propose(
        pg_session, ids, "owner", ActionKind.DELETE_TEAM, {"team_id": ids["north"]}
    )
    done = await confirm(pg_session, ids, "owner", in_use.id)
    assert (done.status, done.result["message"]) == ("failed", TEAM_IN_USE)
    assert await team_named(pg_session, ids["org"], "JVC Sales") is not None
    assert len(await roster(pg_session, ids["north"])) == 3


async def test_add_and_remove_an_agent(pg_session, office):
    ids = office.ids
    action = await propose(
        pg_session,
        ids,
        "owner",
        ActionKind.ADD_TEAM_AGENT,
        {"team_id": ids["north"], "member_id": ids["lina"]},
    )
    assert (action.preview["team"], action.preview["person"]) == ("JVC Sales", "User 2")
    assert action.preview["current_managers"] == ["Nadia Manager"]
    assert "changes" not in action.preview  # Names, never the raw IDs.
    assert (ids["lina"], "agent") not in await roster(pg_session, ids["north"])
    done = await confirm(pg_session, ids, "owner", action.id)
    assert (done.status, done.result["message"]) == (
        "succeeded",
        "User 2 added to JVC Sales as an agent",
    )
    assert (ids["lina"], "agent") in await roster(pg_session, ids["north"])
    assert (ids["lina"], "agent") in await roster(
        pg_session, ids["south"]
    )  # Still in Dubai Marina.

    action = await propose(
        pg_session,
        ids,
        "owner",
        ActionKind.REMOVE_TEAM_MEMBER,
        {"team_id": ids["north"], "member_id": ids["sara"]},
    )
    done = await confirm(pg_session, ids, "owner", action.id)
    assert (done.status, done.result["message"]) == ("succeeded", "User 10 removed from JVC Sales")
    assert ids["sara"] not in {person for person, _ in await roster(pg_session, ids["north"])}
    # Already in, or not in, the team: refused before anything is proposed.
    for kind, person in (
        (ActionKind.ADD_TEAM_AGENT, "omar"),
        (ActionKind.REMOVE_TEAM_MEMBER, "sara"),
    ):
        with pytest.raises(HTTPException) as refused:
            await propose(
                pg_session, ids, "owner", kind, {"team_id": ids["north"], "member_id": ids[person]}
            )
        assert refused.value.status_code == 409


async def test_set_or_change_a_manager(pg_session, office):
    ids = office.ids
    # Promote an agent to co-manager: Nadia stays.
    action = await propose(
        pg_session,
        ids,
        "owner",
        ActionKind.SET_TEAM_MANAGER,
        {"team_id": ids["north"], "member_id": ids["omar"]},
    )
    done = await confirm(pg_session, ids, "owner", action.id)
    assert (done.status, done.result["message"]) == (
        "succeeded",
        "Track 8 is now a manager of JVC Sales",
    )
    assert {(ids["nadia"], "supervisor"), (ids["omar"], "supervisor")} <= await roster(
        pg_session, ids["north"]
    )

    # Change Dubai Marina's manager: the preview names who leaves, and Karim leaves the team.
    action = await propose(
        pg_session,
        ids,
        "owner",
        ActionKind.SET_TEAM_MANAGER,
        {"team_id": ids["south"], "member_id": ids["lina"], "replace_existing": True},
    )
    assert action.preview["managers_leaving_the_team"] == ["Karim South"]
    await confirm(pg_session, ids, "owner", action.id)
    assert await roster(pg_session, ids["south"]) == {(ids["lina"], "supervisor")}
    # Already the manager: nothing to do.
    with pytest.raises(HTTPException) as refused:
        await propose(
            pg_session,
            ids,
            "owner",
            ActionKind.SET_TEAM_MANAGER,
            {"team_id": ids["south"], "member_id": ids["lina"]},
        )
    assert refused.value.detail == "This person already manages this team"


# --- Confirmation rechecks permission and state ----------------------------------------------


async def test_confirmation_rechecks_permission(pg_session, office):
    ids = office.ids
    admin = update(OrganizationMembership).where(OrganizationMembership.user_id == ids["nadia"])
    await pg_session.exec(admin.values(organization_admin=True))
    await pg_session.commit()
    action = await propose(
        pg_session,
        ids,
        "nadia",
        ActionKind.ADD_TEAM_AGENT,
        {"team_id": ids["south"], "member_id": ids["sara"]},
    )
    await pg_session.exec(admin.values(organization_admin=False))  # No longer an administrator.
    await pg_session.commit()
    done = await confirm(pg_session, ids, "nadia", action.id)
    assert done.status == "failed"
    assert (ids["sara"], "agent") not in await roster(pg_session, ids["south"])


async def test_confirmation_rechecks_the_team_as_it_was_previewed(pg_session, office):
    ids = office.ids
    action = await propose(
        pg_session,
        ids,
        "owner",
        ActionKind.REMOVE_TEAM_MEMBER,
        {"team_id": ids["north"], "member_id": ids["sara"]},
    )
    # Someone changes the team in the CRM before the confirmation.
    pg_session.add(
        OrganizationTeamMember(
            team_id=ids["north"], organization_id=ids["org"], user_id=ids["lina"], role="agent"
        )
    )
    await pg_session.commit()
    done = await confirm(pg_session, ids, "owner", action.id)
    assert (done.status, done.result["message"]) == (
        "failed",
        "Record changed since preview; create a new proposal",
    )
    assert (ids["sara"], "agent") in await roster(pg_session, ids["north"])


# --- Through the chat turn -------------------------------------------------------------------


async def test_a_team_change_in_chat_is_proposed_not_done_and_uses_looked_up_ids(
    pg_session, office
):
    ids = office.ids
    chat = await Chat(pg_session, office, "owner").start()

    def propose_add(messages):
        return call(
            "propose_crm_action",
            kind="add_team_agent",
            payload={"team_id": ids["north"], "member_id": ids["lina"]},
        )

    # A guessed ID, without looking the team and person up, is refused for clarification.
    guessed: list = []

    def refused(messages):
        guessed.append(last_return(messages))
        return say("Which team and which person do you mean?")

    await chat.turn(
        "Add User 2 to JVC Sales",
        coordinator=delegate("prepare_action", "Add User 2 to JVC Sales"),
        action=script(propose_add, refused),
    )
    assert guessed[0]["available"] is False and guessed[0]["clarification_required"] is True

    shown = await chat.turn(
        "Add User 2 to the JVC Sales CRM team",
        coordinator=delegate("prepare_action", "Add User 2 to the JVC Sales CRM team"),
        action=script(
            call("find_teams", search="JVC Sales CRM team"),
            call("find_team_people", search="User 2"),
            propose_add,
            say("Done, User 2 has been added to JVC Sales."),
        ),
    )
    assert "awaiting your confirmation" in shown and "has been added" not in shown
    assert (ids["lina"], "agent") not in await roster(pg_session, ids["north"])


async def test_a_manager_asking_to_change_a_team_is_told_why_not(pg_session, office):
    chat = await Chat(pg_session, office, "nadia").start()
    told: list = []

    def explain(messages):
        result = last_return(messages)
        told.append(result)
        return say(result["reason"])

    shown = await chat.turn(
        "Add User 2 to JVC Sales",
        coordinator=delegate("prepare_action", "Add User 2 to JVC Sales"),
        action=script(call("find_teams", search="JVC Sales"), explain),
    )
    assert shown == ADMIN_ONLY


async def test_two_teams_answered_separately_from_crm_data_without_market_tools(
    pg_session, office, monkeypatch
):
    """'Tell me about JVC Sales and Dubai Marina teams and all managers and agents': both
    teams, each with its manager and agents, from the CRM. "JVC" and "Sales" are not a market
    question, and the CRM assistant has no market specialist or tool to reach at all."""
    from app.crm.assistant.agent import agent

    chat = await Chat(pg_session, office, "owner").start()
    teams_found: list = []

    def sections(messages):
        result = last_return(messages)
        teams_found.append(result)
        lines = []
        for team in result["records"]:
            lines += [
                f"## {team['team']}",
                f"- Manager: {', '.join(team['managers']) or 'None assigned'}",
                f"- Agents: {', '.join(team['agents']) or 'None'}",
                "",
            ]
        return say("\n".join(lines).strip())

    question = "Tell me about JVC Sales and Dubai Marina teams and all managers and agents"
    shown = await chat.turn(
        question,
        coordinator=delegate("retrieve_personal_crm", question),
        crm=script(call("query_my_crm_records", resource="teams"), sections),
    )
    assert shown == (
        "## Downtown\n- Manager: None assigned\n- Agents: None\n\n"
        "## Dubai Marina\n- Manager: Karim South\n- Agents: User 2\n\n"
        "## JVC Sales\n- Manager: Nadia Manager\n- Agents: Track 8, User 10"
    )
    # No market specialist or market workflow exists for this question to reach.
    assert not hasattr(workflows, "market_agent")
    assert not {"research_market", "analyze_pricing"} & set(agent._function_toolset.tools)
    assert teams_found[0]["total"] == 3  # Every team of the organization, for the owner.


# --- The CRM's own Teams endpoints behave as before (they share the team writes) ------------


async def test_the_crm_team_service_keeps_its_behaviour(pg_session, office):
    from app.organization import teams
    from app.organization.models import (
        TeamMemberInput,
        TeamMembersUpdateRequest,
        TeamWriteRequest,
    )

    ids = office.ids
    listed = await teams.create_team(pg_session, ids["org"], TeamWriteRequest(name=" Palm "))
    assert "Palm" in [team.name for team in listed.teams]
    with pytest.raises(HTTPException) as refused:
        await teams.create_team(pg_session, ids["org"], TeamWriteRequest(name="Palm"))
    assert (refused.value.status_code, refused.value.detail) == (409, TEAM_NAME_TAKEN)
    # The session is usable after the refusal, and the team is still there once.
    palm = SimpleNamespace(id=(await team_named(pg_session, ids["org"], "Palm")).id)
    with pytest.raises(HTTPException) as refused:
        await teams.delete_team(pg_session, ids["org"], ids["north"])
    assert (refused.value.status_code, refused.value.detail) == (409, TEAM_IN_USE)
    with pytest.raises(HTTPException) as refused:
        await teams.replace_team_members(
            pg_session,
            ids["org"],
            palm.id,
            TeamMembersUpdateRequest(
                members=[TeamMemberInput(user_id=ids["stranger"], role="agent")]
            ),
        )
    assert refused.value.status_code == 422
    await teams.replace_team_members(
        pg_session,
        ids["org"],
        palm.id,
        TeamMembersUpdateRequest(members=[TeamMemberInput(user_id=ids["omar"], role="supervisor")]),
    )
    assert await roster(pg_session, palm.id) == {(ids["omar"], "supervisor")}
    # A team without leads or rules is deleted; its members stay in the organization.
    assert (await teams.delete_team(pg_session, ids["org"], palm.id)).success
    assert await team_named(pg_session, ids["org"], "Palm") is None
    assert await roster(pg_session, palm.id) == set()
