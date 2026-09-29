from typing import List, Optional

from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.chat.models import Conversation, Message


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


async def get_conversation_for_message(db: AsyncSession, conversation_id: int):
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    result = await db.exec(stmt)
    return result.first()


def save_conversation(db: AsyncSession, conversation: Conversation):
    db.add(conversation)


def save_message(db: AsyncSession, message: Message):
    db.add(message)


async def delete_conversation_records(db: AsyncSession, conversation_id: int, user_id: str):
    await db.execute(
        delete(Message)
        .where(Message.conversation_id == conversation_id)
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        delete(Conversation)
        .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .execution_options(synchronize_session=False)
    )
