import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import update as sql_update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.chat.service import create_conversation
from app.config import settings
from app.whatsapp import customer_automation as automation
from app.whatsapp import customer_queue as queue
from app.whatsapp import customer_repository as repository
from app.whatsapp.customer_models import (
    WhatsAppConnection,
    WhatsAppCustomerMessage,
    WhatsAppCustomerThread,
)
from app.whatsapp.models import utcnow
from app.whatsapp.token_crypto import encrypt_token


async def setup(pg_session, monkeypatch):
    c = settings.model_copy(
        update={
            "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": True,
            "WHATSAPP_HUMAN_TIMING_ENABLED": False,
            "WHATSAPP_CUSTOMER_PHONE_NUMBER_ID": str(uuid4()),
            "WHATSAPP_CUSTOMER_ACCOUNT_ID": str(uuid4()),
            "WHATSAPP_CUSTOMER_ACCESS_TOKEN": "offline-token",
            "WHATSAPP_CUSTOMER_TEST_RECIPIENT": None,
            "WHATSAPP_APP_SECRET": "offline-secret",
            "WHATSAPP_GRAPH_API_VERSION": "v25.0",
            "WHATSAPP_PILOT_USER_ID": str(uuid4()),
            "WHATSAPP_PILOT_ORGANIZATION_ID": str(uuid4()),
        }
    )
    # The send worker serves every agent; earlier tests' agents share this database.
    await pg_session.exec(sql_update(WhatsAppConnection).values(enabled=False))
    connection = WhatsAppConnection(
        user_id=c.WHATSAPP_PILOT_USER_ID,
        organization_id=c.WHATSAPP_PILOT_ORGANIZATION_ID,
        phone_number_id=c.WHATSAPP_CUSTOMER_PHONE_NUMBER_ID,
        account_id=c.WHATSAPP_CUSTOMER_ACCOUNT_ID,
        display_name="Business",
        enabled=True,
        access_token_encrypted=encrypt_token("offline-token", c),
        approved_knowledge=[{"id": "faq", "text": "Property price AED 2m."}],
    )
    pg_session.add(connection)
    await pg_session.commit()
    STATE["connection"] = connection
    PENDING.clear()
    monkeypatch.setattr(automation, "channel_access", AsyncMock(return_value=True))

    async def conversation(db, **identity):
        return (await create_conversation(db, **identity, title="WhatsApp customers")).id

    monkeypatch.setattr(automation, "create_customer_conversation", conversation)
    monkeypatch.setattr(
        automation,
        "build_customer_draft",
        AsyncMock(
            return_value=SimpleNamespace(
                reply="Property price AED 2m.",
                risk="routine",
                evidence_ids=["faq"],
                auto_eligible=True,
            )
        ),
    )
    monkeypatch.setattr(automation, "send_reply", AsyncMock(return_value="outbound"))

    async def sessions():
        async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
            yield db

    monkeypatch.setattr(automation, "get_db_session", sessions)
    return c, connection


# Inbound text now reaches the classifier only as an in-memory job (the API process
# runs it after the webhook commits). Tests hold those jobs here and run them in
# order with `step`, which otherwise runs one worker (send/recovery) iteration.
STATE = {}
PENDING = []


def raw_message(body, sender, message_id=None):
    return {
        "id": message_id or str(uuid4()),
        "from": sender,
        "type": "text",
        "text": {"body": body},
        "timestamp": str(int(utcnow().timestamp())),
    }


async def enqueue(db, c, raws):
    connection = await repository.lock_connection(db, STATE["connection"].id)
    jobs = await queue.enqueue(db, connection, raws, c)
    await db.commit()
    PENDING.extend(jobs)
    return jobs


async def receipt(db, c, body="Property price?", sender="919000000000"):
    raw = raw_message(body, sender)
    await enqueue(db, c, [raw])
    message = await db.get(WhatsAppCustomerMessage, raw["id"])
    assert message is not None and message.content is None
    return message, [raw]


async def step(c):
    if PENDING:
        await automation.classify(PENDING.pop(0), c)
        return True
    return await automation.run_customer_once(c)


async def refresh(db, message):
    await db.refresh(message)
    return message


async def due(db, message):
    await refresh(db, message)
    message.send_after = utcnow() - timedelta(seconds=1)
    await db.commit()


async def test_unknown_lead_dedup_and_immediate_reply_without_review_notification(
    pg_session, monkeypatch
):
    c, _ = await setup(pg_session, monkeypatch)
    message, incoming = await receipt(pg_session, c)
    assert await enqueue(pg_session, c, incoming) == []
    started = utcnow()
    assert await step(c)
    await refresh(pg_session, message)
    assert message.status == "auto_pending"
    assert message.notification_created_at is None
    assert started <= message.send_after <= utcnow()
    automation.send_reply.assert_not_called()
    assert await step(c)
    await refresh(pg_session, message)
    assert message.status == "accepted" and message.outbound_id == "outbound"
    assert not await step(c)
    automation.send_reply.assert_awaited_once()


async def test_risky_draft_has_no_timeout_even_after_hours(pg_session, monkeypatch):
    c, _ = await setup(pg_session, monkeypatch)
    automation.build_customer_draft.return_value = SimpleNamespace(
        reply="Broker review", risk="approval", evidence_ids=[], auto_eligible=False
    )
    message, _ = await receipt(pg_session, c)
    await step(c)
    await refresh(pg_session, message)
    assert message.status == "approval_required" and message.send_after is None
    thread = await pg_session.get(WhatsAppCustomerThread, message.thread_id)
    assert thread.paused
    assert message.notification_created_at is not None
    message.created_at = utcnow() - timedelta(hours=3)
    await pg_session.commit()
    assert not await step(c)
    automation.send_reply.assert_not_called()


async def test_human_handoff_survives_followup_and_only_explicit_reply_sends(
    pg_session, monkeypatch
):
    c, connection = await setup(pg_session, monkeypatch)
    automation.build_customer_draft.return_value = SimpleNamespace(
        reply="Property details need verification.",
        risk="approval",
        evidence_ids=[],
        auto_eligible=False,
    )
    message, _ = await receipt(pg_session, c, "Can we negotiate the apartment price?")
    await step(c)
    followup, _ = await receipt(pg_session, c, "What is the property size?")
    await refresh(pg_session, message)
    assert message.status == "approval_required"
    assert followup.status == "ignored" and followup.content is None
    assert not await step(c)
    # Explicit owner approval is one send, not resumption of automatic ownership.
    message.status = "approved"
    message.send_after = utcnow()
    await pg_session.commit()
    await step(c)
    await refresh(pg_session, message)
    thread = await pg_session.get(WhatsAppCustomerThread, message.thread_id)
    await pg_session.refresh(thread)
    assert message.status == "accepted" and thread.paused
    automation.send_reply.assert_awaited_once()


async def test_personal_message_breaks_previous_property_context(pg_session, monkeypatch):
    c, _ = await setup(pg_session, monkeypatch)
    first, _ = await receipt(pg_session, c)
    await step(c)
    await step(c)
    assert await queue.history_for(pg_session, first.thread_id)
    automation.build_customer_draft.return_value = None
    await receipt(pg_session, c, "Dinner tonight?")
    await step(c)
    assert await queue.history_for(pg_session, first.thread_id) == []


@pytest.mark.parametrize("result", [None, PermissionError("budget unavailable")])
async def test_ignored_or_failed_classification_discards_personal_text(
    pg_session, monkeypatch, result
):
    c, _ = await setup(pg_session, monkeypatch)
    if isinstance(result, Exception):
        automation.build_customer_draft.side_effect = result
    else:
        automation.build_customer_draft.return_value = result
    message, _ = await receipt(pg_session, c, "Personal and property mixed")
    await step(c)
    await refresh(pg_session, message)
    assert message.status == ("failed" if isinstance(result, Exception) else "ignored")
    assert message.content is None and message.reply is None
    assert message.notification_created_at is None
    automation.send_reply.assert_not_called()


@pytest.mark.parametrize("command,attribute", [("STOP", "opted_out"), ("HUMAN", "paused")])
async def test_sender_controls_cancel_inflight_generation_without_resurrection(
    pg_session, monkeypatch, command, attribute
):
    c, _ = await setup(pg_session, monkeypatch)
    message, _ = await receipt(pg_session, c)
    entered, release = asyncio.Event(), asyncio.Event()
    result = automation.build_customer_draft.return_value

    async def generate(**kwargs):
        entered.set()
        await release.wait()
        return result

    automation.build_customer_draft.side_effect = generate
    task = asyncio.create_task(step(c))
    await asyncio.wait_for(entered.wait(), timeout=5)
    await receipt(pg_session, c, command)
    release.set()
    await task
    await refresh(pg_session, message)
    thread = await pg_session.get(WhatsAppCustomerThread, message.thread_id)
    assert getattr(thread, attribute)
    assert message.status == "cancelled" and message.reply is None
    assert message.content is None and message.revision == 2
    automation.send_reply.assert_not_called()


async def test_new_question_and_knowledge_change_cancel_stale_generation(pg_session, monkeypatch):
    c, connection = await setup(pg_session, monkeypatch)
    message, _ = await receipt(pg_session, c)
    result = automation.build_customer_draft.return_value

    async def changed_knowledge(**kwargs):
        async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
            locked = await repository.lock_connection(db, STATE["connection"].id)
            locked.approved_knowledge = [{"id": "faq", "text": "Updated price"}]
            await db.commit()
        return result

    automation.build_customer_draft.side_effect = changed_knowledge
    await step(c)
    await refresh(pg_session, message)
    assert message.status == "cancelled" and message.reply is None
    second, _ = await receipt(pg_session, c)
    third, _ = await receipt(pg_session, c, "New property question")
    await refresh(pg_session, second)
    assert second.status == "cancelled" and second.content is None
    assert third.status == "classifying" and third.content is None


async def test_cancellation_edit_and_revoked_access_win_before_sending(pg_session, monkeypatch):
    c, _ = await setup(pg_session, monkeypatch)
    message, _ = await receipt(pg_session, c)
    await step(c)
    await due(pg_session, message)
    claimed = await queue.claim(pg_session, c)
    assert claimed[2].id == message.id
    message.status = "approval_required"  # An owner edit removes automatic permission.
    message.revision += 1
    message.send_after = None
    await pg_session.commit()
    await automation.send(pg_session, (claimed[0].id, claimed[1].id, message.id), c)
    automation.send_reply.assert_not_called()
    message.status = "approved"
    message.send_after = utcnow()
    await pg_session.commit()
    automation.channel_access.return_value = False
    await step(c)
    await refresh(pg_session, message)
    assert message.status == "cancelled"
    automation.send_reply.assert_not_called()


async def test_ambiguous_send_and_lost_classification_are_never_replayed(pg_session, monkeypatch):
    c, _ = await setup(pg_session, monkeypatch)
    message, _ = await receipt(pg_session, c)
    await step(c)
    await due(pg_session, message)
    automation.send_reply.side_effect = httpx.ReadTimeout("offline")
    await step(c)
    await refresh(pg_session, message)
    assert message.status == "unknown"
    assert not await step(c)
    automation.send_reply.assert_awaited_once()
    other, _ = await receipt(pg_session, c)
    PENDING.clear()  # The API process died holding the in-memory text.
    other.status = "classifying"
    other.updated_at = utcnow() - timedelta(minutes=11)
    await pg_session.commit()
    assert not await step(c)
    await refresh(pg_session, other)
    assert other.status == "failed" and other.content is None


async def test_definite_meta_rejection_records_numeric_error_without_automatic_retry(
    pg_session, monkeypatch
):
    c, _ = await setup(pg_session, monkeypatch)
    message, _ = await receipt(pg_session, c)
    await step(c)
    automation.send_reply.side_effect = automation.MetaSendRejected(
        httpx.Response(400, json={"error": {"code": 131042, "message": "PRIVATE"}})
    )
    await step(c)
    await refresh(pg_session, message)
    assert message.status == "failed"
    assert message.error_code == "meta_131042"
    assert message.reason == "Meta rejected the reply (meta_131042)."
    assert message.content == "Property price?"
    assert message.reply == "Property price AED 2m."
    assert message.notification_created_at is not None
    assert not await step(c)
    automation.send_reply.assert_awaited_once()


async def test_daily_cap_disabled_binding_and_thread_history_isolation(pg_session, monkeypatch):
    c, connection = await setup(pg_session, monkeypatch)
    for _ in range(20):
        await receipt(pg_session, c, sender="919000000000")
    capped = raw_message("Property?", "919000000000")
    assert await enqueue(pg_session, c, [capped]) == []
    assert await pg_session.get(WhatsAppCustomerMessage, capped["id"]) is None
    stop = raw_message("STOP", "919000000000")
    assert await enqueue(pg_session, c, [stop]) == []
    assert (await pg_session.get(WhatsAppCustomerMessage, stop["id"])).status == "ignored"
    await receipt(pg_session, c, sender="919000000001")
    rows = (
        await pg_session.exec(
            select(WhatsAppCustomerMessage)
            .where(WhatsAppCustomerMessage.status == "classifying")
            .join(WhatsAppCustomerThread)
            .where(WhatsAppCustomerThread.connection_id == connection.id)
        )
    ).all()
    assert len(rows) == 1
    connection.enabled = False
    await pg_session.commit()
    while PENDING:
        await step(c)
    assert not await step(c)
    automation.build_customer_draft.assert_not_called()


async def test_worker_lanes_never_classify_or_read_fresh_receipts(pg_session, monkeypatch):
    c, _ = await setup(pg_session, monkeypatch)
    first, _ = await receipt(pg_session, c, sender="919000000001")
    await receipt(pg_session, c, sender="919000000002")

    async def claim():
        async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
            return await queue.claim(db, c)

    assert await asyncio.gather(claim(), claim()) == [None, None]
    await refresh(pg_session, first)
    assert first.status == "classifying" and first.content is None
    automation.build_customer_draft.assert_not_called()


async def test_service_window_is_rechecked_after_draft_before_delivery(pg_session, monkeypatch):
    c, _ = await setup(pg_session, monkeypatch)
    message, _ = await receipt(pg_session, c)
    await step(c)
    await due(pg_session, message)
    message.sent_at = utcnow() - timedelta(hours=25)
    await pg_session.commit()
    assert not await step(c)
    await refresh(pg_session, message)
    assert message.status == "expired"
    automation.send_reply.assert_not_called()


async def test_history_includes_only_accepted_messages_from_this_sender(pg_session, monkeypatch):
    c, _ = await setup(pg_session, monkeypatch)
    first, _ = await receipt(pg_session, c, "First property?", sender="919000000001")
    await step(c)
    await due(pg_session, first)
    await step(c)
    second, _ = await receipt(pg_session, c, "Other customer property?", sender="919000000002")
    await step(c)
    assert automation.build_customer_draft.call_args.kwargs["history"] == []
    third, _ = await receipt(pg_session, c, "Same customer property?", sender="919000000001")
    await step(c)  # Deliver the other sender's ready reply first.
    await step(c)
    assert automation.build_customer_draft.call_args.kwargs["history"] == [
        {"role": "user", "content": "First property?"},
        {"role": "assistant", "content": "Property price AED 2m."},
    ]
    assert second.thread_id != third.thread_id


async def test_two_send_workers_attempt_graph_only_once(pg_session, monkeypatch):
    c, _ = await setup(pg_session, monkeypatch)
    message, _ = await receipt(pg_session, c)
    await step(c)
    await due(pg_session, message)
    thread = await pg_session.get(WhatsAppCustomerThread, message.thread_id)
    location = thread.connection_id, thread.id, message.id
    entered, release = asyncio.Event(), asyncio.Event()

    async def sending(*args):
        entered.set()
        await release.wait()
        return "outbound"

    automation.send_reply.side_effect = sending

    async def send():
        async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
            await automation.send(db, location, c)

    task = asyncio.create_task(send())
    await asyncio.wait_for(entered.wait(), timeout=5)
    await send()
    release.set()
    await task
    automation.send_reply.assert_awaited_once()
    await refresh(pg_session, message)
    assert message.status == "accepted"


async def test_start_cannot_resume_owner_takeover_or_revive_cancelled_drafts(
    pg_session, monkeypatch
):
    c, _ = await setup(pg_session, monkeypatch)
    message, _ = await receipt(pg_session, c)
    await step(c)
    await receipt(pg_session, c, "HUMAN")
    await receipt(pg_session, c, "STOP")
    await receipt(pg_session, c, "START")
    await refresh(pg_session, message)
    thread = await pg_session.get(WhatsAppCustomerThread, message.thread_id)
    assert thread.paused and not thread.opted_out
    assert message.status == "cancelled"
    assert not await step(c)
    automation.send_reply.assert_not_called()


async def test_due_reply_is_claimed_while_another_sender_is_classifying(pg_session, monkeypatch):
    c, _ = await setup(pg_session, monkeypatch)
    message, _ = await receipt(pg_session, c, sender="919000000001")
    await step(c)
    other, _ = await receipt(pg_session, c, sender="919000000002")
    await refresh(pg_session, message)
    message.send_after = utcnow() + timedelta(seconds=60)
    await pg_session.commit()
    assert await queue.claim(pg_session, c) is None
    await due(pg_session, message)
    assert await automation.run_customer_once(c)
    await refresh(pg_session, message)
    await refresh(pg_session, other)
    assert message.status == "accepted" and other.status == "classifying"


@pytest.mark.parametrize(
    "change", ["expiry", "revocation", "price", "availability", "wrong_connection"]
)
async def test_publication_rechecked_at_send_boundary(pg_session, monkeypatch, change):
    from app.whatsapp.customer_evidence import listing_evidence
    from app.whatsapp.customer_models import WhatsAppPublishedListing

    c, connection = await setup(pg_session, monkeypatch)
    row = WhatsAppPublishedListing(
        connection_id=connection.id,
        title="Approved apartment",
        location="Marina",
        property_type="apartment",
        transaction="sale",
        price_aed=2_000_000,
        availability="available",
        expires_at=utcnow() + timedelta(hours=1),
    )
    pg_session.add(row)
    await pg_session.commit()
    item = listing_evidence(row)
    automation.build_customer_draft.return_value = SimpleNamespace(
        reply=item.text,
        risk="routine",
        evidence_ids=[item.id],
        evidence_snapshots=[item],
        auto_eligible=True,
    )
    message, _ = await receipt(pg_session, c)
    await step(c)
    await refresh(pg_session, message)
    assert message.status == "auto_pending"
    if change == "expiry":
        row.expires_at = utcnow() - timedelta(seconds=1)
    elif change == "revocation":
        row.revoked_at = utcnow()
    elif change == "price":
        row.price_aed = 3_000_000
    elif change == "availability":
        row.availability = "unavailable"
    else:
        other = WhatsAppConnection(
            user_id=str(uuid4()),
            organization_id=connection.organization_id,
            phone_number_id=str(uuid4()),
            account_id=str(uuid4()),
            display_name="Other broker",
        )
        pg_session.add(other)
        await pg_session.flush()
        row.connection_id = other.id
    await pg_session.commit()
    await step(c)
    await refresh(pg_session, message)
    assert message.status == "cancelled" and message.reason == "evidence_changed"
    automation.send_reply.assert_not_called()


@pytest.mark.parametrize("change", ["expiry", "permission"])
async def test_market_snapshot_rechecked_at_send_boundary(pg_session, monkeypatch, change):
    from app.whatsapp.customer_evidence import CustomerEvidence

    c, connection = await setup(pg_session, monkeypatch)
    connection.market_data_enabled = True
    await pg_session.commit()
    item = CustomerEvidence(
        id="market:sales",
        kind="market",
        text="Observed eligible sales: 20.",
        expires_at=utcnow() + timedelta(minutes=15),
        release_id="release-1",
    )
    automation.build_customer_draft.return_value = SimpleNamespace(
        reply=item.text,
        risk="routine",
        evidence_ids=[item.id],
        evidence_snapshots=[item],
        auto_eligible=True,
    )
    message, _ = await receipt(pg_session, c)
    await step(c)
    await refresh(pg_session, message)
    assert message.status == "auto_pending"
    if change == "permission":
        connection.market_data_enabled = False
    else:
        snapshot = dict(message.evidence_snapshots[0])
        snapshot["expires_at"] = (utcnow() - timedelta(seconds=1)).isoformat()
        message.evidence_snapshots = [snapshot]
    await pg_session.commit()
    await step(c)
    await refresh(pg_session, message)
    assert message.status == "cancelled" and message.reason == "evidence_changed"
    automation.send_reply.assert_not_called()
