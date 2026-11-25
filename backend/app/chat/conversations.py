"""Conversation storage shared by every chat product (CRM Operations Assistant, Market AI and
the WhatsApp pilot): create, list, rename, delete and append, always scoped to the owner."""

from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from app.chat import repository
from app.chat.models import Conversation, Message


async def create_conversation(
    db: AsyncSession,
    user_id: str,
    organization_id: str,
    title: Optional[str] = None,
    assistant: str = "crm",
) -> Conversation:
    """Create a new conversation in one assistant's history (CRM unless stated)."""
    now = datetime.now(timezone.utc)
    conversation = Conversation(
        user_id=user_id,
        organization_id=organization_id,
        title=title or "New Conversation",
        assistant=assistant,
        created_at=now,
        updated_at=now,
    )
    repository.save_conversation(db, conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def get_user_conversations(
    db: AsyncSession,
    user_id: str,
    organization_id: str,
    limit: int = 50,
    offset: int = 0,
    assistant: str = "crm",
) -> List[Conversation]:
    return await repository.get_user_conversations(
        db, user_id, organization_id, limit, offset, assistant=assistant
    )


async def get_conversation(
    db: AsyncSession,
    conversation_id: int,
    user_id: str,
    organization_id: str,
    assistant: str | None = None,
) -> Optional[Conversation]:
    """The owner's conversation; with `assistant`, only if it belongs to that assistant."""
    return await repository.get_conversation(
        db, conversation_id, user_id, organization_id, assistant=assistant
    )


async def update_conversation(
    db: AsyncSession,
    conversation_id: int,
    user_id: str,
    organization_id: str,
    title: str,
    assistant: str = "crm",
) -> Optional[Conversation]:
    """Update a conversation's title"""
    conversation = await get_conversation(
        db, conversation_id, user_id, organization_id, assistant=assistant
    )
    if not conversation:
        return None

    conversation.title = title
    conversation.updated_at = datetime.now(timezone.utc)
    repository.save_conversation(db, conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def delete_conversation(
    db: AsyncSession,
    conversation_id: int,
    user_id: str,
    organization_id: str,
    assistant: str = "crm",
) -> bool:
    """Delete a conversation and all its messages"""
    conversation = await get_conversation(
        db, conversation_id, user_id, organization_id, assistant=assistant
    )
    if not conversation:
        return False

    await repository.delete_conversation_records(db, conversation_id, user_id, organization_id)
    await db.commit()
    return True


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
