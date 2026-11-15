"""Embedded Signup completion with a mocked Graph API (no real Meta calls)."""

import json
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from app.config import settings
from app.whatsapp import customer_connections as connections
from app.whatsapp import customer_graph as graph
from app.whatsapp import customer_repository as repository
from app.whatsapp.customer_models import SignupComplete, WhatsAppConnection
from app.whatsapp.token_crypto import decrypt_token

KEY = Fernet.generate_key().decode()


def config(**update):
    return settings.model_copy(
        update={
            "ENVIRONMENT": "staging",
            "WHATSAPP_CUSTOMER_AUTOMATION_ENABLED": True,
            "WHATSAPP_APP_ID": "1723271579129715",
            "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID": "555",
            "WHATSAPP_APP_SECRET": "app-secret",
            "WHATSAPP_GRAPH_API_VERSION": "v25.0",
            "WHATSAPP_TOKEN_ENCRYPTION_KEY": KEY,
            **update,
        }
    )


class Session:
    def __init__(self):
        self.rows = []
        self.commits = 0

    def add(self, row):
        self.rows.append(row)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


class UsedStates:
    """In-memory stand-in for Redis SET NX EX."""

    def __init__(self):
        self.keys = {}

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys[key] = ex
        return True


@pytest.fixture(autouse=True)
def used_states(monkeypatch):
    store = UsedStates()
    monkeypatch.setattr(connections, "_state_store", lambda: store)
    return store


@pytest.fixture
def db(monkeypatch):
    session = Session()

    async def connection_by_phone(db, phone_number_id):
        return next((r for r in session.rows if r.phone_number_id == phone_number_id), None)

    async def agent_connections(db, user_id, organization_id):
        return [
            r for r in session.rows if (r.user_id, r.organization_id) == (user_id, organization_id)
        ]

    monkeypatch.setattr(repository, "connection_by_phone", connection_by_phone)
    monkeypatch.setattr(repository, "agent_connections", agent_connections)
    return session


@pytest.fixture
def meta(monkeypatch):
    calls = []
    responses = {}

    def respond(request):
        calls.append(request)
        key = (request.method, request.url.path)
        status, body = responses.get(key, (404, {"error": {"code": 100}}))
        return httpx.Response(status, json=body)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        graph.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    responses.update(
        {
            ("GET", "/v25.0/oauth/access_token"): (
                200,
                {"access_token": "EAAG-business", "token_type": "bearer"},
            ),
            ("GET", "/v25.0/1001/phone_numbers"): (
                200,
                {
                    "data": [
                        {
                            "id": "2002",
                            "display_phone_number": "+971 50 000 0001",
                            "verified_name": "Sara Realty",
                            "quality_rating": "GREEN",
                        }
                    ]
                },
            ),
            ("POST", "/v25.0/1001/subscribed_apps"): (200, {"success": True}),
            ("POST", "/v25.0/2002/smb_app_data"): (
                200,
                {"messaging_product": "whatsapp", "request_id": "req-1"},
            ),
            ("POST", "/v25.0/2002/register"): (200, {"success": True}),
            ("GET", "/v25.0/2002"): (
                200,
                {"health_status": {"can_send_message": "AVAILABLE", "entities": []}, "id": "2002"},
            ),
        }
    )
    return SimpleMeta(calls, responses)


class SimpleMeta:
    def __init__(self, calls, responses):
        self.calls = calls
        self.responses = responses

    def paths(self):
        return [(c.method, c.url.path) for c in self.calls]


def request(event="FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING", **update):
    c = config()
    return SignupComplete(
        state=connections.signup_state("user-a", "org-a", c),
        code="short-lived-code",
        phone_number_id="2002",
        waba_id="1001",
        business_id="3003",
        event=event,
        **update,
    )


async def test_coexistence_signup_exchanges_subscribes_and_requests_contacts_once(db, meta):
    c = config()
    row = await connections.complete_signup(
        db, user_id="user-a", organization_id="org-a", request=request(), config=c
    )
    assert meta.paths() == [
        ("GET", "/v25.0/oauth/access_token"),
        ("GET", "/v25.0/1001/phone_numbers"),
        ("POST", "/v25.0/1001/subscribed_apps"),
        ("POST", "/v25.0/2002/smb_app_data"),
        ("GET", "/v25.0/2002"),
    ]
    exchange = parse_qs(meta.calls[0].url.query.decode())
    assert exchange == {
        "client_id": ["1723271579129715"],
        "client_secret": ["app-secret"],
        "code": ["short-lived-code"],
    }
    assert meta.calls[2].headers["authorization"] == "Bearer EAAG-business"
    assert json.loads(meta.calls[3].content) == {
        "messaging_product": "whatsapp",
        "sync_type": "smb_app_state_sync",
    }
    # Message history is never requested.
    assert all(b"history" not in call.content for call in meta.calls)
    assert row.status == "connected" and row.onboarding_type == "coexistence"
    assert (row.user_id, row.organization_id, row.account_id) == ("user-a", "org-a", "1001")
    assert row.display_name == "Sara Realty"
    assert row.display_phone_number == "+971 50 000 0001"
    assert row.enabled is False  # automation starts only after the block-list step
    assert row.access_token_encrypted != "EAAG-business"
    assert decrypt_token(row.access_token_encrypted, c) == "EAAG-business"
    assert row.contacts_sync_requested_at is not None
    assert row.connected_at is not None  # starts Meta's 24-hour contacts sync window
    assert row.health == {"can_send_message": "AVAILABLE", "errors": []}

    # Reconnecting the same number does not request the one-time contacts sync again.
    meta.calls.clear()
    await connections.complete_signup(
        db, user_id="user-a", organization_id="org-a", request=request(), config=c
    )
    assert ("POST", "/v25.0/2002/smb_app_data") not in meta.paths()
    assert len(db.rows) == 1


async def test_reconnect_after_disconnect_resyncs_contacts_and_keeps_automation_off(
    db, meta, monkeypatch
):
    # Disconnect deletes the synced contacts and blocks. Reconnecting the same number must
    # fetch them again and leave automation off until the agent re-reviews the block list.
    from app.whatsapp import customer_service

    async def no_op(*args, **kwargs):
        return None

    monkeypatch.setattr(customer_service, "invalidate_connection", no_op)
    monkeypatch.setattr(repository, "delete_contacts", no_op)
    c = config()
    row = await connections.complete_signup(
        db, user_id="user-a", organization_id="org-a", request=request(), config=c
    )
    row.contacts_synced_at = row.contacts_sync_requested_at
    row.enabled = True  # the agent reviewed blocks and switched automation on

    await connections.disconnect(db, row, reason="agent_disconnected")
    assert row.contacts_sync_requested_at is None and row.contacts_synced_at is None

    meta.calls.clear()
    row = await connections.complete_signup(
        db, user_id="user-a", organization_id="org-a", request=request(), config=c
    )
    assert ("POST", "/v25.0/2002/smb_app_data") in meta.paths()
    assert row.contacts_sync_requested_at is not None and row.contacts_synced_at is None
    assert row.enabled is False


async def test_reconnect_of_a_row_disconnected_before_the_fix_still_resyncs(db, meta):
    # Rows disconnected by older code kept their sync timestamps.
    c = config()
    row = await connections.complete_signup(
        db, user_id="user-a", organization_id="org-a", request=request(), config=c
    )
    row.status, row.enabled, row.access_token_encrypted = "disconnected", True, None
    row.contacts_synced_at = row.contacts_sync_requested_at
    meta.calls.clear()
    row = await connections.complete_signup(
        db, user_id="user-a", organization_id="org-a", request=request(), config=c
    )
    assert ("POST", "/v25.0/2002/smb_app_data") in meta.paths()
    assert row.contacts_synced_at is None and row.enabled is False


async def test_cloud_api_signup_registers_the_number_and_skips_contacts(db, meta):
    row = await connections.complete_signup(
        db, user_id="user-a", organization_id="org-a", request=request("FINISH"), config=config()
    )
    paths = meta.paths()
    assert ("POST", "/v25.0/2002/register") in paths
    assert ("POST", "/v25.0/2002/smb_app_data") not in paths
    body = json.loads(next(c for c in meta.calls if c.url.path.endswith("/register")).content)
    assert body["messaging_product"] == "whatsapp" and len(body["pin"]) == 6
    assert row.onboarding_type == "cloud_api"


async def test_phone_number_outside_the_granted_waba_is_rejected_and_nothing_stored(db, meta):
    meta.responses[("GET", "/v25.0/1001/phone_numbers")] = (200, {"data": [{"id": "2999"}]})
    with pytest.raises(HTTPException) as denied:
        await connections.complete_signup(
            db, user_id="user-a", organization_id="org-a", request=request(), config=config()
        )
    assert denied.value.status_code == 403
    assert db.rows == []
    assert ("POST", "/v25.0/1001/subscribed_apps") not in meta.paths()


async def test_rejected_code_fails_without_storing(db, meta):
    meta.responses[("GET", "/v25.0/oauth/access_token")] = (400, {"error": {"code": 100}})
    with pytest.raises(HTTPException) as failed:
        await connections.complete_signup(
            db, user_id="user-a", organization_id="org-a", request=request(), config=config()
        )
    assert failed.value.status_code == 502
    assert db.rows == []


async def test_forged_or_foreign_state_is_rejected_before_calling_meta(db, meta):
    forged = request().model_copy(
        update={"state": connections.signup_state("user-b", "org-b", config())}
    )
    with pytest.raises(HTTPException) as denied:
        await connections.complete_signup(
            db, user_id="user-a", organization_id="org-a", request=forged, config=config()
        )
    assert denied.value.status_code == 400
    assert meta.calls == []


async def test_number_owned_by_another_agent_is_not_taken_over(db, meta):
    db.rows.append(
        WhatsAppConnection(
            user_id="user-b",
            organization_id="org-b",
            phone_number_id="2002",
            account_id="1001",
            display_name="B",
        )
    )
    with pytest.raises(HTTPException) as conflict:
        await connections.complete_signup(
            db, user_id="user-a", organization_id="org-a", request=request(), config=config()
        )
    assert conflict.value.status_code == 409
    assert meta.calls == []


@pytest.mark.parametrize(
    "missing",
    [
        "WHATSAPP_APP_ID",
        "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID",
        "WHATSAPP_APP_SECRET",
        "WHATSAPP_TOKEN_ENCRYPTION_KEY",
    ],
)
async def test_signup_is_not_configured_without_required_settings(db, meta, missing):
    c = config(**{missing: None})
    assert missing in connections.signup_settings(c)["missing"]
    assert connections.signup_settings(c)["configured"] is False
    with pytest.raises(HTTPException) as unavailable:
        await connections.complete_signup(
            db, user_id="user-a", organization_id="org-a", request=request(), config=c
        )
    assert unavailable.value.status_code == 503
    assert meta.calls == []


def test_signup_settings_expose_only_public_values():
    values = connections.signup_settings(config())
    assert values["configured"] is True
    assert values["app_id"] == "1723271579129715"
    assert values["config_id"] == "555"
    assert values["extras"]["featureType"] == "whatsapp_business_app_onboarding"
    assert "app-secret" not in json.dumps(values)
    assert KEY not in json.dumps(values)


async def test_signup_state_cannot_be_reused(db, meta, used_states):
    c = config()
    replay = request()
    await connections.complete_signup(
        db, user_id="user-a", organization_id="org-a", request=replay, config=c
    )
    calls_after_first = len(meta.calls)
    with pytest.raises(HTTPException) as reused:
        await connections.complete_signup(
            db, user_id="user-a", organization_id="org-a", request=replay, config=c
        )
    assert reused.value.status_code == 400
    assert len(meta.calls) == calls_after_first


async def test_used_state_record_expires_with_the_state(db, meta, used_states):
    await connections.complete_signup(
        db, user_id="user-a", organization_id="org-a", request=request(), config=config()
    )
    (ttl,) = used_states.keys.values()
    assert 0 < ttl <= connections.STATE_TTL_SECONDS


async def test_each_issued_state_is_distinct():
    c = config()
    assert connections.signup_state("u", "o", c) != connections.signup_state("u", "o", c)


async def test_forged_state_does_not_burn_a_nonce(db, meta, used_states):
    forged = request().model_copy(update={"state": "9999999999.abc.deadbeef"})
    with pytest.raises(HTTPException):
        await connections.complete_signup(
            db, user_id="user-a", organization_id="org-a", request=forged, config=config()
        )
    assert used_states.keys == {}


async def test_signup_fails_closed_when_the_state_store_is_unavailable(db, meta, monkeypatch):
    monkeypatch.setattr(connections, "_state_store", lambda: None)
    with pytest.raises(HTTPException) as unavailable:
        await connections.complete_signup(
            db, user_id="user-a", organization_id="org-a", request=request(), config=config()
        )
    assert unavailable.value.status_code == 503
    assert meta.calls == []


def test_state_is_signed_with_a_key_derived_from_the_session_secret():
    c = config(SESSION_SECRET="s" * 40)
    state = connections.signup_state("u", "o", c)
    assert connections.valid_state(state, "u", "o", c)
    expires, nonce, _ = state.split(".")
    raw = connections.hmac.new(
        c.SESSION_SECRET.encode(),
        f"whatsapp-signup|u|o|{expires}|{nonce}".encode(),
        connections.hashlib.sha256,
    ).hexdigest()
    assert not connections.valid_state(f"{expires}.{nonce}.{raw}", "u", "o", c)
