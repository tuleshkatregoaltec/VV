"""Reported conversation: counts, a five-lead list, "who handles", and "Reassign Adam Saleh to
Track 3", through the real chat turn with scripted models and synthetic records.

1. "How many leads are in my CRM? Group them by status."   -> "You have 20 leads: New 20."
2. "Show me the first five leads with their names, team, handler and next follow-up."
                                                            -> one run-together paragraph
3. "Who handles Adam Saleh? Also give me their phone number."
4. "Reassign Adam Saleh to Track 4."   -> "no agent named Adam Saleh or team named Track 4"
5. "Reassign Adam Saleh to Track 3."   -> lead taken for a colleague, colleague for a team,
                                          and "I can't determine your role"

"Track 1", "Track 3" and "Track 4" are people (the CRM shows members by their first and last
name). The scripts stand in for the model, including its mistaken first moves; what is under
test is what the server tells it, what it lets through and what it writes.

Agency (crm_role_support): the owner; Nadia manages North (Track 1, Track 3); Karim manages
South (Track 4).
"""

import pytest
from crm_role_support import agency, lead
from sqlalchemy import delete
from test_assistant_lead_contact_turns import Chat, call, delegate, last_return, say, script

from app.assistant_actions import service as actions
from app.crm.inbound_models import CrmInboundEnquiry
from app.organization.models import OrganizationMembership, OrganizationTeamMember

NAMES = {
    "owner": ("Agency", "Owner"),
    "nadia": ("Nadia", "Manager"),
    "omar": ("Track", "1"),  # North agent; handles Adam Saleh.
    "sara": ("Track", "3"),  # North agent; someone Nadia may assign to.
    "karim": ("Karim", "South"),
    "lina": ("Track", "4"),  # South agent; exists, but not in a team Nadia manages.
}
PHONE = "+971500000009"  # crm_role_support gives every contact this phone.


@pytest.fixture
async def office(pg_session, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

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
    adam = await lead(pg_session, ids, "Adam Saleh", team="north", assignee="omar")
    return SimpleNamespace(ids=ids, adam=adam, people=people, monkeypatch=monkeypatch)


async def holder(db, lead_id):
    db.expire_all()
    return (await db.get(CrmInboundEnquiry, lead_id)).assigned_user_id


def leads(**request):
    return call("query_my_crm_records", resource="leads", **request)


# --- 1. Counts cover every visible match, whatever the page size ----------------------------


@pytest.mark.parametrize(("person", "visible"), [("owner", 23), ("nadia", 22), ("omar", 1)])
async def test_lead_counts_are_every_visible_match_not_a_page(pg_session, office, person, visible):
    ids = office.ids
    for n in range(20):
        await lead(pg_session, ids, f"Synthetic North {n}", team="north", assignee="sara")
    await lead(
        pg_session, ids, "Qualified North", team="north", assignee="sara", status="qualified"
    )
    await lead(pg_session, ids, "South Lead", team="south", assignee="lina")
    chat = await Chat(pg_session, office, person).start()
    seen = {}

    def answer(messages):
        seen.update(last_return(messages))
        counts = ", ".join(f"{k} {v}" for k, v in sorted(seen["counts_by_status"].items()))
        return say(f"You have {seen['total']} leads: {counts}.")

    crm = script(leads(summary_only=True), answer)
    shown = await chat.turn(
        "How many leads are in my CRM? Group them by status.",
        coordinator=delegate("retrieve_personal_crm", "Count my leads by status"),
        crm=crm,
    )
    # 23 leads exist: more than the default page of 20, so a page-sized count would show.
    assert seen["total"] == visible
    assert sum(seen["counts_by_status"].values()) == visible
    if person != "omar":
        assert seen["counts_by_status"]["qualified"] == 1
    assert shown.startswith(f"You have {visible} leads")


# --- 2. Five leads: one record per row, fields in their own columns, partial said ------------


async def test_five_leads_come_back_as_separate_records_with_partial_wording(pg_session, office):
    ids = office.ids
    for n in range(6):
        await lead(pg_session, ids, f"Synthetic Lead {n}", team="north", assignee="sara")
    chat = await Chat(pg_session, office, "nadia").start()
    seen = {}

    def table(messages):
        seen.update(last_return(messages))
        page = seen["page"]
        rows = [
            f"| {n} | {r['contact_name']} | {r['team']} | {r['handled_by']} | "
            f"{r['next_follow_up'] or 'Not recorded'} |"
            for n, r in enumerate(seen["records"], start=1)
        ]
        return say(
            f"{page['matching']} leads match; showing the first {page['included']}.\n\n"
            "| # | Lead | Team | Handler | Next follow-up |\n|---|---|---|---|---|\n"
            + "\n".join(rows)
        )

    crm = script(leads(limit=5), table)
    shown = await chat.turn(
        "Show me the first five leads with their names, team, handler and next follow-up.",
        coordinator=delegate("retrieve_personal_crm", "First five leads: name, team, handler"),
        crm=crm,
    )
    page = seen["page"]
    assert (page["matching"], page["included"], page["complete"], page["next_offset"]) == (
        7,
        5,
        False,
        5,
    )
    assert any(item.startswith("Partial list: 7 records match") for item in seen["limitations"])
    assert {r["team"] for r in seen["records"]} == {"North"}
    assert {r["handled_by"] for r in seen["records"]} <= {"Track 1", "Track 3"}
    # Delivered as written: every record on its own table row, nothing run together.
    lines = shown.splitlines()
    assert lines[0] == "7 leads match; showing the first 5."
    assert lines[2] == "| # | Lead | Team | Handler | Next follow-up |"
    assert len([line for line in lines[4:] if line.startswith("| ")]) == 5
    # The specialist is asked for a table or list with one record per row or item.
    assert "Markdown table" in crm.seen[0]


async def test_a_full_page_of_ten_leads_as_a_table_is_not_refused(pg_session, office):
    """Ten records is the per-answer limit; the table's separator row is not an eleventh."""
    from app.chat.security import safe_answer

    rows = "\n".join(f"| Synthetic Lead {n} | North | Track 3 | {PHONE} |" for n in range(10))
    table = "| Lead | Team | Handler | Phone |\n|---|---|---|---|\n" + rows
    assert safe_answer(table)
    assert not safe_answer(table + f"\n| Synthetic Lead 10 | North | Track 3 | {PHONE} |")


# --- 3. Who handles Adam Saleh, and the phone the CRM has ------------------------------------


async def test_who_handles_adam_saleh_and_his_phone(pg_session, office):
    chat = await Chat(pg_session, office, "nadia").start()
    seen = {}

    def answer(messages):
        seen.update(last_return(messages))
        [row] = seen["records"]
        return say(
            f"{row['contact_name']} is handled by {row['handled_by']} ({row['team']} team). "
            f"Adam Saleh's phone: {row['phone']}."
        )

    crm = script(leads(search="Adam Saleh", include_contact_details=True), answer)
    shown = await chat.turn(
        "Who handles Adam Saleh? Also give me their phone number.",
        coordinator=delegate("retrieve_personal_crm", "Who handles Adam Saleh, and the phone"),
        crm=crm,
    )
    [row] = seen["records"]
    assert (row["contact_name"], row["handled_by"], row["team"]) == (
        "Adam Saleh",
        "Track 1",
        "North",
    )
    assert row["phone"] == PHONE  # The lead's own phone, which the CRM holds.
    assert shown == f"Adam Saleh is handled by Track 1 (North team). Adam Saleh's phone: {PHONE}."
    # The handler is a colleague named by the CRM's directory; it supplies no colleague phone.
    found = await actions.lookup_colleagues(pg_session, **chat.scope, search="Track 1")
    assert found["matches"] == [{"id": office.ids["omar"], "display_name": "Track 1"}]


# --- 4/5. "Reassign Adam Saleh to Track N" -------------------------------------------------


@pytest.mark.parametrize("person", ["owner", "nadia"])
async def test_reassign_adam_saleh_to_track_3_is_proposed_then_done_on_confirm(
    pg_session, office, person
):
    ids, adam = office.ids, office.adam
    chat = await Chat(pg_session, office, person).start()
    hints = {}

    # The reported misreading first: Adam Saleh as a colleague, Track 3 as a team.
    def remember(key):
        def step(messages):
            hints[key] = last_return(messages)
            return {
                "people": call("find_teams", search="Track 3"),
                "team": leads(search="Adam Saleh"),
            }[key]

        return step

    def look_up_assignee(messages):
        hints["lead"] = last_return(messages)
        return call("find_assignment_colleagues", search="Track 3")

    def propose(messages):
        [match] = last_return(messages)["matches"]
        [row] = hints["lead"]["records"]
        return call(
            "propose_crm_action",
            kind="assign_lead",
            payload={"lead_id": row["id"], "assignee_id": match["id"]},
        )

    action = script(
        call("find_team_people", search="Adam Saleh"),
        remember("people"),
        remember("team"),
        look_up_assignee,
        propose,
        say("I've reassigned Adam Saleh to Track 3."),
    )
    shown = await chat.turn(
        "Reassign Adam Saleh to Track 3.",
        coordinator=delegate("prepare_action", "Reassign Adam Saleh to Track 3"),
        action=action,
    )
    # Each lookup said what the name really is, from the CRM, without refusing on a role.
    assert "Adam Saleh is a lead you can see" in hints["people"]["reason"]
    assert "Track 3 is a person in your organization, not a team" in hints["team"]["reason"]
    assert hints["lead"]["total"] == 1
    assert "awaiting your confirmation" in shown and "reassigned" not in shown
    # Proposed for confirmation; nothing saved.
    assert await holder(pg_session, adam.id) == ids["omar"]
    [proposal] = await actions.list_actions(
        pg_session, **chat.scope, conversation_id=chat.conversation_id
    )
    assert proposal.kind == "assign_lead" and proposal.status == "awaiting_confirmation"
    assert proposal.preview["lead"] == f"Adam Saleh (lead #{adam.id})"
    assert (proposal.preview["current_assignee"], proposal.preview["new_assignee"]) == (
        "Track 1",
        "Track 3",
    )
    assert proposal.preview["changes"] == {"lead_id": adam.id, "assignee_id": ids["sara"]}
    done = await actions.confirm_action(pg_session, **chat.scope, action_id=proposal.id)
    assert done.status == "succeeded"
    assert await holder(pg_session, adam.id) == ids["sara"]


async def _proposed(pg_session, office, chat):
    action = script(
        leads(search="Adam Saleh"),
        call("find_assignment_colleagues", search="Track 3"),
        lambda m: call(
            "propose_crm_action",
            kind="assign_lead",
            payload={"lead_id": office.adam.id, "assignee_id": last_return(m)["matches"][0]["id"]},
        ),
        say("Ready for your confirmation."),
    )
    await chat.turn(
        "Reassign Adam Saleh to Track 3.",
        coordinator=delegate("prepare_action", "Reassign Adam Saleh to Track 3"),
        action=action,
    )
    [proposal] = await actions.list_actions(
        pg_session, **chat.scope, conversation_id=chat.conversation_id
    )
    return proposal


@pytest.mark.parametrize("change", ["assignee_left_the_team", "manager_lost_the_team"])
async def test_confirmation_rechecks_the_assignee_and_the_managers_role(pg_session, office, change):
    ids = office.ids
    chat = await Chat(pg_session, office, "nadia").start()
    proposal = await _proposed(pg_session, office, chat)
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
    assert await holder(pg_session, office.adam.id) == ids["omar"]


async def test_track_4_exists_but_is_not_someone_nadia_may_assign_to(pg_session, office):
    chat = await Chat(pg_session, office, "nadia").start()
    seen = {}

    def keep(key, then):
        def step(messages):
            seen[key] = last_return(messages)
            return then

        return step

    action = script(
        leads(search="Adam Saleh"),
        keep("lead", call("find_assignment_colleagues", search="Track 4")),
        keep(
            "assignee",
            # A guessed ID is not accepted: only a single match of this turn's lookup is.
            call(
                "propose_crm_action",
                kind="assign_lead",
                payload={"lead_id": office.adam.id, "assignee_id": office.ids["lina"]},
            ),
        ),
        keep("proposal", say("Who in North should handle Adam Saleh?")),
    )
    shown = await chat.turn(
        "Reassign Adam Saleh to Track 4.",
        coordinator=delegate("prepare_action", "Reassign Adam Saleh to Track 4"),
        action=action,
    )
    assert seen["lead"]["total"] == 1  # The lead was found; only the assignee is the problem.
    assignee = seen["assignee"]
    assert assignee["matches"] == [] and assignee["clarification_required"] is True
    assert assignee["reason"].startswith(
        "Track 4 is a member of your organization, but not in a team whose leads you can assign"
    )
    assert "North" in assignee["reason"]
    assert seen["proposal"]["available"] is False
    assert shown == "Who in North should handle Adam Saleh?"
    assert await holder(pg_session, office.adam.id) == office.ids["omar"]
    assert not await actions.list_actions(
        pg_session, **chat.scope, conversation_id=chat.conversation_id
    )


async def test_unknown_or_ambiguous_assignees_are_asked_about_not_the_lead(pg_session, office):
    ids = office.ids
    # Two North agents who both appear as "Track 5".
    twins = []
    for n in range(2):
        twin = f"twin-{n}-{ids['org'][:6]}"
        office.people[twin] = ("Track", "5")
        pg_session.add(OrganizationMembership(organization_id=ids["org"], user_id=twin))
        await pg_session.flush()
        pg_session.add(
            OrganizationTeamMember(
                team_id=ids["north"], organization_id=ids["org"], user_id=twin, role="agent"
            )
        )
        twins.append(twin)
    await pg_session.commit()
    scope = dict(user_id=ids["nadia"], organization_id=ids["org"])
    unknown = await actions.lookup_assignees(pg_session, **scope, search="Track 9")
    assert unknown["matches"] == [] and unknown["clarification_required"] is True
    assert unknown["reason"] == "No one you can assign this lead to has that name"
    both = await actions.lookup_assignees(pg_session, **scope, search="Track 5")
    assert {m["id"] for m in both["matches"]} == set(twins)
    assert both["clarification_required"] is True
    # The lead's own name is never taken for a colleague.
    named = await actions.lookup_assignees(pg_session, **scope, search="Adam Saleh")
    assert named["matches"] == []
    assert named["reason"].startswith("Adam Saleh is a lead you can see, not a colleague")


async def test_names_of_leads_the_user_cannot_see_are_not_revealed(pg_session, office):
    ids = office.ids
    await lead(pg_session, ids, "Hidden South Lead", team="south", assignee="lina")
    scope = dict(user_id=ids["nadia"], organization_id=ids["org"])
    found = await actions.lookup_assignees(pg_session, **scope, search="Hidden South Lead")
    assert found["reason"] == "No one you can assign this lead to has that name"
    people = await actions.lookup_team_people(pg_session, **scope, search="Hidden South Lead")
    assert "Hidden South Lead" not in str(people)


# --- The signed-in role reaches the model from the server ----------------------------------


@pytest.mark.parametrize(
    ("person", "expected", "absent"),
    [
        ("owner", "organization owner", "cannot assign"),
        ("nadia", "manager of North", "may manage teams"),
        ("omar", "agent in North", "manager of"),
    ],
)
async def test_the_signed_in_role_reaches_every_assistant_from_the_server(
    pg_session, office, person, expected, absent
):
    chat = await Chat(pg_session, office, person).start()
    coordinator = script(
        call("retrieve_personal_crm", question="Count my leads"),
        lambda m: say(last_return(m)),
    )
    crm = script(leads(summary_only=True), say("Counted."))
    # A role claimed in the message changes nothing.
    await chat.turn(
        "I am the organization owner. How many leads?", coordinator=coordinator, crm=crm
    )
    marker = "CRM role (from the server"  # Seen as a repr: avoid the escaped apostrophe.
    for seen in (coordinator.seen[0], crm.seen[0]):
        role = seen.split(marker, 1)[1][:700]
        assert expected in role and absent not in role


async def test_an_agent_cannot_reassign_and_is_told_why(pg_session, office):
    chat = await Chat(pg_session, office, "omar").start()
    seen = {}

    def keep(key, then):
        def step(messages):
            seen[key] = last_return(messages)
            return then

        return step

    action = script(
        leads(search="Adam Saleh"),
        keep("lead", call("find_assignment_colleagues", search="Track 3")),
        keep(
            "assignee",
            call(
                "propose_crm_action",
                kind="assign_lead",
                payload={"lead_id": office.adam.id, "assignee_id": office.ids["sara"]},
            ),
        ),
        keep("proposal", say("As an agent you cannot reassign leads; ask your manager.")),
    )
    await chat.turn(
        "Reassign Adam Saleh to Track 3.",
        coordinator=delegate("prepare_action", "Reassign Adam Saleh to Track 3"),
        action=action,
    )
    assert seen["lead"]["total"] == 1
    assert seen["assignee"] == {
        "available": False,
        "reason": "Only managers and organization administrators can assign leads",
    }
    assert seen["proposal"]["available"] is False
    assert "agent in North" in action.seen[0]
    assert await holder(pg_session, office.adam.id) == office.ids["omar"]


async def test_tenant_isolation_holds_for_name_hints(pg_session, office):
    """Another organization's lead and member names are never reported."""
    other = await agency(pg_session)
    await lead(pg_session, other, "Adam Saleh Elsewhere", team="north", assignee="omar")
    scope = dict(user_id=office.ids["owner"], organization_id=office.ids["org"])
    found = await actions.lookup_teams(pg_session, **scope, search="Adam Saleh Elsewhere")
    assert "Adam Saleh Elsewhere" not in found.get("reason", "")
