"""Durable customer receipts. All mutations lock connection, thread, then message.

Inbound text is never written here: a receipt row is content-free until the
in-memory classifier admits the message as a property enquiry.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_
from sqlmodel import select

from app.whatsapp import customer_repository as repository
from app.whatsapp.customer_models import (
    WhatsAppConnection,
    WhatsAppCustomerMessage,
    WhatsAppCustomerThread,
)
from app.whatsapp.models import utcnow

MAX_DAILY_MESSAGES = 20
COMMANDS = {"STOP", "START", "HUMAN"}
SEND_STATUSES = ("auto_pending", "grace_pending", "approved")


@dataclass(frozen=True)
class ClassificationJob:
    """Work for the in-process classifier. The text lives only in this object."""

    connection_id: str
    thread_id: str
    message_id: str
    revision: int
    content: str = field(repr=False)


def require_customer_config(config):
    if not (config.WHATSAPP_APP_SECRET and config.WHATSAPP_GRAPH_API_VERSION):
        raise ValueError("Customer automation configuration is incomplete")


def pilot_recipient(connection, config):
    """The env pilot's single-recipient restriction applies to that pilot number only."""
    recipient = config.WHATSAPP_CUSTOMER_TEST_RECIPIENT
    if recipient and connection.phone_number_id == config.WHATSAPP_CUSTOMER_PHONE_NUMBER_ID:
        return recipient
    return None


def bound(connection, thread, config, *, allow_paused=False):
    recipient = pilot_recipient(connection, config)
    return bool(
        config.WHATSAPP_CUSTOMER_AUTOMATION_ENABLED
        and connection.enabled
        and connection.status == "connected"
        and connection.access_token_encrypted
        and (not recipient or thread.sender == recipient)
        and (not thread.paused or allow_paused)
        and not thread.opted_out
    )


def wa_id_of(value):
    return (
        value
        if isinstance(value, str) and value.isascii() and value.isdigit() and 6 <= len(value) <= 20
        else None
    )


def bsuid_of(value):
    return value if isinstance(value, str) and 1 <= len(value) <= 128 else None


def sender_identity(message):
    """Who sent it, read before (and independently of) any message content."""
    return wa_id_of(message.get("from")), bsuid_of(
        message.get("user_id") or message.get("from_user_id")
    )


def inbound_text(message, now):
    """Bound the text receipt; returns (message_id, body, sent_at) or None."""
    if message.get("type") != "text" or not isinstance(message.get("text"), dict):
        return None
    body, message_id = message["text"].get("body"), message.get("id")
    if (
        not isinstance(body, str)
        or not body.strip()
        or len(body) > 8000
        or not isinstance(message_id, str)
        or not 1 <= len(message_id) <= 512
    ):
        return None
    try:
        sent_at = datetime.fromtimestamp(int(message["timestamp"]), timezone.utc)
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        return None
    if not now - timedelta(hours=24) < sent_at <= now + timedelta(minutes=5):
        return None
    return message_id, body.strip(), sent_at


async def cancel_pending(db, thread):
    for message in await repository.messages(db, thread.id, lock=True):
        if message.status in repository.UNSENT_STATUSES:
            if message.status in ("queued", "classifying"):
                message.content = None
            message.status = "cancelled"
            message.revision += 1
            message.send_after = None
            message.updated_at = utcnow()


async def enqueue(db, connection, raw_messages, config):
    """Record content-free receipts for one routed, locked connection.

    Blocked senders are dropped before their text is looked at and leave no row.
    Returns in-memory classification jobs; the caller commits, then runs them.
    """
    if not connection.enabled or not isinstance(raw_messages, list):
        return []
    now = utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    counts = None
    recipient = pilot_recipient(connection, config)
    jobs = []
    for raw in raw_messages:
        # Groups are unsupported for coexistence numbers; never automate them.
        if not isinstance(raw, dict) or raw.get("group_id") or raw.get("group"):
            continue
        sender, bsuid = sender_identity(raw)
        if sender is None or (recipient and sender != recipient):
            continue
        if await repository.blocked_contact(db, connection.id, sender, bsuid):
            continue
        receipt = inbound_text(raw, now)
        if receipt is None:
            continue
        message_id, body, sent_at = receipt
        if await repository.message_exists(db, message_id):
            continue
        if counts is None:
            counts = await repository.daily_counts(db, connection.id, today)
        command = body.upper() if body.upper() in COMMANDS else None
        if counts.get(sender, 0) >= MAX_DAILY_MESSAGES and command is None:
            continue
        thread = await repository.thread_for_sender(db, connection.id, sender)
        if thread is None:
            thread = WhatsAppCustomerThread(connection_id=connection.id, sender=sender)
            db.add(thread)
            await db.flush()
        # A human-owned thread retains its review draft; ordinary follow-ups cannot
        # cancel the handoff or silently restore automatic ownership.
        if not thread.paused or command in {"STOP", "HUMAN"}:
            await cancel_pending(db, thread)
        if command == "STOP":
            thread.opted_out = True
        elif command == "START":
            thread.opted_out = False
        elif command == "HUMAN":
            thread.paused = True
        thread.updated_at = now
        ignored = command is not None or thread.opted_out or thread.paused
        receipt_row = WhatsAppCustomerMessage(
            id=message_id,
            thread_id=thread.id,
            content=None,
            status="ignored" if ignored else "classifying",
            sent_at=sent_at,
        )
        db.add(receipt_row)
        await db.flush()
        counts[sender] = counts.get(sender, 0) + 1
        if not ignored:
            jobs.append(
                ClassificationJob(
                    connection_id=connection.id,
                    thread_id=thread.id,
                    message_id=message_id,
                    revision=receipt_row.revision,
                    content=body,
                )
            )
    return jobs


async def locked_context(db, connection_id, thread_id, message_id):
    connection = await repository.lock_connection(db, connection_id)
    if connection is None:
        return None
    thread = await repository.lock_thread(db, thread_id, connection.id)
    if thread is None:
        return None
    message = await repository.lock_message(db, message_id, thread.id)
    return (connection, thread, message) if message else None


async def claim(db, config):
    """Claim one due send across all agents, or recover a lost in-flight row."""
    now = utcnow()
    stale = now - timedelta(minutes=10)
    candidates = (
        await db.exec(
            select(
                WhatsAppCustomerMessage.id,
                WhatsAppCustomerThread.id,
                WhatsAppCustomerThread.connection_id,
            )
            .join(WhatsAppCustomerThread)
            .join(WhatsAppConnection)
            .where(
                or_(
                    and_(
                        WhatsAppCustomerMessage.status.in_(["classifying", "sending"]),
                        WhatsAppCustomerMessage.updated_at < stale,
                    ),
                    WhatsAppCustomerMessage.status == "approved",
                    and_(
                        WhatsAppCustomerMessage.status.in_(["auto_pending", "grace_pending"]),
                        WhatsAppCustomerMessage.send_after <= now,
                    ),
                )
            )
            .order_by(WhatsAppCustomerMessage.created_at, WhatsAppCustomerMessage.id)
            .limit(50)
        )
    ).all()
    await db.commit()
    for message_id, thread_id, connection_id in candidates:
        context = await locked_context(db, connection_id, thread_id, message_id)
        if context is None:
            await db.commit()
            continue
        connection, thread, message = context
        if message.status in ("classifying", "sending"):
            # In-memory classification died with its process, or a send is unconfirmed.
            if message.updated_at < stale:
                message.status = "unknown" if message.status == "sending" else "failed"
                message.error_code = "worker_lost"
                message.content = None if message.status == "failed" else message.content
                message.updated_at = now
            await db.commit()
            continue
        due = message.status == "approved" or (
            message.status in SEND_STATUSES
            and message.send_after is not None
            and message.send_after <= now
        )
        if not due:
            await db.commit()
            continue
        if not bound(connection, thread, config, allow_paused=message.status == "approved"):
            message.status = "cancelled"
            message.send_after = None
            message.revision += 1
            message.updated_at = now
            await db.commit()
            continue
        if now >= message.sent_at + timedelta(hours=24):
            message.status = "expired"
            message.send_after = None
            message.updated_at = now
            await db.commit()
            continue
        await db.commit()
        return connection, thread, message
    return None


async def history_for(db, thread_id):
    # Personal/ambiguous messages break property context. A later bare "120k" must
    # not be treated as a lead answer using an unrelated earlier enquiry.
    boundary = (
        await db.exec(
            select(func.max(WhatsAppCustomerMessage.created_at)).where(
                WhatsAppCustomerMessage.thread_id == thread_id,
                WhatsAppCustomerMessage.status.in_(["ignored", "failed"]),
            )
        )
    ).one()
    cutoff = (
        max(boundary, utcnow() - timedelta(hours=24))
        if boundary
        else utcnow() - timedelta(hours=24)
    )
    rows = (
        await db.exec(
            select(WhatsAppCustomerMessage)
            .where(
                WhatsAppCustomerMessage.thread_id == thread_id,
                WhatsAppCustomerMessage.status == "accepted",
                WhatsAppCustomerMessage.created_at > cutoff,
            )
            .order_by(WhatsAppCustomerMessage.created_at.desc())
            .limit(3)
            # Content is written by another session once admitted; never trust a stale copy.
            .execution_options(populate_existing=True)
        )
    ).all()
    history = []
    for message in reversed(rows):
        if message.content:
            history.append({"role": "user", "content": message.content[:1000]})
        if message.reply:
            history.append({"role": "assistant", "content": message.reply[:1000]})
    return history
