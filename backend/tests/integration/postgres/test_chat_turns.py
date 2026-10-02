"""Durable retry identity protects user messages and charges across workers."""

import asyncio
from uuid import uuid4

from sqlmodel.ext.asyncio.session import AsyncSession

from app.chat import repository
from app.chat.service import create_conversation, get_conversation_messages


async def test_duplicate_turn_claims_and_replay_are_atomic(pg_session):
    user, org = str(uuid4()), str(uuid4())
    conversation = await create_conversation(pg_session, user, org)
    cid = conversation.id
    request = str(uuid4())

    async def claim():
        async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
            result, message = await repository.claim_turn(
                db, cid, user, org, request, "Original question"
            )
            await db.commit()
            return result, message.id

    claims = await asyncio.gather(claim(), claim())
    assert sorted(status for status, _ in claims) == ["claimed", "running"]
    assert claims[0][1] == claims[1][1]
    message_id = claims[0][1]
    await repository.finish_turn(
        pg_session, cid, user, org, message_id, "complete", "Grounded answer", {"total_tokens": 17}
    )
    await pg_session.commit()
    status, message = await repository.claim_turn(
        pg_session, cid, user, org, request, "Original question"
    )
    assert status == "complete"
    replay = await repository.replay_turn(pg_session, message)
    assert replay.content == "Grounded answer"
    assert replay.meta_data["total_tokens"] == 17
    await pg_session.rollback()
    messages = await get_conversation_messages(pg_session, cid, user, org)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[0].meta_data["turn_status"] == "complete"


async def test_retry_conflict_and_cross_tenant_claim_do_not_insert(pg_session):
    user, org = str(uuid4()), str(uuid4())
    conversation = await create_conversation(pg_session, user, org)
    cid = conversation.id
    request = str(uuid4())
    status, message = await repository.claim_turn(pg_session, cid, user, org, request, "Private")
    message_id = message.id
    assert status == "claimed"
    await pg_session.commit()
    assert (await repository.claim_turn(pg_session, cid, user, org, request, "Changed"))[
        0
    ] == "conflict"
    await pg_session.rollback()
    assert (await repository.claim_turn(pg_session, cid, user, "other-org", request, "Private"))[
        0
    ] == "missing"
    await pg_session.rollback()
    assert (await repository.claim_turn(pg_session, cid, user, org, str(uuid4()), "Another"))[
        0
    ] == "busy"
    await pg_session.rollback()
    await repository.finish_turn(pg_session, cid, user, org, message_id, "cancelled")
    await pg_session.commit()
    assert (await repository.claim_turn(pg_session, cid, user, org, request, "Private"))[
        0
    ] == "cancelled"
    await pg_session.rollback()
    assert len(await get_conversation_messages(pg_session, cid, user, org)) == 1


async def test_replaying_crashed_request_reconciles_stale_running_state(pg_session):
    from datetime import datetime, timedelta, timezone

    user, org = str(uuid4()), str(uuid4())
    conversation = await create_conversation(pg_session, user, org)
    cid = conversation.id
    request = str(uuid4())
    _, message = await repository.claim_turn(pg_session, cid, user, org, request, "Before crash")
    message.created_at = datetime.now(timezone.utc) - timedelta(minutes=6)
    pg_session.add(message)
    await pg_session.commit()
    status, message = await repository.claim_turn(
        pg_session, cid, user, org, request, "Before crash"
    )
    assert status == "interrupted"
    await pg_session.commit()
    pg_session.expire_all()
    messages = await get_conversation_messages(pg_session, cid, user, org)
    assert len(messages) == 1 and messages[0].meta_data["turn_status"] == "interrupted"
