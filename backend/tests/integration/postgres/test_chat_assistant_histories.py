"""The CRM Operations Assistant and Market AI keep separate conversation histories.

conversations.assistant ('crm' or 'market', migration c5e9a3b7d1f4) says which product a
conversation belongs to. Each product lists only its own conversations, and each answer stream
finds only its own: a conversation is never shown in, or continued by, the other product.
Existing conversations are kept, every message with them: those Market AI answered in become
Market AI conversations, every other one a CRM Assistant conversation.
"""

import json
import os
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg2
import pytest
from psycopg2 import sql
from sqlalchemy.engine import make_url

from app.chat.conversations import (
    add_message,
    create_conversation,
    get_conversation,
    get_user_conversations,
)
from app.crm.assistant import service

BACKEND = Path(__file__).parents[3]


def _alembic(url: str, *args: str) -> None:
    subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "POSTGRES_URL": url},
        check=True,
        capture_output=True,
        text=True,
    )


def test_existing_conversations_are_kept_and_split_by_who_answered(postgres_test_url):
    """On its own database: migrate to the revision before, store conversations as they are
    today, then migrate. Market AI conversations move to Market AI; nothing else changes."""
    url = make_url(postgres_test_url)
    database = "vv_history_split_" + uuid.uuid4().hex
    admin = psycopg2.connect(
        url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    )
    admin.autocommit = True
    with admin.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    target = url.set(database=database)
    try:
        _alembic(target.render_as_string(hide_password=False), "upgrade", "b8d4f6a2c0e3")
        connection = psycopg2.connect(
            target.set(drivername="postgresql").render_as_string(hide_password=False)
        )
        connection.autocommit = True
        with connection.cursor() as cursor:
            ids = {}
            for name in ("market", "crm", "empty", "whatsapp"):
                cursor.execute(
                    "INSERT INTO conversations (user_id, organization_id, title, created_at, "
                    "updated_at) VALUES ('u', 'o', %s, now(), now()) RETURNING id",
                    (name,),
                )
                ids[name] = cursor.fetchone()[0]
            messages = [
                ("market", "user", "JVC sales?", {}),
                (
                    "market",
                    "assistant",
                    "12 sales",
                    {"guardrail_version": 1, "assistant": "market"},
                ),
                ("crm", "user", "My leads?", {}),
                ("crm", "assistant", "Two leads", {"guardrail_version": 1, "private": True}),
                ("whatsapp", "assistant", "Reply", {"guardrail_version": 1}),
            ]
            for conversation, role, content, meta in messages:
                cursor.execute(
                    "INSERT INTO messages (conversation_id, role, content, meta_data, created_at) "
                    "VALUES (%s, %s, %s, %s, now())",
                    (ids[conversation], role, content, json.dumps(meta)),
                )

        _alembic(target.render_as_string(hide_password=False), "upgrade", "head")

        with connection.cursor() as cursor:
            cursor.execute("SELECT title, assistant FROM conversations ORDER BY id")
            assert dict(cursor.fetchall()) == {
                "market": "market",
                "crm": "crm",
                "empty": "crm",
                "whatsapp": "crm",
            }
            cursor.execute("SELECT count(*) FROM messages")
            assert cursor.fetchone()[0] == len(messages)  # Every message kept.
            # Only the two products exist.
            with pytest.raises(psycopg2.errors.CheckViolation):
                cursor.execute("UPDATE conversations SET assistant = 'other'")
        connection.close()
    finally:
        with admin.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
            )
        admin.close()


async def test_each_assistant_lists_only_its_own_conversations(pg_session):
    scope = {"user_id": f"u-{uuid.uuid4().hex[:6]}", "organization_id": str(uuid.uuid4())}
    crm = await create_conversation(pg_session, **scope, title="My leads")
    market = await create_conversation(pg_session, **scope, title="JVC sales", assistant="market")
    assert (crm.assistant, market.assistant) == ("crm", "market")  # CRM when not stated.

    listed_crm = await get_user_conversations(pg_session, **scope)
    listed_market = await get_user_conversations(pg_session, **scope, assistant="market")
    assert [c.id for c in listed_crm] == [crm.id]
    assert [c.id for c in listed_market] == [market.id]

    # Reading a conversation through the other product finds nothing.
    assert await get_conversation(pg_session, market.id, **scope, assistant="crm") is None
    assert await get_conversation(pg_session, crm.id, **scope, assistant="market") is None
    assert (await get_conversation(pg_session, market.id, **scope)).id == market.id


@pytest.fixture
def turn(monkeypatch):
    monkeypatch.setattr(service.settings, "ASSISTANT_ENABLED", True)
    monkeypatch.setattr(service.settings, "ASSISTANT_TYPED_ROUTING_ENABLED", False)
    acquire = AsyncMock(return_value=service.admission.TurnLease("lease", 160_000))
    monkeypatch.setattr(service.admission, "acquire", acquire)
    monkeypatch.setattr(service.admission, "finish", AsyncMock())
    ran = []

    async def run(*args, **kwargs):
        ran.append(True)
        return SimpleNamespace(output="Answered.")

    monkeypatch.setattr(service, "agent", SimpleNamespace(run=run))
    return SimpleNamespace(acquire=acquire, ran=ran, run=run)


async def _stream(db, conversation_id, scope, runtime=None):
    return [
        json.loads(event.removeprefix("data: "))
        async for event in service.stream_chat_response(
            db, conversation_id, "hello", **scope, runtime=runtime
        )
    ]


async def test_neither_assistant_answers_in_the_others_conversation(pg_session, turn):
    scope = {"user_id": f"u-{uuid.uuid4().hex[:6]}", "organization_id": str(uuid.uuid4())}
    crm = await create_conversation(pg_session, **scope)
    market = await create_conversation(pg_session, **scope, assistant="market")
    market_ai = service.AssistantRuntime(
        name="market", agent=SimpleNamespace(run=turn.run), run_routed_turn=turn.run
    )

    for conversation, runtime in ((market.id, None), (crm.id, market_ai)):
        events = await _stream(pg_session, conversation, scope, runtime)
        assert [event.get("code") for event in events] == ["conversation_not_found"]
    turn.acquire.assert_not_awaited()  # Refused before anything is reserved or run.
    assert turn.ran == []

    # Each answers in its own, and the answer stays in that conversation.
    assert (await _stream(pg_session, crm.id, scope))[-1] == {"type": "done"}
    assert (await _stream(pg_session, market.id, scope, market_ai))[-1] == {"type": "done"}
    assert turn.ran == [True, True]


async def test_whatsapp_pilot_conversations_stay_crm(pg_session):
    """The WhatsApp pilot answers with the CRM assistant; its conversations are CRM's."""
    from app.chat import operations

    scope = {"user_id": f"u-{uuid.uuid4().hex[:6]}", "organization_id": str(uuid.uuid4())}
    created = await create_conversation(pg_session, **scope, title="WhatsApp pilot")
    assert created.assistant == "crm"
    assert operations.create_conversation is create_conversation
    await add_message(pg_session, created.id, "user", "hi", **scope)
    assert [c.id for c in await get_user_conversations(pg_session, **scope)] == [created.id]
