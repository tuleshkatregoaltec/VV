"""Kian's env-configured pilot number moves into per-agent encrypted storage."""

import httpx
import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.whatsapp import customer_automation as automation
from app.whatsapp import customer_connections as connections
from app.whatsapp import customer_intake as intake
from app.whatsapp import customer_queue as queue
from app.whatsapp import customer_repository as repository
from app.whatsapp.customer_models import WhatsAppConnection, WhatsAppCustomerThread
from app.whatsapp.token_crypto import decrypt_token

KEY = Fernet.generate_key().decode()


def config(**update):
    return settings.model_copy(
        update={
            "ENVIRONMENT": "staging",
            "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": True,
            "WHATSAPP_APP_SECRET": "secret",
            "WHATSAPP_GRAPH_API_VERSION": "v25.0",
            "WHATSAPP_CUSTOMER_PHONE_NUMBER_ID": "111",
            "WHATSAPP_CUSTOMER_ACCOUNT_ID": "222",
            "WHATSAPP_CUSTOMER_ACCESS_TOKEN": "kian-env-token",
            "WHATSAPP_CUSTOMER_TEST_RECIPIENT": None,
            "WHATSAPP_PILOT_USER_ID": "kian",
            "WHATSAPP_PILOT_ORGANIZATION_ID": "vitevue",
            "WHATSAPP_TOKEN_ENCRYPTION_KEY": KEY,
            **update,
        }
    )


class Session:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def add(self, row):
        self.rows.append(row)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture
def lookup(monkeypatch):
    def install(session):
        async def connection_by_phone(db, phone_number_id):
            return next((r for r in session.rows if r.phone_number_id == phone_number_id), None)

        async def routed_connection(db, account_id, phone_number_id):
            return next(
                (
                    r
                    for r in session.rows
                    if (r.account_id, r.phone_number_id) == (account_id, phone_number_id)
                    and r.status == "connected"
                ),
                None,
            )

        monkeypatch.setattr(repository, "connection_by_phone", connection_by_phone)
        monkeypatch.setattr(repository, "routed_connection", routed_connection)
        return session

    return install


def kian_row(**update):
    # The row created on the server through POST /connections before this change.
    values = {
        "user_id": "kian",
        "organization_id": "vitevue",
        "phone_number_id": "111",
        "account_id": "222",
        "display_name": "Kian",
        "enabled": True,
        "onboarding_type": "env",
    }
    return WhatsAppConnection(**{**values, **update})


async def test_existing_env_row_gets_the_env_token_encrypted_and_stays_enabled(lookup):
    db = lookup(Session([kian_row()]))
    c = config()
    row = await connections.bootstrap_env_connection(db, c)
    assert row is db.rows[0]
    assert row.enabled is True and row.status == "connected"
    assert row.access_token_encrypted != "kian-env-token"
    assert "kian-env-token" not in row.access_token_encrypted
    assert decrypt_token(row.access_token_encrypted, c) == "kian-env-token"
    stored = row.access_token_encrypted
    await connections.bootstrap_env_connection(db, c)
    assert row.access_token_encrypted == stored  # idempotent

    rotated = config(WHATSAPP_CUSTOMER_ACCESS_TOKEN="kian-new-token")
    await connections.bootstrap_env_connection(db, rotated)
    assert decrypt_token(row.access_token_encrypted, c) == "kian-new-token"


async def test_missing_env_row_is_created_with_automation_off(lookup):
    db = lookup(Session())
    row = await connections.bootstrap_env_connection(db, config())
    assert db.rows == [row]
    assert (row.user_id, row.organization_id, row.account_id) == ("kian", "vitevue", "222")
    assert row.enabled is False and row.onboarding_type == "env"


async def test_bootstrap_respects_disconnect_and_foreign_owner(lookup):
    disconnected = kian_row(status="disconnected")
    db = lookup(Session([disconnected]))
    await connections.bootstrap_env_connection(db, config())
    assert disconnected.access_token_encrypted is None
    foreign = kian_row(user_id="someone-else")
    db = lookup(Session([foreign]))
    await connections.bootstrap_env_connection(db, config())
    assert foreign.access_token_encrypted is None


async def test_bootstrap_fails_closed_without_an_encryption_key_outside_local(lookup):
    row = kian_row()
    db = lookup(Session([row]))
    assert (
        await connections.bootstrap_env_connection(db, config(WHATSAPP_TOKEN_ENCRYPTION_KEY=None))
        is None
    )
    assert row.access_token_encrypted is None
    thread = WhatsAppCustomerThread(connection_id=row.id, sender="971500000001")
    assert not queue.bound(row, thread, config())


async def test_migrated_pilot_still_routes_and_sends_with_its_own_token(lookup, monkeypatch):
    db = lookup(Session([kian_row()]))
    c = config()
    row = await connections.bootstrap_env_connection(db, c)

    async def sessions():
        yield db

    monkeypatch.setattr(intake, "get_db_session", sessions)
    routed = await repository.routed_connection(db, "222", "111")
    assert routed is row
    thread = WhatsAppCustomerThread(connection_id=row.id, sender="971500000001")
    assert queue.bound(row, thread, c)

    captured = []

    def respond(request):
        captured.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.out"}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        automation.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    message = type("Message", (), {"id": "wamid.in", "reply": "Marina 2BR AED 2m."})()
    # The env token is no longer read at send time; only the stored ciphertext is.
    send_config = c.model_copy(update={"WHATSAPP_CUSTOMER_ACCESS_TOKEN": None})
    assert await automation.send_reply(row, thread, message, send_config) == "wamid.out"
    assert captured[0].url.path == "/v25.0/111/messages"
    assert captured[0].headers["authorization"] == "Bearer kian-env-token"
