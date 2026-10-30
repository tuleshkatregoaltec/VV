"""Confirm re-checks everything against the signed-in user and organisation, runs the change
through the existing Leads services exactly once, and leaves the lead alone otherwise."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from assistant_helpers import ORG_A, ORG_B, USER, FakeSession, make_deps, make_lead
from fastapi import HTTPException

from app.crm.assistant import actions, scope
from app.crm.assistant.models import CrmAssistantAction
from app.crm.inbound_models import CrmInboundActivity


class FakeActionStore:
    """Scoped like the real repository: an action is visible only to its user in its org."""

    def __init__(self):
        self.actions: dict[str, CrmAssistantAction] = {}
        self.claims = 0

    def add(self, action_type="status", payload=None, *, enquiry_id=1, expires_in=10, **kw):
        now = datetime.now(timezone.utc)
        action = CrmAssistantAction(
            id=f"a{len(self.actions) + 1}",
            organization_id=kw.get("organization_id", ORG_A),
            user_id=kw.get("user_id", USER),
            enquiry_id=enquiry_id,
            action_type=action_type,
            payload=payload or {"status": "qualified"},
            summary="Move Ahmed Khan to qualified",
            before={},
            after={},
            status="pending",
            expires_at=now + timedelta(minutes=expires_in),
            created_at=now,
        )
        self.actions[action.id] = action
        return action

    async def get_action(self, db, action_id, user_id, organization_id):
        action = self.actions.get(action_id)
        if action and action.user_id == user_id and action.organization_id == organization_id:
            return action
        return None

    async def claim_action(self, db, action_id):
        self.claims += 1
        action = self.actions[action_id]
        if action.status != "pending":
            return False
        action.status = "confirmed"
        return True


@pytest.fixture
def store(monkeypatch):
    fake = FakeActionStore()
    monkeypatch.setattr(actions.repository, "get_action", fake.get_action)
    monkeypatch.setattr(actions.repository, "claim_action", fake.claim_action)
    return fake


@pytest.fixture
def services(monkeypatch):
    """The existing Leads services, recorded. They commit, like the real ones."""
    calls = []

    async def update(db, *, enquiry_id, organization_id, user_id, payload):
        calls.append(
            ("update", enquiry_id, organization_id, payload.model_dump(exclude_unset=True))
        )
        await db.commit()

    async def note(db, *, enquiry_id, organization_id, user_id, body):
        calls.append(("note", enquiry_id, organization_id, body))
        await db.commit()

    monkeypatch.setattr(actions, "update_inbound_enquiry", update)
    monkeypatch.setattr(actions, "add_inbound_note", note)
    return calls


@pytest.fixture
def members(monkeypatch):
    in_org = {ORG_A: {USER, "omar"}}

    async def membership(db, org_id, user_id):
        return SimpleNamespace() if user_id in in_org.get(org_id, set()) else None

    async def all_members(context_organization, db):
        return [
            dict(id=uid, first_name=uid.title(), last_name="", role="member")
            for uid in sorted(in_org.get(context_organization.id, set()))
        ]

    monkeypatch.setattr(scope.organization_repository, "get_membership_in_org", membership)
    monkeypatch.setattr(scope.organization_service, "get_organization_members", all_members)
    return in_org


@pytest.fixture
def session():
    return FakeSession()


async def confirm(session, action_id, organization_id=ORG_A, user_id=USER):
    return await actions.confirm_action(
        make_deps(organization_id, user_id, db=session), action_id=action_id
    )


async def test_status_confirm_runs_existing_service_and_logs_assistant_activity(
    store, services, fake_leads, session
):
    fake_leads.add(make_lead(1))
    action = store.add("status", {"status": "qualified"})

    result = await confirm(session, action.id)

    assert services == [("update", 1, ORG_A, {"status": "qualified"})]
    [activity] = session.of_type(CrmInboundActivity)
    assert activity.activity_type == "assistant"
    assert activity.body == "Move Ahmed Khan to qualified (via Assistant)"
    assert activity.metadata_json == {"action_id": action.id}
    assert (result.status, result.lead_id) == ("confirmed", 1)
    # The service's commit carries the claim and the activity with the change.
    assert session.commits == 1


async def test_closed_lost_reason_reaches_the_service(store, services, fake_leads, session):
    fake_leads.add(make_lead(1))
    action = store.add("status", {"status": "closed_lost", "lost_reason": "Bought elsewhere"})
    await confirm(session, action.id)
    assert services[0][3] == {"status": "closed_lost", "lost_reason": "Bought elsewhere"}


@pytest.mark.parametrize("organization_id,user_id", [(ORG_A, "colleague"), (ORG_B, USER)])
async def test_confirm_by_other_user_or_org_is_not_found(
    store, services, fake_leads, session, organization_id, user_id
):
    fake_leads.add(make_lead(1))
    action = store.add()
    with pytest.raises(HTTPException) as error:
        await confirm(session, action.id, organization_id, user_id)
    assert (error.value.status_code, error.value.detail) == (404, "Action not found")
    assert services == [] and action.status == "pending"


async def test_expired_action_is_rejected(store, services, fake_leads, session):
    fake_leads.add(make_lead(1))
    action = store.add(expires_in=-1)
    with pytest.raises(HTTPException) as error:
        await confirm(session, action.id)
    assert (error.value.status_code, error.value.detail) == (410, "Action expired")
    assert action.status == "expired" and action.resolved_at is not None
    assert services == [] and store.claims == 0


async def test_second_confirm_is_rejected_and_runs_once(store, services, fake_leads, session):
    fake_leads.add(make_lead(1))
    action = store.add()
    await confirm(session, action.id)
    with pytest.raises(HTTPException) as error:
        await confirm(session, action.id)
    assert (error.value.status_code, error.value.detail) == (409, "Action already confirmed")
    assert len(services) == 1


async def test_lost_claim_race_is_rejected(store, services, fake_leads, session, monkeypatch):
    """Two requests both read 'pending'; only the one that wins the claim runs the change."""
    fake_leads.add(make_lead(1))
    action = store.add()

    async def lost_race(db, action_id):
        return False

    monkeypatch.setattr(actions.repository, "claim_action", lost_race)
    with pytest.raises(HTTPException) as error:
        await confirm(session, action.id)
    assert error.value.status_code == 409
    assert services == [] and session.of_type(CrmInboundActivity) == []


async def test_confirm_after_lead_left_org_is_not_found(store, services, fake_leads, session):
    fake_leads.add(make_lead(1))
    action = store.add()
    fake_leads.rows[1].organization_id = ORG_B
    with pytest.raises(HTTPException) as error:
        await confirm(session, action.id)
    assert error.value.status_code == 404
    assert action.status == "pending" and services == [] and store.claims == 0


async def test_assign_confirm_rechecks_membership(store, services, fake_leads, session, members):
    fake_leads.add(make_lead(1))
    action = store.add("assign", {"assigned_user_id": "omar"})
    members[ORG_A].discard("omar")
    with pytest.raises(HTTPException) as error:
        await confirm(session, action.id)
    assert (error.value.status_code, error.value.detail) == (404, "Member not found")
    assert action.status == "pending" and services == []


async def test_assign_and_follow_up_run_through_update(
    store, services, fake_leads, session, members
):
    fake_leads.add(make_lead(1))
    assign = store.add("assign", {"assigned_user_id": "omar"})
    follow_up = store.add("follow_up", {"next_follow_up": "2026-11-03"})
    await confirm(session, assign.id)
    await confirm(session, follow_up.id)
    assert services[0][3] == {"assigned_user_id": "omar"}
    assert str(services[1][3]["next_follow_up"]) == "2026-11-03"


async def test_note_and_teammate_share_add_notes(store, services, fake_leads, session, members):
    fake_leads.add(make_lead(1))
    note = store.add("note", {"body": "Prefers mornings"})
    share = store.add("share", {"channel": "teammate", "member_user_id": "omar"})
    await confirm(session, note.id)
    await confirm(session, share.id)
    assert services == [
        ("note", 1, ORG_A, "Prefers mornings"),
        ("note", 1, ORG_A, "Shared with Omar via Assistant"),
    ]


async def test_whatsapp_and_email_confirm_return_drafts_and_log(
    store, services, fake_leads, session
):
    fake_leads.add(make_lead(1))
    text = "Hi Ahmed, following up?"
    whatsapp = store.add("share", {"channel": "whatsapp", "to": "+971 50 123 4567", "text": text})
    email = store.add("share", {"channel": "email", "to": "ahmed@example.com", "text": text})

    sent_whatsapp = await confirm(session, whatsapp.id)
    sent_email = await confirm(session, email.id)

    assert sent_whatsapp.href == f"https://wa.me/971501234567?text={quote(text)}"
    assert sent_email.href == f"mailto:ahmed@example.com?body={quote(text)}"
    assert services == []
    logged = [a for a in session.of_type(CrmInboundActivity) if a.activity_type == "shared"]
    assert [a.metadata_json["channel"] for a in logged] == ["whatsapp", "email"]


async def test_whatsapp_confirm_rechecks_do_not_contact(store, services, fake_leads, session):
    fake_leads.add(make_lead(1, do_not_contact=True))
    action = store.add("share", {"channel": "whatsapp", "to": "+971501234567", "text": "Hi"})
    with pytest.raises(HTTPException) as error:
        await confirm(session, action.id)
    assert (error.value.status_code, error.value.detail) == (
        409,
        "This lead has asked not to be contacted",
    )
    assert action.status == "pending"


async def test_service_failure_rolls_back_the_claim(store, fake_leads, session, monkeypatch):
    fake_leads.add(make_lead(1))
    action = store.add()

    async def broken(db, **kwargs):
        raise HTTPException(status_code=422, detail="bad")

    monkeypatch.setattr(actions, "update_inbound_enquiry", broken)
    rolled_back = []

    async def rollback():
        rolled_back.append(True)

    session.rollback = rollback
    with pytest.raises(HTTPException):
        await confirm(session, action.id)
    assert rolled_back == [True]


async def test_cancel_marks_cancelled_and_confirm_then_409(store, services, fake_leads, session):
    fake_leads.add(make_lead(1))
    action = store.add()
    result = await actions.cancel_action(make_deps(db=session), action_id=action.id)
    assert result.status == "cancelled" and action.status == "cancelled"
    with pytest.raises(HTTPException) as error:
        await confirm(session, action.id)
    assert (error.value.status_code, error.value.detail) == (409, "Action already cancelled")
    assert services == []


async def test_cancel_by_other_org_is_not_found(store, session):
    action = store.add()
    with pytest.raises(HTTPException) as error:
        await actions.cancel_action(make_deps(ORG_B, db=session), action_id=action.id)
    assert error.value.status_code == 404
    assert action.status == "pending"
