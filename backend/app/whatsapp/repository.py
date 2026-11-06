from datetime import timedelta

from sqlalchemy import func, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import select

from app.whatsapp.models import WhatsAppTurn, utcnow


def scope(config):
    return (
        WhatsAppTurn.phone_number_id == config.WHATSAPP_PHONE_NUMBER_ID,
        WhatsAppTurn.sender == config.WHATSAPP_TEST_RECIPIENT,
        WhatsAppTurn.user_id == config.WHATSAPP_PILOT_USER_ID,
        WhatsAppTurn.organization_id == config.WHATSAPP_PILOT_ORGANIZATION_ID,
    )


async def queue_lock(db):
    # One small pilot queue; serializes receipt caps and worker claims across processes.
    await db.execute(text("SELECT pg_advisory_xact_lock(726431902)"))


async def enqueue(db, turns, config) -> int:
    await queue_lock(db)
    now = utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    count = (
        await db.exec(
            select(func.count())
            .select_from(WhatsAppTurn)
            .where(*scope(config), WhatsAppTurn.created_at >= today)
        )
    ).one()
    queued = 0
    for turn in turns:
        if count >= config.WHATSAPP_MAX_DAILY_TURNS:
            break
        result = await db.execute(
            insert(WhatsAppTurn)
            .values(**turn.model_dump())
            .on_conflict_do_nothing(index_elements=[WhatsAppTurn.id])
            .returning(WhatsAppTurn.id)
        )
        if result.scalar_one_or_none() is not None:
            count += 1
            queued += 1
    await db.commit()
    return queued


async def claim(db, config):
    await queue_lock(db)
    now = utcnow()
    # A lost worker may have called a provider. Never replay ambiguous side effects.
    await db.execute(
        update(WhatsAppTurn)
        .where(
            *scope(config),
            WhatsAppTurn.status.in_(["processing", "sending"]),
            WhatsAppTurn.updated_at < now - timedelta(minutes=10),
        )
        .values(status="unknown", error_code="worker_lost", updated_at=now)
    )
    busy = (
        await db.exec(
            select(WhatsAppTurn.id)
            .where(*scope(config), WhatsAppTurn.status.in_(["processing", "sending"]))
            .limit(1)
        )
    ).first()
    if busy:
        await db.commit()
        return None
    turn = (
        await db.exec(
            select(WhatsAppTurn)
            .where(*scope(config), WhatsAppTurn.status.in_(["queued", "reply_ready"]))
            .order_by(WhatsAppTurn.created_at, WhatsAppTurn.id)
            .limit(1)
            .with_for_update()
        )
    ).first()
    if turn:
        turn.status = "processing"
        turn.updated_at = now
        await db.commit()
    else:
        await db.commit()
    return turn


async def previous_conversation(db, config):
    return (
        await db.exec(
            select(WhatsAppTurn.conversation_id)
            .where(*scope(config), WhatsAppTurn.conversation_id.is_not(None))
            .order_by(WhatsAppTurn.created_at.desc())
            .limit(1)
        )
    ).first()


async def save(db, turn, status, *, error=None):
    turn.status = status
    turn.updated_at = utcnow()
    turn.error_code = error
    db.add(turn)
    await db.commit()
