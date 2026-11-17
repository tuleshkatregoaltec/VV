import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx

from app.chat.operations import (
    answer_channel,
    channel_access,
    channel_input,
    create_channel_conversation,
)
from app.config import settings
from app.postgres import get_db_session
from app.whatsapp import repository
from app.whatsapp.models import WhatsAppTurn, utcnow

logger = logging.getLogger(__name__)


def require_automation_config(config):
    required = (
        config.WHATSAPP_APP_SECRET,
        config.WHATSAPP_ACCESS_TOKEN,
        config.WHATSAPP_PHONE_NUMBER_ID,
        config.WHATSAPP_TEST_RECIPIENT,
        config.WHATSAPP_GRAPH_API_VERSION,
        config.WHATSAPP_PILOT_USER_ID,
        config.WHATSAPP_PILOT_ORGANIZATION_ID,
    )
    if not config.WHATSAPP_DEMO_ENABLED or not all(required):
        raise ValueError("WhatsApp automation configuration is incomplete")


def inbound_turns(event, config):
    now = utcnow()
    turns = []
    for entry in event.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if (
                change.get("field") != "messages"
                or value.get("metadata", {}).get("phone_number_id")
                != config.WHATSAPP_PHONE_NUMBER_ID
            ):
                continue
            for message in value.get("messages", []):
                if (
                    message.get("from") != config.WHATSAPP_TEST_RECIPIENT
                    or message.get("type") != "text"
                ):
                    continue
                body, message_id = message.get("text", {}).get("body"), message.get("id")
                if (
                    not isinstance(body, str)
                    or not body.strip()
                    or not isinstance(message_id, str)
                    or not 1 <= len(message_id) <= 512
                ):
                    continue
                if channel_input(body) is None:
                    continue
                try:
                    sent_at = datetime.fromtimestamp(int(message["timestamp"]), timezone.utc)
                except (KeyError, ValueError, TypeError, OverflowError, OSError):
                    continue
                if not now - timedelta(hours=24) < sent_at <= now + timedelta(minutes=5):
                    continue
                turns.append(
                    WhatsAppTurn(
                        id=message_id,
                        phone_number_id=config.WHATSAPP_PHONE_NUMBER_ID,
                        sender=config.WHATSAPP_TEST_RECIPIENT,
                        user_id=config.WHATSAPP_PILOT_USER_ID,
                        organization_id=config.WHATSAPP_PILOT_ORGANIZATION_ID,
                        content=body,
                        sent_at=sent_at,
                    )
                )
    return turns


async def receive(event, config):
    require_automation_config(config)
    turns = inbound_turns(event, config)
    if not turns:
        return 0
    async with asynccontextmanager(get_db_session)() as db:
        return await repository.enqueue(db, turns, config)


def bound(turn, config):
    return (
        config.WHATSAPP_AUTOMATION_ENABLED
        and config.WHATSAPP_DEMO_ENABLED
        and turn.phone_number_id == config.WHATSAPP_PHONE_NUMBER_ID
        and turn.sender == config.WHATSAPP_TEST_RECIPIENT
        and turn.user_id == config.WHATSAPP_PILOT_USER_ID
        and turn.organization_id == config.WHATSAPP_PILOT_ORGANIZATION_ID
    )


def inside_window(turn):
    return utcnow() < turn.sent_at + timedelta(hours=24)


async def send_reply(turn, config):
    url = f"https://graph.facebook.com/{config.WHATSAPP_GRAPH_API_VERSION}/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {config.WHATSAPP_ACCESS_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "to": turn.sender,
                "type": "text",
                "context": {"message_id": turn.id},
                "text": {"body": turn.reply},
            },
        )
    # The caller records ambiguous outcomes without resending.
    if response.status_code != 200:
        raise ValueError("Meta rejected reply")
    return response.json()["messages"][0]["id"]


async def process(db, turn, config):
    scope = {"user_id": turn.user_id, "organization_id": turn.organization_id}
    try:
        if not bound(turn, config) or not await channel_access(db, **scope):
            await repository.save(db, turn, "revoked")
            return
        if not inside_window(turn):
            await repository.save(db, turn, "expired")
            return
        if not turn.reply:
            if not turn.conversation_id:
                turn.conversation_id = await repository.previous_conversation(db, config)
                if not turn.conversation_id:
                    turn.conversation_id = await create_channel_conversation(db, **scope)
                await repository.save(db, turn, "processing")
            turn.reply = await answer_channel(
                db, conversation_id=turn.conversation_id, message=turn.content, **scope
            )
            await repository.save(db, turn, "reply_ready")
        if not bound(turn, config) or not await channel_access(db, **scope):
            await repository.save(db, turn, "revoked")
            return
        if not inside_window(turn):
            await repository.save(db, turn, "expired")
            return
        await repository.save(db, turn, "sending")
        # No retries: a timeout may mean Meta already accepted the message.
        turn.outbound_id = await send_reply(turn, config)
        await repository.save(db, turn, "accepted")
        logger.info("WhatsApp pilot reply accepted by Meta")
    except Exception as exc:
        logger.error("WhatsApp turn failed (%s)", type(exc).__name__)
        await db.rollback()
        # Read state afresh: rollback may expire this ORM instance.
        await db.refresh(turn)
        status = "unknown" if turn.status == "sending" else "failed"
        await repository.save(db, turn, status, error=type(exc).__name__)


async def run_once(config=settings):
    if not config.WHATSAPP_AUTOMATION_ENABLED:
        return False
    require_automation_config(config)
    async with asynccontextmanager(get_db_session)() as db:
        turn = await repository.claim(db, config)
        if turn is None:
            return False
        async with asyncio.timeout(360):
            await process(db, turn, config)
        return True
