import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, List, Optional

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    UserPromptPart,
    TextPart,
)
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from pydantic_ai.models.openrouter import OpenRouterModelSettings

from app.chat.agent import agent
from app.chat.models import Conversation, Message
from app.token_usage.service import token_usage_service

logger = logging.getLogger(__name__)


async def create_conversation(
    db: AsyncSession, user_id: str, title: Optional[str] = None
) -> Conversation:
    """Create a new conversation"""
    now = datetime.now(timezone.utc)
    conversation = Conversation(
        user_id=user_id,
        title=title or "New Conversation",
        created_at=now,
        updated_at=now,
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def get_user_conversations(
    db: AsyncSession, user_id: str, limit: int = 50, offset: int = 0
) -> List[Conversation]:
    """Get all conversations for a user"""
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.exec(stmt)
    return list(result.all())


async def get_conversation(
    db: AsyncSession, conversation_id: int, user_id: str
) -> Optional[Conversation]:
    """Get a conversation by ID (with auth check)"""
    stmt = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user_id
    )
    result = await db.exec(stmt)
    return result.first()


async def update_conversation(
    db: AsyncSession, conversation_id: int, user_id: str, title: str
) -> Optional[Conversation]:
    """Update a conversation's title"""
    conversation = await get_conversation(db, conversation_id, user_id)
    if not conversation:
        return None

    conversation.title = title
    conversation.updated_at = datetime.now(timezone.utc)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def delete_conversation(
    db: AsyncSession, conversation_id: int, user_id: str
) -> bool:
    """Delete a conversation and all its messages"""
    conversation = await get_conversation(db, conversation_id, user_id)
    if not conversation:
        return False

    await db.delete(conversation)
    await db.commit()
    return True


async def get_conversation_messages(
    db: AsyncSession, conversation_id: int, limit: int = 100
) -> List[Message]:
    """Get messages for a conversation"""
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .limit(limit)
    )
    result = await db.exec(stmt)
    return list(result.all())


async def add_message(
    db: AsyncSession,
    conversation_id: int,
    role: str,
    content: str,
    meta_data: Optional[dict[str, Any]] = None,
) -> Message:
    """Add a message to a conversation"""
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        meta_data=meta_data or {},
        created_at=datetime.now(timezone.utc),
    )
    db.add(message)

    # Update conversation timestamp
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    result = await db.exec(stmt)
    conversation = result.first()
    if conversation:
        conversation.updated_at = datetime.now(timezone.utc)
        # Auto-generate title from first user message
        if not conversation.title or conversation.title == "New Conversation":
            conversation.title = content[:50] + ("..." if len(content) > 50 else "")

    await db.commit()
    await db.refresh(message)
    return message


def _convert_to_pydantic_messages(messages: List[Message]) -> List[ModelMessage]:
    """Convert database messages to Pydantic AI message format"""
    pydantic_messages: List[ModelMessage] = []

    for msg in messages:
        if msg.role == "user":
            pydantic_messages.append(
                ModelRequest(parts=[UserPromptPart(content=msg.content)])
            )
        elif msg.role == "assistant":
            pydantic_messages.append(
                ModelResponse(parts=[TextPart(content=msg.content)])
            )

    return pydantic_messages


async def stream_chat_response(
    db: AsyncSession,
    conversation_id: int,
    user_message: str,
    user_id: str,
    organization_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Stream chat response using Pydantic AI agent via SSE"""
    # Verify conversation ownership
    conversation = await get_conversation(db, conversation_id, user_id)
    if not conversation:
        yield f"data: {json.dumps({'type': 'error', 'error': 'Conversation not found'})}\n\n"
        return

    # Save user message
    await add_message(db, conversation_id, "user", user_message)

    # Get conversation history
    messages = await get_conversation_messages(db, conversation_id)
    message_history = _convert_to_pydantic_messages(
        messages[:-1]
    )  # Exclude the just-added message

    assistant_message = ""
    total_tokens = 0

    try:
        # Stream agent response with native reasoning
        async with agent.run_stream(
            user_message,
            message_history=message_history,
            model_settings=OpenRouterModelSettings(
                openrouter_reasoning={"effort": "low"}
            ),
        ) as result:
            yield f"data: {json.dumps({'type': 'thinking'})}\n\n"
            async for chunk_text in result.stream_text(delta=True, debounce_by=0.01):
                assistant_message += chunk_text
                yield f"data: {json.dumps({'type': 'content', 'content': chunk_text})}\n\n"

            # Track token usage (if available in result)
            if hasattr(result, "usage") and result.usage():
                usage = result.usage()
                if usage:
                    total_tokens = getattr(usage, "total_tokens", 0)
                    prompt_tokens = getattr(usage, "request_tokens", 0)
                    completion_tokens = getattr(usage, "response_tokens", 0)

                    logger.info(
                        f"Token usage: prompt={prompt_tokens}, "
                        f"completion={completion_tokens}, "
                        f"total={total_tokens}"
                    )

                    await token_usage_service.record_usage(
                        db=db,
                        user_id=user_id,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                    )

        # Save assistant message with metadata
        if assistant_message:
            meta_data = {}
            if total_tokens:
                meta_data["total_tokens"] = total_tokens

            await add_message(
                db, conversation_id, "assistant", assistant_message, meta_data
            )

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except Exception as e:
        logger.exception("Error during chat streaming")
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
