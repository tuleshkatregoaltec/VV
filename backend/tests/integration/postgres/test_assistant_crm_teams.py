"""CRM team questions, and the reported conversation, through the real chat turn.

Reported conversation (the organization's owner):
1. "Assign Bilal Hameed lead to Track 8."       the proposal later showed as "unavailable"
2. "Who handles Bilal Hameed lead?"
3. "Can you give me Bilal Hameed's contact?"   refused as internal data
4. "How many teams in my org?"                 counted only teams in a partial view
5. "Tell me about Dubai Marina team."           "the CRM team or the property market?"
6. "Dubai Marina CRM team."                     the clarification was lost; no team found

The assistant's team view is the CRM's own (crm/assignment.scope_response): an administrator
sees every team of the organization with its members, a manager the teams they manage with
their members, an agent only the names of their own teams; team workload is for managers and
administrators. Models are scripted (see test_assistant_lead_contact_turns); routing, tools,
access checks, history and persistence are real.

Agency (crm_role_support): Nadia manages Dubai Marina (Track 8, User 10); Karim manages South
(User 2); Downtown has no members yet.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from crm_role_support import lead
from sqlalchemy import update
from test_assistant_lead_contact_turns import (
    EMAIL,
    PHONE,
    Chat,
    call,
    contact_answer,
    delegate,
    last_return,
    leads,
    say,
    script,
    setup_office,
)

from app.assistant_actions import service as actions
from app.chat.security import REFUSAL, RESTRICTED_HISTORY
from app.crm.assistant.service import get_conversation_messages
from app.organization.models import (
    Organization,
    OrganizationMembership,
    OrganizationTeam,
    OrganizationTeamMember,
)


@pytest.fixture
async def agency(pg_session, monkeypatch):
    office = await setup_office(pg_session, monkeypatch)
    ids = office.ids
    await pg_session.exec(
        update(OrganizationTeam)
        .where(OrganizationTeam.id == ids["north"])
        .values(name="Dubai Marina")
    )
    pg_session.add(OrganizationTeam(organization_id=ids["org"], name="Downtown"))
    # Another organization with a team of the same name, a member and a lead.
    other_org, stranger = str(uuid4()), f"stranger-{uuid4().hex[:6]}"
    pg_session.add(Organization(id=other_org, name="Rival", subscription_status="active"))
    await pg_session.flush()
    pg_session.add(
        OrganizationMembership(organization_id=other_org, user_id=stranger, role="owner")
    )
    rival = OrganizationTeam(organization_id=other_org, name="Dubai Marina")
    pg_session.add(rival)
    await pg_session.flush()
    pg_session.add(
        OrganizationTeamMember(
            team_id=rival.id, organization_id=other_org, user_id=stranger, role="supervisor"
        )
    )
    await pg_session.commit()
    rival_ids = {"org": other_org, "stranger": stranger, "rival": rival.id}
    await lead(pg_session, rival_ids, "Rival Client", team="rival", assignee="stranger")
    return SimpleNamespace(**vars(office), rival=rival_ids)


def teams(**request):
    return call("query_my_crm_records", resource="teams", **request)


def workload(**request):
    return call("query_my_crm_records", resource="team_workload", **request)


def capture(found: list):
    """A final answer that records the tool result it was given and relays it as JSON-ish."""

    def answer(messages):
        result = last_return(messages)
        found.append(result)
        return say(f"total={result.get('total')} records={result.get('records')}")

    return answer


async def ask(chat, message, *steps):
    """One CRM turn: the coordinator delegates, the CRM specialist runs `steps`."""
    found: list = []
    shown = await chat.turn(
        message,
        coordinator=delegate("retrieve_personal_crm", message),
        crm=script(*steps, capture(found)),
    )
    return found[-1], shown


# --- The reported conversation --------------------------------------------------------------


async def test_the_reported_conversation(pg_session, agency):
    bilal = agency.bilal
    chat = await Chat(pg_session, agency, "owner").start()

    # 1. Assign to Track 8: proposed, not done.
    def propose(messages):
        [match] = last_return(messages)["matches"]
        return call(
            "propose_crm_action",
            kind="assign_lead",
            payload={"lead_id": bilal.id, "assignee_id": match["id"]},
        )

    shown = await chat.turn(
        "Assign Bilal Hameed lead to Track 8.",
        coordinator=delegate("prepare_action", "Assign Bilal Hameed's lead to Track 8"),
        action=script(
            leads(search="Bilal Hameed"),
            call("find_assignment_colleagues", search="Track 8"),
            propose,
            say("I've assigned Bilal Hameed's lead to Track 8. It was handled by User 10."),
        ),
    )
    assert "awaiting your confirmation" in shown and "I've assigned" not in shown
    [proposal] = await actions.list_actions(
        pg_session, **chat.scope, conversation_id=chat.conversation_id
    )
    confirmed = await actions.confirm_action(pg_session, **chat.scope, action_id=proposal.id)
    assert confirmed.status == "succeeded"

    # The proposal stays in the conversation, stating the server's outcome; its prose (who
    # handled the lead at the time) is out of date and left out, not the whole message.
    first = (await get_conversation_messages(pg_session, chat.conversation_id, **chat.scope))[1]
    assert first.content != RESTRICTED_HISTORY
    assert "completed" in first.content and "handled by User 10" not in first.content

    # 2. Who handles it now.
    crm = script(
        leads(search="Bilal Hameed"),
        lambda m: say(f"Handled by {last_return(m)['records'][0]['handled_by']}."),
    )
    shown = await chat.turn(
        "Who handles Bilal Hameed lead?",
        coordinator=delegate("retrieve_personal_crm", "Who handles Bilal Hameed's lead?"),
        crm=crm,
    )
    assert shown == "Handled by Track 8."

    # 3. The contact, answered the first time it is asked.
    shown = await chat.turn(
        "Can you give me Bilal Hameed’s contact?",
        coordinator=delegate("retrieve_personal_crm", "Bilal Hameed's contact"),
        crm=script(leads(search="Bilal Hameed", include_contact_details=True), contact_answer),
    )
    assert shown != REFUSAL and PHONE in shown and EMAIL in shown

    # 4. The organization's teams: all three, including one with no members yet.
    found, _ = await ask(chat, "How many teams in my org?", teams(summary_only=True))
    assert found["total"] == 3
    assert any("Every team in your organization" in note for note in found["limitations"])

    # 5. Ambiguous: the coordinator asks, using no records.
    def clarify(messages):
        return say("Do you mean the Dubai Marina CRM team or the Dubai Marina property market?")

    shown = await chat.turn("Tell me about Dubai Marina team.", coordinator=script(clarify))
    assert shown.startswith("Do you mean")

    # 6. The answer keeps the question's meaning and resolves the team in this organization.
    def resolve(messages):
        replay = str(messages)
        assert "Tell me about Dubai Marina team." in replay and "Do you mean the Dubai" in replay
        # Earlier private answers are still not replayed.
        assert PHONE not in replay and EMAIL not in replay
        return call("retrieve_personal_crm", question="Members of the Dubai Marina CRM team")

    found: list = []
    await chat.turn(
        "Dubai Marina CRM team.",
        coordinator=script(resolve, lambda m: say(last_return(m))),
        crm=script(teams(team="Dubai Marina CRM team"), capture(found)),
    )
    [team] = found[0]["records"]
    assert team == {
        "team": "Dubai Marina",
        "your_role": None,
        "member_count": 3,
        "managers": ["Nadia Manager"],
        "agents": ["Track 8", "User 10"],
    }


async def test_a_bare_team_reply_after_the_question_keeps_its_subject(pg_session, agency):
    chat = await Chat(pg_session, agency, "owner").start()
    # A private lookup first: from then on earlier private prose is never replayed.
    await ask(chat, "Bilal's contact", leads(search="Bilal Hameed", include_contact_details=True))
    await chat.turn(
        "Tell me about Dubai Marina",
        coordinator=script(say("The Dubai Marina CRM team, or the Dubai Marina market?")),
    )

    def resolve(messages):
        assert "The Dubai Marina CRM team, or the Dubai Marina market?" in str(messages)
        return say("resolved")

    assert await chat.turn("team", coordinator=script(resolve)) == "resolved"

    # Once a private answer follows, that exchange is no longer replayed.
    await ask(chat, "Dubai Marina team", teams(team="Dubai Marina"))

    def fresh(messages):
        assert "Dubai Marina market" not in str(messages)
        return say("ok")

    await chat.turn("and South?", coordinator=script(fresh))


# --- Each role sees the teams the CRM shows it ----------------------------------------------


async def test_owner_sees_every_team_and_its_members(pg_session, agency):
    chat = await Chat(pg_session, agency, "owner").start()
    found, _ = await ask(chat, "List my org's teams", teams())
    assert [t["team"] for t in found["records"]] == ["Downtown", "Dubai Marina", "South"]
    assert found["records"][0] == {
        "team": "Downtown",
        "your_role": None,
        "member_count": 0,
        "managers": [],
        "agents": [],
    }
    south = found["records"][2]
    assert (south["managers"], south["agents"]) == (["Karim South"], ["User 2"])


async def test_manager_sees_only_the_teams_they_manage(pg_session, agency):
    chat = await Chat(pg_session, agency, "nadia").start()
    found, _ = await ask(chat, "How many teams?", teams())
    assert found["total"] == 1
    [team] = found["records"]
    assert team["team"] == "Dubai Marina" and team["your_role"] == "manager"
    assert team["managers"] == ["you"] and team["agents"] == ["Track 8", "User 10"]
    assert any("not your organization's team count" in n for n in found["limitations"])
    # Another manager's team is not shown, and not confirmed to exist.
    found, _ = await ask(chat, "Tell me about South team", teams(team="South"))
    assert found["records"] == [] and found["total"] == 0
    assert "No team you can see in the CRM has that name." in found["limitations"]


async def test_agent_sees_only_their_own_teams_name(pg_session, agency):
    chat = await Chat(pg_session, agency, "omar").start()
    found, _ = await ask(chat, "What team am I in?", teams())
    # As in the CRM: the name and their role, no members and no other teams.
    assert found["records"] == [{"team": "Dubai Marina", "your_role": "member"}]
    assert any("agents do not see team members" in n for n in found["limitations"])
    found, _ = await ask(chat, "Tell me about Downtown team", teams(team="Downtown"))
    assert found["records"] == []


async def test_another_organizations_teams_and_leads_are_never_shown(pg_session, agency):
    chat = await Chat(pg_session, agency, "owner").start()
    found, shown = await ask(chat, "Dubai Marina team", teams(team="Dubai Marina"))
    [team] = found["records"]
    assert team["member_count"] == 3 and "you" not in team["managers"]
    assert "stranger" not in shown and agency.rival["stranger"] not in shown
    found, shown = await ask(chat, "Rival Client's contact", leads(search="Rival Client"))
    assert found["total"] == 0 and "Rival" not in str(found["records"])
    # The rival owner, likewise, sees only their own team.
    rival_office = SimpleNamespace(
        ids={"org": agency.rival["org"], "stranger": agency.rival["stranger"]},
        monkeypatch=agency.monkeypatch,
    )
    rival_chat = await Chat(pg_session, rival_office, "stranger").start()
    found, _ = await ask(rival_chat, "How many teams?", teams())
    assert [t["team"] for t in found["records"]] == ["Dubai Marina"]
    assert found["records"][0]["agents"] == []


# --- Team workload --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("person", "expected"),
    [("owner", {"Dubai Marina", "South"}), ("nadia", {"Dubai Marina"}), ("omar", None)],
)
async def test_team_workload_follows_the_crm(pg_session, agency, person, expected):
    chat = await Chat(pg_session, agency, person).start()
    found, _ = await ask(chat, "How is the team's workload?", workload())
    if expected is None:
        # The CRM refuses agents this view; the reason is said, nothing is shown.
        assert found["available"] is False and found["records"] == []
        assert "only to team managers and organization administrators" in found["limitations"][0]
        return
    assert {team["team"] for team in found["records"]} == expected
    # Narrowed to one team by the name as the user gave it.
    found, _ = await ask(
        chat, "Dubai Marina CRM team workload", workload(team="Dubai Marina CRM team")
    )
    [team] = found["records"]
    assert team["team"] == "Dubai Marina"
    assert {m["name"] for m in team["members"]} >= {"Track 8", "User 10"}


# --- Leads of a team named the way people say it --------------------------------------------


async def test_a_teams_leads_by_its_spoken_name(pg_session, agency):
    chat = await Chat(pg_session, agency, "owner").start()
    found, _ = await ask(
        chat, "Leads of the Dubai Marina CRM team", leads(team="Dubai Marina CRM team")
    )
    assert [row["contact_name"] for row in found["records"]] == ["Bilal Hameed"]


# --- Missing or ambiguous team names are asked about ----------------------------------------


def ask_which_team(messages):
    """The model's follow-up when a name resolves to no single team."""
    result = last_return(messages)
    if len(result["records"]) == 1:
        return say(f"{result['records'][0]['team']}: {result['records'][0]}")
    names = ", ".join(team["team"] for team in result["records"]) or "none"
    return say(f"Which team do you mean? Matching teams you can see: {names}.")


async def test_an_unknown_team_is_asked_about(pg_session, agency):
    chat = await Chat(pg_session, agency, "owner").start()
    found: list = []

    def answer(messages):
        found.append(last_return(messages))
        return ask_which_team(messages)

    shown = await chat.turn(
        "Tell me about the Palm Jumeirah team",
        coordinator=delegate("retrieve_personal_crm", "Palm Jumeirah team"),
        crm=script(teams(team="Palm Jumeirah team"), answer),
    )
    assert found[0]["records"] == []
    assert "No team you can see in the CRM has that name." in found[0]["limitations"]
    assert shown == "Which team do you mean? Matching teams you can see: none."


async def test_two_teams_answering_to_one_name_are_asked_about(pg_session, agency):
    ids = agency.ids
    pg_session.add(OrganizationTeam(organization_id=ids["org"], name="Dubai Marina Team"))
    await pg_session.commit()
    chat = await Chat(pg_session, agency, "owner").start()
    found: list = []

    def answer(messages):
        found.append(last_return(messages))
        return ask_which_team(messages)

    shown = await chat.turn(
        "Dubai Marina CRM team",
        coordinator=delegate("retrieve_personal_crm", "Dubai Marina CRM team"),
        crm=script(teams(team="Dubai Marina CRM team"), answer),
    )
    assert [team["team"] for team in found[0]["records"]] == ["Dubai Marina", "Dubai Marina Team"]
    assert "Several teams match that name; ask the user which one." in found[0]["limitations"]
    assert shown.startswith("Which team do you mean?")


async def test_the_workload_total_is_not_presented_as_the_team_count(pg_session, agency):
    chat = await Chat(pg_session, agency, "owner").start()
    found, _ = await ask(chat, "Workload", workload(summary_only=True))
    counted, _ = await ask(chat, "How many teams?", teams(summary_only=True))
    # Downtown has no members: the CRM's workload view leaves it out, the team list does not.
    assert (found["total"], counted["total"]) == (2, 3)
    assert any("not a team count" in note for note in found["limitations"])
