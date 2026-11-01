from typing import List, Optional

from sqlalchemy import delete, func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.chat.models import ChatTurnLease, Conversation, Message

# Every statement is scoped to the trusted (user, organization) pair from AuthContext. A user
# who moves to another organization keeps the same user_id, so user_id alone is not a boundary.


def _owned_conversation_ids(conversation_id: int, user_id: str, organization_id: str):
    return select(Conversation.id).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user_id,
        Conversation.organization_id == organization_id,
    )


async def get_user_conversations(
    db: AsyncSession, user_id: str, organization_id: str, limit: int = 50, offset: int = 0
) -> List[Conversation]:
    """Get the user's conversations in the current organization"""
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.organization_id == organization_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.exec(stmt)
    return list(result.all())


async def get_conversation(
    db: AsyncSession, conversation_id: int, user_id: str, organization_id: str
) -> Optional[Conversation]:
    """Get a conversation by ID (with auth check)"""
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user_id,
        Conversation.organization_id == organization_id,
    )
    result = await db.exec(stmt)
    return result.first()


async def get_conversation_messages(
    db: AsyncSession,
    conversation_id: int,
    user_id: str,
    organization_id: str,
    limit: int = 100,
    before_id: int | None = None,
) -> List[Message]:
    """Get messages for a conversation the caller owns"""
    stmt = (
        select(Message)
        .where(
            Message.conversation_id.in_(
                _owned_conversation_ids(conversation_id, user_id, organization_id)
            )
        )
        .where(Message.id < before_id if before_id is not None else True)
        .order_by(Message.id.desc())
        .limit(limit)
    )
    result = await db.exec(stmt)
    return list(reversed(result.all()))


def save_conversation(db: AsyncSession, conversation: Conversation):
    db.add(conversation)


def save_message(db: AsyncSession, message: Message):
    db.add(message)


async def lock_turn_admission(db, user_id, organization_id):
    for key in (f"chat:tenant:{organization_id}", f"chat:user:{user_id}"):
        await db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


async def active_turn_count(db, field, value, now):
    return (
        await db.exec(
            select(func.count())
            .select_from(ChatTurnLease)
            .where(
                ChatTurnLease.status == "active",
                ChatTurnLease.expires_at > now,
                getattr(ChatTurnLease, field) == value,
            )
        )
    ).one()


async def locked_turn_lease(db, lease_id):
    return (
        await db.exec(
            select(ChatTurnLease)
            .where(ChatTurnLease.id == lease_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()


async def delete_conversation_records(
    db: AsyncSession, conversation_id: int, user_id: str, organization_id: str
):
    # Messages are deleted only through the owned-conversation predicate, never by ID alone.
    await db.execute(
        delete(Message)
        .where(
            Message.conversation_id.in_(
                _owned_conversation_ids(conversation_id, user_id, organization_id)
            )
        )
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        delete(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.organization_id == organization_id,
        )
        .execution_options(synchronize_session=False)
    )
