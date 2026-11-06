"""Selective customer drafting and durable delivery; never private chat answers."""

import asyncio
import copy
import logging
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx

from app.chat.operations import channel_access, create_customer_conversation
from app.config import settings
from app.postgres import get_db_session
from app.whatsapp import customer_access, token_crypto
from app.whatsapp import customer_queue as queue
from app.whatsapp import customer_repository as repository
from app.whatsapp import customer_timing as timing
from app.whatsapp import customer_voice as voice
from app.whatsapp.customer_agent import build_customer_draft
from app.whatsapp.models import utcnow

logger = logging.getLogger(__name__)


class MetaSendRejected(ValueError):
    """A definite Graph rejection, containing only allowlisted numeric metadata."""

    def __init__(self, response):
        self.error_code = f"meta_http_{response.status_code}"
        try:
            error = response.json().get("error", {})
            code = error.get("code")
            subcode = error.get("error_subcode")
            if type(code) is int:
                self.error_code = f"meta_{code}"
                if type(subcode) is int:
                    self.error_code += f"_{subcode}"
        except (ValueError, TypeError, AttributeError):
            pass
        super().__init__(self.error_code)


def eligible(connection, thread, message, config):
    return queue.bound(
        connection, thread, config, allow_paused=message.status == "approved"
    ) and utcnow() < message.sent_at + timedelta(hours=24)


async def eligible_now(db, connection, thread, message, config):
    # A contact blocked after receipt is never answered or read again.
    return eligible(connection, thread, message, config) and not await repository.blocked_contact(
        db, connection.id, thread.sender, None
    )


def scope(connection):
    return {"user_id": connection.user_id, "organization_id": connection.organization_id}


async def draft(db, location, revision, config, content):
    """Classify and draft from in-memory `content`; persist it only if admitted."""
    context = await queue.locked_context(db, *location)
    if context is None:
        await db.commit()
        return
    connection, thread, message = context
    if message.status != "classifying" or message.revision != revision:
        await db.commit()
        return
    if not await eligible_now(db, *context, config) or not await channel_access(
        db, **scope(connection)
    ):
        message.status = "cancelled"
        message.content = None
        message.updated_at = utcnow()
        await db.commit()
        return
    knowledge = copy.deepcopy(connection.approved_knowledge)
    voice_profile = copy.deepcopy(connection.reply_voice)
    agent_name = connection.display_name
    history = await queue.history_for(db, thread.id)
    identity = scope(connection)
    conversation_id = thread.conversation_id
    await db.commit()
    if not conversation_id:
        # An empty technical conversation scopes quota only. No inbound body is saved to chat.
        conversation_id = await create_customer_conversation(db, **identity)
        context = await queue.locked_context(db, *location)
        if context is None:
            await db.commit()
            return
        connection, thread, message = context
        if message.status != "classifying" or message.revision != revision:
            await db.commit()
            return
        if (
            not await eligible_now(db, *context, config)
            or connection.approved_knowledge != knowledge
        ):
            message.status = "cancelled"
            message.content = None
            message.updated_at = utcnow()
            await db.commit()
            return
        thread.conversation_id = conversation_id
        await db.commit()

    async def retrieve_evidence(request):
        # Independent short-lived read session; no model call holds database locks.
        async with asynccontextmanager(get_db_session)() as evidence_db:
            return await customer_access.retrieve(
                evidence_db, request, connection_id=location[0], **identity
            )

    # No database locks or transaction span the model/provider call.
    result = await build_customer_draft(
        message=content,
        knowledge=knowledge,
        history=history,
        conversation_id=conversation_id,
        retrieve_evidence=retrieve_evidence,
        voice_profile=voice_profile,
        agent_name=agent_name,
        **identity,
    )
    context = await queue.locked_context(db, *location)
    if context is None:
        await db.commit()
        return
    connection, thread, message = context
    if message.status != "classifying" or message.revision != revision:
        await db.commit()
        return
    if (
        not await eligible_now(db, *context, config)
        or connection.approved_knowledge != knowledge
        or not await channel_access(db, **identity)
    ):
        message.status = "cancelled"
        message.content = None
    elif result is None:
        message.status = "ignored"
        message.content = None
        message.reply = None
        message.evidence_ids = []
    else:
        silent = bool(getattr(result, "silent", False))
        if not silent and (
            not result.reply
            or len(result.reply) > 4000
            or result.risk not in ("routine", "approval")
        ):
            raise ValueError("Invalid customer draft")
        snapshots = [
            item.model_dump(mode="json") for item in getattr(result, "evidence_snapshots", [])
        ]
        if not silent and not await customer_access.valid_evidence(
            db,
            connection,
            result.evidence_ids,
            snapshots,
            result.reply,
            context=[content, *[turn["content"] for turn in history]],
        ):
            message.status = "cancelled"
            message.content = None
            message.reason = "evidence_changed"
            message.updated_at = utcnow()
            await db.commit()
            return
        message.evidence_snapshots = snapshots
        # The only point where inbound text becomes durable: an admitted property enquiry.
        message.content = content
        message.reply = result.reply
        message.risk = result.risk
        message.topic = "real_estate"
        message.evidence_ids = result.evidence_ids
        message.handoff_summary = getattr(result, "summary", None)
        message.asked_detail = getattr(result, "asked", None)
        if silent:
            message.reason = getattr(result, "reason", None)
        automatic = not silent and result.risk == "routine" and result.auto_eligible
        message.status = "auto_pending" if automatic else "approval_required"
        now = utcnow()
        message.send_after = (
            timing.reading_due(
                now, message.sent_at, len(content), enabled=config.WHATSAPP_HUMAN_TIMING_ENABLED
            )
            if automatic
            else None
        )
        if not automatic:
            message.notification_created_at = now
            thread.paused = True
            thread.updated_at = now
    message.updated_at = utcnow()
    await db.commit()


def connection_token(connection, config):
    if not connection.access_token_encrypted:
        raise token_crypto.TokenEncryptionUnavailable("No WhatsApp token is stored")
    return token_crypto.decrypt_token(connection.access_token_encrypted, config)


def _messages_url(connection, config):
    return (
        f"https://graph.facebook.com/{config.WHATSAPP_GRAPH_API_VERSION}/"
        f"{connection.phone_number_id}/messages"
    )


async def mark_read_typing(connection, message, config) -> bool:
    """Mark the buyer's message read and show Meta's typing indicator (max 25 seconds,
    cleared when we reply). Cosmetic, so any failure is logged by class and ignored."""
    try:
        token = connection_token(connection, config)
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            response = await client.post(
                _messages_url(connection, config),
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": message.id,
                    "typing_indicator": {"type": "text"},
                },
            )
        return response.status_code == 200
    except Exception as exc:
        logger.warning("WhatsApp typing indicator failed (%s)", type(exc).__name__)
        return False


async def _post_text(client, url, token, thread, body, reply_to=None):
    payload = {
        "messaging_product": "whatsapp",
        "to": thread.sender,
        "type": "text",
        "text": {"body": body},
    }
    if reply_to is not None:
        payload["context"] = {"message_id": reply_to}
    response = await client.post(url, headers={"Authorization": f"Bearer {token}"}, json=payload)
    if response.status_code != 200:
        if 400 <= response.status_code < 500:
            raise MetaSendRejected(response)
        raise ValueError("Meta send outcome unconfirmed")
    outbound_id = response.json()["messages"][0]["id"]
    if not isinstance(outbound_id, str) or not 1 <= len(outbound_id) <= 512:
        raise ValueError("Invalid Meta message ID")
    return outbound_id


async def send_reply(connection, thread, message, config):
    token = connection_token(connection, config)
    url = _messages_url(connection, config)
    # Generated replies may go out as two short texts, the way people write. An agent's
    # own edit is sent exactly as written.
    split = (
        config.WHATSAPP_HUMAN_TIMING_ENABLED and getattr(message, "reason", None) != "human_edited"
    )
    parts = voice.split_reply(message.reply) if split else [message.reply]
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        outbound_id = await _post_text(client, url, token, thread, parts[0], message.id)
        for part in parts[1:]:
            # The first text is already delivered, so a failure here must not look like a
            # failed send (and is never retried: that would repeat the first text).
            try:
                await mark_read_typing(connection, message, config)
                await asyncio.sleep(timing.split_gap(len(part)))
                await _post_text(client, url, token, thread, part)
            except Exception as exc:
                logger.warning("WhatsApp second text not sent (%s)", type(exc).__name__)
                break
    return outbound_id


async def show_typing(db, location, config, context):
    """First pass of a humanized send: read receipt and typing indicator, then wait.

    The wait is a later `send_after`, not a sleep, so this worker lane stays free for other
    agents. A short lease keeps other lanes off the row while the Graph call is in flight.
    """
    connection, _, message = context
    revision, now = message.revision, utcnow()
    message.typing_started_at = now
    message.send_after = now + timedelta(seconds=30)
    message.updated_at = now
    await db.commit()
    await mark_read_typing(connection, message, config)
    context = await queue.locked_context(db, *location)
    if context is not None:
        connection, thread, message = context
        if message.revision == revision and message.status in ("auto_pending", "grace_pending"):
            now = utcnow()
            message.send_after = timing.typing_due(now, message.sent_at, len(message.reply))
            message.updated_at = now
    await db.commit()


async def send(db, location, config):
    context = await queue.locked_context(db, *location)
    if context is None:
        await db.commit()
        return
    connection, thread, message = context
    if message.status not in ("auto_pending", "grace_pending", "approved"):
        await db.commit()
        return
    if message.send_after is None or message.send_after > utcnow():
        await db.commit()
        return
    if not await eligible_now(db, *context, config) or not await channel_access(
        db, **scope(connection)
    ):
        message.status = (
            "expired" if utcnow() >= message.sent_at + timedelta(hours=24) else "cancelled"
        )
        message.send_after = None
        message.updated_at = utcnow()
        await db.commit()
        return
    history = await queue.history_for(db, thread.id)
    if not await customer_access.valid_evidence(
        db,
        connection,
        message.evidence_ids,
        message.evidence_snapshots,
        message.reply,
        human_edited=message.reason == "human_edited",
        context=[message.content or "", *[turn["content"] for turn in history]],
    ):
        message.status = "cancelled"
        message.reason = "evidence_changed"
        message.send_after = None
        message.updated_at = utcnow()
        await db.commit()
        return
    if not message.reply or len(message.reply) > 4000:
        raise ValueError("Invalid customer reply")
    try:
        connection_token(connection, config)
    except token_crypto.TokenEncryptionUnavailable:
        # Fail before `sending`: nothing reached Meta, so the outcome is definite.
        message.status = "failed"
        message.error_code = "token_unavailable"
        message.reason = "The WhatsApp connection needs to be reconnected."
        message.notification_created_at = utcnow()
        message.send_after = None
        message.updated_at = utcnow()
        await db.commit()
        return
    if (
        config.WHATSAPP_HUMAN_TIMING_ENABLED
        and message.status in ("auto_pending", "grace_pending")
        and message.reason != "human_edited"
        and message.typing_started_at is None
        and timing.fits_window(utcnow(), message.sent_at)
    ):
        await show_typing(db, location, config, context)
        return
    # Commit is the send/cancel linearization point. Owner operations reject `sending`;
    # cancellation committed first wins. There is no retry after this point.
    message.status = "sending"
    message.updated_at = utcnow()
    await db.commit()
    outbound_id = await send_reply(*context, config)
    context = await queue.locked_context(db, *location)
    if context and context[2].status == "sending":
        context[2].outbound_id = outbound_id
        context[2].status = "accepted"
        context[2].updated_at = utcnow()
    await db.commit()


async def record_failure(db, location, revision, error):
    await db.rollback()
    context = await queue.locked_context(db, *location)
    if context:
        message = context[2]
        if message.revision == revision and message.status in (
            "classifying",
            "auto_pending",
            "grace_pending",
            "approved",
            "sending",
        ):
            message.status = (
                "unknown"
                if message.status == "sending" and not isinstance(error, MetaSendRejected)
                else "failed"
            )
            if message.status == "failed" and message.topic != "real_estate":
                message.content = None
                message.reply = None
            message.error_code = (
                error.error_code if isinstance(error, MetaSendRejected) else type(error).__name__
            )
            if isinstance(error, MetaSendRejected):
                message.reason = (
                    "Meta denied permission to send for this WhatsApp account."
                    if error.error_code == "meta_10"
                    else f"Meta rejected the reply ({error.error_code})."
                )
            if message.topic == "real_estate":
                message.notification_created_at = utcnow()
            message.send_after = None
            message.updated_at = utcnow()
    await db.commit()


async def classify(job, config=settings):
    """Run one in-memory classification job in its own session (no locks held over LLM)."""
    location = job.connection_id, job.thread_id, job.message_id
    async with asynccontextmanager(get_db_session)() as db:
        try:
            async with asyncio.timeout(360):
                await draft(db, location, job.revision, config, job.content)
        except Exception as exc:
            logger.error("WhatsApp customer classification failed (%s)", type(exc).__name__)
            await record_failure(db, location, job.revision, exc)


async def run_customer_once(config=settings):
    """Worker lane: deliver due replies for every connected agent."""
    if not config.WHATSAPP_CUSTOMER_AUTOMATION_ENABLED:
        return False
    queue.require_customer_config(config)
    async with asynccontextmanager(get_db_session)() as db:
        claimed = await queue.claim(db, config)
        if claimed is None:
            return False
        connection, thread, message = claimed
        location = connection.id, thread.id, message.id
        revision = message.revision
        try:
            async with asyncio.timeout(360):
                await send(db, location, config)
        except Exception as exc:
            logger.error(
                "WhatsApp customer work failed (%s)",
                exc.error_code if isinstance(exc, MetaSendRejected) else type(exc).__name__,
            )
            await record_failure(db, location, revision, exc)
        return True
