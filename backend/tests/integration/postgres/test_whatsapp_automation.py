import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.whatsapp import automation, repository
from app.whatsapp.models import WhatsAppTurn, utcnow


def config():
    return settings.model_copy(
        update={
            "WHATSAPP_DEMO_ENABLED": True,
            "WHATSAPP_AUTOMATION_ENABLED": True,
            "WHATSAPP_PHONE_NUMBER_ID": "123",
            "WHATSAPP_TEST_RECIPIENT": "919000000000",
            "WHATSAPP_PILOT_USER_ID": str(uuid4()),
            "WHATSAPP_PILOT_ORGANIZATION_ID": str(uuid4()),
            "WHATSAPP_MAX_DAILY_TURNS": 2,
        }
    )


def turn(c, **kwargs):
    return WhatsAppTurn(
        id=str(uuid4()),
        phone_number_id=c.WHATSAPP_PHONE_NUMBER_ID,
        sender=c.WHATSAPP_TEST_RECIPIENT,
        user_id=c.WHATSAPP_PILOT_USER_ID,
        organization_id=c.WHATSAPP_PILOT_ORGANIZATION_ID,
        content="coverage",
        sent_at=utcnow(),
        **kwargs,
    )


async def test_committed_receipt_is_deduplicated_and_daily_work_is_bounded(pg_session):
    c = config()
    first = turn(c)
    assert await repository.enqueue(pg_session, [first, first], c) == 1
    assert await repository.enqueue(pg_session, [first], c) == 0
    assert await repository.enqueue(pg_session, [turn(c), turn(c)], c) == 1
    rows = (await pg_session.exec(select(WhatsAppTurn).where(*repository.scope(c)))).all()
    assert len(rows) == 2


async def test_worker_claim_prevents_concurrent_processing_and_wrong_scope(pg_session):
    c = config()
    await repository.enqueue(pg_session, [turn(c), turn(c)], c)
    assert await repository.claim(pg_session, config()) is None
    first = await repository.claim(pg_session, c)
    assert first.status == "processing"
    assert await repository.claim(pg_session, c) is None
    await repository.save(pg_session, first, "accepted")
    second = await repository.claim(pg_session, c)
    assert second.id != first.id


async def test_lost_worker_is_not_replayed_after_possible_provider_side_effect(pg_session):
    c = config()
    first = turn(c, status="sending", updated_at=utcnow() - timedelta(minutes=11))
    pg_session.add(first)
    await pg_session.commit()
    assert await repository.claim(pg_session, c) is None
    await pg_session.refresh(first)
    assert first.status == "unknown"
    assert first.error_code == "worker_lost"


async def test_timeout_is_durable_unknown_and_never_automatically_resent(pg_session, monkeypatch):
    c = config()
    first = turn(c, status="processing", reply="Stored answer")
    pg_session.add(first)
    await pg_session.commit()
    monkeypatch.setattr(automation, "channel_access", AsyncMock(return_value=True))
    send = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
    monkeypatch.setattr(automation, "send_reply", send)
    await automation.process(pg_session, first, c)
    await pg_session.refresh(first)
    assert first.status == "unknown"
    assert await repository.claim(pg_session, c) is None
    send.assert_awaited_once()


async def test_separate_worker_sessions_cannot_claim_same_pilot_simultaneously(pg_session):
    c = config()
    await repository.enqueue(pg_session, [turn(c), turn(c)], c)

    async def claim():
        async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
            return await repository.claim(db, c)

    results = await asyncio.gather(claim(), claim())
    assert sum(result is not None for result in results) == 1
