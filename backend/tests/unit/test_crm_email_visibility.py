"""Email reaches only leads the sender may see (lead assignment): an agent their own and their
team pool's, a manager their teams', an administrator the organization's."""

import re

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.crm import assignment, brevo, email_pipeline
from app.crm.assignment import AssignmentScope
from app.crm.email_models import EmailSendCreate

AGENT = AssignmentScope(
    organization_id="org",
    user_id="omar",
    organization_admin=False,
    supervised_team_ids=frozenset(),
    team_members={},
    member_team_ids=frozenset({"north"}),
)


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def _filters_by_assignment(statement) -> bool:
    """True when the query restricts rows by who holds the lead (not just selects the column)."""
    return bool(re.search(r"assigned_user_id (=|IS)", _sql(statement)))


class CapturingDb:
    def __init__(self):
        self.statements = []

    async def exec(self, statement):
        self.statements.append(statement)

        class Rows:
            def all(self):
                return []

            def first(self):
                return None

            def one(self):
                return 0

        return Rows()


def test_lead_rows_apply_the_callers_visibility():
    assert not _filters_by_assignment(email_pipeline._lead_rows("org"))
    assert _filters_by_assignment(
        email_pipeline._lead_rows("org", visible=assignment.visible_clause(AGENT))
    )


async def test_listing_email_leads_is_scoped(monkeypatch):
    db = CapturingDb()
    monkeypatch.setattr(email_pipeline.email_store, "read", _empty_store, raising=False)
    try:
        await email_pipeline.list_email_leads(
            db,
            organization_id="org",
            search=None,
            intent=None,
            source=None,
            limit=10,
            offset=0,
            visible=assignment.visible_clause(AGENT),
        )
    except Exception:
        pass  # only the queries matter here
    assert db.statements, "no query was run"
    assert all(_filters_by_assignment(s) for s in db.statements)


async def test_sending_to_a_lead_outside_the_scope_finds_nothing(monkeypatch):
    db = CapturingDb()
    monkeypatch.setattr(brevo, "is_configured", lambda: True)
    with pytest.raises(HTTPException) as missing:
        await email_pipeline.send_emails(
            db,
            organization_id="org",
            user_id="omar",
            payload=EmailSendCreate(enquiry_ids=[99], subject="Hi", body="Hello"),
            visible=assignment.visible_clause(AGENT),
        )
    assert missing.value.status_code == 404
    assert _filters_by_assignment(db.statements[0])


async def _empty_store():
    return email_pipeline.EmailStoreData()


def _store_with_two_leads():
    from datetime import datetime, timezone

    from app.crm.email_models import CrmEmailInbound, CrmEmailSend

    now = datetime(2026, 11, 18, tzinfo=timezone.utc)

    def send(i, lead, by):
        return CrmEmailSend(
            id=i, organization_id="org", enquiry_id=lead, to_email=f"l{lead}@example.com",
            subject="s", body="b", sent_by_user_id=by, created_at=now, updated_at=now,
        )  # fmt: skip

    def mail(i, lead):
        return CrmEmailInbound(
            id=i, organization_id="org", enquiry_id=lead, from_email=f"l{lead}@example.com",
            subject="s", body="b", received_at=now, created_at=now,
        )  # fmt: skip

    return email_pipeline.EmailStoreData(
        sends=[send(1, 10, "omar"), send(2, 20, "sara"), send(3, None, "sara")],
        inbound=[mail(1, 10), mail(2, 20), mail(3, None)],
    )


@pytest.fixture
def store(monkeypatch):
    data = _store_with_two_leads()

    async def read():
        return data

    monkeypatch.setattr(email_pipeline.email_store, "read", read)
    return data


async def test_tracking_shows_only_sends_to_visible_leads_and_counts_them(store):
    everything = await email_pipeline.list_sends(
        organization_id="org", status=None, limit=50, offset=0
    )
    mine = await email_pipeline.list_sends(
        organization_id="org", status=None, limit=50, offset=0, visible_lead_ids={10}
    )
    assert len(everything.items) == 3
    assert [s.enquiry_id for s in mine.items] == [10]
    assert sum(mine.counts.values()) == 1


async def test_inbox_shows_only_mail_from_visible_leads(store):
    db = CapturingDb()
    everything = await email_pipeline.list_inbound(db, organization_id="org", limit=50, offset=0)
    mine = await email_pipeline.list_inbound(
        db, organization_id="org", limit=50, offset=0, visible_lead_ids={20}
    )
    assert everything.total == 3
    assert [m.enquiry_id for m in mine.items] == [20] and mine.total == 1
