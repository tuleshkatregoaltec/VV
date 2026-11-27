"""Two reported CRM Assistant bugs, through the real chat turn with scripted models.

1. Earlier answers turned into "This earlier answer is unavailable..." after later questions
   or actions, although the user could still see every record they were built from. They
   must stay shown while access remains, and still be withheld once it is lost.
2. "Reassign Mariam Ali to Track 6 agent": after confirming, the card said "Completed / Lead
   assigned" next to "current assignee: Track 3, new assignee: Track 6". The card must show
   the outcome the CRM actually holds, and never success that did not happen.

Agency (crm_role_support): the owner; Nadia manages North (Track 3, Track 6); Karim manages
South (User 2). Synthetic records only.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from crm_role_support import agency, lead
from sqlalchemy import delete, update
from test_assistant_lead_contact_turns import Chat, call, delegate, last_return, say, script

from app.assistant_actions import service as actions
from app.chat.security import RESTRICTED_HISTORY
from app.crm import assignment
from app.crm.assistant.service import get_conversation_messages
from app.crm.inbound_models import CrmInboundEnquiry
from app.organization.models import OrganizationMembership, OrganizationTeamMember

NAMES = {
    "owner": ("Agency", "Owner"),
    "nadia": ("Nadia", "Manager"),
    "omar": ("Track", "3"),  # North agent; handles Mariam Ali.
    "sara": ("Track", "6"),  # North agent; the intended new handler.
    "karim": ("Karim", "South"),
    "lina": ("User", "2"),
}


@pytest.fixture
async def office(pg_session, monkeypatch):
    from app.crm.assistant import crm_tools, service, workflows
    from app.organization import service as organizations
    from app.organization import teams

    ids = await agency(pg_session)
    people = {ids[person]: name for person, name in NAMES.items()}

    async def profile(user_id):
        first, last = people.get(user_id, ("Former", "Member"))
        return SimpleNamespace(first_name=first, last_name=last, email=f"{user_id}@example.test")

    for module in (organizations, actions, teams):
        monkeypatch.setattr(module, "get_user_by_id", profile)

    async def session():
        yield pg_session

    for module in (workflows, crm_tools):
        monkeypatch.setattr(module, "get_db_session", session)
    monkeypatch.setattr(service.settings, "ASSISTANT_ENABLED", True)
    monkeypatch.setattr(service.settings, "ASSISTANT_TYPED_ROUTING_ENABLED", False)
    monkeypatch.setattr(
        service.admission,
        "acquire",
        AsyncMock(return_value=service.admission.TurnLease("l", 150_000)),
    )
    monkeypatch.setattr(service.admission, "finish", AsyncMock())
    mariam = await lead(pg_session, ids, "Mariam Ali", team="north", assignee="omar")
    other = await lead(pg_session, ids, "Mariam Ali Khan", team="north", assignee="sara")
    return SimpleNamespace(
        ids=ids, mariam=mariam, other=other, people=people, monkeypatch=monkeypatch
    )


def leads(**request):
    return call("query_my_crm_records", resource="leads", **request)


async def holder(db, lead_id):
    db.expire_all()
    return (await db.get(CrmInboundEnquiry, lead_id)).assigned_user_id


async def shown(db, chat):
    return [
        m.content for m in await get_conversation_messages(db, chat.conversation_id, **chat.scope)
    ]


async def list_answer(db, office, chat, search="Mariam"):
    crm = script(
        leads(search=search),
        lambda m: say(f"{last_return(m)['total']} leads match: Mariam Ali, Mariam Ali Khan."),
    )
    return await chat.turn(
        "Show my Mariam leads",
        coordinator=delegate("retrieve_personal_crm", "Leads named Mariam"),
        crm=crm,
    )


# --- 1. Earlier answers stay while access remains -------------------------------------------


async def test_an_answer_stays_after_its_leads_change_while_still_visible(pg_session, office):
    chat = await Chat(pg_session, office, "nadia").start()
    first = await list_answer(pg_session, office, chat)
    # Later edits to the same leads: a new stage and a different handler within North.
    await pg_session.execute(
        update(CrmInboundEnquiry)
        .where(CrmInboundEnquiry.id == office.mariam.id)
        .values(status="contacted")
    )
    await pg_session.commit()
    scope = await assignment.load_scope(pg_session, office.ids["org"], office.ids["nadia"])
    await assignment.reassign(pg_session, scope, [office.other.id], office.ids["omar"])
    await pg_session.commit()
    # A later question, then the history loads again.
    count = script(leads(summary_only=True), lambda m: say(f"{last_return(m)['total']} leads."))
    await chat.turn(
        "How many leads?",
        coordinator=delegate("retrieve_personal_crm", "Count my leads"),
        crm=count,
    )
    history = await shown(pg_session, chat)
    assert history[1] == first == "2 leads match: Mariam Ali, Mariam Ali Khan."
    assert RESTRICTED_HISTORY not in history


async def test_counts_and_workload_stay_after_new_leads_arrive(pg_session, office):
    chat = await Chat(pg_session, office, "nadia").start()
    crm = script(
        leads(summary_only=True),
        call("query_my_crm_records", resource="team_workload"),
        say("North has 2 open leads."),
    )
    answer = await chat.turn(
        "How many leads and what's my team's workload?",
        coordinator=delegate("retrieve_personal_crm", "Lead count and team workload"),
        crm=crm,
    )
    await lead(pg_session, office.ids, "New Arrival", team="north", assignee="omar")
    assert (await shown(pg_session, chat))[1] == answer


async def test_an_answer_is_withheld_once_one_of_its_leads_is_out_of_reach(pg_session, office):
    """Privacy holds: a listed lead moving to a team Nadia does not manage hides the answer."""
    chat = await Chat(pg_session, office, "nadia").start()
    await list_answer(pg_session, office, chat)
    owner = await assignment.load_scope(pg_session, office.ids["org"], office.ids["owner"])
    await assignment.reassign(
        pg_session, owner, [office.other.id], office.ids["lina"], team_id=office.ids["south"]
    )
    await pg_session.commit()
    assert (await shown(pg_session, chat))[1] == RESTRICTED_HISTORY


async def test_a_workload_answer_is_withheld_once_the_manager_loses_the_team(pg_session, office):
    chat = await Chat(pg_session, office, "nadia").start()
    crm = script(call("query_my_crm_records", resource="team_workload"), say("North: 2 open."))
    await chat.turn(
        "My team's workload?",
        coordinator=delegate("retrieve_personal_crm", "Team workload"),
        crm=crm,
    )
    await pg_session.exec(
        delete(OrganizationTeamMember).where(
            OrganizationTeamMember.team_id == office.ids["north"],
            OrganizationTeamMember.user_id == office.ids["nadia"],
        )
    )
    await pg_session.commit()
    assert (await shown(pg_session, chat))[1] == RESTRICTED_HISTORY


async def test_answers_are_withheld_after_leaving_the_organization(pg_session, office):
    chat = await Chat(pg_session, office, "nadia").start()
    await list_answer(pg_session, office, chat)
    await pg_session.exec(
        delete(OrganizationMembership).where(
            OrganizationMembership.organization_id == office.ids["org"],
            OrganizationMembership.user_id == office.ids["nadia"],
        )
    )
    await pg_session.commit()
    assert (await shown(pg_session, chat))[1] == RESTRICTED_HISTORY


# --- 2. The assignment card shows the CRM's real outcome ------------------------------------


async def propose_to_track_6(pg_session, office, chat):
    found = {}

    def propose(messages):
        found["assignee"] = last_return(messages)
        [match] = found["assignee"]["matches"]
        return call(
            "propose_crm_action",
            kind="assign_lead",
            payload={"lead_id": office.mariam.id, "assignee_id": match["id"]},
        )

    action = script(
        leads(search="Mariam Ali"),
        call("find_assignment_colleagues", search="Track 6 agent"),
        propose,
        say("Mariam Ali is handled by Track 3."),
    )
    answer = await chat.turn(
        "Reassign Mariam Ali to Track 6 agent",
        coordinator=delegate("prepare_action", "Reassign Mariam Ali to Track 6 agent"),
        action=action,
    )
    [proposal] = await actions.list_actions(
        pg_session, **chat.scope, conversation_id=chat.conversation_id
    )
    return found, answer, proposal


async def test_the_card_reports_the_assignee_the_crm_now_holds(pg_session, office):
    ids = office.ids
    chat = await Chat(pg_session, office, "nadia").start()
    found, answer, proposal = await propose_to_track_6(pg_session, office, chat)
    # "Track 6 agent" is the person Track 6; the lead is Mariam Ali, not the near namesake.
    assert found["assignee"]["matches"] == [{"id": ids["sara"], "display_name": "Track 6"}]
    assert proposal.preview["lead"] == f"Mariam Ali (lead #{office.mariam.id})"
    # Before confirmation: proposed, not done, nothing written.
    assert proposal.status == "awaiting_confirmation"
    assert (proposal.preview["current_assignee"], proposal.preview["new_assignee"]) == (
        "Track 3",
        "Track 6",
    )
    assert "awaiting your confirmation" in answer and "completed" not in answer
    assert await holder(pg_session, office.mariam.id) == ids["omar"]

    done = await actions.confirm_action(pg_session, **chat.scope, action_id=proposal.id)
    assert done.status == "succeeded"
    assert await holder(pg_session, office.mariam.id) == ids["sara"]
    # The card states the CRM's state now: Track 6 holds it; Track 3 is the previous holder.
    for card in (done, await actions.get_action(pg_session, **chat.scope, action_id=proposal.id)):
        assert card.preview["current_assignee"] == "Track 6"
        assert card.preview["previous_assignee"] == "Track 3"
        assert "new_assignee" not in card.preview
        assert card.result["message"] == "Lead assigned to Track 6"
    # And so does the answer above it.
    history = await shown(pg_session, chat)
    assert history[1].startswith("Assign lead: completed. Lead assigned to Track 6")


@pytest.mark.parametrize("change", ["assignee_left_the_team", "manager_lost_the_team"])
async def test_a_failed_confirmation_never_claims_success(pg_session, office, change):
    ids = office.ids
    chat = await Chat(pg_session, office, "nadia").start()
    _, _, proposal = await propose_to_track_6(pg_session, office, chat)
    person = "sara" if change == "assignee_left_the_team" else "nadia"
    await pg_session.exec(
        delete(OrganizationTeamMember).where(
            OrganizationTeamMember.team_id == ids["north"],
            OrganizationTeamMember.user_id == ids[person],
        )
    )
    await pg_session.commit()
    done = await actions.confirm_action(pg_session, **chat.scope, action_id=proposal.id)
    assert done.status == "failed"
    assert await holder(pg_session, office.mariam.id) == ids["omar"]
    assert "Lead assigned" not in str(done.result)
    assert "previous_assignee" not in done.preview
    history = await shown(pg_session, chat)
    assert "completed" not in history[1]


async def test_an_ambiguous_assignee_is_never_proposed(pg_session, office):
    ids = office.ids
    twin = f"twin-{ids['org'][:6]}"
    office.people[twin] = ("Track", "6")
    pg_session.add(OrganizationMembership(organization_id=ids["org"], user_id=twin))
    await pg_session.flush()
    pg_session.add(
        OrganizationTeamMember(
            team_id=ids["north"], organization_id=ids["org"], user_id=twin, role="agent"
        )
    )
    await pg_session.commit()
    chat = await Chat(pg_session, office, "nadia").start()
    seen = {}

    def guess(messages):
        seen["assignee"] = last_return(messages)
        return call(
            "propose_crm_action",
            kind="assign_lead",
            payload={"lead_id": office.mariam.id, "assignee_id": ids["sara"]},
        )

    def ask(messages):
        seen["proposal"] = last_return(messages)
        return say("Two colleagues are called Track 6. Which one?")

    action = script(
        leads(search="Mariam Ali"),
        call("find_assignment_colleagues", search="Track 6 agent"),
        guess,
        ask,
    )
    await chat.turn(
        "Reassign Mariam Ali to Track 6 agent",
        coordinator=delegate("prepare_action", "Reassign Mariam Ali to Track 6 agent"),
        action=action,
    )
    assert seen["assignee"]["clarification_required"] is True
    assert len(seen["assignee"]["matches"]) == 2
    assert seen["proposal"]["available"] is False
    assert not await actions.list_actions(
        pg_session, **chat.scope, conversation_id=chat.conversation_id
    )
    assert await holder(pg_session, office.mariam.id) == ids["omar"]
