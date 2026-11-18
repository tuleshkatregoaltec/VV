from datetime import date, datetime, timezone
from uuid import uuid4

from sqlmodel import select

from app.crm import calendar_service
from app.crm.calendar_models import CrmCalendarConnection, CrmCalendarEvent


async def test_full_sync_drops_rows_google_no_longer_lists(pg_session, monkeypatch):
    """Google omits purged events (and another account's events) without a "cancelled" entry,
    so only a full sync can tell they are gone. The calendar must not keep showing them, but a
    CRM repeating series (listed by Google as instances) and unsynced local edits must survive."""
    now = datetime.now(timezone.utc)
    org, user = str(uuid4()), str(uuid4())
    pg_session.add(
        CrmCalendarConnection(
            organization_id=org,
            user_id=user,
            google_email="agent@example.com",
            refresh_token_encrypted="unused",
            updated_at=now,
        )
    )

    def row(title: str, google_id: str | None, status: str, repeat: str = "none"):
        event = CrmCalendarEvent(
            organization_id=org,
            user_id=user,
            title=title,
            event_date=date(2026, 10, 30),
            event_time="10:00",
            repeat=repeat,
            google_event_id=google_id,
            google_sync_status=status,
            updated_at=now,
        )
        pg_session.add(event)
        return event

    row("Purged in Google", "gone", "synced")
    row("Weekly series", "series", "synced", repeat="weekly")
    row("Still in Google", "kept", "synced")
    row("Edit not pushed yet", "gone-too", "pending")
    await pg_session.commit()

    async def fake_token(_connection):
        return "token"

    async def fake_google(method, url, *, token, params=None, body=None):
        return {
            "items": [
                {
                    "id": "series_20261030T060000Z",
                    "recurringEventId": "series",
                    "extendedProperties": {"private": {"crmEventId": "1"}},
                },
                {
                    "id": "kept",
                    "summary": "Still in Google",
                    "start": {"dateTime": "2026-10-30T10:00:00+04:00"},
                    "end": {"dateTime": "2026-10-30T11:00:00+04:00"},
                },
            ],
            "nextSyncToken": "next",
        }

    monkeypatch.setattr(calendar_service, "_access_token", fake_token)
    monkeypatch.setattr(calendar_service, "_google", fake_google)

    await calendar_service.sync_google_events(pg_session, user_id=user, organization_id=org)

    titles = set(
        (
            await pg_session.exec(
                select(CrmCalendarEvent.title).where(CrmCalendarEvent.user_id == user)
            )
        ).all()
    )
    assert titles == {"Weekly series", "Still in Google", "Edit not pushed yet"}
    connection = await pg_session.get(CrmCalendarConnection, (org, user))
    assert connection.sync_token == "next"
