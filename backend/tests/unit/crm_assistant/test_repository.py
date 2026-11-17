"""History stays reachable and concurrent requests cannot relabel an executed action."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.assistant import actions, repository, service
from app.crm.assistant.models import (
    CrmAssistantAction,
    CrmAssistantConversation,
    CrmAssistantMessage,
)

from .assistant_helpers import make_deps


@pytest.fixture
async def engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'assistant.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(
            SQLModel.metadata.create_all,
            tables=[
                CrmAssistantConversation.__table__,
                CrmAssistantMessage.__table__,
                CrmAssistantAction.__table__,
            ],
        )
    yield engine
    await engine.dispose()


async def test_recent_window_pages_back_without_losing_latest_turn(engine):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        chat = await service.create_conversation(db, "user-1", "org-a")
        # Equal timestamps exercise the deterministic ID tie breaker.
        now = datetime.now(timezone.utc)
        for i in range(202):
            db.add(
                CrmAssistantMessage(
                    conversation_id=chat.id, role="user", content=str(i), created_at=now
                )
            )
        await db.commit()
        recent = await repository.list_messages(db, chat.id, "user-1", "org-a", 100)
        assert [int(m.content) for m in recent] == list(range(102, 202))
        previous = await repository.list_messages(db, chat.id, "user-1", "org-a", 100, 100)
        assert [int(m.content) for m in previous] == list(range(2, 102))
        assert await repository.list_messages(db, chat.id, "other", "org-a") == []


async def test_conversation_count_includes_older_pages_and_is_scoped(engine):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        now = datetime.now(timezone.utc)
        for i in range(51):
            db.add(
                CrmAssistantConversation(
                    user_id="user-1",
                    organization_id="org-a",
                    title=str(i),
                    created_at=now,
                    updated_at=now,
                )
            )
        db.add(
            CrmAssistantConversation(
                user_id="other",
                organization_id="org-a",
                title="Private",
                created_at=now,
                updated_at=now,
            )
        )
        await db.commit()
        assert await repository.count_conversations(db, "user-1", "org-a") == 51
        first = await repository.list_conversations(db, "user-1", "org-a", 50)
        [last] = await repository.list_conversations(db, "user-1", "org-a", 50, 50)
        assert last.id not in {row.id for row in first}


@pytest.mark.parametrize("expired", [False, True])
async def test_cancel_and_expiry_cannot_overwrite_a_concurrent_confirmation(
    engine, monkeypatch, expired
):
    now = datetime.now(timezone.utc)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db.add(
            CrmAssistantAction(
                id="race",
                user_id="user-1",
                organization_id="org-a",
                enquiry_id=1,
                action_type="status",
                summary="Move lead",
                created_at=now,
                expires_at=now + timedelta(minutes=-1 if expired else 5),
            )
        )
        await db.commit()
    get_action = repository.get_action

    async def read_then_confirm(db, *args):
        stale = await get_action(db, *args)
        async with AsyncSession(engine) as confirming:
            assert await repository.claim_action(confirming, "race")
            await confirming.commit()
        return stale

    monkeypatch.setattr(repository, "get_action", read_then_confirm)
    async with AsyncSession(engine, expire_on_commit=False) as cancelling:
        with pytest.raises(HTTPException) as error:
            await actions.cancel_action(make_deps(db=cancelling), action_id="race")
        assert (error.value.status_code, error.value.detail) == (409, "Action already confirmed")
    async with AsyncSession(engine) as check:
        assert (await get_action(check, "race", "user-1", "org-a")).status == "confirmed"
