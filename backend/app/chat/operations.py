"""Authorized non-browser entry point to the same guarded chat execution."""

import asyncio
import json
from contextlib import aclosing, asynccontextmanager

from pydantic_ai.usage import RunUsage

from app.chat import admission, budget
from app.chat.conversations import create_conversation
from app.chat.security import input_refusal, safe_answer
from app.crm.assistant import has_current_access
from app.crm.assistant.service import stream_chat_response
from app.postgres import get_db_session

# Raised by `channel_budget` when a turn cannot start yet; nothing was reserved or spent.
AdmissionRefused = admission.AdmissionRefused
# Shared LLM cost controls for other domains (feasibility): the same per-user admission
# and daily allowance, history bound and in-turn tool-output compaction.
admitted_run = admission.admitted_run
bound_history = budget.bound_history
compact_tool_outputs = budget.compact_tool_outputs


def channel_input(message: str) -> str | None:
    return None if input_refusal(message) else message


def channel_output_allowed(message: str) -> bool:
    return safe_answer(message)


async def channel_access(db, *, user_id: str, organization_id: str) -> bool:
    return await has_current_access(db, user_id=user_id, organization_id=organization_id)


async def create_channel_conversation(db, *, user_id: str, organization_id: str) -> int:
    if not await channel_access(db, user_id=user_id, organization_id=organization_id):
        raise PermissionError("Channel access revoked")
    conversation = await create_conversation(db, user_id, organization_id, "WhatsApp pilot")
    return conversation.id


async def create_customer_conversation(db, *, user_id: str, organization_id: str) -> int:
    if not await channel_access(db, user_id=user_id, organization_id=organization_id):
        raise PermissionError("Channel access revoked")
    conversation = await create_conversation(db, user_id, organization_id, "WhatsApp customer")
    return conversation.id


@asynccontextmanager
async def channel_budget(*, user_id: str, organization_id: str, conversation_id: int):
    """Share durable web-chat quotas without exposing its private tools to customers."""
    async with asynccontextmanager(get_db_session)() as db:
        if not await channel_access(db, user_id=user_id, organization_id=organization_id):
            raise PermissionError("Channel access revoked")
    lease = await admission.acquire(
        user_id=user_id, organization_id=organization_id, conversation_id=conversation_id
    )
    usage = RunUsage()
    completed = False
    try:
        yield usage
        completed = True
    finally:
        await asyncio.shield(admission.finish(lease.id, usage, successful=completed))


async def answer_channel(
    db, *, conversation_id: int, message: str, user_id: str, organization_id: str
) -> str:
    scope = {"user_id": user_id, "organization_id": organization_id}
    if not await channel_access(db, **scope):
        raise PermissionError("Channel access revoked")
    chunks = []
    completed = proposed = False
    async with aclosing(stream_chat_response(db, conversation_id, message, **scope)) as stream:
        async for frame in stream:
            for line in frame.splitlines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if event.get("type") == "error":
                    raise RuntimeError("Chat execution failed")
                if event.get("type") == "content":
                    chunks.append(event["content"])
                completed |= event.get("type") == "done"
                proposed |= event.get("type") == "action_proposed"
    if not completed or not chunks:
        raise RuntimeError("Chat did not finish")
    if not await channel_access(db, **scope):
        raise PermissionError("Channel access revoked")
    answer = "".join(chunks)
    if proposed:
        answer += "\nReview and confirm proposed changes in Vitevue. WhatsApp cannot confirm them."
    if len(answer) > 4000:
        answer = (
            answer[:3900]
            + "\n[Full answer is saved in your WhatsApp pilot conversation in Vitevue.]"
        )
    return answer
