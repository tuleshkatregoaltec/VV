"""Multi-agent intake, privacy and agent self-service against real PostgreSQL tables."""

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy import update as sql_update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.chat.service import create_conversation
from app.config import settings
from app.whatsapp import customer_automation as automation
from app.whatsapp import customer_connections as connections
from app.whatsapp import customer_graph as graph
from app.whatsapp import customer_intake as intake
from app.whatsapp.customer_models import (
    BlockRequest,
    SignupComplete,
    WhatsAppConnection,
    WhatsAppContact,
)
from app.whatsapp.models import utcnow
from app.whatsapp.token_crypto import decrypt_token, encrypt_token

KEY = Fernet.generate_key().decode()


def config(**update):
    return settings.model_copy(
        update={
            "ENVIRONMENT": "staging",
            "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": True,
            "WHATSAPP_APP_SECRET": "offline-secret",
            "WHATSAPP_GRAPH_API_VERSION": "v25.0",
            "WHATSAPP_APP_ID": "1723271579129715",
            "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID": "555",
            "WHATSAPP_TOKEN_ENCRYPTION_KEY": KEY,
            "WHATSAPP_CUSTOMER_TEST_RECIPIENT": None,
            "WHATSAPP_CUSTOMER_PHONE_NUMBER_ID": None,
            "WHATSAPP_CUSTOMER_ACCOUNT_ID": None,
            "WHATSAPP_CUSTOMER_ACCESS_TOKEN": None,
            **update,
        }
    )


@pytest.fixture
async def env(pg_session, monkeypatch):
    async def sessions():
        async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
            yield db

    monkeypatch.setattr(intake, "get_db_session", sessions)
    monkeypatch.setattr(automation, "get_db_session", sessions)
    monkeypatch.setattr(automation, "channel_access", AsyncMock(return_value=True))

    async def conversation(db, **identity):
        return (await create_conversation(db, **identity, title="WhatsApp customers")).id

    monkeypatch.setattr(automation, "create_customer_conversation", conversation)
    # Earlier tests' agents share this database; keep the worker scoped to ours.
    await pg_session.exec(sql_update(WhatsAppConnection).values(enabled=False))
    await pg_session.commit()
    return config()


async def agent(db, c, **update):
    row = WhatsAppConnection(
        **{
            "user_id": str(uuid4()),
            "organization_id": str(uuid4()),
            "phone_number_id": str(uuid4().int)[:15],
            "account_id": str(uuid4().int)[:15],
            "display_name": "Agent",
            "enabled": True,
            "onboarding_type": "coexistence",
            "connected_at": utcnow(),
            "access_token_encrypted": encrypt_token("token-" + str(uuid4()), c),
            "approved_knowledge": [{"id": "faq", "text": "Marina 2BR AED 2m."}],
            **update,
        }
    )
    db.add(row)
    await db.commit()
    return row


def event(row, field, **value):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": row.account_id,
                "changes": [
                    {
                        "field": field,
                        "value": {"metadata": {"phone_number_id": row.phone_number_id}, **value},
                    }
                ],
            }
        ],
    }


def inbound(row, body, sender="971500000001", **extra):
    return event(
        row,
        "messages",
        messages=[
            {
                "id": "wamid." + str(uuid4()),
                "from": sender,
                "type": "text",
                "text": {"body": body},
                "timestamp": str(int(utcnow().timestamp())),
                **extra,
            }
        ],
    )


async def tables_containing(bind, needle):
    """Every public table whose rows contain `needle` anywhere, via a fresh session."""
    found = []
    async with AsyncSession(bind) as db:
        names = (
            await db.exec(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            )
        ).all()
        for (name,) in names:
            count = (
                await db.exec(
                    text(f'SELECT count(*) FROM "{name}" t WHERE t::text LIKE :needle'),
                    params={"needle": f"%{needle}%"},
                )
            ).one()[0]
            if count:
                found.append(name)
    return found


async def row_count(bind, table):
    async with AsyncSession(bind) as db:
        return (await db.exec(text(f"SELECT count(*) FROM {table}"))).one()[0]


async def test_blocked_sender_leaves_no_row_in_any_table(pg_session, env, monkeypatch):
    row = await agent(pg_session, env)
    pg_session.add(WhatsAppContact(connection_id=row.id, wa_id="971500000077", blocked=True))
    await pg_session.commit()
    classify = AsyncMock()
    monkeypatch.setattr(automation, "build_customer_draft", classify)
    body = "BLOCKED-" + str(uuid4())
    threads, messages = (
        await row_count(pg_session.bind, "whatsapp_customer_threads"),
        await row_count(pg_session.bind, "whatsapp_customer_messages"),
    )
    assert await intake.receive_customer(inbound(row, body, "971500000077"), env) == 0
    await intake.drain()
    assert await tables_containing(pg_session.bind, body) == []
    assert await tables_containing(pg_session.bind, "971500000077") == ["whatsapp_contacts"]
    assert await row_count(pg_session.bind, "whatsapp_customer_threads") == threads
    assert await row_count(pg_session.bind, "whatsapp_customer_messages") == messages
    classify.assert_not_awaited()


async def test_personal_text_never_reaches_any_table_at_any_stage(pg_session, env, monkeypatch):
    row = await agent(pg_session, env)
    body = "PERSONAL-" + str(uuid4()) + " see you at dinner"
    during = []

    async def classify(**kwargs):
        assert kwargs["message"] == body
        during.append(await tables_containing(pg_session.bind, body))
        return None

    monkeypatch.setattr(automation, "build_customer_draft", classify)
    assert await intake.receive_customer(inbound(row, body), env) == 1
    after_webhook = await tables_containing(pg_session.bind, body)
    await intake.drain()
    assert after_webhook == []
    assert during == [[]]
    assert await tables_containing(pg_session.bind, body) == []
    async with AsyncSession(pg_session.bind) as db:
        receipt = (
            await db.exec(
                text(
                    "SELECT m.status, m.content FROM whatsapp_customer_messages m "
                    "JOIN whatsapp_customer_threads t ON t.id = m.thread_id "
                    "WHERE t.connection_id = :c"
                ),
                params={"c": row.id},
            )
        ).one()
    assert tuple(receipt) == ("ignored", None)


async def test_property_text_is_persisted_only_after_admission(pg_session, env, monkeypatch):
    row = await agent(pg_session, env)
    body = "PROPERTY-" + str(uuid4()) + " is the Marina 2BR available?"
    during = []

    async def classify(**kwargs):
        during.append(await tables_containing(pg_session.bind, body))
        return SimpleNamespace(
            reply="Marina 2BR AED 2m.", risk="routine", evidence_ids=["faq"], auto_eligible=True
        )

    monkeypatch.setattr(automation, "build_customer_draft", classify)
    await intake.receive_customer(inbound(row, body), env)
    assert await tables_containing(pg_session.bind, body) == []
    await intake.drain()
    assert during == [[]]
    assert await tables_containing(pg_session.bind, body) == ["whatsapp_customer_messages"]


async def test_two_agents_are_routed_and_answered_from_their_own_numbers(
    pg_session, env, monkeypatch
):
    a = await agent(pg_session, env)
    b = await agent(pg_session, env)
    monkeypatch.setattr(
        automation,
        "build_customer_draft",
        AsyncMock(
            return_value=SimpleNamespace(
                reply="Marina 2BR AED 2m.", risk="routine", evidence_ids=["faq"], auto_eligible=True
            )
        ),
    )
    payload = inbound(a, "Marina 2BR price?")
    payload["entry"] += inbound(b, "Marina 2BR price?", sender="971500000002")["entry"]
    # Agent B's number claimed under agent A's WABA is dropped.
    payload["entry"] += [
        {**inbound(b, "spoof", sender="971500000003")["entry"][0], "id": a.account_id}
    ]
    assert await intake.receive_customer(payload, env) == 2
    await intake.drain()
    sent = []

    def respond(request):
        sent.append((request.url.path, request.headers["authorization"]))
        return httpx.Response(200, json={"messages": [{"id": "wamid." + str(uuid4())}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        automation.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    while await automation.run_customer_once(env):
        pass
    expected = {
        (
            f"/v25.0/{row.phone_number_id}/messages",
            "Bearer " + decrypt_token(row.access_token_encrypted, env),
        )
        for row in (a, b)
    }
    assert set(sent) == expected and len(sent) == 2
    assert await tables_containing(pg_session.bind, "spoof") == []


async def test_contacts_sync_listing_and_bulk_block(pg_session, env, monkeypatch):
    row = await agent(pg_session, env, enabled=False)
    items = [
        {"type": "contact", "action": "add", "contact": {"full_name": name, "phone_number": phone}}
        for name, phone in [
            ("Sara Buyer", "+971 50 111 2222"),
            ("Mum", "971503334444"),
            ("Omar Tenant", "971505556666"),
        ]
    ]
    await intake.receive_customer(event(row, "smb_app_state_sync", state_sync=items), env)
    await intake.receive_customer(
        event(
            row,
            "smb_app_state_sync",
            state_sync=[
                {
                    "type": "contact",
                    "action": "edit",
                    "contact": {"full_name": "Sara (Marina)", "phone_number": "971501112222"},
                },
                {
                    "type": "contact",
                    "action": "remove",
                    "contact": {"phone_number": "971505556666"},
                },
            ],
        ),
        env,
    )
    identity = {"user_id": row.user_id, "organization_id": row.organization_id}
    async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
        page = await connections.list_agent_contacts(
            db, **identity, search=None, blocked=None, limit=50, offset=0
        )
        assert [(c.name, c.wa_id) for c in page.items] == [
            ("Mum", "971503334444"),
            ("Sara (Marina)", "971501112222"),
        ]
        found = await connections.list_agent_contacts(
            db, **identity, search="sara", blocked=None, limit=1, offset=0
        )
        assert found.total == 1 and found.items[0].wa_id == "971501112222"
        mum = page.items[0].id
        result = await connections.block_contacts(
            db,
            **identity,
            request=BlockRequest(
                contact_ids=[mum], phone_numbers=["+971 50 999 0000"], blocked=True
            ),
        )
        assert (result.updated, result.blocked_total) == (2, 2)
        blocked = await connections.list_agent_contacts(
            db, **identity, search=None, blocked=True, limit=50, offset=0
        )
        assert {c.wa_id for c in blocked.items} == {"971503334444", "971509990000"}
        status = await connections.agent_status(db, **identity, config=env)
        assert status.contacts.total == 3 and status.contacts.blocked == 2
        assert status.contacts.synced_at is not None


async def test_automation_toggle_disconnect_and_admin_overview(pg_session, env, monkeypatch):
    row = await agent(pg_session, env, enabled=False)
    pg_session.add(WhatsAppContact(connection_id=row.id, wa_id="971501112222"))
    await pg_session.commit()
    identity = {"user_id": row.user_id, "organization_id": row.organization_id}
    unsubscribe = AsyncMock()
    monkeypatch.setattr(graph, "unsubscribe_app", unsubscribe)
    monkeypatch.setattr(
        "app.auth.service.get_user_by_id",
        AsyncMock(return_value=SimpleNamespace(email="agent@example.com")),
    )
    async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
        status = await connections.set_automation(db, **identity, enabled=True, config=env)
        assert status.state == "connected" and status.automation_enabled
        overview = await connections.admin_connections(db)
        mine = next(item for item in overview.items if item.connection_id == row.id)
        assert mine.status == "connected" and mine.automation_enabled
        assert mine.user_email == "agent@example.com" and mine.contacts_total == 1
        assert overview.connected >= 1 and overview.total >= overview.connected

        status = await connections.disconnect_agent(db, **identity, config=env)
        assert status.state == "disconnected" and not status.automation_enabled
        assert status.contacts.total == 0
    unsubscribe.assert_awaited_once()
    assert unsubscribe.await_args.args[0] == row.account_id
    async with AsyncSession(pg_session.bind) as db:
        stored = (
            await db.exec(
                text(
                    "SELECT access_token_encrypted, enabled, status FROM whatsapp_connections WHERE id = :i"
                ),
                params={"i": row.id},
            )
        ).one()
    assert tuple(stored) == (None, False, "disconnected")
    # Webhooks for a disconnected number are no longer routed.
    assert await intake.receive_customer(inbound(row, "hello again"), env) == 0
    assert await tables_containing(pg_session.bind, "hello again") == []


async def test_token_is_encrypted_in_the_database_and_env_pilot_migrates(pg_session, env):
    phone, account = str(uuid4().int)[:15], str(uuid4().int)[:15]
    pilot = env.model_copy(
        update={
            "WHATSAPP_CUSTOMER_PHONE_NUMBER_ID": phone,
            "WHATSAPP_CUSTOMER_ACCOUNT_ID": account,
            "WHATSAPP_CUSTOMER_ACCESS_TOKEN": "EAAG-kian-env-token",
            "WHATSAPP_PILOT_USER_ID": str(uuid4()),
            "WHATSAPP_PILOT_ORGANIZATION_ID": str(uuid4()),
        }
    )
    existing = await agent(
        pg_session,
        env,
        user_id=pilot.WHATSAPP_PILOT_USER_ID,
        organization_id=pilot.WHATSAPP_PILOT_ORGANIZATION_ID,
        phone_number_id=phone,
        account_id=account,
        access_token_encrypted=None,
        onboarding_type="env",
    )
    async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
        await connections.bootstrap_env_connection(db, pilot)
    async with AsyncSession(pg_session.bind) as db:
        raw = (
            await db.exec(
                text(
                    "SELECT access_token_encrypted, enabled FROM whatsapp_connections WHERE id = :i"
                ),
                params={"i": existing.id},
            )
        ).one()
    assert raw[0] and raw[0] != "EAAG-kian-env-token" and "EAAG" not in raw[0]
    assert decrypt_token(raw[0], pilot) == "EAAG-kian-env-token"
    assert raw[1] is True
    assert await tables_containing(pg_session.bind, "EAAG-kian-env-token") == []


async def test_signup_completion_persists_an_encrypted_connection(pg_session, env, monkeypatch):
    waba, phone = str(uuid4().int)[:15], str(uuid4().int)[:15]
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("/oauth/access_token"):
            return httpx.Response(200, json={"access_token": "EAAG-signup-token"})
        if path.endswith("/phone_numbers"):
            return httpx.Response(200, json={"data": [{"id": phone, "verified_name": "Agent Co"}]})
        if path.endswith("/smb_app_data"):
            return httpx.Response(200, json={"request_id": "r"})
        if path.endswith(f"/{phone}"):
            return httpx.Response(200, json={"health_status": {"can_send_message": "LIMITED"}})
        return httpx.Response(200, json={"success": True})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        graph.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    user, org = str(uuid4()), str(uuid4())
    request = SignupComplete(
        state=connections.signup_state(user, org, env),
        code="code",
        phone_number_id=phone,
        waba_id=waba,
        event="FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
    )
    async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
        status = await connections.connect(
            db, user_id=user, organization_id=org, request=request, config=env
        )
    assert status.state == "connected" and status.display_name == "Agent Co"
    assert status.can_send_message == "LIMITED" and not status.automation_enabled
    assert status.contacts.sync_requested_at is not None
    assert ("POST", f"/v25.0/{phone}/smb_app_data") in calls
    assert await tables_containing(pg_session.bind, "EAAG-signup-token") == []
    assert json.dumps(status.model_dump(mode="json")).find("EAAG") == -1
    assert utcnow() - status.connected_at < timedelta(minutes=1)
