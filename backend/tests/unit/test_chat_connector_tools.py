"""Assistant read tools for the calendar and lead email: the caller's own rows only, bounded,
and their evidence re-checked by access."""

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.chat import connector_tools
from app.chat.dependencies import ChatDependencies


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class Db:
    def __init__(self, rows=(), connection=None):
        self.rows, self.connection, self.statements = list(rows), connection, []

    async def exec(self, statement):
        self.statements.append(statement)
        return Rows(self.rows)

    async def get(self, model, key):
        return self.connection


def install(monkeypatch, db):
    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(connector_tools, "get_db_session", session)
    monkeypatch.setattr(connector_tools, "asynccontextmanager", lambda f: f)


def ctx():
    return SimpleNamespace(deps=ChatDependencies("omar", "org"), tool_call_id="t", tool_name="x")


def event(i, day):
    return SimpleNamespace(
        id=i, title=f"Viewing {i}", event_date=day, event_time="10:00", event_end_date=None,
        event_end_time="11:00", all_day=False, kind="viewing", lead_id=7, location="Marina",
        meet_link=None, done=False, google_sync_status="synced",
    )  # fmt: skip


async def test_calendar_reads_only_the_callers_events_and_bounds_the_range(monkeypatch):
    from app.crm import calendar_service

    monkeypatch.setattr(calendar_service, "configured", lambda: True)
    db = Db(rows=[event(1, date(2026, 11, 20))], connection=object())
    install(monkeypatch, db)
    c = ctx()

    result = await connector_tools.query_my_calendar(c, date(2026, 11, 1), date(2027, 6, 1))

    sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert "crm_calendar_events.organization_id =" in sql and "crm_calendar_events.user_id =" in sql
    params = db.statements[0].compile(dialect=postgresql.dialect()).params
    assert "omar" in params.values() and "org" in params.values()
    assert result["range"] == {"start": "2026-11-01", "end": "2027-01-02"}  # 62 days at most
    assert result["google_calendar_connected"] is True
    assert result["events"][0]["on_google"] is True and result["events"][0]["lead_id"] == 7
    assert c.deps.evidence == [{"private": True, "type": "calendar_lookup"}]


async def test_calendar_says_when_more_events_exist(monkeypatch):
    from app.crm import calendar_service

    monkeypatch.setattr(calendar_service, "configured", lambda: False)
    rows = [event(i, date(2026, 11, 20)) for i in range(connector_tools.MAX_EVENTS + 1)]
    install(monkeypatch, Db(rows=rows))
    result = await connector_tools.query_my_calendar(ctx(), date(2026, 11, 1), date(2026, 11, 30))
    assert result["truncated"] is True and len(result["events"]) == connector_tools.MAX_EVENTS
    assert result["google_calendar_connected"] is False


async def test_lead_emails_refuse_a_lead_the_caller_does_not_hold(monkeypatch):
    from app.assistant_actions import repository
    from app.crm import email_pipeline

    async def not_mine(db, **kwargs):
        return None

    async def thread(**kwargs):
        raise AssertionError("must not read another agent's mail")

    install(monkeypatch, Db())
    monkeypatch.setattr(repository, "own_lead", not_mine)
    monkeypatch.setattr(email_pipeline, "lead_thread", thread)
    c = ctx()
    result = await connector_tools.query_my_lead_emails(c, 8)
    assert result == {"available": False, "reason": "Own lead not found"}
    assert c.deps.evidence == []


async def test_lead_emails_show_the_newest_ten(monkeypatch):
    from app.assistant_actions import repository
    from app.crm import email_pipeline
    from app.crm.email_models import EmailThreadItem

    async def mine(db, **kwargs):
        return object()

    async def thread(*, organization_id, enquiry_id):
        assert (organization_id, enquiry_id) == ("org", 7)
        return [
            EmailThreadItem(
                direction="out" if i % 2 else "in",
                id=i,
                subject=f"S{i}",
                body="b",
                at=datetime(2026, 11, 1 + i, tzinfo=timezone.utc),
                status=None,
                counterpart="x",
            )  # fmt: skip
            for i in range(12)
        ]

    install(monkeypatch, Db())
    monkeypatch.setattr(repository, "own_lead", mine)
    monkeypatch.setattr(email_pipeline, "lead_thread", thread)
    c = ctx()
    result = await connector_tools.query_my_lead_emails(c, 7)
    assert result["total"] == 12 and len(result["emails"]) == 10
    assert result["emails"][0]["subject"] == "S11"  # newest first
    assert c.deps.evidence == [{"private": True, "type": "lead_email_thread", "lead_id": 7}]


async def test_evidence_is_rechecked_by_access(monkeypatch):
    from app.assistant_actions import repository

    holder = {"lead": object()}

    async def own(db, **kwargs):
        return holder["lead"]

    monkeypatch.setattr(repository, "own_lead", own)
    check = connector_tools.evidence_still_accessible
    owner = {"user_id": "omar", "organization_id": "org"}
    assert await check(None, {"type": "calendar_lookup"}, **owner)
    assert await check(None, {"type": "lead_email_thread", "lead_id": 7}, **owner)
    holder["lead"] = None  # the lead was reassigned
    assert not await check(None, {"type": "lead_email_thread", "lead_id": 7}, **owner)
    assert not await check(None, {"type": "something_else"}, **owner)
