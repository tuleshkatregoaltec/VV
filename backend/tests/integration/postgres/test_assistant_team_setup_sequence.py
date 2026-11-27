"""Setting up a team over several turns ends with every requested member in the CRM.

Reported sequence (an organization owner):
1. Create JVT Sales.
2. Set Track 8 as supervisor.
3. Track 1, Track 2 and Track 3 as agents, in one message.
   -> three proposals, each previewing the same roster (Track 8 only). Confirming Track 1
      changed that roster, so Track 2 and Track 3 failed as "Record changed since preview";
      the Teams page showed only Track 8 and Track 1.

The stale check is right: a confirmation must apply only to the team as it was shown. The
cause was the proposals' granularity. The CRM's Teams page saves a team's whole roster in one
write (PUT /teams/{id}/members), so several members are now one update_team_members proposal,
applied together on confirmation; and only one change per team may await confirmation at a
time, so a later one always previews the roster as the earlier confirmation left it.

Models are scripted; routing, lookups, proposals, persistence and confirmation are real.
"""

import pytest
from fastapi import HTTPException
from test_assistant_lead_contact_turns import Chat, call, delegate, last_return, say, script
from test_assistant_team_clarification_turns import setup_track_office
from test_assistant_team_management import roster, team_named
from test_assistant_team_supervisor_turns import expecting, jvt_sales, make_admin

from app.assistant_actions import service as actions
from app.assistant_actions.models import ActionKind, ActionProposalRequest
from app.crm.assistant import service
from app.organization import teams as org_teams
from app.organization.models import OrganizationTeamMember

AGENTS_REQUEST = "Add Track 1, Track 2 and Track 3 to JVT Sales as agents"


@pytest.fixture
async def office(pg_session, monkeypatch):
    return await setup_track_office(pg_session, monkeypatch)


async def propose(db, office, person, kind, payload, key):
    """A proposal straight through the service, as the confirmation card's API would."""
    chat = await Chat(db, office, person).start()
    return await actions.propose_action(
        db,
        **chat.scope,
        request=ActionProposalRequest(
            kind=kind,
            conversation_id=chat.conversation_id,
            payload=payload,
            idempotency_key=f"proposal-{key}",
        ),
    )


def as_agents(office, *people):
    return [{"member_id": office.ids[p], "role": "agent"} for p in people]


async def teams_page(db, office, team_name):
    """What the CRM's Teams page shows for the team: each member's name and role."""
    page = await org_teams.list_teams(db, office.ids["org"])
    [team] = [team for team in page.teams if team.name == team_name]
    return {(member.name, member.role) for member in team.members}


async def confirm(db, chat, action_id):
    return await actions.confirm_action(db, **chat.scope, action_id=action_id)


# --- The reported sequence ---------------------------------------------------------------------


async def test_create_set_supervisor_then_three_agents_all_persist(pg_session, office):
    ids = office.ids
    chat = await Chat(pg_session, office, "owner").start()

    # 1. Create JVT Sales.
    await chat.turn(
        "Create JVT Sales",
        coordinator=delegate("prepare_action", "Create the team JVT Sales"),
        action=script(
            call("propose_crm_action", kind="create_team", payload={"name": "JVT Sales"}),
            say("Please confirm."),
        ),
    )
    [create] = await actions.list_actions(
        pg_session, **chat.scope, conversation_id=chat.conversation_id
    )
    assert (await confirm(pg_session, chat, create.id)).status == "succeeded"
    team_id = (await team_named(pg_session, ids["org"], "JVT Sales")).id

    # 2. Track 8 as supervisor.
    await chat.turn(
        "Set Track 8 as supervisor of JVT Sales",
        coordinator=delegate("prepare_action", "Set Track 8 as supervisor of JVT Sales"),
        action=script(
            call("find_teams", search="JVT Sales"),
            expecting("JVT Sales", call("find_team_people", search="Track 8")),
            expecting(
                "Track 8",
                call(
                    "propose_crm_action",
                    kind="set_team_manager",
                    payload={"team_id": team_id, "member_id": ids["omar"]},
                ),
            ),
            say("Please confirm."),
        ),
    )
    supervisor = (
        await actions.list_actions(pg_session, **chat.scope, conversation_id=chat.conversation_id)
    )[0]
    assert supervisor.kind == "set_team_manager"
    assert (await confirm(pg_session, chat, supervisor.id)).status == "succeeded"
    assert await roster(pg_session, team_id) == {(ids["omar"], "supervisor")}

    # 3. Three agents in one message: one proposal for all of them.
    refused: list = []

    def propose_all(messages):
        return call(
            "propose_crm_action",
            kind="update_team_members",
            payload={"team_id": team_id, "members": as_agents(office, "sara", "lina", "nadia")},
        )

    def then_one_more_for_the_same_team(messages):
        # The old pattern: another proposal for this team while one awaits. Refused.
        assert last_return(messages)["confirmation_required"] is True
        return call(
            "propose_crm_action",
            kind="add_team_agent",
            payload={"team_id": team_id, "member_id": ids["lina"]},
        )

    def claims_success(messages):
        refused.append(last_return(messages))
        return say("Done! Track 1, Track 2 and Track 3 have been added as agents.")

    shown = await chat.turn(
        AGENTS_REQUEST,
        coordinator=delegate("prepare_action", AGENTS_REQUEST),
        action=script(
            call("find_teams", search="JVT Sales"),
            expecting("JVT Sales", call("find_team_people", search="Track 1")),
            expecting("Track 1", call("find_team_people", search="Track 2")),
            expecting("Track 2", call("find_team_people", search="Track 3")),
            expecting("Track 3", propose_all(None)),
            then_one_more_for_the_same_team,
            claims_success,
        ),
    )
    assert refused[0] == {"available": False, "reason": actions.PENDING_TEAM_CHANGE}
    assert "awaiting your confirmation" in shown and "have been added" not in shown

    proposals = await actions.list_actions(
        pg_session, **chat.scope, conversation_id=chat.conversation_id
    )
    waiting = [p for p in proposals if p.status == "awaiting_confirmation"]
    assert [p.kind for p in waiting] == ["update_team_members"]  # Exactly one to confirm.
    card = waiting[0]
    assert card.preview["current_supervisors"] == ["Track 8"]
    assert card.preview["current_agents"] == []
    assert card.preview["becoming_agents"] == ["Track 1", "Track 2", "Track 3"]
    # Nothing changes before confirmation.
    assert await roster(pg_session, team_id) == {(ids["omar"], "supervisor")}

    done = await confirm(pg_session, chat, card.id)
    assert (done.status, done.result["message"]) == (
        "succeeded",
        "Track 1, Track 2 and Track 3 are now agents of JVT Sales",
    )
    # The CRM: Track 8 is still the supervisor and all three are agents.
    assert await roster(pg_session, team_id) == {
        (ids["omar"], "supervisor"),
        (ids["sara"], "agent"),
        (ids["lina"], "agent"),
        (ids["nadia"], "agent"),
    }
    assert await teams_page(pg_session, office, "JVT Sales") == {
        ("Track 8", "supervisor"),
        ("Track 1", "agent"),
        ("Track 2", "agent"),
        ("Track 3", "agent"),
    }
    # The assistant's answer, when shown again, states the confirmed outcome from the server.
    messages = await service.get_conversation_messages(
        pg_session, chat.conversation_id, **chat.scope
    )
    assert messages[-1].content.startswith(
        "Update team members: completed. Track 1, Track 2 and Track 3 are now agents of JVT Sales"
    )
    assert "have been added" not in messages[-1].content


# --- One change per team at a time, each from the latest roster ------------------------------


async def test_a_second_change_to_a_team_waits_for_the_first_and_sees_its_result(
    pg_session, office
):
    ids = office.ids
    team_id = await jvt_sales(pg_session, office, [("omar", "supervisor")])
    chat = await Chat(pg_session, office, "owner").start()

    first = await propose(
        pg_session,
        office,
        "owner",
        ActionKind.ADD_TEAM_AGENT,
        {"team_id": team_id, "member_id": ids["sara"]},
        "first-agent",
    )
    with pytest.raises(HTTPException) as refused:
        await propose(
            pg_session,
            office,
            "owner",
            ActionKind.ADD_TEAM_AGENT,
            {"team_id": team_id, "member_id": ids["lina"]},
            "second-agent",
        )
    assert (refused.value.status_code, refused.value.detail) == (409, actions.PENDING_TEAM_CHANGE)
    # Another team is not held up.
    other = await propose(
        pg_session,
        office,
        "owner",
        ActionKind.ADD_TEAM_AGENT,
        {"team_id": ids["south"], "member_id": ids["sara"]},
        "other-team",
    )
    assert other.status == "awaiting_confirmation"
    assert await roster(pg_session, team_id) == {(ids["omar"], "supervisor")}

    assert (await confirm(pg_session, chat, first.id)).status == "succeeded"
    # Now the next change is proposed against the roster the first one left, and succeeds.
    second = await propose(
        pg_session,
        office,
        "owner",
        ActionKind.ADD_TEAM_AGENT,
        {"team_id": team_id, "member_id": ids["lina"]},
        "second-agent-again",
    )
    assert second.preview["current_agents"] == ["Track 1"]
    assert (await confirm(pg_session, chat, second.id)).status == "succeeded"
    assert await roster(pg_session, team_id) == {
        (ids["omar"], "supervisor"),
        (ids["sara"], "agent"),
        (ids["lina"], "agent"),
    }


async def test_a_stale_waiting_change_does_not_block_a_fresh_one(pg_session, office):
    ids = office.ids
    team_id = await jvt_sales(pg_session, office, [("omar", "supervisor")])
    chat = await Chat(pg_session, office, "owner").start()
    old = await propose(
        pg_session,
        office,
        "owner",
        ActionKind.UPDATE_TEAM_MEMBERS,
        {"team_id": team_id, "members": as_agents(office, "sara", "lina")},
        "old-roster",
    )
    # Someone edits the team on the Teams page meanwhile.
    pg_session.add(
        OrganizationTeamMember(
            team_id=team_id, organization_id=ids["org"], user_id=ids["nadia"], role="agent"
        )
    )
    await pg_session.commit()
    fresh = await propose(
        pg_session,
        office,
        "owner",
        ActionKind.UPDATE_TEAM_MEMBERS,
        {"team_id": team_id, "members": as_agents(office, "sara", "lina")},
        "new-roster",
    )
    assert fresh.preview["current_agents"] == ["Track 3"]
    stale = await actions.get_action(pg_session, **chat.scope, action_id=old.id)
    assert (stale.status, stale.result["message"]) == (
        "failed",
        "Record changed since preview; create a new proposal",
    )
    assert (await confirm(pg_session, chat, fresh.id)).status == "succeeded"
    assert await roster(pg_session, team_id) == {
        (ids["omar"], "supervisor"),
        (ids["nadia"], "agent"),
        (ids["sara"], "agent"),
        (ids["lina"], "agent"),
    }


# --- Confirmation still rechecks state and permission; nothing is written before -------------


async def test_a_changed_team_refuses_the_whole_change_and_it_can_be_retried(pg_session, office):
    ids = office.ids
    team_id = await jvt_sales(pg_session, office, [("omar", "supervisor")])
    chat = await Chat(pg_session, office, "owner").start()
    action = await propose(
        pg_session,
        office,
        "owner",
        ActionKind.UPDATE_TEAM_MEMBERS,
        {"team_id": team_id, "members": as_agents(office, "sara", "lina", "nadia")},
        "three-agents",
    )
    assert await roster(pg_session, team_id) == {(ids["omar"], "supervisor")}
    # Someone removes Track 8 on the Teams page before the confirmation.
    await org_teams.replace_team_members(
        pg_session, ids["org"], team_id, org_teams.TeamMembersUpdateRequest(members=[])
    )
    done = await confirm(pg_session, chat, action.id)
    assert (done.status, done.result["message"]) == (
        "failed",
        "Record changed since preview; create a new proposal",
    )
    assert await roster(pg_session, team_id) == set()  # None of the three was added.

    # Retried: proposed again from the team as it is now, then confirmed.
    retry = await propose(
        pg_session,
        office,
        "owner",
        ActionKind.UPDATE_TEAM_MEMBERS,
        {"team_id": team_id, "members": as_agents(office, "sara", "lina", "nadia")},
        "three-agents-retry",
    )
    assert retry.preview["current_supervisors"] == []
    assert (await confirm(pg_session, chat, retry.id)).status == "succeeded"
    assert await roster(pg_session, team_id) == {
        (ids["sara"], "agent"),
        (ids["lina"], "agent"),
        (ids["nadia"], "agent"),
    }


async def test_confirmation_rechecks_permission(pg_session, office):
    ids = office.ids
    team_id = await jvt_sales(pg_session, office, [("omar", "supervisor")])
    await make_admin(pg_session, office, "karim")
    chat = await Chat(pg_session, office, "karim").start()
    action = await propose(
        pg_session,
        office,
        "karim",
        ActionKind.UPDATE_TEAM_MEMBERS,
        {"team_id": team_id, "members": as_agents(office, "sara", "lina", "nadia")},
        "karim-agents",
    )
    await make_admin(pg_session, office, "karim", value=False)
    done = await confirm(pg_session, chat, action.id)
    assert done.status == "failed"
    assert await roster(pg_session, team_id) == {(ids["omar"], "supervisor")}


@pytest.mark.parametrize("person", ["nadia", "sara"])  # A team's own supervisor; an agent.
async def test_only_administrators_may_propose_it(pg_session, office, person):
    team_id = await jvt_sales(pg_session, office)
    with pytest.raises(HTTPException) as refused:
        await propose(
            pg_session,
            office,
            person,
            ActionKind.UPDATE_TEAM_MEMBERS,
            {"team_id": team_id, "members": as_agents(office, "lina")},
            f"not-admin-{person}",
        )
    assert refused.value.status_code == 403
    assert await roster(pg_session, team_id) == set()


async def test_someone_already_in_that_role_is_named(pg_session, office):
    team_id = await jvt_sales(pg_session, office, [("omar", "supervisor"), ("sara", "agent")])
    with pytest.raises(HTTPException) as refused:
        await propose(
            pg_session,
            office,
            "owner",
            ActionKind.UPDATE_TEAM_MEMBERS,
            {"team_id": team_id, "members": as_agents(office, "lina", "sara")},
            "already-there",
        )
    assert refused.value.detail == "Track 1 is already in this team as agent"


async def test_another_organizations_team_is_unreachable(pg_session, office):
    """Tenant isolation: the lookup and the proposal see only the user's organization."""
    from uuid import uuid4

    from app.organization.models import Organization, OrganizationMembership, OrganizationTeam

    rival_org = str(uuid4())
    pg_session.add(Organization(id=rival_org, name="Rival", subscription_status="active"))
    await pg_session.flush()
    pg_session.add(OrganizationMembership(organization_id=rival_org, user_id="x-1", role="owner"))
    rival = OrganizationTeam(organization_id=rival_org, name="JVT Sales")
    pg_session.add(rival)
    await pg_session.commit()
    with pytest.raises(HTTPException) as refused:
        await propose(
            pg_session,
            office,
            "owner",
            ActionKind.UPDATE_TEAM_MEMBERS,
            {"team_id": rival.id, "members": as_agents(office, "lina")},
            "rival-team",
        )
    assert refused.value.status_code == 404
