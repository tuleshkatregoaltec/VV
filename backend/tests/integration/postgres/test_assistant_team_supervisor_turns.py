"""Team supervisors and agents through the assistant, as the CRM stores and names them.

Reported conversation (an organization owner):
1. "Create team jvt sales in this manager is track 8 agents is track1,2,3"
                                     -> the team was created, the requested members dropped
2. "Set Track 8 as manager of JVT Sales."
                                     -> "Do you mean the colleague named Track 8?" (no proposal)
3. "yes make track 8 manager"        -> "Replace the current manager(s) or add a co-manager?"
                                        although the team had no members at all

The CRM stores a team member's role as "supervisor" or "agent" (organization_team_members);
its Teams page calls them Supervisor ("manages the team, imports leads and assigns them") and
Agent, and organization/teams.py says a team's supervisors are its managers. A team may have
several supervisors, and making someone a supervisor never removes the others.

So: a new team can be proposed with its supervisors and agents, applied together on
confirmation; an exact, unique lookup is not asked about again; replacing versus co-supervising
is only a choice when the team has another supervisor. Nothing is written before confirmation,
and confirmation rechecks permission and the team's state.

Models are scripted; routing, history loading, lookups, proposals and confirmation are real.
"""

import pytest
from sqlalchemy import delete, update
from sqlmodel import select
from test_assistant_lead_contact_turns import (
    Chat,
    call,
    delegate,
    last_return,
    leads,
    say,
    script,
)
from test_assistant_team_clarification_turns import carries_lead_handles, setup_track_office
from test_assistant_team_management import roster, team_named

from app.assistant_actions import service as actions
from app.assistant_actions.models import ActionKind, ActionProposalRequest, AssistantAction
from app.organization.models import (
    OrganizationMembership,
    OrganizationTeam,
    OrganizationTeamMember,
)

CREATE_REQUEST = "Create team jvt sales\nin this manager is track 8\nagents is track1,2,3"


@pytest.fixture
async def office(pg_session, monkeypatch):
    return await setup_track_office(pg_session, monkeypatch)


def expecting(match, next_step):
    """A step that checks the last lookup found exactly `match`, then takes `next_step`."""

    def step(messages):
        result = last_return(messages)
        assert result["clarification_required"] is False, result
        assert [m.get("display_name") or m.get("name") for m in result["matches"]] == [match]
        return next_step

    return step


async def jvt_sales(db, office, members=()):
    """An existing "JVT Sales" team with the given (person, role) members."""
    team = OrganizationTeam(organization_id=office.ids["org"], name="JVT Sales")
    db.add(team)
    await db.flush()
    for person, role in members:
        db.add(
            OrganizationTeamMember(
                team_id=team.id,
                organization_id=office.ids["org"],
                user_id=office.ids[person],
                role=role,
            )
        )
    await db.commit()
    return team.id


async def stored_actions(db, conversation_id):
    db.expire_all()
    rows = (
        await db.exec(
            select(AssistantAction).where(AssistantAction.conversation_id == conversation_id)
        )
    ).all()
    return [(row.id, row.kind, row.status, row.payload) for row in rows]


async def make_admin(db, office, person, value=True):
    membership = update(OrganizationMembership).where(
        OrganizationMembership.organization_id == office.ids["org"],
        OrganizationMembership.user_id == office.ids[person],
    )
    await db.exec(membership.values(organization_admin=value))
    await db.commit()


# --- 1. A new team with its supervisor and agents ------------------------------------------


async def test_create_team_proposes_its_supervisor_and_agents_together(pg_session, office):
    ids = office.ids
    chat = await Chat(pg_session, office, "owner").start()
    members = [
        {"member_id": ids["omar"], "role": "supervisor"},  # Track 8
        {"member_id": ids["sara"], "role": "agent"},  # Track 1
        {"member_id": ids["lina"], "role": "agent"},  # Track 2
        {"member_id": ids["nadia"], "role": "agent"},  # Track 3
    ]
    refused: list = []

    def guessed_member_is_refused(messages):
        # Track 10 was never looked up this turn: the server refuses the guessed ID.
        return call(
            "propose_crm_action",
            kind="create_team",
            payload={
                "name": "jvt sales",
                "members": [*members, {"member_id": ids["karim"], "role": "agent"}],
            },
        )

    def then_the_looked_up_members(messages):
        refused.append(last_return(messages))
        return call(
            "propose_crm_action",
            kind="create_team",
            payload={"name": "jvt sales", "members": members},
        )

    def claims_success(messages):
        assert last_return(messages)["confirmation_required"] is True
        return say("Done! jvt sales is created with Track 8 managing it.")

    shown = await chat.turn(
        CREATE_REQUEST,
        coordinator=delegate("prepare_action", CREATE_REQUEST),
        action=script(
            call("find_team_people", search="track 8"),
            expecting("Track 8", call("find_team_people", search="Track 1")),
            expecting("Track 1", call("find_team_people", search="Track 2")),
            expecting("Track 2", call("find_team_people", search="Track 3")),
            expecting("Track 3", guessed_member_is_refused(None)),
            then_the_looked_up_members,
            claims_success,
        ),
    )
    assert refused[0]["available"] is False and refused[0]["clarification_required"] is True

    [(action_id, kind, status, payload)] = await stored_actions(pg_session, chat.conversation_id)
    assert (kind, status, payload) == (
        "create_team",
        "awaiting_confirmation",
        {"name": "jvt sales", "members": members},
    )
    card = await actions.get_action(pg_session, **chat.scope, action_id=action_id)
    # The card names the CRM's roles and every requested member; nothing is left for later.
    assert card.title == "Create team"
    assert card.preview["team"] == "jvt sales"
    assert card.preview["supervisors"] == ["Track 8"]
    assert card.preview["agents"] == ["Track 1", "Track 2", "Track 3"]
    assert "afterwards" not in card.preview["consequence"]
    assert "manager" not in str(card.preview).casefold()
    assert "awaiting your confirmation" in shown and "Done" not in shown
    # Proposed is not done.
    assert await team_named(pg_session, ids["org"], "jvt sales") is None

    done = await actions.confirm_action(pg_session, **chat.scope, action_id=action_id)
    assert done.status == "succeeded", done.result
    team = await team_named(pg_session, ids["org"], "jvt sales")
    assert await roster(pg_session, team.id) == {
        (ids["omar"], "supervisor"),
        (ids["sara"], "agent"),
        (ids["lina"], "agent"),
        (ids["nadia"], "agent"),
    }


async def test_create_team_confirmation_rechecks_permission_and_members(pg_session, office):
    """All or nothing: a refused confirmation creates neither the team nor its roster."""
    ids = office.ids
    await make_admin(pg_session, office, "karim")
    chat = await Chat(pg_session, office, "karim").start()

    async def propose(name, members):
        return await actions.propose_action(
            pg_session,
            **chat.scope,
            request=ActionProposalRequest(
                kind=ActionKind.CREATE_TEAM,
                conversation_id=chat.conversation_id,
                payload={"name": name, "members": members},
                idempotency_key=f"create-team-{name}",
            ),
        )

    leaving = await propose("Palm", [{"member_id": ids["lina"], "role": "supervisor"}])
    revoked = await propose("Creek", [{"member_id": ids["omar"], "role": "agent"}])

    # Track 2 leaves the organization before the first is confirmed.
    await pg_session.exec(
        delete(OrganizationMembership).where(OrganizationMembership.user_id == ids["lina"])
    )
    await pg_session.commit()
    done = await actions.confirm_action(pg_session, **chat.scope, action_id=leaving.id)
    assert done.status == "failed"
    assert await team_named(pg_session, ids["org"], "Palm") is None

    # Karim is no longer an administrator when the second is confirmed.
    await make_admin(pg_session, office, "karim", value=False)
    done = await actions.confirm_action(pg_session, **chat.scope, action_id=revoked.id)
    assert done.status == "failed"
    assert await team_named(pg_session, ids["org"], "Creek") is None


# --- 2. A direct supervisor request is proposed, not re-asked --------------------------------


async def test_set_supervisor_is_proposed_without_reconfirming_a_unique_lookup(pg_session, office):
    ids = office.ids
    team_id = await jvt_sales(pg_session, office)  # No members at all.
    chat = await Chat(pg_session, office, "owner").start()
    held: list = []

    def tries_to_ask_first(messages):
        return call(
            "hold_pending_request",
            kind="set_team_manager",
            details={
                "team": "JVT Sales",
                "managers": ["Track 8"],
                "missing": ["Confirm the intended team member"],
            },
        )

    def proposes(messages):
        held.append(last_return(messages))
        return call(
            "propose_crm_action",
            kind="set_team_manager",
            payload={"team_id": team_id, "member_id": ids["omar"]},
        )

    request = "Set Track 8 as manager of JVT Sales."
    shown = await chat.turn(
        request,
        coordinator=delegate("prepare_action", request),
        action=script(
            call("find_teams", search="JVT Sales"),
            expecting("JVT Sales", call("find_team_people", search="Track 8")),
            expecting("Track 8", tries_to_ask_first(None)),
            proposes,
            say("Track 8 is now the supervisor of JVT Sales."),
        ),
    )
    # Both lookups were exact and unique and the team has no supervisor to replace: the server
    # refuses to hold a question and directs the model to propose.
    assert held[0]["available"] is False and held[0]["propose_now"] is True

    [(action_id, kind, status, payload)] = await stored_actions(pg_session, chat.conversation_id)
    assert (kind, status) == ("set_team_manager", "awaiting_confirmation")
    card = await actions.get_action(pg_session, **chat.scope, action_id=action_id)
    assert card.title == "Set team supervisor"
    assert card.preview["person"] == "Track 8"
    assert card.preview["current_supervisors"] == []
    assert "supervisor" in card.preview["consequence"].casefold()
    assert "manager" not in str(card.preview).casefold()
    assert "awaiting your confirmation" in shown and "is now the supervisor" not in shown
    assert await roster(pg_session, team_id) == set()  # No write before confirmation.

    # Someone changes the team in the CRM first: confirmation rechecks it and changes nothing.
    pg_session.add(
        OrganizationTeamMember(
            team_id=team_id, organization_id=ids["org"], user_id=ids["lina"], role="agent"
        )
    )
    await pg_session.commit()
    done = await actions.confirm_action(pg_session, **chat.scope, action_id=action_id)
    assert (done.status, done.result["message"]) == (
        "failed",
        "Record changed since preview; create a new proposal",
    )
    assert await roster(pg_session, team_id) == {(ids["lina"], "agent")}


@pytest.mark.parametrize(
    ("search", "why"),
    [("Track", "several people match"), ("Nobody Known", "no one matches")],
)
async def test_an_ambiguous_or_unknown_person_may_still_be_asked_about(
    pg_session, office, search, why
):
    await jvt_sales(pg_session, office)
    chat = await Chat(pg_session, office, "owner").start()
    held: list = []

    def asks(messages):
        assert last_return(messages)["clarification_required"] is True, why
        return call(
            "hold_pending_request",
            kind="set_team_manager",
            details={"team": "JVT Sales", "managers": [search], "missing": ["which person"]},
        )

    def records(messages):
        held.append(last_return(messages))
        return say("Which person do you mean?")

    await chat.turn(
        f"Set {search} as supervisor of JVT Sales",
        coordinator=delegate("prepare_action", f"Set {search} as supervisor of JVT Sales"),
        action=script(
            call("find_teams", search="JVT Sales"),
            call("find_team_people", search=search),
            asks,
            records,
        ),
    )
    assert held[0]["available"] is True
    assert await stored_actions(pg_session, chat.conversation_id) == []


# --- 3. "yes" answers the team-role question just asked ----------------------------------------


async def test_yes_answers_the_replace_question_not_an_older_lead_answer(pg_session, office):
    ids = office.ids
    team_id = await jvt_sales(pg_session, office, [("nadia", "supervisor")])  # Track 3.
    await make_admin(pg_session, office, "karim")
    chat = await Chat(pg_session, office, "karim").start()

    await chat.turn(
        "give me latest 5 leads",
        coordinator=delegate("retrieve_personal_crm", "The latest 5 leads"),
        crm=script(leads(), say("The latest leads are Mariam Ali and Bilal Hameed.")),
    )

    held: list = []

    def asks_replace(messages):
        held.append(last_return(messages))
        return say("Should Track 8 replace Track 3 as the supervisor of JVT Sales?")

    request = "Change the manager of JVT Sales to Track 8"
    await chat.turn(
        request,
        coordinator=delegate("prepare_action", request),
        action=script(
            call("find_teams", search="JVT Sales"),
            expecting("JVT Sales", call("find_team_people", search="Track 8")),
            expecting(
                "Track 8",
                call(
                    "hold_pending_request",
                    kind="set_team_manager",
                    details={
                        "team": "JVT Sales",
                        "managers": ["Track 8"],
                        "missing": ["replace Track 3 or supervise alongside them"],
                    },
                ),
            ),
            asks_replace,
        ),
    )
    # Another supervisor exists, so replacing or co-supervising is a real choice to ask about.
    assert held[0]["available"] is True

    def continues(messages):
        replay = str(messages)
        assert not carries_lead_handles(replay)
        assert '"kind": "set_team_manager"' in replay and '"team": "JVT Sales"' in replay
        return call("prepare_action", question="Replace JVT Sales's supervisor with Track 8")

    def replaces(messages):
        return call(
            "propose_crm_action",
            kind="set_team_manager",
            payload={"team_id": team_id, "member_id": ids["omar"], "replace_existing": True},
        )

    def task_has_the_request(messages):
        replay = str(messages)
        assert not carries_lead_handles(replay)
        task = replay[replay.index("Pending request this message may answer") :]
        assert '"team": "JVT Sales"' in task and '"managers": ["Track 8"]' in task
        return call("find_teams", search="JVT Sales")

    shown = await chat.turn(
        "yes",
        coordinator=script(continues, lambda m: say(last_return(m))),
        action=script(
            task_has_the_request,
            expecting("JVT Sales", call("find_team_people", search="Track 8")),
            expecting("Track 8", replaces(None)),
            lambda m: say("Track 8 replaces Track 3."),
        ),
    )
    assert "Mariam" not in shown and "awaiting your confirmation" in shown
    [(action_id, kind, status, payload)] = await stored_actions(pg_session, chat.conversation_id)
    assert (kind, status, payload["replace_existing"]) == (
        "set_team_manager",
        "awaiting_confirmation",
        True,
    )
    card = await actions.get_action(pg_session, **chat.scope, action_id=action_id)
    assert card.preview["current_supervisors"] == ["Track 3"]
    assert card.preview["supervisors_leaving_the_team"] == ["Track 3"]
    assert await roster(pg_session, team_id) == {(ids["nadia"], "supervisor")}

    # 4. Karim loses administrator rights before confirming: refused, nothing changes.
    await make_admin(pg_session, office, "karim", value=False)
    done = await actions.confirm_action(pg_session, **chat.scope, action_id=action_id)
    assert done.status == "failed"
    assert await roster(pg_session, team_id) == {(ids["nadia"], "supervisor")}
