"""Write tools only propose: they validate, check the lead is this organisation's, and store a
pending action. Nothing on the lead changes until a person confirms."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.crm.assistant import scope
from app.crm.assistant.models import CrmAssistantAction
from app.crm.assistant.tools import leads as tools
from app.crm.inbound_models import CrmInboundActivity

from .assistant_helpers import ORG_A, ORG_B, FakeSession, ctx, make_deps, make_lead


@pytest.fixture
def session():
    return FakeSession()


@pytest.fixture
def members(monkeypatch):
    """Org membership lookups: user ids per org."""
    by_org = {ORG_A: {"user-1", "omar"}, ORG_B: {"org-b-user"}}

    async def membership(db, org_id, user_id):
        return SimpleNamespace(user_id=user_id) if user_id in by_org.get(org_id, set()) else None

    async def all_members(context_organization, db):
        return [
            dict(id=user_id, first_name=user_id.title(), last_name="", role="member")
            for user_id in sorted(by_org.get(context_organization.id, set()))
        ]

    monkeypatch.setattr(scope.organization_repository, "get_membership_in_org", membership)
    monkeypatch.setattr(scope.organization_service, "get_organization_members", all_members)
    return by_org


def pending(session):
    return session.of_type(CrmAssistantAction)


async def test_propose_does_not_change_the_lead(fake_leads, session):
    fake_leads.add(make_lead(1, status="contacted"))
    result = await tools.propose_status_change(
        ctx(make_deps(db=session)), lead_id=1, new_status="qualified"
    )

    assert fake_leads.rows[1].status == "contacted"
    [action] = pending(session)
    assert action.status == "pending"
    assert (action.organization_id, action.user_id, action.enquiry_id) == (ORG_A, "user-1", 1)
    expected_expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    assert abs((action.expires_at - expected_expiry).total_seconds()) < 5
    assert result["action_id"] == action.id
    assert result["before"] == {"status": "contacted"}
    assert result["after"] == {"status": "qualified"}
    assert "Ahmed Khan" in result["summary"]


async def test_action_ids_are_unguessable(fake_leads, session):
    fake_leads.add(make_lead(1))
    first = await tools.propose_add_note(ctx(make_deps(db=session)), lead_id=1, body="Called")
    second = await tools.propose_add_note(ctx(make_deps(db=session)), lead_id=1, body="Again")
    assert len(first["action_id"]) == 32 and first["action_id"] != second["action_id"]


async def test_closed_lost_without_reason_is_rejected(fake_leads, session):
    fake_leads.add(make_lead(1))
    for reason in (None, "   "):
        result = await tools.propose_status_change(
            ctx(make_deps(db=session)), lead_id=1, new_status="closed_lost", lost_reason=reason
        )
        assert result == {"error": "A lost reason is required to close a lead as lost"}
    assert pending(session) == []

    ok = await tools.propose_status_change(
        ctx(make_deps(db=session)),
        lead_id=1,
        new_status="closed_lost",
        lost_reason="Bought elsewhere",
    )
    assert pending(session)[0].payload == {
        "status": "closed_lost",
        "lost_reason": "Bought elsewhere",
    }
    assert ok["after"] == {"status": "closed_lost", "lost_reason": "Bought elsewhere"}


async def test_invalid_status_is_rejected(fake_leads, session):
    fake_leads.add(make_lead(1))
    result = await tools.propose_status_change(
        ctx(make_deps(db=session)), lead_id=1, new_status="archived"
    )
    assert result["error"].startswith("Unknown status")
    assert pending(session) == []


async def test_same_status_is_rejected(fake_leads, session):
    fake_leads.add(make_lead(1, status="qualified"))
    result = await tools.propose_status_change(
        ctx(make_deps(db=session)), lead_id=1, new_status="qualified"
    )
    assert result == {"error": "Lead is already qualified"}


async def test_follow_up_and_note_proposals(fake_leads, session):
    fake_leads.add(make_lead(1))
    follow_up = await tools.propose_follow_up(
        ctx(make_deps(db=session)), lead_id=1, date=date(2026, 11, 3)
    )
    assert follow_up["after"] == {"next_follow_up": "2026-11-03"}
    note = await tools.propose_add_note(ctx(make_deps(db=session)), lead_id=1, body="  ")
    assert note == {"error": "A note needs some text"}
    assert [a.action_type for a in pending(session)] == ["follow_up"]


@pytest.mark.parametrize("channel", ["whatsapp", "email"])
async def test_share_blocked_for_do_not_contact(fake_leads, session, channel):
    fake_leads.add(make_lead(1, do_not_contact=True))
    result = await tools.propose_share(ctx(make_deps(db=session)), lead_id=1, channel=channel)
    assert result == {"error": "This lead has asked not to be contacted"}
    assert pending(session) == []


@pytest.mark.parametrize("channel", ["whatsapp", "email"])
async def test_share_blocked_for_withdrawn_consent(fake_leads, session, channel):
    fake_leads.add(make_lead(1, consent_status="withdrawn"))
    result = await tools.propose_share(ctx(make_deps(db=session)), lead_id=1, channel=channel)
    assert result == {"error": "This lead has asked not to be contacted"}
    assert pending(session) == []


async def test_whatsapp_share_is_a_pending_draft_to_the_lead(fake_leads, session):
    fake_leads.add(make_lead(1))
    result = await tools.propose_share(ctx(make_deps(db=session)), lead_id=1, channel="whatsapp")
    [action] = pending(session)
    assert action.action_type == "share"
    assert action.payload["channel"] == "whatsapp"
    assert action.payload["to"] == "+971501234567"
    assert "Ahmed" in action.payload["text"]
    assert result["action_id"] == action.id
    # The card shows who the draft goes to: the model may pick the recipient, so the agent
    # must see it before confirming.
    assert result["after"]["to"] == "+971501234567"


async def test_draft_to_another_recipient_shows_that_recipient(fake_leads, session):
    fake_leads.add(make_lead(1))
    result = await tools.propose_share(
        ctx(make_deps(db=session)), lead_id=1, channel="email", recipient="someone@else.test"
    )
    assert result["after"]["to"] == "someone@else.test"
    assert pending(session)[0].payload["to"] == "someone@else.test"


async def test_copy_share_returns_text_and_logs_without_pending_row(fake_leads, session):
    fake_leads.add(make_lead(1))
    result = await tools.propose_share(ctx(make_deps(db=session)), lead_id=1, channel="copy")
    assert pending(session) == []
    assert result["share"]["channel"] == "copy"
    assert "Ahmed Khan" in result["share"]["text"]
    assert "/crm/leads?lead=1" in result["share"]["text"]
    [activity] = session.of_type(CrmInboundActivity)
    assert (activity.activity_type, activity.organization_id) == ("shared", ORG_A)
    assert session.commits == 1


async def test_teammate_share_requires_a_member(fake_leads, session, members):
    fake_leads.add(make_lead(1))
    result = await tools.propose_share(
        ctx(make_deps(db=session)), lead_id=1, channel="teammate", recipient="org-b-user"
    )
    assert result == {"error": "Member not found"}
    ok = await tools.propose_share(
        ctx(make_deps(db=session)), lead_id=1, channel="teammate", recipient="omar"
    )
    assert pending(session)[0].payload == {"channel": "teammate", "member_user_id": "omar"}
    assert "Omar" in ok["summary"]


async def test_propose_on_other_org_lead_is_not_found(fake_leads, session, members):
    fake_leads.add(make_lead(5), organization_id=ORG_B)
    deps = make_deps(ORG_A, db=session)
    results = [
        await tools.propose_status_change(ctx(deps), lead_id=5, new_status="qualified"),
        await tools.propose_add_note(ctx(deps), lead_id=5, body="x"),
        await tools.propose_follow_up(ctx(deps), lead_id=5, date=date(2026, 11, 3)),
        await tools.propose_assign(ctx(deps), lead_id=5, member_user_id="omar"),
        await tools.propose_share(ctx(deps), lead_id=5, channel="copy"),
        await tools.propose_share(ctx(deps), lead_id=5, channel="whatsapp"),
    ]
    assert all(result == {"error": "Lead not found"} for result in results)
    assert session.added == []


async def test_assign_to_non_member_is_rejected(fake_leads, session, members):
    fake_leads.add(make_lead(1))
    result = await tools.propose_assign(
        ctx(make_deps(db=session)), lead_id=1, member_user_id="org-b-user"
    )
    assert result == {"error": "Member not found"}
    assert pending(session) == []

    ok = await tools.propose_assign(ctx(make_deps(db=session)), lead_id=1, member_user_id="omar")
    assert pending(session)[0].payload == {"assigned_user_id": "omar"}
    assert ok["after"] == {"assignee": "Omar"}
