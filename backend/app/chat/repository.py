from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.chat.models import Conversation, Message

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
    db: AsyncSession, conversation_id: int, user_id: str, organization_id: str, limit: int = 100
) -> List[Message]:
    """Get messages for a conversation the caller owns"""
    stmt = (
        select(Message)
        .where(
            Message.conversation_id.in_(
                _owned_conversation_ids(conversation_id, user_id, organization_id)
            )
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    result = await db.exec(stmt)
    return list(reversed(result.all()))


def save_conversation(db: AsyncSession, conversation: Conversation):
    db.add(conversation)


def save_message(db: AsyncSession, message: Message):
    db.add(message)


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


async def claim_turn(
    db: AsyncSession,
    conversation_id: int,
    user_id: str,
    organization_id: str,
    request_id: str,
    content: str,
) -> tuple[str, Message | None]:
    """Serialize claims across workers and retain request identities after disconnects.

    The conversation lock protects both the duplicate lookup and message insert. Existing
    JSON metadata holds the small turn ledger so historical message schemas remain valid.
    """
    result = await db.exec(
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.organization_id == organization_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    conversation = result.first()
    if conversation is None:
        return "missing", None
    existing = (
        await db.exec(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.role == "user",
                Message.meta_data["request_id"].as_string() == request_id,
            )
        )
    ).first()
    if existing is not None:
        if existing.content != content:
            return "conflict", existing
        status = (existing.meta_data or {}).get("turn_status", "interrupted")
        created = existing.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if status == "running" and created <= datetime.now(timezone.utc) - timedelta(seconds=300):
            status = "interrupted"
            existing.meta_data = {**(existing.meta_data or {}), "turn_status": status}
            db.add(existing)
        return status, existing
    running = (
        await db.exec(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.role == "user",
                Message.meta_data["turn_status"].as_string() == "running",
            )
        )
    ).all()
    now = datetime.now(timezone.utc)
    for message in running:
        created = message.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        # The runtime deadline is 180 seconds; reserve an additional cleanup margin.
        if created > now - timedelta(seconds=300):
            return "busy", None
        message.meta_data = {**(message.meta_data or {}), "turn_status": "interrupted"}
        db.add(message)
    message = Message(
        conversation_id=conversation_id,
        role="user",
        content=content,
        created_at=now,
        meta_data={"request_id": request_id, "turn_status": "running"},
    )
    db.add(message)
    conversation.updated_at = now
    if not conversation.title or conversation.title == "New Conversation":
        conversation.title = content[:50] + ("..." if len(content) > 50 else "")
    db.add(conversation)
    await db.flush()
    return "claimed", message


async def finish_turn(
    db: AsyncSession,
    conversation_id: int,
    user_id: str,
    organization_id: str,
    message_id: int,
    status: str,
    content: str = "",
    metadata: dict[str, Any] | None = None,
) -> Message | None:
    owned = (
        await db.exec(
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.organization_id == organization_id,
            )
            .with_for_update()
        )
    ).first()
    if owned is None:
        raise LookupError("Conversation not found")
    message = (
        await db.exec(
            select(Message)
            .where(
                Message.id == message_id,
                Message.conversation_id == conversation_id,
                Message.role == "user",
            )
            .execution_options(populate_existing=True)
        )
    ).first()
    if message is None or (message.meta_data or {}).get("turn_status") != "running":
        raise LookupError("Turn is no longer active")
    assistant = None
    if status == "complete":
        assistant = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            meta_data={**(metadata or {}), "request_id": message.meta_data["request_id"]},
            created_at=datetime.now(timezone.utc),
        )
        db.add(assistant)
        await db.flush()
    message.meta_data = {
        **(message.meta_data or {}),
        "turn_status": status,
        "assistant_message_id": assistant.id if assistant else None,
    }
    db.add(message)
    owned.updated_at = datetime.now(timezone.utc)
    db.add(owned)
    return assistant


async def replay_turn(db: AsyncSession, message: Message) -> Message | None:
    assistant_id = (message.meta_data or {}).get("assistant_message_id")
    return (
        await db.exec(
            select(Message).where(
                Message.id == assistant_id,
                Message.conversation_id == message.conversation_id,
                Message.role == "assistant",
            )
        )
    ).first()
