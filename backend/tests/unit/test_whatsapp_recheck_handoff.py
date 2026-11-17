"""A saved draft that fails its locked re-check reaches the agent; it never just vanishes.

`valid_evidence` re-runs the evidence and wording checks under the connection lock before a
draft is saved and again before it is sent. A draft that fails them is never sent. The
admitted enquiry becomes an approval handoff with a fixed holding line and a notification.
A draft that was superseded (newer revision, agent took over) stays quiet: no duplicate
notification.
"""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.whatsapp import customer_automation as automation
from app.whatsapp import customer_voice as voice
from app.whatsapp.customer_access import valid_evidence as REAL_VALID_EVIDENCE
from app.whatsapp.customer_agent import DRAFT_FAILED_SUMMARY
from app.whatsapp.customer_models import (
    WhatsAppConnection,
    WhatsAppCustomerMessage,
    WhatsAppCustomerThread,
)
from app.whatsapp.models import utcnow

ENQUIRY = "Is the 2 bedroom in Marina still available?"
DRAFTED = "Yes, the Marina 2BR is AED 2m."
SNAPSHOT = {"id": "listing:1", "kind": "listing", "text": DRAFTED}


class Db:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


def config(**update):
    return settings.model_copy(
        update={
            "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": True,
            "WHATSAPP_HUMAN_TIMING_ENABLED": False,
            "WHATSAPP_CUSTOMER_TEST_RECIPIENT": None,
            **update,
        }
    )


@pytest.fixture
def world(monkeypatch):
    connection = WhatsAppConnection(
        user_id="user",
        organization_id="org",
        phone_number_id="agent-number",
        account_id="agent-account",
        display_name="Kian",
        access_token_encrypted="ciphertext",
        enabled=True,
        status="connected",
        approved_knowledge=[{"id": "faq", "text": "Marina 2BR AED 2m."}],
    )
    thread = WhatsAppCustomerThread(
        connection_id=connection.id, sender="971500000001", conversation_id=7
    )
    message = WhatsAppCustomerMessage(
        id="wamid.1", thread_id=thread.id, sent_at=utcnow(), status="classifying"
    )
    checks = AsyncMock(return_value=False)
    sent = AsyncMock(return_value="out-1")
    monkeypatch.setattr(
        automation.queue,
        "locked_context",
        AsyncMock(side_effect=lambda *_: (connection, thread, message)),
    )
    monkeypatch.setattr(automation.queue, "history_for", AsyncMock(return_value=[]))
    monkeypatch.setattr(automation.repository, "blocked_contact", AsyncMock(return_value=False))
    monkeypatch.setattr(automation, "channel_access", AsyncMock(return_value=True))
    monkeypatch.setattr(automation.customer_access, "valid_evidence", checks)
    monkeypatch.setattr(automation, "connection_token", lambda *_: "agent-token")
    monkeypatch.setattr(automation, "send_reply", sent)
    monkeypatch.setattr(
        automation,
        "build_customer_draft",
        AsyncMock(
            return_value=SimpleNamespace(
                reply=DRAFTED,
                risk="routine",
                evidence_ids=["listing:1"],
                evidence_snapshots=[],
                auto_eligible=True,
            )
        ),
    )
    return SimpleNamespace(
        connection=connection, thread=thread, message=message, checks=checks, sent=sent
    )


def location(world):
    return world.connection.id, world.thread.id, world.message.id


def assert_handed_to_agent(message, thread):
    assert message.status == "approval_required"
    assert message.notification_created_at is not None
    assert thread.paused is True
    # Never the failed draft: a fixed holding line the agent can approve, edit or replace.
    assert message.reply in voice.HOLDING_LINES and message.reply != DRAFTED
    assert message.risk == "approval"
    assert message.evidence_ids == [] and message.evidence_snapshots == []
    assert message.send_after is None
    assert message.handoff_summary
    # An admitted property enquiry: its text is kept so the agent can answer it.
    assert message.content == ENQUIRY and message.topic == "real_estate"


async def test_draft_failing_recheck_at_save_is_handed_to_the_agent(world):
    db = Db()
    await automation.draft(db, location(world), world.message.revision, config(), ENQUIRY)

    world.checks.assert_awaited_once()
    assert_handed_to_agent(world.message, world.thread)
    assert world.message.handoff_summary == DRAFT_FAILED_SUMMARY
    assert world.message.reason == "draft_failed"
    world.sent.assert_not_called()


@pytest.mark.parametrize("status", ["auto_pending", "grace_pending", "approved"])
async def test_draft_failing_recheck_at_send_is_never_sent_and_reaches_the_agent(world, status):
    message, thread = world.message, world.thread
    message.status = status
    message.content = ENQUIRY
    message.topic = "real_estate"
    message.reply = DRAFTED
    message.risk = "routine"
    message.evidence_ids = ["listing:1"]
    message.evidence_snapshots = [SNAPSHOT]
    message.send_after = utcnow() - timedelta(seconds=1)
    thread.paused = status == "approved"
    revision = message.revision

    await automation.send(Db(), location(world), config())

    world.checks.assert_awaited_once()
    world.sent.assert_not_called()
    assert_handed_to_agent(message, thread)
    assert message.reason == "evidence_changed"
    assert message.handoff_summary == automation.SEND_RECHECK_SUMMARY
    # The reply changed under any open review, so a stale approval is rejected.
    assert message.revision == revision + 1


async def test_superseded_draft_at_save_is_left_alone_without_a_notification(world):
    db = Db()
    world.message.revision = 2  # a newer customer message re-queued this receipt
    await automation.draft(db, location(world), 1, config(), ENQUIRY)

    world.checks.assert_not_awaited()
    assert world.message.status == "classifying"
    assert world.message.notification_created_at is None
    assert world.message.content is None


async def test_draft_the_agent_already_took_over_is_cancelled_quietly_at_send(world):
    message, thread = world.message, world.thread
    message.status = "auto_pending"
    message.content = ENQUIRY
    message.reply = DRAFTED
    message.send_after = utcnow() - timedelta(seconds=1)
    thread.paused = True  # the agent replied from the phone

    await automation.send(Db(), location(world), config())

    world.checks.assert_not_awaited()
    world.sent.assert_not_called()
    assert message.status == "cancelled"
    assert message.notification_created_at is None
    assert message.reason != "evidence_changed"


async def test_draft_passing_recheck_at_send_still_goes_out(world):
    message = world.message
    message.status = "auto_pending"
    message.content = ENQUIRY
    message.reply = DRAFTED
    message.send_after = utcnow() - timedelta(seconds=1)
    world.checks.return_value = True

    await automation.send(Db(), location(world), config())

    world.sent.assert_awaited_once()
    assert message.status == "accepted" and message.outbound_id == "out-1"
    assert message.notification_created_at is None


@pytest.mark.parametrize("line", voice.HOLDING_LINES)
async def test_holding_line_passes_the_send_recheck_so_approving_it_cannot_loop(world, line):
    assert await REAL_VALID_EVIDENCE("db", world.connection, [], [], line, context=[ENQUIRY])
