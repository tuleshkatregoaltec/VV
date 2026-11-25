"""Human-paced sending, silent identity handoffs and handoff summaries against Postgres."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy import update as sql_update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.chat.conversations import create_conversation
from app.config import settings
from app.whatsapp import customer_automation as automation
from app.whatsapp import customer_queue as queue
from app.whatsapp import customer_repository as repository
from app.whatsapp import customer_timing as timing
from app.whatsapp.customer_models import (
    WhatsAppConnection,
    WhatsAppCustomerMessage,
    WhatsAppCustomerThread,
)
from app.whatsapp.models import utcnow
from app.whatsapp.token_crypto import encrypt_token

STATE = {}
PENDING = []
EVENTS = []


async def setup(pg_session, monkeypatch, *, timing_on=True):
    c = settings.model_copy(
        update={
            "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": True,
            "WHATSAPP_HUMAN_TIMING_ENABLED": timing_on,
            "WHATSAPP_CUSTOMER_PHONE_NUMBER_ID": str(uuid4()),
            "WHATSAPP_CUSTOMER_ACCOUNT_ID": str(uuid4()),
            "WHATSAPP_CUSTOMER_ACCESS_TOKEN": "offline-token",
            "WHATSAPP_CUSTOMER_TEST_RECIPIENT": None,
            "WHATSAPP_APP_SECRET": "offline-secret",
            "WHATSAPP_GRAPH_API_VERSION": "v25.0",
            "WHATSAPP_PILOT_USER_ID": str(uuid4()),
            "WHATSAPP_PILOT_ORGANIZATION_ID": str(uuid4()),
        }
    )
    await pg_session.exec(sql_update(WhatsAppConnection).values(enabled=False))
    connection = WhatsAppConnection(
        user_id=c.WHATSAPP_PILOT_USER_ID,
        organization_id=c.WHATSAPP_PILOT_ORGANIZATION_ID,
        phone_number_id=c.WHATSAPP_CUSTOMER_PHONE_NUMBER_ID,
        account_id=c.WHATSAPP_CUSTOMER_ACCOUNT_ID,
        display_name="Kian",
        enabled=True,
        access_token_encrypted=encrypt_token("offline-token", c),
        approved_knowledge=[{"id": "faq", "text": "Marina 2 bed asking AED 2m."}],
        reply_voice={"tone": "warm", "agent_name": "Kian"},
    )
    pg_session.add(connection)
    await pg_session.commit()
    STATE["connection"] = connection
    PENDING.clear()
    EVENTS.clear()
    monkeypatch.setattr(automation, "channel_access", AsyncMock(return_value=True))

    async def conversation(db, **identity):
        return (await create_conversation(db, **identity, title="WhatsApp customers")).id

    monkeypatch.setattr(automation, "create_customer_conversation", conversation)
    draft = AsyncMock(
        return_value=SimpleNamespace(
            reply="Yep, 2 bed in Marina, asking AED 2m.",
            risk="routine",
            evidence_ids=["faq"],
            auto_eligible=True,
        )
    )
    monkeypatch.setattr(automation, "build_customer_draft", draft)

    async def typing(*args, **kwargs):
        EVENTS.append(("typing", args[1].id))
        return True

    async def send_reply(*args, **kwargs):
        EVENTS.append(("send", args[2].id))
        return "outbound"

    monkeypatch.setattr(automation, "mark_read_typing", typing)
    monkeypatch.setattr(automation, "send_reply", send_reply)
    sleeps = AsyncMock()
    monkeypatch.setattr(automation.asyncio, "sleep", sleeps)

    async def sessions():
        async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
            yield db

    monkeypatch.setattr(automation, "get_db_session", sessions)
    return c, draft, sleeps


async def receipt(db, c, body="Is the Marina 2 bed available?", sender="919000000000", age=None):
    when = utcnow() - (age or timedelta())
    raw = {
        "id": str(uuid4()),
        "from": sender,
        "type": "text",
        "text": {"body": body},
        "timestamp": str(int(when.timestamp())),
    }
    connection = await repository.lock_connection(db, STATE["connection"].id)
    PENDING.extend(await queue.enqueue(db, connection, [raw], c))
    await db.commit()
    return await db.get(WhatsAppCustomerMessage, raw["id"])


async def step(c):
    if PENDING:
        await automation.classify(PENDING.pop(0), c)
        return True
    return await automation.run_customer_once(c)


async def refresh(db, message):
    await db.refresh(message)
    return message


async def due(db, message):
    await refresh(db, message)
    message.send_after = utcnow() - timedelta(seconds=1)
    await db.commit()


async def test_reply_waits_reads_types_then_sends_without_blocking_the_lane(
    pg_session, monkeypatch
):
    c, _, sleeps = await setup(pg_session, monkeypatch)
    message = await receipt(pg_session, c)
    started = utcnow()
    await step(c)
    await refresh(pg_session, message)
    assert message.status == "auto_pending"
    wait = (message.send_after - started).total_seconds()
    assert timing.MIN_READING - 1 <= wait <= timing.MAX_READING + 1
    assert not await step(c), "Nothing is due during the reading delay"
    assert EVENTS == []

    await due(pg_session, message)
    typing_at = utcnow()
    assert await step(c)
    await refresh(pg_session, message)
    assert EVENTS == [("typing", message.id)], "Read and typing indicator come first"
    assert message.status == "auto_pending" and message.typing_started_at is not None
    pause = (message.send_after - typing_at).total_seconds()
    assert timing.MIN_TYPING - 1 <= pause <= timing.MAX_TYPING + 1
    sleeps.assert_not_called()
    assert not await step(c), "The lane is free for other agents while the typing delay runs"

    await due(pg_session, message)
    assert await step(c)
    await refresh(pg_session, message)
    assert EVENTS == [("typing", message.id), ("send", message.id)]
    assert message.status == "accepted" and message.outbound_id == "outbound"
    assert not await step(c)


async def test_two_lanes_cannot_both_start_typing_for_one_reply(pg_session, monkeypatch):
    c, _, _ = await setup(pg_session, monkeypatch)
    message = await receipt(pg_session, c)
    await step(c)
    await due(pg_session, message)
    await step(c)
    assert [name for name, _ in EVENTS] == ["typing"]
    assert not await step(c) and [name for name, _ in EVENTS] == ["typing"]


async def test_agent_replying_during_the_delay_cancels_the_send(pg_session, monkeypatch):
    c, _, _ = await setup(pg_session, monkeypatch)
    message = await receipt(pg_session, c)
    await step(c)
    await due(pg_session, message)
    await step(c)
    thread = await pg_session.get(WhatsAppCustomerThread, message.thread_id)
    thread.paused = True  # the agent answered from their phone
    await pg_session.commit()
    await due(pg_session, message)
    await step(c)
    await refresh(pg_session, message)
    assert message.status == "cancelled"
    assert [name for name, _ in EVENTS] == ["typing"]


async def test_no_delay_when_the_24_hour_window_is_about_to_close(pg_session, monkeypatch):
    c, _, _ = await setup(pg_session, monkeypatch)
    message = await receipt(pg_session, c, age=timedelta(hours=23, minutes=58))
    started = utcnow()
    await step(c)
    await refresh(pg_session, message)
    assert message.send_after <= utcnow() and message.send_after >= started - timedelta(seconds=1)
    await step(c)
    await refresh(pg_session, message)
    assert EVENTS == [("send", message.id)] and message.status == "accepted"


async def test_window_expiry_still_wins_over_a_pending_typing_delay(pg_session, monkeypatch):
    c, _, _ = await setup(pg_session, monkeypatch)
    message = await receipt(pg_session, c)
    await step(c)
    await due(pg_session, message)
    message.sent_at = utcnow() - timedelta(hours=24, seconds=5)
    await pg_session.commit()
    await step(c)
    await refresh(pg_session, message)
    assert message.status == "expired" and EVENTS == []


async def test_agent_approved_replies_skip_the_artificial_delay(pg_session, monkeypatch):
    c, draft, _ = await setup(pg_session, monkeypatch)
    draft.return_value = SimpleNamespace(
        reply="Let me check with the owner.",
        risk="approval",
        evidence_ids=[],
        auto_eligible=False,
        summary="Buyer offers AED 1.8m.",
    )
    message = await receipt(pg_session, c, "Would the owner take 1.8m?")
    await step(c)
    await refresh(pg_session, message)
    assert message.status == "approval_required"
    assert message.handoff_summary == "Buyer offers AED 1.8m."
    message.status, message.send_after = "approved", utcnow()
    await pg_session.commit()
    await step(c)
    await refresh(pg_session, message)
    assert EVENTS == [("send", message.id)] and message.status == "accepted"


async def test_identity_question_pauses_the_thread_notifies_and_sends_nothing(
    pg_session, monkeypatch
):
    c, draft, _ = await setup(pg_session, monkeypatch)
    draft.return_value = SimpleNamespace(
        reply=None,
        risk="approval",
        evidence_ids=[],
        auto_eligible=False,
        silent=True,
        summary="The customer asked whether they are talking to a bot.",
        reason="identity_question",
    )
    message = await receipt(pg_session, c, "Are you a bot?")
    await step(c)
    await refresh(pg_session, message)
    thread = await pg_session.get(WhatsAppCustomerThread, message.thread_id)
    await pg_session.refresh(thread)
    assert message.status == "approval_required" and message.reply is None
    assert message.reason == "identity_question" and message.send_after is None
    assert message.handoff_summary.startswith("The customer asked")
    assert message.notification_created_at is not None and thread.paused
    for _ in range(3):
        await step(c)
    assert EVENTS == []


async def test_first_message_identity_question_keeps_no_text_but_pauses_and_notifies(
    pg_session, monkeypatch
):
    c, draft, _ = await setup(pg_session, monkeypatch)
    draft.return_value = SimpleNamespace(
        reply=None,
        risk="approval",
        evidence_ids=[],
        auto_eligible=False,
        silent=True,
        store_content=False,
        summary="A contact asked whether replies are automated or from a real person.",
        reason="identity_question",
    )
    message = await receipt(pg_session, c, "Are you a bot?", sender="971500000001")
    await step(c)
    await refresh(pg_session, message)
    thread = await pg_session.get(WhatsAppCustomerThread, message.thread_id)
    await pg_session.refresh(thread)
    # Only the sender, the pause and a content-free notification are stored.
    assert message.content is None and message.reply is None
    assert message.status == "approval_required" and message.reason == "identity_question"
    assert message.topic == "identity" and "automated" in message.handoff_summary
    assert message.notification_created_at is not None and thread.paused
    connection = STATE["connection"]
    listed = await repository.threads(pg_session, connection.id)
    assert [row.id for row in listed] == [thread.id], "agent must see who asked"
    notes = await repository.notifications(
        pg_session, connection.user_id, connection.organization_id
    )
    assert [note.id for note in notes] == [message.id]
    # The buyer's next property message is not auto-answered: the thread is the agent's.
    draft.reset_mock()
    follow_up = await receipt(pg_session, c, "Ok, what's the 2BR price?", sender="971500000001")
    for _ in range(3):
        await step(c)
    await refresh(pg_session, follow_up)
    assert follow_up.status == "ignored" and follow_up.content is None
    draft.assert_not_called()
    assert EVENTS == []


async def test_voice_and_name_are_passed_to_the_drafter(pg_session, monkeypatch):
    c, draft, _ = await setup(pg_session, monkeypatch)
    await receipt(pg_session, c)
    await step(c)
    kwargs = draft.call_args.kwargs
    assert kwargs["voice_profile"] == {"tone": "warm", "agent_name": "Kian"}
    assert kwargs["agent_name"] == "Kian"


async def test_asked_question_travels_in_history_for_the_next_bare_answer(pg_session, monkeypatch):
    c, draft, _ = await setup(pg_session, monkeypatch, timing_on=False)
    draft.return_value = SimpleNamespace(
        reply="Nice. Buying or renting?",
        risk="routine",
        evidence_ids=[],
        auto_eligible=True,
        asked="transaction",
    )
    message = await receipt(pg_session, c, "Looking for a two bedroom in Marina")
    await step(c)
    await step(c)
    await refresh(pg_session, message)
    assert message.status == "accepted" and message.asked_detail == "transaction"
    history = await queue.history_for(pg_session, message.thread_id)
    assert history[-1] == {
        "role": "assistant",
        "content": "Nice. Buying or renting?",
        "asked": "transaction",
    }


async def test_voice_is_stored_per_agent_scoped_to_the_owner_and_resettable(
    pg_session, monkeypatch
):
    import pytest
    from fastapi import HTTPException

    from app.whatsapp import customer_service as service
    from app.whatsapp.customer_models import VoiceProfile, VoiceUpdate

    c, _, _ = await setup(pg_session, monkeypatch)
    connection = STATE["connection"]
    voice = VoiceProfile(tone="dry and brief", sample_messages=["Yep, still around."])
    owner = {"user_id": connection.user_id, "organization_id": connection.organization_id}
    row = await service.update_voice(
        pg_session, **owner, connection_id=connection.id, request=VoiceUpdate(voice=voice)
    )
    assert row.reply_voice == voice.model_dump()
    with pytest.raises(HTTPException) as denied:
        await service.update_voice(
            pg_session,
            user_id="someone-else",
            organization_id=connection.organization_id,
            connection_id=connection.id,
            request=VoiceUpdate(voice=None),
        )
    assert denied.value.status_code == 404
    await pg_session.refresh(connection)
    assert connection.reply_voice == voice.model_dump()
    row = await service.update_voice(
        pg_session, **owner, connection_id=connection.id, request=VoiceUpdate(voice=None)
    )
    assert row.reply_voice is None
