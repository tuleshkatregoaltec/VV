"""'Give me all leads': how many match, how many this answer holds, and how to see the rest.

One answer may include at most 10 records with personal details: the turn's retrieval budget
(ChatDependencies.retrieval_budget) and the output guard (security.MAX_DETAIL_ROWS) both hold
it, by design. The CRM count covers every match. The reported answer said 20 leads but listed
10 in one paragraph, without saying the list was partial or how to continue. The tool result
now carries a page (matching, included, complete, next_offset) and a partial-list note; a later
message continues with offset.

Real chat turn, tools, access checks and output guard; scripted models (the answer is written
the way the CRM prompt now instructs). Agency (crm_role_support): Nadia manages North (Track 8,
User 10); Karim manages South (User 2).
"""

import re
from datetime import date

import pytest
from crm_role_support import lead
from sqlalchemy import update
from test_assistant_lead_contact_turns import (
    Chat,
    call,
    delegate,
    last_return,
    say,
    script,
    setup_office,
)

from app.chat.security import REFUSAL
from app.crm.inbound_models import CrmInboundContact

NORTH = [f"North Client {n:02d}" for n in range(1, 12)]  # With Bilal Hameed: 12 in North.
SOUTH = [f"South Client {n:02d}" for n in range(1, 9)]  # 8 in South.
SPARSE = "North Client 03"  # No phone, no email, no handler, no follow-up.


@pytest.fixture
async def office(pg_session, monkeypatch):
    office = await setup_office(pg_session, monkeypatch)
    ids = office.ids
    for n, name in enumerate(NORTH):
        await lead(
            pg_session,
            ids,
            name,
            team="north",
            assignee=None if name == SPARSE else ("omar" if n % 2 else "sara"),
            creator="nadia",
            next_follow_up=None if name == SPARSE else date(2026, 12, 1 + n),
        )
    for name in SOUTH:
        await lead(pg_session, ids, name, team="south", assignee="lina")
    await pg_session.exec(
        update(CrmInboundContact)
        .where(CrmInboundContact.full_name == SPARSE)
        .values(phone=None, email=None)
    )
    await pg_session.commit()
    return office


def leads(**request):
    return call("query_my_crm_records", resource="leads", include_contact_details=True, **request)


def listing(messages):
    """The answer as the CRM prompt instructs: counts first, one numbered line per returned
    lead, only fields with values, and continuation when the page is partial."""
    result = last_return(messages)
    page = result["page"]
    if page["complete"] and page["first"] in (1, None):
        head = f"{page['matching']} leads match; all {page['included']} are shown."
    else:
        head = f"{page['matching']} leads match; this answer shows {page['first']}-{page['last']}."
    lines = [head, ""]
    for number, row in enumerate(result["records"], start=page["first"] or 1):
        holder = " / ".join(value for value in (row.get("team"), row.get("handled_by")) if value)
        follow_up = row.get("next_follow_up")
        fields = [
            row["contact_name"],
            row.get("phone"),
            row.get("email"),
            holder,
            row.get("status"),
            f"follow-up {follow_up}" if follow_up else None,
        ]
        lines.append(f"{number}. " + " · ".join(field for field in fields if field))
    if not page["complete"]:
        lines += [
            "",
            f"This list is partial. Say 'show the next 10' for {page['next_offset'] + 1} "
            "onwards, or narrow it by team, handler, area or status.",
        ]
    return say("\n".join(lines))


def numbered(shown):
    return re.findall(r"^\d+\. (.+)$", shown, re.MULTILINE)


async def list_turn(chat, message, *steps):
    found: list = []

    def answer(messages):
        found.append(last_return(messages))
        return listing(messages)

    shown = await chat.turn(
        message, coordinator=delegate("retrieve_personal_crm", message), crm=script(*steps, answer)
    )
    return found[-1], shown


# --- 20 visible leads, 10 per answer ---------------------------------------------------------


async def test_all_leads_says_20_match_10_shown_and_offers_the_rest(pg_session, office):
    chat = await Chat(pg_session, office, "owner").start()
    # Asking for 20 (the query default) is held to the 10-record answer limit.
    result, shown = await list_turn(chat, "give me all leads", leads(limit=20))
    assert result["page"] == {
        "matching": 20,
        "included": 10,
        "first": 1,
        "last": 10,
        "complete": False,
        "next_offset": 10,
    }
    assert any(note.startswith("Partial list: 20 records match") for note in result["limitations"])
    assert shown != REFUSAL  # Ten leads with phone and email pass the output guard.
    assert shown.startswith("20 leads match; this answer shows 1-10.")
    rows = numbered(shown)
    assert len(rows) == 10 and len(shown.splitlines()) == 14  # Not one long paragraph.
    assert "show the next 10" in shown and "team, handler, area or status" in shown
    # Nothing is said about the ten not returned: their names never appear.
    listed = {row["contact_name"] for row in result["records"]}
    for name in {"Bilal Hameed", *NORTH, *SOUTH} - listed:
        assert name not in shown
    # Progress labels are never part of the answer.
    for label in ("✓", "ready", "complete", "Reviewing your CRM"):
        assert label not in shown

    # "show the next 10", in the next message: the remaining ten, and the list is now whole.
    result, shown = await list_turn(chat, "show the next 10", leads(limit=10, offset=10))
    assert result["page"] == {
        "matching": 20,
        "included": 10,
        "first": 11,
        "last": 20,
        "complete": True,
        "next_offset": None,
    }
    assert shown.startswith("20 leads match; this answer shows 11-20.")
    assert "partial" not in shown
    second = {row["contact_name"] for row in result["records"]}
    assert len(numbered(shown)) == 10 and not second & listed
    assert listed | second == {"Bilal Hameed", *NORTH, *SOUTH}


async def test_one_answer_cannot_read_past_the_limit(pg_session, office):
    """Continuing in the same answer is refused: the cap is per answer, not per call."""
    chat = await Chat(pg_session, office, "owner").start()
    second: list = []

    def read_more(messages):
        return leads(limit=10, offset=10)

    def answer(messages):
        second.append(last_return(messages))
        return say("Only the first 10 can be shown in this answer.")

    await chat.turn(
        "give me all leads",
        coordinator=delegate("retrieve_personal_crm", "all leads"),
        crm=script(leads(limit=10), read_more, answer),
    )
    assert second[0]["available"] is False
    assert "private detail limit is reached" in second[0]["reason"]


async def test_ten_or_fewer_is_said_to_be_complete(pg_session, office):
    chat = await Chat(pg_session, office, "karim").start()  # South's manager: 8 leads.
    result, shown = await list_turn(chat, "give me all leads", leads(limit=20))
    assert result["page"]["complete"] is True and result["page"]["next_offset"] is None
    assert not any(note.startswith("Partial list") for note in result["limitations"])
    assert shown.startswith("8 leads match; all 8 are shown.")
    assert {row.split(" · ")[0] for row in numbered(shown)} == set(SOUTH)
    assert "partial" not in shown and "next 10" not in shown


# --- Each role lists and counts only what it may see -----------------------------------------


@pytest.mark.parametrize(
    ("person", "matching", "allowed"),
    [
        ("owner", 20, {"Bilal Hameed", *NORTH, *SOUTH}),
        ("nadia", 12, {"Bilal Hameed", *NORTH}),  # North's manager.
        ("omar", 5, set(NORTH[1::2])),  # An agent: only the leads assigned to them.
    ],
)
async def test_lists_and_counts_follow_the_crm_role(pg_session, office, person, matching, allowed):
    chat = await Chat(pg_session, office, person).start()
    result, shown = await list_turn(chat, "give me all leads", leads(limit=10))
    assert result["page"]["matching"] == matching == result["total"]
    returned = {row["contact_name"] for row in result["records"]}
    assert returned <= allowed and len(returned) == min(matching, 10)
    for name in {"Bilal Hameed", *NORTH, *SOUTH} - allowed:
        assert name not in shown


# --- Missing values ---------------------------------------------------------------------------


async def test_missing_contact_handler_and_follow_up_render_cleanly(pg_session, office):
    chat = await Chat(pg_session, office, "owner").start()
    result, shown = await list_turn(chat, f"show {SPARSE}", leads(search=SPARSE, limit=10))
    [row] = result["records"]
    assert (row["phone"], row["email"], row["handled_by"], row["next_follow_up"]) == (
        None,
        None,
        "unassigned",
        None,
    )
    [line] = numbered(shown)
    assert line == f"{SPARSE} · North / unassigned · new"
    for empty in ("None", "null", "··", " ·  ·"):
        assert empty not in shown
