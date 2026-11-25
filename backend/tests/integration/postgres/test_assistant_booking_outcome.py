"""End to end: proposal, confirmation, CRM save, Google delivery and the answer the user reads.

The calendar service is replaced by a stub, so no real calendar (CRM or Google) is touched and
no invitation can be sent. The stored answer is what the model wrote when it proposed the
booking; what the conversation shows afterwards must follow the action's recorded outcome.
"""

from uuid import uuid4

import pytest

from app.assistant_actions import service
from app.assistant_actions.models import ActionProposalRequest, AssistantAction
from app.chat.conversations import add_message
from app.chat.models import Conversation
from app.crm import calendar_service
from app.crm.assistant.service import get_conversation_messages
from app.organization.models import Organization, OrganizationMembership

STALE_PROPOSAL_TEXT = (
    "You're free tomorrow at 15:00. This is only a proposal; nothing has been added to your "
    "CRM or Google Calendar yet."
)
MEETING = {
    "title": "Pipeline review",
    "starts_at": "2026-11-25T15:00:00+04:00",
    "ends_at": "2026-11-25T16:00:00+04:00",
}


@pytest.fixture
def calendar(monkeypatch):
    """A stand-in calendar: records saves and answers with the chosen Google sync state."""
    stub = {"sync": "synced", "saved": 0, "raise": None}

    async def create(db, **kwargs):
        if stub["raise"]:
            raise stub["raise"]
        stub["saved"] += 1
        return {"google_sync_status": stub["sync"]}

    monkeypatch.setattr(calendar_service, "create_event", create)
    # No Google connection is read for the card; the stub decides the delivery outcome.
    monkeypatch.setattr(calendar_service, "configured", lambda: False)
    return stub


async def booking_turn(db):
    """A user's proposal turn as the chat stores it: the model's text plus the action id."""
    user, org = f"agent-{uuid4().hex[:6]}", str(uuid4())
    db.add(Organization(id=org, name="Booking outcome", subscription_status="active"))
    await db.flush()
    db.add(OrganizationMembership(user_id=user, organization_id=org))
    conversation = Conversation(user_id=user, organization_id=org)
    db.add(conversation)
    await db.commit()
    identity = {"user_id": user, "organization_id": org}
    action = await service.propose_action(
        db,
        **identity,
        request=ActionProposalRequest(
            kind="book_calendar_meeting",
            conversation_id=conversation.id,
            payload=MEETING,
            idempotency_key=uuid4().hex,
        ),
    )
    await add_message(
        db,
        conversation.id,
        "assistant",
        STALE_PROPOSAL_TEXT,
        {"guardrail_version": 1, "private": True, "actions": [{"id": action.id}]},
        **identity,
    )
    return identity, conversation.id, action.id


async def shown_answer(db, identity, conversation_id) -> str:
    messages = await get_conversation_messages(db, conversation_id, **identity)
    return messages[-1].content


async def test_completed_booking_says_completed_and_google_updated(pg_session, calendar):
    identity, conversation_id, action_id = await booking_turn(pg_session)
    result = await service.confirm_action(pg_session, **identity, action_id=action_id)
    assert result.status == "succeeded" and calendar["saved"] == 1
    shown = await shown_answer(pg_session, identity, conversation_id)
    assert shown.startswith("Book calendar meeting: completed. Saved on your CRM calendar")
    assert "added to your Google Calendar" in shown
    assert "only a proposal" not in shown and "nothing has been added" not in shown


async def test_pending_confirmation_says_pending_and_nothing_added(pg_session, calendar):
    identity, conversation_id, _ = await booking_turn(pg_session)
    shown = await shown_answer(pg_session, identity, conversation_id)
    assert "awaiting your confirmation" in shown
    assert "completed" not in shown and calendar["saved"] == 0


async def test_failed_execution_says_failed_and_saves_nothing(pg_session, calendar):
    identity, conversation_id, action_id = await booking_turn(pg_session)
    # The stored arguments no longer match what was previewed: execution is refused.
    row = await pg_session.get(AssistantAction, action_id)
    row.payload = {**row.payload, "title": "Something else"}
    await pg_session.commit()
    result = await service.confirm_action(pg_session, **identity, action_id=action_id)
    assert result.status == "failed" and calendar["saved"] == 0
    shown = await shown_answer(pg_session, identity, conversation_id)
    assert shown.startswith("Book calendar meeting: failed.")
    assert "not confirmed as done" in shown
    assert "completed" not in shown and "added to your" not in shown


async def test_a_calendar_error_during_delivery_is_not_reported_as_added(pg_session, calendar):
    identity, conversation_id, action_id = await booking_turn(pg_session)
    calendar["raise"] = RuntimeError("calendar unavailable")
    result = await service.confirm_action(pg_session, **identity, action_id=action_id)
    # A failure inside delivery is never a success; it is recorded as unknown, not retried.
    assert result.status == "unknown"
    shown = await shown_answer(pg_session, identity, conversation_id)
    assert "outcome is not known" in shown
    assert "completed" not in shown and "added to your" not in shown


async def test_crm_saved_but_google_failed_is_partial(pg_session, calendar):
    identity, conversation_id, action_id = await booking_turn(pg_session)
    calendar["sync"] = "error"
    result = await service.confirm_action(pg_session, **identity, action_id=action_id)
    assert result.status == "partially_succeeded" and calendar["saved"] == 1
    shown = await shown_answer(pg_session, identity, conversation_id)
    assert shown.startswith("Book calendar meeting: partly completed. Saved on your CRM calendar")
    assert "Google Calendar was not updated" in shown
    assert "added to your Google Calendar" not in shown
