from datetime import datetime, timezone

from sqlalchemy import delete, func, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.assistant.models import (
    CrmAssistantAction,
    CrmAssistantConversation,
    CrmAssistantMessage,
)

# Every statement is scoped to the trusted (user, organization) pair from AuthContext. A user
# who moves to another organization keeps the same user_id, so user_id alone is not a boundary.


def _owned_conversation_ids(conversation_id: int, user_id: str, organization_id: str):
    return select(CrmAssistantConversation.id).where(
        CrmAssistantConversation.id == conversation_id,
        CrmAssistantConversation.user_id == user_id,
        CrmAssistantConversation.organization_id == organization_id,
    )


def save(db: AsyncSession, record):
    db.add(record)


async def list_conversations(
    db: AsyncSession, user_id: str, organization_id: str, limit: int = 50, offset: int = 0
) -> list[CrmAssistantConversation]:
    result = await db.exec(
        select(CrmAssistantConversation)
        .where(
            CrmAssistantConversation.user_id == user_id,
            CrmAssistantConversation.organization_id == organization_id,
        )
        .order_by(CrmAssistantConversation.updated_at.desc(), CrmAssistantConversation.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.all())


async def count_conversations(db: AsyncSession, user_id: str, organization_id: str) -> int:
    result = await db.exec(
        select(func.count())
        .select_from(CrmAssistantConversation)
        .where(
            CrmAssistantConversation.user_id == user_id,
            CrmAssistantConversation.organization_id == organization_id,
        )
    )
    return result.one()


async def get_conversation(
    db: AsyncSession, conversation_id: int, user_id: str, organization_id: str
) -> CrmAssistantConversation | None:
    result = await db.exec(
        select(CrmAssistantConversation).where(
            CrmAssistantConversation.id == conversation_id,
            CrmAssistantConversation.user_id == user_id,
            CrmAssistantConversation.organization_id == organization_id,
        )
    )
    return result.first()


async def list_messages(
    db: AsyncSession,
    conversation_id: int,
    user_id: str,
    organization_id: str,
    limit: int = 100,
    offset: int = 0,
) -> list[CrmAssistantMessage]:
    result = await db.exec(
        select(CrmAssistantMessage)
        .where(
            CrmAssistantMessage.conversation_id.in_(
                _owned_conversation_ids(conversation_id, user_id, organization_id)
            )
        )
        .order_by(CrmAssistantMessage.created_at.desc(), CrmAssistantMessage.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(reversed(result.all()))


async def delete_conversation_records(
    db: AsyncSession, conversation_id: int, user_id: str, organization_id: str
):
    # Messages are deleted only through the owned-conversation predicate, never by ID alone.
    await db.execute(
        delete(CrmAssistantMessage)
        .where(
            CrmAssistantMessage.conversation_id.in_(
                _owned_conversation_ids(conversation_id, user_id, organization_id)
            )
        )
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        delete(CrmAssistantConversation)
        .where(
            CrmAssistantConversation.id == conversation_id,
            CrmAssistantConversation.user_id == user_id,
            CrmAssistantConversation.organization_id == organization_id,
        )
        .execution_options(synchronize_session=False)
    )


async def get_action(
    db: AsyncSession, action_id: str, user_id: str, organization_id: str
) -> CrmAssistantAction | None:
    result = await db.exec(
        select(CrmAssistantAction).where(
            CrmAssistantAction.id == action_id,
            CrmAssistantAction.user_id == user_id,
            CrmAssistantAction.organization_id == organization_id,
        )
    )
    return result.first()


async def get_actions_by_ids(
    db: AsyncSession, action_ids: list[str], user_id: str, organization_id: str
) -> list[CrmAssistantAction]:
    if not action_ids:
        return []
    result = await db.exec(
        select(CrmAssistantAction).where(
            CrmAssistantAction.id.in_(action_ids),
            CrmAssistantAction.user_id == user_id,
            CrmAssistantAction.organization_id == organization_id,
        )
    )
    return list(result.all())


async def claim_action(db: AsyncSession, action_id: str) -> bool:
    """Move a pending action to confirmed; False when another request already resolved it."""
    result = await db.execute(
        update(CrmAssistantAction)
        .where(CrmAssistantAction.id == action_id, CrmAssistantAction.status == "pending")
        .values(status="confirmed", resolved_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


async def resolve_pending_action(db: AsyncSession, action_id: str, status: str) -> bool:
    """Cancel or expire only if no confirmation has claimed this action."""
    result = await db.execute(
        update(CrmAssistantAction)
        .where(CrmAssistantAction.id == action_id, CrmAssistantAction.status == "pending")
        .values(status=status, resolved_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1
