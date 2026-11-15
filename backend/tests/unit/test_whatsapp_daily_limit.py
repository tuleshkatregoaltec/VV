"""Per-contact daily automatic-reply limit: never silent, never charged to personal receipts.

Runs the real queue and repository against in-memory SQLite (no Postgres needed).
"""

import logging

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.whatsapp import customer_queue as queue
from app.whatsapp.customer_models import (
    WhatsAppConnection,
    WhatsAppContact,
    WhatsAppCustomerMessage,
    WhatsAppCustomerThread,
)
from app.whatsapp.models import utcnow

SENDER = "971500000001"
BODY = "Is the 2 bedroom in Marina still available? my secret code is 4417"
TABLES = (WhatsAppConnection, WhatsAppContact, WhatsAppCustomerThread, WhatsAppCustomerMessage)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync: SQLModel.metadata.create_all(sync, tables=[t.__table__ for t in TABLES])
        )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


async def seed(db, *, status, count=settings.WHATSAPP_MAX_DAILY_TURNS, topic=None):
    connection = WhatsAppConnection(
        user_id="u",
        organization_id="o",
        phone_number_id="p1",
        account_id="w1",
        display_name="Agent",
        access_token_encrypted="x",
        enabled=True,
    )
    db.add(connection)
    await db.flush()
    thread = WhatsAppCustomerThread(connection_id=connection.id, sender=SENDER)
    db.add(thread)
    await db.flush()
    for index in range(count):
        db.add(
            WhatsAppCustomerMessage(
                id=f"old.{index}",
                thread_id=thread.id,
                status=status,
                topic=topic,
                sent_at=utcnow(),
            )
        )
    await db.commit()
    return connection, thread


def incoming(message_id="wamid.new"):
    return [
        {
            "id": message_id,
            "from": SENDER,
            "type": "text",
            "text": {"body": BODY},
            "timestamp": str(int(utcnow().timestamp())),
        }
    ]


async def test_message_over_the_daily_limit_reaches_the_agent_without_its_text(db, caplog):
    connection, thread = await seed(db, status="sent", topic="real_estate")
    caplog.set_level(logging.INFO)
    jobs = await queue.enqueue(db, connection, incoming(), settings)
    await db.commit()
    assert jobs == []
    row = await db.get(WhatsAppCustomerMessage, "wamid.new")
    assert row is not None
    assert row.status == "approval_required"
    assert row.topic == "unprocessed"
    assert row.content is None and row.reply is None
    assert row.notification_created_at is not None
    assert "limit" in row.handoff_summary and "reply yourself" in row.handoff_summary
    await db.refresh(thread)
    assert thread.paused is True
    assert BODY not in caplog.text and "4417" not in caplog.text
    assert "daily" in caplog.text.lower()


async def test_personal_receipts_do_not_use_up_the_daily_allowance(db):
    connection, _ = await seed(db, status="ignored")
    jobs = await queue.enqueue(db, connection, incoming(), settings)
    await db.commit()
    assert [job.message_id for job in jobs] == ["wamid.new"]
    row = await db.get(WhatsAppCustomerMessage, "wamid.new")
    assert row.status == "classifying"
    assert len((await db.exec(select(WhatsAppCustomerMessage))).all()) == 21


async def test_customer_lane_cap_follows_the_shared_daily_setting(db):
    custom = settings.model_copy(update={"WHATSAPP_MAX_DAILY_TURNS": 5})
    connection, _ = await seed(db, status="sent", count=5, topic="real_estate")
    jobs = await queue.enqueue(db, connection, incoming(), custom)
    await db.commit()
    assert jobs == []
    assert (await db.get(WhatsAppCustomerMessage, "wamid.new")).topic == "unprocessed"


async def test_customer_lane_admits_below_the_configured_cap(db):
    custom = settings.model_copy(update={"WHATSAPP_MAX_DAILY_TURNS": 30})
    connection, _ = await seed(db, status="sent", count=25, topic="real_estate")
    jobs = await queue.enqueue(db, connection, incoming(), custom)
    assert [job.message_id for job in jobs] == ["wamid.new"]


def test_the_shared_daily_cap_defaults_to_twenty():
    assert settings.model_fields["WHATSAPP_MAX_DAILY_TURNS"].default == 20
