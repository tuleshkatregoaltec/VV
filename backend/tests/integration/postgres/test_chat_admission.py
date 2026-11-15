"""Real transactions prove cross-worker capacity and accounting, without models."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic_ai.usage import RunUsage
from sqlalchemy import func
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.chat import admission
from app.config import settings
from app.token_usage import repository
from app.token_usage.models import UserTokenUsage
from app.token_usage.service import token_usage_service


@pytest.fixture
async def admission_engine(postgres_test_url):
    engine = create_async_engine(postgres_test_url)
    yield engine
    await engine.dispose()


async def reserve(engine, user, org, conversation, limit=500000):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        return await admission.reserve(
            db,
            user_id=user,
            organization_id=org,
            conversation_id=conversation,
            daily_limit=limit,
        )


async def usage_total(engine, user):
    async with AsyncSession(engine) as db:
        row = await repository.get_usage(db, user, datetime.now(timezone.utc).date())
        return row.total_tokens


async def test_concurrent_same_user_cannot_reserve_multiple_turns(admission_engine):
    user, org = str(uuid4()), str(uuid4())
    results = await asyncio.gather(
        *(reserve(admission_engine, user, org, index + 1000) for index in range(12)),
        return_exceptions=True,
    )
    assert sum(isinstance(item, admission.TurnLease) for item in results) == 1
    assert all(
        isinstance(item, admission.TurnLease)
        or isinstance(item, HTTPException)
        and item.status_code == 429
        for item in results
    )
    assert await usage_total(admission_engine, user) == settings.ASSISTANT_TURN_TOKEN_LIMIT


async def test_tenant_capacity_and_same_conversation_are_shared_across_workers(
    admission_engine, monkeypatch
):
    monkeypatch.setattr(admission, "TENANT_CONCURRENCY", 2)
    org = str(uuid4())
    users = [str(uuid4()) for _ in range(3)]
    first = await reserve(admission_engine, users[0], org, 2000)
    with pytest.raises(HTTPException, match="Another assistant turn"):
        await reserve(admission_engine, users[1], org, 2000)
    await reserve(admission_engine, users[1], org, 2001)
    with pytest.raises(HTTPException, match="Another assistant turn"):
        await reserve(admission_engine, users[2], org, 2002)
    async with AsyncSession(admission_engine) as db:
        await admission.settle(db, first.id, RunUsage(input_tokens=100), successful=True)
    assert await reserve(admission_engine, users[2], org, 2002)


async def test_success_refunds_unused_allowance_once_then_budget_blocks(admission_engine):
    user, org = str(uuid4()), str(uuid4())
    limit = settings.ASSISTANT_TURN_MIN_TOKENS + 1000
    lease = await reserve(admission_engine, user, org, 3000, limit=limit)
    assert lease.token_budget == limit  # capped by the remaining daily allowance
    for _ in range(2):
        async with AsyncSession(admission_engine) as db:
            await admission.settle(
                db, lease.id, RunUsage(input_tokens=1000, output_tokens=500), successful=True
            )
    assert await usage_total(admission_engine, user) == 1500
    with pytest.raises(HTTPException, match="Insufficient daily"):
        await reserve(admission_engine, user, org, 3001, limit=limit)
    assert await usage_total(admission_engine, user) == 1500


async def test_failure_charges_only_observed_usage_and_releases_capacity(admission_engine):
    user, org = str(uuid4()), str(uuid4())
    lease = await reserve(admission_engine, user, org, 4000)
    async with AsyncSession(admission_engine) as db:
        await admission.settle(db, lease.id, RunUsage(input_tokens=123), successful=False)
        row = await db.get(admission.ChatTurnLease, lease.id)
        assert row.status == "failed"
    assert await usage_total(admission_engine, user) == 123
    next_lease = await reserve(admission_engine, user, org, 4000)
    async with AsyncSession(admission_engine) as db:
        await admission.settle(db, next_lease.id, RunUsage(input_tokens=25000), successful=False)
    assert await usage_total(admission_engine, user) == 123 + 25000


async def test_expired_process_lease_frees_capacity_but_never_budget(admission_engine):
    user, org = str(uuid4()), str(uuid4())
    lease_id = (await reserve(admission_engine, user, org, 5000, limit=24000)).id
    async with AsyncSession(admission_engine) as db:
        lease = await db.get(admission.ChatTurnLease, lease_id)
        lease.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    with pytest.raises(HTTPException, match="Insufficient daily"):
        await reserve(admission_engine, user, org, 5000, limit=24000)
    # A late finalizer still knows the observed usage and settles to it.
    async with AsyncSession(admission_engine) as db:
        await admission.settle(db, lease_id, RunUsage(input_tokens=10), successful=True)
    assert await usage_total(admission_engine, user) == 10
    assert await reserve(admission_engine, user, org, 5000, limit=48000)


async def test_all_usage_writers_increment_atomically_without_lost_charges(admission_engine):
    user = str(uuid4())

    async def write():
        async with AsyncSession(admission_engine) as db:
            await token_usage_service.record_usage(db, user, 3, 7, 10)

    await asyncio.gather(*(write() for _ in range(25)))
    assert await usage_total(admission_engine, user) == 250
    async with AsyncSession(admission_engine) as db:
        count = (
            await db.exec(
                select(func.count())
                .select_from(UserTokenUsage)
                .where(UserTokenUsage.user_id == user)
            )
        ).one()
        assert count == 1


async def test_migration_preserves_duplicate_history_and_sums_new_ledger(admission_engine):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    path = Path(__file__).parents[3] / "migrations/versions/9b5d2f7a1e04_chat_admission.py"
    spec = importlib.util.spec_from_file_location("admission_migration_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = "admission_migration_" + uuid4().hex

    def upgrade(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

    async with admission_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        await connection.execute(
            text("CREATE TABLE user_token_usage (LIKE public.user_token_usage INCLUDING ALL)")
        )
        await connection.execute(
            text("""INSERT INTO user_token_usage
            (user_id,date,prompt_tokens,completion_tokens,total_tokens,created_at,updated_at)
            VALUES ('history',CURRENT_DATE,10,20,30,now(),now()),
                   ('history',CURRENT_DATE,3,4,7,now(),now())""")
        )
        await connection.run_sync(upgrade)
        assert (
            await connection.execute(text("SELECT count(*) FROM user_token_usage"))
        ).scalar_one() == 2
        rows = (
            await connection.execute(
                text(
                    "SELECT prompt_tokens, completion_tokens, total_tokens FROM user_token_usage_totals"
                )
            )
        ).all()
        assert rows == [(13, 24, 37)]
