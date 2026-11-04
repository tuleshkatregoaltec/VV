"""Connectors › WhatsApp, live: tell open WhatsApp screens that a chat changed.

A webhook (a new message, a delivery status) can land on any worker, so it publishes a small
change event to the organization's Redis channel. Every socket subscribes to its organization and
forwards only the changes its user may see: their own agent number, or the campaign number for
owners. The event names the chat, never its content; the screen refetches through the usual
endpoints, which keep their own access checks.
"""

import asyncio
import json
import logging
from contextlib import suppress
from dataclasses import asdict, dataclass

import redis.asyncio as redis
from fastapi import HTTPException, WebSocket, WebSocketDisconnect

from app.auth.service import verify_user
from app.config import settings
from app.core.dependencies import AuthContext, ensure_active_subscription, require_membership
from app.postgres import get_db_session

logger = logging.getLogger(__name__)

AUTH_TIMEOUT = 10.0
PING_EVERY = 25.0
# Close codes in the application range; the screen stops retrying on 4401/4403.
UNAUTHORIZED = 4401
FORBIDDEN = 4403


@dataclass(frozen=True)
class ChatChange:
    wa_id: str
    purpose: str  # "agent" | "campaign"
    user_id: str | None  # the agent's, for an agent number


def _channel(organization_id: str) -> str:
    return f"crm:whatsapp:org:{organization_id}"


def _client() -> redis.Redis:
    return redis.from_url(
        settings.REDIS_URL,
        password=settings.REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


async def publish(organization_id: str, changes: set[ChatChange]) -> None:
    """Best effort: the change is already stored, so a screen that misses it catches up on its
    next refetch. A Redis failure must never fail Meta's webhook."""
    if not changes:
        return
    client = _client()
    try:
        for change in changes:
            await client.publish(_channel(organization_id), json.dumps(asdict(change)))
    except Exception as e:
        logger.warning("WhatsApp live publish failed for org %s: %s", organization_id, e)
    finally:
        await client.aclose()


def visible_to(change: dict, *, user_id: str, owner: bool) -> bool:
    if change.get("purpose") == "campaign":
        return owner
    return change.get("user_id") == user_id


async def _authenticate(websocket: WebSocket) -> AuthContext | None:
    """The first frame carries the token: browsers cannot set headers on a socket, and a token in
    the URL would end up in access logs."""
    try:
        frame = await asyncio.wait_for(websocket.receive_json(), AUTH_TIMEOUT)
    except (TimeoutError, ValueError, WebSocketDisconnect):
        return None
    token = frame.get("token") if isinstance(frame, dict) else None
    if not isinstance(token, str) or not token:
        return None
    user = await verify_user(token)
    if user is None:
        return None
    async for db in get_db_session():
        return ensure_active_subscription(await require_membership(user, db))
    return None


async def serve(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        context = await _authenticate(websocket)
    except HTTPException:
        await websocket.close(code=FORBIDDEN)
        return
    if context is None:
        await websocket.close(code=UNAUTHORIZED)
        return

    user_id = str(context.user.id)
    owner = context.membership.role == "owner"
    client = _client()
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(_channel(str(context.organization.id)))
    except Exception as e:
        logger.warning("WhatsApp live subscribe failed: %s", e)
        await client.aclose()
        await websocket.close(code=1011)
        return
    await websocket.send_json({"type": "ready"})

    async def forward() -> None:
        last_ping = asyncio.get_running_loop().time()
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is not None:
                change = json.loads(message["data"])
                if visible_to(change, user_id=user_id, owner=owner):
                    await websocket.send_json({"type": "chat.changed", "wa_id": change["wa_id"]})
            now = asyncio.get_running_loop().time()
            if now - last_ping >= PING_EVERY:
                # Keeps proxies from closing an idle socket.
                await websocket.send_json({"type": "ping"})
                last_ping = now

    async def drain() -> None:
        # Nothing is expected from the screen; reading notices when it goes away.
        while True:
            await websocket.receive_text()

    tasks = [asyncio.create_task(forward()), asyncio.create_task(drain())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError, Exception):
                await task
        with suppress(Exception):
            await pubsub.aclose()
        await client.aclose()
        with suppress(Exception):
            await websocket.close()
