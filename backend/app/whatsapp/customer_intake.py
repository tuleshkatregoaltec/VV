"""Signed customer webhooks for every connected agent.

Routing: each change is matched to the connection that owns both the entry's WABA ID
and the change's phone_number_id. Unmatched, disconnected or spoofed pairs are dropped.

Privacy: blocked senders are dropped before their text is read and leave no row.
Other text is never written to PostgreSQL, logs, Redis or disk before classification;
it is held only in an in-process task. If the process dies mid-classification, the
content-free receipt is marked failed by the worker after ten minutes and the text
is lost by design.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from app.postgres import get_db_session
from app.whatsapp import customer_automation as automation
from app.whatsapp import customer_contacts as contacts
from app.whatsapp import customer_queue as queue
from app.whatsapp import customer_repository as repository
from app.whatsapp.customer_connections import disconnect
from app.whatsapp.customer_service import cancel_unsent
from app.whatsapp.models import utcnow

logger = logging.getLogger(__name__)

ROUTED_FIELDS = {"messages", "smb_app_state_sync", "smb_message_echoes"}
DISCONNECT_EVENTS = {"PARTNER_REMOVED", "ACCOUNT_OFFBOARDED"}

_tasks: set[asyncio.Task] = set()
_loop = None
_slots: asyncio.Semaphore | None = None
_thread_locks: dict[str, list] = {}  # thread_id -> [lock, users]


def parse(event):
    """Validated (waba_id, field, value) changes; raises ValueError for invalid events."""
    if not isinstance(event, dict) or event.get("object") != "whatsapp_business_account":
        raise ValueError("Invalid WhatsApp event")
    entries = event.get("entry", [])
    if not isinstance(entries, list):
        raise ValueError("Invalid WhatsApp event")
    changes = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("changes", []), list):
            raise ValueError("Invalid WhatsApp event")
        account_id = entry.get("id")
        if not isinstance(account_id, str) or not account_id:
            continue
        for change in entry.get("changes", []):
            if not isinstance(change, dict) or not isinstance(change.get("value", {}), dict):
                raise ValueError("Invalid WhatsApp event")
            field = change.get("field")
            if field in ROUTED_FIELDS or field == "account_update":
                changes.append((account_id, field, change.get("value", {})))
    return changes


def _echo_time(echo):
    try:
        return datetime.fromtimestamp(int(echo["timestamp"]), timezone.utc)
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        return None


async def cancel_in_flight(db, thread, before):
    """The agent answered while these were still being classified: never answer twice."""
    for message in await repository.messages(db, thread.id, lock=True):
        if message.status in ("queued", "classifying") and (
            before is None or message.sent_at <= before
        ):
            message.content = None
            message.reply = None
            message.evidence_ids = []
            message.status = "cancelled"
            message.reason = "agent_replied"
            message.send_after = None
            message.revision += 1
            message.updated_at = utcnow()


async def apply_echoes(db, connection, echoes):
    """An agent reply from the phone app takes over a property thread, and cancels any
    automated answer still being prepared for earlier messages. Echo text is never read or
    stored, and no thread is created for a personal chat."""
    if not isinstance(echoes, list):
        return
    for echo in echoes:
        if not isinstance(echo, dict):
            continue
        recipient = queue.wa_id_of(echo.get("to"))
        if recipient is None:
            continue
        thread = await repository.thread_for_sender(db, connection.id, recipient)
        if thread is None or thread.paused:
            continue
        if not await repository.has_property_messages(db, thread.id):
            # Topic is unknown until classification ends; only in-flight work is cancelled.
            await cancel_in_flight(db, thread, _echo_time(echo))
            continue
        thread.paused = True
        thread.updated_at = utcnow()
        await cancel_unsent(db, thread, "agent_replied")


async def apply_account_update(db, account_id, value):
    event = value.get("event")
    if not isinstance(event, str) or len(event) > 64:
        return
    for connection in await repository.account_connections(db, account_id):
        if event in DISCONNECT_EVENTS and connection.status == "connected":
            await disconnect(db, connection, reason=event)
        connection.last_account_event = event
        connection.updated_at = utcnow()


async def receive_customer(event, config):
    if not config.WHATSAPP_CUSTOMER_AUTOMATION_ENABLED:
        return 0
    queue.require_customer_config(config)
    changes = parse(event)
    if not changes:
        return 0
    jobs = []
    failure = None
    async with asynccontextmanager(get_db_session)() as db:
        # One transaction per change: at most one connection lock is held at a time. A
        # failing change is rolled back alone; receipts committed by the others are still
        # classified, and the error is raised afterwards so Meta retries (deduplicated).
        for account_id, field, value in changes:
            try:
                jobs.extend(await _apply_change(db, account_id, field, value, config))
            except Exception as exc:
                failure = failure or exc
                logger.error("WhatsApp webhook change failed (%s)", type(exc).__name__)
                try:
                    await db.rollback()
                except Exception as rollback_exc:
                    logger.error(
                        "WhatsApp webhook rollback failed (%s)", type(rollback_exc).__name__
                    )
                    break
    for job in jobs:
        spawn(job, config)
    if failure is not None:
        raise failure
    return len(jobs)


async def _apply_change(db, account_id, field, value, config):
    """Apply and commit one change; returns its classification jobs (only once committed)."""
    if field == "account_update":
        await apply_account_update(db, account_id, value)
        await db.commit()
        return []
    metadata = value.get("metadata")
    phone_number_id = metadata.get("phone_number_id") if isinstance(metadata, dict) else None
    if not isinstance(phone_number_id, str):
        return []
    connection = await repository.routed_connection(db, account_id, phone_number_id)
    if connection is None:
        await db.commit()
        return []
    jobs = []
    if field == "messages":
        jobs = await queue.enqueue(db, connection, value.get("messages", []), config)
    elif field == "smb_app_state_sync":
        await contacts.apply_state_sync(db, connection, value.get("state_sync", []))
    else:
        await apply_echoes(db, connection, value.get("message_echoes", []))
    await db.commit()
    return jobs


def _reset_for_loop():
    global _loop, _slots, _thread_locks
    loop = asyncio.get_running_loop()
    if loop is not _loop:
        _loop = loop
        _slots = None
        _thread_locks = {}
    return loop


def spawn(job, config):
    _reset_for_loop()
    task = asyncio.create_task(_run(job, config))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _run(job, config):
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(config.WHATSAPP_CLASSIFIER_CONCURRENCY)
    entry = _thread_locks.setdefault(job.thread_id, [asyncio.Lock(), 0])
    entry[1] += 1
    try:
        # Per-thread order keeps conversation history coherent within this process.
        async with entry[0], _slots:
            await automation.classify(job, config)
    except Exception as exc:
        logger.error("WhatsApp classification task failed (%s)", type(exc).__name__)
    finally:
        entry[1] -= 1
        if entry[1] == 0 and _thread_locks.get(job.thread_id) is entry:
            del _thread_locks[job.thread_id]


async def drain():
    """Wait for in-flight classification (tests and graceful shutdown)."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


async def shutdown(timeout=30):
    """Give in-flight classification a bounded chance to finish on process exit."""
    try:
        await asyncio.wait_for(drain(), timeout)
    except TimeoutError:
        logger.warning("WhatsApp classification still running at shutdown; text discarded")
