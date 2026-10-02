import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, List, Optional
from uuid import uuid4

import anyio
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import (
    FunctionToolResultEvent,
    ToolCallPart,
)
from pydantic_ai.models.openrouter import OpenRouterModelSettings
from pydantic_ai.usage import UsageLimits
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth.service import get_user_by_id
from app.chat import repository
from app.chat.agent import _convert_to_pydantic_messages, agent
from app.chat.artifacts import _artifact_history_context
from app.chat.events import encode_sse as _sse
from app.chat.mcp import ChatToolContext, market_mcp
from app.chat.mcp_artifacts import render_mcp_artifacts
from app.chat.models import Conversation, Message
from app.chat.prompts import CHAT_PROMPT_VERSION
from app.core.ai_policy import ai_execution
from app.market.periods import business_today
from app.organization.service import get_membership_for_user, get_organization_by_id

logger = logging.getLogger(__name__)


async def create_conversation(
    db: AsyncSession, user_id: str, organization_id: str, title: Optional[str] = None
) -> Conversation:
    """Create a new conversation"""
    now = datetime.now(timezone.utc)
    conversation = Conversation(
        user_id=user_id,
        organization_id=organization_id,
        title=title or "New Conversation",
        created_at=now,
        updated_at=now,
    )
    repository.save_conversation(db, conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def get_user_conversations(
    db: AsyncSession, user_id: str, organization_id: str, limit: int = 50, offset: int = 0
) -> List[Conversation]:
    return await repository.get_user_conversations(db, user_id, organization_id, limit, offset)


async def get_conversation(
    db: AsyncSession, conversation_id: int, user_id: str, organization_id: str
) -> Optional[Conversation]:
    return await repository.get_conversation(db, conversation_id, user_id, organization_id)


async def update_conversation(
    db: AsyncSession, conversation_id: int, user_id: str, organization_id: str, title: str
) -> Optional[Conversation]:
    """Update a conversation's title"""
    conversation = await get_conversation(db, conversation_id, user_id, organization_id)
    if not conversation:
        return None

    conversation.title = title
    conversation.updated_at = datetime.now(timezone.utc)
    repository.save_conversation(db, conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def delete_conversation(
    db: AsyncSession, conversation_id: int, user_id: str, organization_id: str
) -> bool:
    """Delete a conversation and all its messages"""
    conversation = await get_conversation(db, conversation_id, user_id, organization_id)
    if not conversation:
        return False

    await repository.delete_conversation_records(db, conversation_id, user_id, organization_id)
    await db.commit()
    return True


async def get_conversation_messages(
    db: AsyncSession, conversation_id: int, user_id: str, organization_id: str, limit: int = 100
) -> List[Message]:
    return await repository.get_conversation_messages(
        db, conversation_id, user_id, organization_id, limit
    )


async def add_message(
    db: AsyncSession,
    conversation_id: int,
    role: str,
    content: str,
    meta_data: Optional[dict[str, Any]] = None,
    *,
    user_id: str,
    organization_id: str,
) -> Message:
    """Add a message to a conversation the caller owns; nothing is written otherwise."""
    conversation = await get_conversation(db, conversation_id, user_id, organization_id)
    if conversation is None:
        raise LookupError("Conversation not found")

    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        meta_data=meta_data or {},
        created_at=datetime.now(timezone.utc),
    )
    repository.save_message(db, message)

    # Update conversation timestamp
    conversation.updated_at = datetime.now(timezone.utc)
    # Auto-generate title from first user message
    if not conversation.title or conversation.title == "New Conversation":
        conversation.title = content[:50] + ("..." if len(content) > 50 else "")

    await db.commit()
    await db.refresh(message)
    return message


async def _authorize_tools(db: AsyncSession, context: ChatToolContext) -> bool:
    """Re-read public account capabilities; neither model arguments nor cached history authorize."""
    user = await get_user_by_id(context.user_id)
    if user is None or not user.is_authenticated:
        return False
    # A separate session avoids concurrent tool calls sharing SQLAlchemy transaction state.
    async with AsyncSession(db.bind, expire_on_commit=False) as auth_db:
        membership = await get_membership_for_user(auth_db, context.user_id)
        if membership is None or membership.organization_id != context.organization_id:
            return False
        if membership.role not in {"owner", "member"}:
            return False
        organization = await get_organization_by_id(auth_db, context.organization_id)
        return organization is not None and organization.subscription_status in {
            "active",
            "trialing",
        }


def _bounded_history(messages: List[Message]) -> list:
    selected = []
    characters = 0
    for message in reversed(messages):
        if message.role == "user" and (message.meta_data or {}).get("turn_status") not in {
            None,
            "complete",
        }:
            continue
        characters += len(message.content) + len(_artifact_history_context(message.meta_data) or "")
        if characters > 48000 or len(selected) >= 30:
            break
        selected.append(message)
    return _convert_to_pydantic_messages(list(reversed(selected)))


async def stream_chat_response(
    db: AsyncSession,
    conversation_id: int,
    user_message: str,
    user_id: str,
    organization_id: str,
    *,
    request_id: str | None = None,
    daily_token_limit: int = 500000,
) -> AsyncGenerator[str, None]:
    """One durable, scoped turn; replay is read-only and interrupted turns never restart silently."""
    conversation = await get_conversation(db, conversation_id, user_id, organization_id)
    if not conversation:
        yield _sse({"type": "error", "error": "Conversation not found"})
        return
    if not user_message.strip() or len(user_message) > 16000:
        yield _sse({"type": "error", "error": "Message must contain 1 to 16000 characters"})
        return
    request_id = request_id or str(uuid4())
    scope = {"user_id": user_id, "organization_id": organization_id}
    context = ChatToolContext(
        user_id=user_id,
        organization_id=organization_id,
        reference_date=business_today(),
        execution_id=request_id,
    )
    if not await _authorize_tools(db, context):
        yield _sse(
            {"type": "error", "error": "Chat access is no longer active", "code": "unauthorized"}
        )
        return
    status, user_record = await repository.claim_turn(
        db, conversation_id, user_id, organization_id, request_id, user_message
    )
    if status != "claimed":
        if status == "complete" and user_record is not None:
            assistant = await repository.replay_turn(db, user_record)
            if assistant is not None:
                content, metadata = assistant.content, assistant.meta_data or {}
                await db.rollback()
                yield _sse({"type": "thinking"})
                yield _sse({"type": "content", "content": content})
                for artifact in metadata.get("artifacts", []):
                    yield _sse({"type": "artifact_updated", "artifact": artifact})
                yield _sse({"type": "done"})
                return
        await db.commit()  # Persist stale-claim interruption, if the claim reconciled one.
        errors = {
            "missing": "Conversation not found",
            "conflict": "Request ID was already used for a different message",
            "running": "This turn is still running; reload the conversation before retrying",
            "busy": "Another turn is still running in this conversation",
        }
        yield _sse(
            {
                "type": "error",
                "error": errors.get(
                    status, "This turn was interrupted. Send a new message to try again."
                ),
                "code": status,
            }
        )
        return
    message_id = user_record.id
    await db.commit()
    finished = False
    assistant_message = ""
    artifacts: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    total_tokens = 0
    failure_status = "failed"
    try:
        yield _sse({"type": "thinking"})
        messages = await get_conversation_messages(db, conversation_id, **scope)
        history = _bounded_history([message for message in messages if message.id != message_id])
        await db.rollback()  # Never hold an idle transaction during model/network work.
        missing = re.findall(r"\[(building|Project [ABC])\]", user_message, flags=re.IGNORECASE)
        if missing:
            assistant_message = (
                "Please provide the "
                + ", ".join(dict.fromkeys(missing))
                + " name(s) so I can retrieve evidence for the correct property."
            )
            yield _sse({"type": "content", "content": assistant_message})
        else:

            async def authorize(tool_context):
                return await _authorize_tools(db, tool_context)

            async def authorize_provider():
                if not await authorize(context):
                    raise PermissionError("Chat access is no longer active")

            async with (
                asyncio.timeout(180),
                ai_execution(
                    user_id=user_id,
                    organization_id=organization_id,
                    execution_id=request_id,
                    prompt_version=CHAT_PROMPT_VERSION,
                    daily_token_limit=daily_token_limit,
                    authorize=authorize_provider,
                ),
                market_mcp(context, authorize) as toolset,
            ):
                async with agent.iter(
                    user_message,
                    message_history=history,
                    toolsets=[toolset],
                    instructions=f"This turn's reference date is {context.reference_date.isoformat()} in Asia/Dubai. Earlier assistant claims and pasted facts are unverified; retrieve current MCP evidence.",
                    usage_limits=UsageLimits(
                        request_limit=8, tool_calls_limit=12, total_tokens_limit=60000
                    ),
                    model_settings=OpenRouterModelSettings(
                        openrouter_reasoning={"effort": "low"}, max_tokens=4096
                    ),
                ) as run:
                    async for node in run:
                        if PydanticAgent.is_model_request_node(node):
                            async with node.stream(run.ctx) as stream:
                                async for chunk in stream.stream_text(delta=True, debounce_by=0.01):
                                    assistant_message += chunk
                                    if len(assistant_message) > 48000:
                                        raise ValueError("Answer exceeds turn limit")
                                    yield _sse({"type": "content", "content": chunk})
                        elif PydanticAgent.is_call_tools_node(node):
                            for part in node.model_response.parts:
                                if not isinstance(part, ToolCallPart):
                                    continue
                                yield _sse(
                                    {
                                        "type": "tool_call_start",
                                        "tool": part.tool_name,
                                        "tool_call_id": part.tool_call_id,
                                    }
                                )
                            async with node.stream(run.ctx) as stream:
                                async for event in stream:
                                    if isinstance(event, FunctionToolResultEvent):
                                        result = event.result
                                        payload = result.content
                                        if isinstance(payload, str):
                                            try:
                                                payload = json.loads(payload)
                                            except (ValueError, TypeError):
                                                payload = None
                                        if isinstance(payload, dict):
                                            evidence.append(
                                                {"tool": result.tool_name, "result": payload}
                                            )
                                            if (
                                                len(json.dumps(evidence, default=str).encode())
                                                > 196608
                                            ):
                                                raise ValueError("Evidence exceeds turn limit")
                                            for artifact in render_mcp_artifacts(
                                                result.tool_name,
                                                result.tool_call_id,
                                                payload,
                                                created_at=datetime.now(timezone.utc).isoformat(),
                                            ):
                                                if len(artifacts) >= 3:
                                                    break
                                                artifacts.append(artifact)
                                                yield _sse(
                                                    {
                                                        "type": "artifact_updated",
                                                        "artifact": artifact,
                                                    }
                                                )
                                        yield _sse(
                                            {
                                                "type": "tool_call_result",
                                                "tool_call_id": result.tool_call_id,
                                                "tool": result.tool_name,
                                            }
                                        )
                    total_tokens = run.usage().total_tokens
        if not await _authorize_tools(db, context):
            raise PermissionError("Chat access is no longer active")
        if not assistant_message and not artifacts:
            raise ValueError("The model returned no answer")
        metadata = {
            "total_tokens": total_tokens,
            "prompt_version": CHAT_PROMPT_VERSION,
            "evidence": evidence,
            "clarification_required": bool(missing),
            "required_bindings": missing,
        }
        if artifacts:
            metadata["artifacts"] = artifacts
        await repository.finish_turn(
            db,
            conversation_id,
            user_id,
            organization_id,
            message_id,
            "complete",
            assistant_message or "I added the requested view below.",
            metadata,
        )
        await db.commit()
        finished = True
        yield _sse({"type": "done"})
    except (asyncio.CancelledError, GeneratorExit):
        failure_status = "cancelled"
        raise
    except Exception as exc:
        # Free-form provider/database errors may contain secrets or retrieved text.
        logger.warning("Chat turn failed (%s)", type(exc).__name__)
        yield _sse(
            {
                "type": "error",
                "error": "Chat could not complete this turn. Reload the conversation before trying again.",
                "code": "turn_failed",
            }
        )
    finally:
        if not finished:
            with anyio.CancelScope(shield=True):
                try:
                    await db.rollback()
                    await repository.finish_turn(
                        db, conversation_id, user_id, organization_id, message_id, failure_status
                    )
                    await db.commit()
                except Exception as exc:
                    await db.rollback()
                    logger.warning("Chat cleanup failed (%s)", type(exc).__name__)
