"""Durable customer receipts. All mutations lock connection, thread, then message."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
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


def require_customer_config(config):
    if not all(
        (
            config.WHATSAPP_APP_SECRET,
            config.WHATSAPP_CUSTOMER_PHONE_NUMBER_ID,
            config.WHATSAPP_CUSTOMER_ACCOUNT_ID,
            config.WHATSAPP_CUSTOMER_ACCESS_TOKEN,
            config.WHATSAPP_GRAPH_API_VERSION,
            config.WHATSAPP_PILOT_USER_ID,
            config.WHATSAPP_PILOT_ORGANIZATION_ID,
        )
    ):
        raise ValueError("Customer automation configuration is incomplete")


def scope(config):
    return (
        WhatsAppConnection.phone_number_id == config.WHATSAPP_CUSTOMER_PHONE_NUMBER_ID,
        WhatsAppConnection.account_id == config.WHATSAPP_CUSTOMER_ACCOUNT_ID,
        WhatsAppConnection.user_id == config.WHATSAPP_PILOT_USER_ID,
        WhatsAppConnection.organization_id == config.WHATSAPP_PILOT_ORGANIZATION_ID,
    )


def bound(connection, thread, config, *, allow_paused=False):
    recipient = config.WHATSAPP_CUSTOMER_TEST_RECIPIENT
    return (
        config.WHATSAPP_CUSTOMER_AUTOMATION_ENABLED
        and connection.enabled
        and connection.phone_number_id == config.WHATSAPP_CUSTOMER_PHONE_NUMBER_ID
        and connection.account_id == config.WHATSAPP_CUSTOMER_ACCOUNT_ID
        and connection.user_id == config.WHATSAPP_PILOT_USER_ID
        and connection.organization_id == config.WHATSAPP_PILOT_ORGANIZATION_ID
        and (not recipient or thread.sender == recipient)
        and (not thread.paused or allow_paused)
        and not thread.opted_out
    )


def inbound_messages(event, config):
    """Validate account/number/sender and bound text before assigning any identity."""
    if not isinstance(event, dict) or event.get("object") != "whatsapp_business_account":
        raise ValueError("Invalid WhatsApp event")
    now = utcnow()
    result = []
    for entry in event.get("entry", []):
        if entry.get("id") != config.WHATSAPP_CUSTOMER_ACCOUNT_ID:
            continue
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if (
                change.get("field") != "messages"
                or value.get("metadata", {}).get("phone_number_id")
                != config.WHATSAPP_CUSTOMER_PHONE_NUMBER_ID
            ):
                continue
            for message in value.get("messages", []):
                sender = message.get("from")
                recipient = config.WHATSAPP_CUSTOMER_TEST_RECIPIENT
                if (
                    not isinstance(sender, str)
                    or not sender.isascii()
                    or not sender.isdigit()
                    or not 6 <= len(sender) <= 20
                    or (recipient and sender != recipient)
                    or message.get("type") != "text"
                ):
                    continue
                body, message_id = message.get("text", {}).get("body"), message.get("id")
                if (
                    not isinstance(body, str)
                    or not body.strip()
                    or len(body) > 8000
                    or not isinstance(message_id, str)
                    or not 1 <= len(message_id) <= 512
                ):
                    continue
                try:
                    sent_at = datetime.fromtimestamp(int(message["timestamp"]), timezone.utc)
                except (KeyError, ValueError, TypeError, OverflowError, OSError):
                    continue
                if now - timedelta(hours=24) < sent_at <= now + timedelta(minutes=5):
                    result.append((message_id, sender, body.strip(), sent_at))
    return result


async def configured_connection(db, config):
    return (
        await db.exec(
            select(WhatsAppConnection)
            .where(*scope(config))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()


async def cancel_pending(db, thread):
    for message in await repository.messages(db, thread.id, lock=True):
        if message.status in repository.UNSENT_STATUSES:
            if message.status in ("queued", "classifying"):
                message.content = None
            message.status = "cancelled"
            message.revision += 1
            message.send_after = None
            message.updated_at = utcnow()


async def enqueue(db, incoming, config):
    connection = await configured_connection(db, config)
    if connection is None or not connection.enabled:
        await db.commit()
        return 0
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    counts = dict(
        (
            await db.exec(
                select(WhatsAppCustomerThread.sender, func.count())
                .select_from(WhatsAppCustomerMessage)
                .join(WhatsAppCustomerThread)
                .where(
                    WhatsAppCustomerThread.connection_id == connection.id,
                    WhatsAppCustomerMessage.created_at >= today,
                )
                .group_by(WhatsAppCustomerThread.sender)
            )
        ).all()
    )
    queued = 0
    for message_id, sender, body, sent_at in incoming:
        if await db.get(WhatsAppCustomerMessage, message_id) is not None:
            continue
        command = body.upper() if body.upper() in COMMANDS else None
        if counts.get(sender, 0) >= MAX_DAILY_MESSAGES and command is None:
            continue
        thread = (
            await db.exec(
                select(WhatsAppCustomerThread)
                .where(
                    WhatsAppCustomerThread.connection_id == connection.id,
                    WhatsAppCustomerThread.sender == sender,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).first()
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
        thread.updated_at = utcnow()
        ignored = command is not None or thread.opted_out or thread.paused
        db.add(
            WhatsAppCustomerMessage(
                id=message_id,
                thread_id=thread.id,
                content=None if ignored else body,
                status="ignored" if ignored else "queued",
                sent_at=sent_at,
            )
        )
        await db.flush()
        counts[sender] = counts.get(sender, 0) + 1
        queued += 1
    await db.commit()
    return queued


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
    connection = await configured_connection(db, config)
    if connection is None:
        await db.commit()
        return None
    now = utcnow()
    candidates = (
        await db.exec(
            select(WhatsAppCustomerMessage, WhatsAppCustomerThread.id)
            .join(WhatsAppCustomerThread)
            .where(
                WhatsAppCustomerThread.connection_id == connection.id,
                WhatsAppCustomerMessage.status.in_(
                    [
                        "queued",
                        "classifying",
                        "auto_pending",
                        "grace_pending",
                        "approved",
                        "sending",
                    ]
                ),
            )
            .order_by(WhatsAppCustomerMessage.created_at, WhatsAppCustomerMessage.id)
        )
    ).all()
    busy = False
    ready = []
    for message, thread_id in candidates:
        thread = await repository.lock_thread(db, thread_id, connection.id)
        message = await repository.lock_message(db, message.id, thread.id)
        if message.status in ("classifying", "sending"):
            if message.updated_at < now - timedelta(minutes=10):
                message.status = "unknown" if message.status == "sending" else "failed"
                message.error_code = "worker_lost"
                message.content = None if message.status == "failed" else message.content
                message.updated_at = now
            else:
                busy |= message.status == "classifying"
            continue
        if message.status == "queued":
            ready.append((False, connection, thread, message))
        elif message.status == "approved" or (
            message.send_after is not None and message.send_after <= now
        ):
            ready.append((True, connection, thread, message))
    # Due sends have priority so new inbound traffic cannot starve ready replies.
    ready.sort(key=lambda item: not item[0])
    for sending, connection, thread, message in ready:
        if busy and not sending:
            continue
        if not bound(connection, thread, config, allow_paused=message.status == "approved"):
            message.content = None if message.status == "queued" else message.content
            message.status = "cancelled"
            message.send_after = None
            message.revision += 1
            message.updated_at = now
            continue
        if now >= message.sent_at + timedelta(hours=24):
            message.status = "expired"
            message.send_after = None
            message.updated_at = now
            continue
        if not sending:
            message.status = "classifying"
            message.updated_at = now
        await db.commit()
        return sending, connection, thread, message
    await db.commit()
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
        )
    ).all()
    history = []
    for message in reversed(rows):
        if message.content:
            history.append({"role": "user", "content": message.content[:1000]})
        if message.reply:
            history.append({"role": "assistant", "content": message.reply[:1000]})
    return history
