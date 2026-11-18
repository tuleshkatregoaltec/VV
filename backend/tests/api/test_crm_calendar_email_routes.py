"""Calendar and email routes: who may reach them, and that lead assignment holds at the route.

Google, Brevo and the assignment lookups are stubbed; the services themselves are covered by
test_crm_calendar_oauth, test_crm_email_visibility and test_crm_brevo.
"""

import logging
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import app.postgres.models  # noqa: F401 - registers every table
from app.config import settings
from app.crm import assignment, calendar_service, connector_public_router, email_pipeline
from app.crm import router as crm_router
from app.crm.assignment import AssignmentScope
from app.crm.email_models import EmailSendListResponse
from app.organization.models import Organization
from app.postgres import get_db_session

# The mocked signed-in user (tests/conftest.py): user "test-user-id", organization "1".
USER, ORG = "test-user-id", "1"


def _scope(admin: bool) -> AssignmentScope:
    return AssignmentScope(
        organization_id=ORG,
        user_id=USER,
        organization_admin=admin,
        supervised_team_ids=frozenset(),
        team_members={},
        member_team_ids=frozenset(),
    )


@pytest.fixture(autouse=True)
def no_postgres_actor_context(monkeypatch):
    """CRM routes stamp each transaction with set_config, which SQLite lacks."""

    async def skip(db):
        return None

    monkeypatch.setattr("app.crm.router.apply_actor_context", skip)


@pytest.fixture
async def db(client):
    from app.main import app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Organization(id=ORG, name=ORG))
        await session.commit()

        async def override():
            yield session

        app.dependency_overrides[get_db_session] = override
        yield session
    await engine.dispose()


@pytest.fixture
def agent(monkeypatch):
    """The signed-in user is an agent who may see lead 7 only."""

    async def load_scope(db, organization_id, user_id):
        return _scope(admin=False)

    async def load_visible(db, scope, enquiry_id, *, lock=False):
        if enquiry_id != 7:
            raise HTTPException(status_code=404, detail="Inbound enquiry not found")
        return type("Lead", (), {"id": 7, "contact_id": 1})()

    async def visible_ids(db, scope, ids):
        return {i for i in ids if i == 7}

    monkeypatch.setattr(assignment, "load_scope", load_scope)
    monkeypatch.setattr(assignment, "load_visible", load_visible)
    monkeypatch.setattr(assignment, "visible_ids", visible_ids)


@pytest.fixture
def calls(monkeypatch):
    """Records service calls the routes make instead of reaching Google or the store."""
    seen: list[tuple[str, dict]] = []

    def record(name, result=None):
        async def fn(*args, **kwargs):
            seen.append((name, kwargs))
            return result

        return fn

    status = {"configured": True, "connected": True, "email": "agent@example.com"}
    monkeypatch.setattr(calendar_service, "finish_connection", record("finish"))
    monkeypatch.setattr(calendar_service, "connection_status", record("status", status))
    monkeypatch.setattr(calendar_service, "create_event", record("create_event"))
    empty = EmailSendListResponse(items=[], total=0, counts={})
    monkeypatch.setattr(crm_router, "list_sends", record("list_sends", empty))
    monkeypatch.setattr(crm_router, "delete_send", record("delete_send"))
    monkeypatch.setattr(crm_router, "lead_thread", record("lead_thread", []))

    async def no_store():
        return email_pipeline.EmailStoreData(
            sends=[_send(1, 7), _send(2, 8)],
        )

    monkeypatch.setattr(crm_router.email_store, "read", no_store)
    return seen


def _send(i: int, lead: int):
    from datetime import datetime, timezone

    from app.crm.email_models import CrmEmailSend

    now = datetime(2026, 11, 18, tzinfo=timezone.utc)
    return CrmEmailSend(
        id=i, organization_id=ORG, enquiry_id=lead, to_email=f"l{lead}@example.com",
        subject="s", body="b", sent_by_user_id=USER, created_at=now, updated_at=now,
    )  # fmt: skip


# ── who may reach them ──


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/crm/calendar/google"),
        ("POST", "/api/v1/crm/calendar/google/connect"),
        ("POST", "/api/v1/crm/calendar/google/complete"),
        ("GET", "/api/v1/crm/calendar/events?start=2026-11-01&end=2026-11-30"),
        ("POST", "/api/v1/crm/calendar/events"),
        ("GET", "/api/v1/crm/email/status"),
        ("GET", "/api/v1/crm/email/leads"),
        ("POST", "/api/v1/crm/email/send"),
        ("GET", "/api/v1/crm/email/sends"),
        ("GET", "/api/v1/crm/email/inbound"),
    ],
)
async def test_calendar_and_email_require_sign_in(client_no_auth, method, path):
    assert (await client_no_auth.request(method, path, json={})).status_code in {401, 403}


# ── Google sign-in ──


async def test_google_callback_hands_code_to_the_page_without_exchanging_it(client_no_auth):
    response = await client_no_auth.get(
        "/api/v1/crm/calendar/google/callback", params={"code": "abc", "state": "s" * 43}
    )
    assert response.status_code == 303
    target = urlparse(response.headers["location"])
    assert target.path == "/crm/calendar" and target.query == ""  # fragment only, never query
    assert parse_qs(target.fragment) == {"google_code": ["abc"], "google_state": ["s" * 43]}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize(
    "params", [{"error": "access_denied"}, {"code": "abc"}, {"code": "x" * 3000, "state": "s"}]
)
async def test_google_callback_reports_errors(client_no_auth, params):
    response = await client_no_auth.get("/api/v1/crm/calendar/google/callback", params=params)
    assert parse_qs(urlparse(response.headers["location"]).fragment) == {
        "google_calendar": ["error"]
    }


async def test_completion_is_bound_to_the_signed_in_user(client, db, calls):
    response = await client.post(
        "/api/v1/crm/calendar/google/complete", json={"code": "abc", "state": "s" * 43}
    )
    assert response.status_code == 200
    assert response.json()["connected"] is True
    name, kwargs = calls[0]
    assert name == "finish"
    assert (kwargs["user_id"], kwargs["organization_id"]) == (USER, ORG)
    assert (kwargs["code"], kwargs["state"]) == ("abc", "s" * 43)


async def test_a_refused_completion_is_a_400(client, db, monkeypatch):
    async def refuse(db, **kwargs):
        raise ValueError("This Google sign-in was started by another account; connect again")

    monkeypatch.setattr(calendar_service, "finish_connection", refuse)
    response = await client.post(
        "/api/v1/crm/calendar/google/complete", json={"code": "abc", "state": "s" * 43}
    )
    assert response.status_code == 400
    assert "another account" in response.json()["detail"]


async def test_connect_reports_unavailable_sign_in_as_503(client, db, monkeypatch):
    async def down(user_id, organization_id):
        raise RuntimeError("Could not start Google sign-in; try again")

    monkeypatch.setattr(calendar_service, "authorization_url", down)
    assert (await client.post("/api/v1/crm/calendar/google/connect")).status_code == 503


# ── lead assignment at the route ──

EVENT = {"title": "Call", "date": "2026-11-20", "time": "10:00", "kind": "follow_up"}


async def test_an_event_cannot_be_linked_to_a_lead_outside_the_scope(client, db, agent, calls):
    response = await client.post("/api/v1/crm/calendar/events", json={**EVENT, "lead_id": 8})
    assert response.status_code == 404
    assert not [c for c in calls if c[0] == "create_event"]


async def test_a_viewing_cannot_be_booked_for_a_lead_outside_the_scope(client, db, agent, calls):
    response = await client.post(
        "/api/v1/crm/calendar/viewings/8", json={"date": "2026-11-20", "time": "10:00"}
    )
    assert response.status_code == 404
    assert not [c for c in calls if c[0] == "create_event"]


async def test_a_lead_thread_outside_the_scope_is_not_found(client, db, agent, calls):
    assert (await client.get("/api/v1/crm/email/leads/8/thread")).status_code == 404
    assert (await client.get("/api/v1/crm/email/leads/7/thread")).status_code == 200
    assert [c[1]["enquiry_id"] for c in calls if c[0] == "lead_thread"] == [7]


async def test_tracking_and_delete_are_limited_to_the_agents_leads(client, db, agent, calls):
    assert (await client.get("/api/v1/crm/email/sends")).status_code == 200
    assert (await client.delete("/api/v1/crm/email/sends/2")).status_code == 204
    by_name = dict(calls)
    assert by_name["list_sends"]["visible_lead_ids"] == {7}
    assert by_name["delete_send"]["visible_lead_ids"] == {7}


async def test_an_administrator_is_not_limited(client, db, calls, monkeypatch):
    async def admin(db, organization_id, user_id):
        return _scope(admin=True)

    monkeypatch.setattr(assignment, "load_scope", admin)
    assert (await client.get("/api/v1/crm/email/sends")).status_code == 200
    assert dict(calls)["list_sends"]["visible_lead_ids"] is None


# ── Brevo webhooks ──


async def test_brevo_webhook_refuses_without_a_configured_secret(client_no_auth, monkeypatch):
    monkeypatch.setattr(settings, "BREVO_WEBHOOK_SECRET", None)
    response = await client_no_auth.post("/api/v1/crm/email/brevo-webhook?secret=x", json={})
    assert response.status_code == 503


async def test_brevo_webhook_refuses_a_wrong_secret(client_no_auth, monkeypatch):
    monkeypatch.setattr(settings, "BREVO_WEBHOOK_SECRET", "right-secret")
    for query in ("", "?secret=wrong"):
        response = await client_no_auth.post(f"/api/v1/crm/email/brevo-webhook{query}", json={})
        assert response.status_code == 401


async def test_brevo_webhook_accepts_the_right_secret(client_no_auth, monkeypatch):
    monkeypatch.setattr(settings, "BREVO_WEBHOOK_SECRET", "right-secret")

    async def receive(*, secret, payload):
        email_pipeline._check_secret(secret)
        return 0

    monkeypatch.setattr(connector_public_router, "receive_webhook", receive)
    response = await client_no_auth.post(
        "/api/v1/crm/email/brevo-webhook?secret=right-secret", json={"event": "delivered"}
    )
    assert response.status_code == 200 and response.json() == {"ok": True, "applied": 0}


def test_secrets_and_google_codes_are_kept_out_of_the_access_log():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', None, None
    )
    record.args = (
        "1.2.3.4",
        "GET",
        "/api/v1/crm/calendar/google/callback?code=4/abc&state=xyz&scope=email",
        "1.1",
        303,
    )
    connector_public_router.RedactConnectorSecrets().filter(record)
    line = record.getMessage()
    assert "4/abc" not in line and "xyz" not in line
    assert "scope=email" in line
