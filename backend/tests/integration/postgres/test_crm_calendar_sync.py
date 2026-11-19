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


# ── Role-scoped reads: stored rows only, never another user's Google account ──


def _stored(org: str, user: str, title: str, **values) -> CrmCalendarEvent:
    return CrmCalendarEvent(
        organization_id=org,
        user_id=user,
        title=title,
        event_date=values.pop("event_date", date(2026, 11, 20)),
        event_time="10:00",
        event_end_time="11:00",
        updated_at=datetime.now(timezone.utc),
        **values,
    )


NOV = (date(2026, 11, 1), date(2026, 11, 30))


async def test_stored_events_reads_only_requested_owners(pg_session):
    org, u1, u2, u3 = (str(uuid4()) for _ in range(4))
    pg_session.add_all(
        [
            _stored(org, u1, "u1"),
            _stored(org, u2, "u2"),
            _stored(org, u3, "u3"),
            _stored(org, u1, "u1 done", done=True),
        ]
    )
    await pg_session.commit()

    rows = await calendar_service.stored_events(
        pg_session, organization_id=org, user_ids=frozenset({u1, u2}), start=NOV[0], end=NOV[1]
    )

    assert sorted(r.title for r in rows) == ["u1", "u2"]


async def test_other_organization_rows_never_returned(pg_session):
    org_a, org_b, u1 = (str(uuid4()) for _ in range(3))
    pg_session.add_all([_stored(org_a, u1, "in A"), _stored(org_b, u1, "in B")])
    await pg_session.commit()

    rows = await calendar_service.stored_events(
        pg_session, organization_id=org_a, user_ids=frozenset({u1}), start=NOV[0], end=NOV[1]
    )

    assert [r.title for r in rows] == ["in A"]


async def test_shared_repeating_private_event_is_redacted_per_occurrence(pg_session):
    from app.crm.calendar_visibility import serialize_for_viewer

    org, u1, u2 = (str(uuid4()) for _ in range(3))
    pg_session.add(
        _stored(
            org,
            u2,
            "Doctor",
            event_date=date(2026, 11, 2),
            repeat="weekly",
            visibility="private",
            detail="secret",
        )
    )
    await pg_session.commit()
    rows = await calendar_service.stored_events(
        pg_session, organization_id=org, user_ids=frozenset({u1, u2}), start=NOV[0], end=NOV[1]
    )

    items = calendar_service.expand_occurrences(
        rows,
        NOV[0],
        NOV[1],
        lambda r: serialize_for_viewer(r, viewer_id=u1, owner_name="U2", lead_visible=True),
    )

    assert [i["date"] for i in items] == [
        "2026-11-02",
        "2026-11-09",
        "2026-11-16",
        "2026-11-23",
        "2026-11-30",
    ]
    assert all(i["title"] == "Busy" and i["detail"] == "" for i in items)


async def test_events_between_stays_own_only(pg_session):
    org, u1, u2 = (str(uuid4()) for _ in range(3))
    pg_session.add_all([_stored(org, u1, "mine"), _stored(org, u2, "colleague")])
    await pg_session.commit()

    rows = await calendar_service.events_between(
        pg_session, user_id=u1, organization_id=org, start=NOV[0], end=NOV[1], limit=10
    )

    assert [r.title for r in rows] == ["mine"]
