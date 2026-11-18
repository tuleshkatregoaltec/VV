import base64
import hashlib
import json
import secrets
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from cryptography.fernet import Fernet, InvalidToken
from dateutil.rrule import DAILY, MONTHLY, WEEKLY, YEARLY, rrule
from sqlalchemy import Text, and_, cast, func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.core.decorators import cache
from app.crm.calendar_models import CrmCalendarConnection, CrmCalendarEvent

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_SCOPES = "openid email https://www.googleapis.com/auth/calendar.events"
VALID_KINDS = {"viewing", "call", "follow_up", "deal_date", "deadline"}
BUSINESS_TZ = ZoneInfo("Asia/Dubai")


def configured() -> bool:
    return bool(
        settings.GOOGLE_CALENDAR_CLIENT_ID
        and settings.GOOGLE_CALENDAR_CLIENT_SECRET
        and settings.GOOGLE_CALENDAR_REDIRECT_URI
        and settings.GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY
    )


def _fernet() -> Fernet:
    key = settings.GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY
    if not key:
        raise RuntimeError("Google Calendar token encryption is not configured")
    return Fernet(key.encode())


# Sign-in (PR 50 review finding 2): the link carries only a random, single-use state; the PKCE
# verifier and the identity that started it stay on the server for ten minutes.
OAUTH_TTL_SECONDS = 600


def oauth_key(state: str) -> str:
    return f"crm:google-calendar:oauth:{state}"


async def authorization_url(user_id: str, organization_id: str) -> str:
    if not configured():
        raise RuntimeError("Google Calendar integration is not configured")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_urlsafe(32)
    stored = await cache.put_new(
        oauth_key(state),
        {"user_id": user_id, "organization_id": organization_id, "verifier": verifier},
        expire=OAUTH_TTL_SECONDS,
    )
    if not stored:
        raise RuntimeError("Could not start Google sign-in; try again")
    return (
        GOOGLE_AUTH
        + "?"
        + urlencode(
            {
                "client_id": settings.GOOGLE_CALENDAR_CLIENT_ID,
                "redirect_uri": str(settings.GOOGLE_CALENDAR_REDIRECT_URI),
                "response_type": "code",
                "scope": GOOGLE_SCOPES,
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": state,
                "code_challenge": challenge.rstrip(b"=").decode(),
                "code_challenge_method": "S256",
            }
        )
    )


async def _exchange_code(code: str, verifier: str) -> tuple[dict, str]:
    """Google's tokens for this code, and the connected account's email."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CALENDAR_CLIENT_ID,
                "client_secret": settings.GOOGLE_CALENDAR_CLIENT_SECRET,
                "redirect_uri": str(settings.GOOGLE_CALENDAR_REDIRECT_URI),
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
        if response.is_error:
            raise ValueError("Google authorization failed; connect again")
        token = response.json()
        if not token.get("refresh_token"):
            raise ValueError("Google did not return a refresh token; reconnect and grant access")
        profile = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        email = profile.json().get("email") if not profile.is_error else None
        if not email:
            raise ValueError("Could not read the connected Google account")
    return token, email


async def _store_connection(
    db: AsyncSession, *, user_id: str, organization_id: str, email: str, refresh_token: str
) -> None:
    now = datetime.now(timezone.utc)
    encrypted = _fernet().encrypt(refresh_token.encode()).decode()
    connection = await db.get(CrmCalendarConnection, (organization_id, user_id))
    if connection is None:
        db.add(
            CrmCalendarConnection(
                organization_id=organization_id,
                user_id=user_id,
                google_email=email,
                refresh_token_encrypted=encrypted,
                updated_at=now,
            )
        )
    else:
        connection.google_email = email
        connection.refresh_token_encrypted = encrypted
        connection.sync_token = None
        connection.updated_at = now
    await db.commit()


async def finish_connection(
    db: AsyncSession, *, code: str, state: str, user_id: str, organization_id: str
) -> None:
    """Complete sign-in for the signed-in user who started it; each state works once."""
    if not configured():
        raise RuntimeError("Google Calendar integration is not configured")
    started = await cache.take(oauth_key(state))
    if not started:
        raise ValueError("Google sign-in expired or was already used; connect again")
    if started.get("user_id") != user_id or started.get("organization_id") != organization_id:
        raise ValueError("This Google sign-in was started by another account; connect again")
    token, email = await _exchange_code(code, started["verifier"])
    await _store_connection(
        db,
        user_id=user_id,
        organization_id=organization_id,
        email=email,
        refresh_token=token["refresh_token"],
    )


async def connection_status(db: AsyncSession, *, user_id: str, organization_id: str) -> dict:
    connection = await db.get(CrmCalendarConnection, (organization_id, user_id))
    return {
        "configured": configured(),
        "connected": connection is not None,
        "email": connection.google_email if connection else None,
    }


async def disconnect(db: AsyncSession, *, user_id: str, organization_id: str) -> None:
    connection = await db.get(CrmCalendarConnection, (organization_id, user_id))
    if connection:
        refresh_token = _fernet().decrypt(connection.refresh_token_encrypted.encode()).decode()
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://oauth2.googleapis.com/revoke",
                data={"token": refresh_token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if response.status_code >= 500:
            response.raise_for_status()
        await db.delete(connection)
        await db.commit()


async def _access_token(connection: CrmCalendarConnection) -> str:
    try:
        refresh_token = _fernet().decrypt(connection.refresh_token_encrypted.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Saved Google token could not be decrypted") from exc
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            GOOGLE_TOKEN,
            data={
                "client_id": settings.GOOGLE_CALENDAR_CLIENT_ID,
                "client_secret": settings.GOOGLE_CALENDAR_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if response.is_error:
        raise RuntimeError("Google Calendar authorization expired; reconnect the account")
    return response.json()["access_token"]


async def _google(
    method: str, url: str, *, token: str, params: dict | None = None, body: dict | None = None
) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.request(
            method,
            url,
            params=params,
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
    if response.status_code == 410:
        raise httpx.HTTPStatusError(
            "Google sync token expired", request=response.request, response=response
        )
    response.raise_for_status()
    return response.json() if response.content else {}


def _event_payload(event: CrmCalendarEvent) -> dict:
    all_day = event.all_day or event.event_time is None
    if not all_day:
        start = datetime.combine(
            event.event_date, time.fromisoformat(event.event_time), BUSINESS_TZ
        )
        end_date = event.event_end_date or event.event_date
        end_time = event.event_end_time
        end = (
            datetime.combine(end_date, time.fromisoformat(end_time), BUSINESS_TZ)
            if end_time
            else start + timedelta(hours=1)
        )
        interval = {
            "start": {"dateTime": start.isoformat(), "timeZone": str(BUSINESS_TZ)},
            "end": {"dateTime": end.isoformat(), "timeZone": str(BUSINESS_TZ)},
        }
    else:
        end_date = event.event_end_date or event.event_date
        interval = {
            "start": {"date": event.event_date.isoformat()},
            "end": {"date": (end_date + timedelta(days=1)).isoformat()},
        }
    payload = {
        "summary": event.title,
        "description": event.detail,
        "location": event.location or None,
        "visibility": event.visibility,
        "transparency": "transparent" if event.show_as == "free" else "opaque",
        "attendees": [{"email": email} for email in event.guests],
        "guestsCanModify": event.guests_can_modify,
        "guestsCanInviteOthers": event.guests_can_invite_others,
        "guestsCanSeeOtherGuests": event.guests_can_see_other_guests,
        "reminders": {
            "useDefault": event.reminders_use_default,
            "overrides": [{"method": "popup", "minutes": minutes} for minutes in event.reminders],
        },
        **interval,
    }
    if event.repeat != "none":
        payload["recurrence"] = [f"RRULE:FREQ={event.repeat.upper()}"]
    if event.meet and not event.meet_link:
        event.meet_request_id = event.meet_request_id or secrets.token_urlsafe(20)
        payload["conferenceData"] = {
            "createRequest": {
                "requestId": event.meet_request_id,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
    if event.google_event_id:
        # PATCH merges nested objects, so clear what an edit switched off.
        if all_day:
            payload["start"].update(dateTime=None, timeZone=None)
            payload["end"].update(dateTime=None, timeZone=None)
        else:
            payload["start"]["date"] = None
            payload["end"]["date"] = None
        if event.repeat == "none":
            payload["recurrence"] = []
        if not event.meet:
            payload["conferenceData"] = None
    # Sync reads the kind back from here, so it must follow edits.
    payload["extendedProperties"] = {"private": {"crmEventId": str(event.id), "kind": event.kind}}
    payload["extendedProperties"]["private"]["crmRevision"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()
    return payload


async def _push_event(event: CrmCalendarEvent, *, token: str) -> None:
    url = f"{GOOGLE_API}/calendars/primary/events"
    params = {"sendUpdates": "all", "conferenceDataVersion": 1}
    saved = None
    if event.google_event_id:
        try:
            saved = await _google(
                "PATCH",
                f"{url}/{event.google_event_id}",
                token=token,
                params=params,
                body=_event_payload(event),
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (404, 410):
                raise
            # Gone from Google (deleted there, or another account): create it again.
            event.google_event_id = None
            event.etag = None
            event.meet_link = None
            event.meet_request_id = secrets.token_urlsafe(20) if event.meet else None
    if saved is None:
        if event.id is None:
            raise ValueError("Persist calendar events before contacting Google")
        # Committed CRM identity makes the insert id stable across timeouts and retries.
        google_id = hashlib.sha256(
            f"vv-calendar:{event.organization_id}:{event.user_id}:{event.id}".encode()
        ).hexdigest()
        body = {**_event_payload(event), "id": google_id}
        try:
            saved = await _google("POST", url, token=token, params=params, body=body)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 409:
                raise
            # An earlier insert may have succeeded even though its response was lost.
            saved = await _google("GET", f"{url}/{google_id}", token=token)
            if saved.get("status") == "cancelled" or (
                (saved.get("extendedProperties") or {}).get("private", {}).get("crmEventId")
                != str(event.id)
            ):
                raise RuntimeError("Google event identity conflict") from exc
            if (saved.get("extendedProperties") or {}).get("private", {}).get("crmRevision") != (
                body["extendedProperties"]["private"]["crmRevision"]
            ):
                # The local intent may have changed after the ambiguous insert.
                # Reconcile that edit on the existing event, preserving its identity.
                event.google_event_id = google_id
                saved = await _google(
                    "PATCH",
                    f"{url}/{google_id}",
                    token=token,
                    params=params,
                    body=_event_payload(event),
                )
    event.google_event_id = saved["id"]
    event.etag = saved.get("etag")
    event.meet_link = saved.get("hangoutLink") or next(
        (
            point.get("uri")
            for point in (saved.get("conferenceData") or {}).get("entryPoints", [])
            if point.get("entryPointType") == "video"
        ),
        event.meet_link,
    )
    event.google_sync_status = "synced"
    event.updated_at = datetime.now(timezone.utc)


def _google_date_time(event: dict) -> tuple[date, str | None] | None:
    start = event.get("start") or {}
    if start.get("date"):
        return date.fromisoformat(start["date"]), None
    raw = start.get("dateTime")
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo:
        parsed = parsed.astimezone(BUSINESS_TZ)
    return parsed.date(), parsed.strftime("%H:%M")


def _google_repeat(event: dict) -> str:
    rules = event.get("recurrence") or []
    for rule in rules:
        if rule.startswith("RRULE:"):
            frequency = dict(part.split("=", 1) for part in rule[6:].split(";") if "=" in part).get(
                "FREQ"
            )
            repeat = (frequency or "").lower()
            if repeat in {"daily", "weekly", "monthly", "yearly"}:
                return repeat
    return "none"


async def _store_google_event(
    db: AsyncSession,
    *,
    event: dict,
    user_id: str,
    organization_id: str,
    sync_started_at: datetime | None = None,
) -> None:
    google_id = event.get("id")
    if not google_id:
        return
    existing = await db.exec(
        select(CrmCalendarEvent)
        .where(
            CrmCalendarEvent.organization_id == organization_id,
            CrmCalendarEvent.user_id == user_id,
            CrmCalendarEvent.google_event_id == google_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = existing.first()
    # Local edits own the row until a successful push; stale Google pages must not erase them.
    if row and (
        row.google_sync_status in {"pending", "error"}
        or (sync_started_at and row.updated_at.replace(tzinfo=timezone.utc) >= sync_started_at)
    ):
        return
    private = (event.get("extendedProperties") or {}).get("private") or {}
    recurring_event_id = event.get("recurringEventId")
    if not row and recurring_event_id:
        recurring_source = await db.exec(
            select(CrmCalendarEvent).where(
                CrmCalendarEvent.organization_id == organization_id,
                CrmCalendarEvent.user_id == user_id,
                CrmCalendarEvent.google_event_id == recurring_event_id,
            )
        )
        if recurring_source.first():
            return
    if not row and private.get("crmEventId"):
        try:
            source_id = int(private["crmEventId"])
        except (TypeError, ValueError):
            source_id = None
        if source_id is not None:
            source = await db.get(CrmCalendarEvent, source_id)
            if source and source.organization_id == organization_id and source.user_id == user_id:
                # Google expands recurring events into instances; keep our CRM series as one row.
                return
    if event.get("status") == "cancelled":
        if row:
            await db.delete(row)
        return
    when = _google_date_time(event)
    if when is None:
        return
    end = _google_date_time({"start": event.get("end") or {}})
    all_day = bool((event.get("start") or {}).get("date"))
    raw_reminders = event.get("reminders") or {}
    conference = event.get("conferenceData") or {}
    meet_link = event.get("hangoutLink") or next(
        (
            point.get("uri")
            for point in conference.get("entryPoints", [])
            if point.get("entryPointType") == "video"
        ),
        None,
    )
    kind = private.get("kind", "follow_up")
    values = {
        "title": event.get("summary") or "Google Calendar event",
        "event_date": when[0],
        "event_time": when[1],
        "event_end_date": end[0] - timedelta(days=1)
        if all_day and end
        else (end[0] if end else when[0]),
        "event_end_time": end[1] if end and not all_day else None,
        "all_day": all_day,
        "repeat": _google_repeat(event),
        "meet": bool(meet_link),
        "meet_link": meet_link,
        "location": event.get("location") or "",
        "reminders": [
            reminder["minutes"]
            for reminder in raw_reminders.get("overrides", [])[:5]
            if isinstance(reminder.get("minutes"), int)
        ],
        "reminders_use_default": bool(raw_reminders.get("useDefault", False)),
        "guests": [guest["email"] for guest in event.get("attendees", []) if guest.get("email")],
        "guests_can_modify": bool(event.get("guestsCanModify", False)),
        "guests_can_invite_others": bool(event.get("guestsCanInviteOthers", True)),
        "guests_can_see_other_guests": bool(event.get("guestsCanSeeOtherGuests", True)),
        "show_as": "free" if event.get("transparency") == "transparent" else "busy",
        "visibility": event.get("visibility", "default"),
        "kind": kind if kind in VALID_KINDS else "follow_up",
        "detail": event.get("description") or "",
        "etag": event.get("etag"),
        "google_sync_status": "synced",
        "updated_at": datetime.now(timezone.utc),
    }
    if row:
        for key, value in values.items():
            setattr(row, key, value)
    else:
        db.add(
            CrmCalendarEvent(
                organization_id=organization_id,
                user_id=user_id,
                google_event_id=google_id,
                **values,
            )
        )


async def sync_google_events(db: AsyncSession, *, user_id: str, organization_id: str) -> None:
    sync_started_at = datetime.now(timezone.utc)
    connection = await db.get(CrmCalendarConnection, (organization_id, user_id))
    if not connection:
        return
    token = await _access_token(connection)
    # No orderBy: Google returns no nextSyncToken for ordered lists, which forced a full
    # download on every load. Incremental requests must keep the same singleEvents/showDeleted.
    params: dict = {"maxResults": 2500, "singleEvents": "true", "showDeleted": "true"}
    full = not connection.sync_token
    if not full:
        params["syncToken"] = connection.sync_token
    seen: set[str] = set()
    try:
        while True:
            page = await _google(
                "GET", f"{GOOGLE_API}/calendars/primary/events", token=token, params=params
            )
            for event in page.get("items", []):
                seen.update(filter(None, (event.get("id"), event.get("recurringEventId"))))
                await _store_google_event(
                    db,
                    event=event,
                    user_id=user_id,
                    organization_id=organization_id,
                    sync_started_at=sync_started_at,
                )
            if page.get("nextPageToken"):
                params["pageToken"] = page["nextPageToken"]
                continue
            if page.get("nextSyncToken"):
                connection.sync_token = page["nextSyncToken"]
            break
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 410 and connection.sync_token:
            connection.sync_token = None
            await db.commit()
            return await sync_google_events(db, user_id=user_id, organization_id=organization_id)
        raise
    if full:
        # Google drops purged events (and a previous account's events) from the list without a
        # "cancelled" entry, so a full sync removes synced rows it no longer returns.
        stale = await db.exec(
            select(CrmCalendarEvent)
            .where(
                CrmCalendarEvent.organization_id == organization_id,
                CrmCalendarEvent.user_id == user_id,
                CrmCalendarEvent.google_sync_status == "synced",
                CrmCalendarEvent.updated_at < sync_started_at,
                CrmCalendarEvent.google_event_id.is_not(None),
                CrmCalendarEvent.google_event_id.not_in(seen),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        for row in stale.all():
            await db.delete(row)
    await db.commit()


async def _sync_pending(db: AsyncSession, *, connection: CrmCalendarConnection, token: str) -> None:
    rows = await db.exec(
        select(CrmCalendarEvent)
        .where(
            CrmCalendarEvent.organization_id == connection.organization_id,
            CrmCalendarEvent.user_id == connection.user_id,
            or_(
                CrmCalendarEvent.google_sync_status.in_(("pending", "error")),
                (CrmCalendarEvent.google_sync_status == "local")
                & CrmCalendarEvent.google_event_id.is_(None),
            ),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    for event in rows.all():
        try:
            await _push_event(event, token=token)
        except (httpx.HTTPError, RuntimeError, KeyError):
            event.google_sync_status = "error"
            continue
    await db.commit()


def serialize_event(event: CrmCalendarEvent) -> dict:
    return {
        "id": event.id,
        "date": event.event_date.isoformat(),
        "time": event.event_time,
        "end_date": (event.event_end_date or event.event_date).isoformat(),
        "end_time": event.event_end_time,
        "all_day": event.all_day or event.event_time is None,
        "repeat": event.repeat,
        "meet": event.meet,
        "meet_link": event.meet_link,
        "location": event.location,
        "reminders": event.reminders,
        "reminders_use_default": event.reminders_use_default,
        "guests": event.guests,
        "guests_can_modify": event.guests_can_modify,
        "guests_can_invite_others": event.guests_can_invite_others,
        "guests_can_see_other_guests": event.guests_can_see_other_guests,
        "show_as": event.show_as,
        "visibility": event.visibility,
        "kind": event.kind,
        "title": event.title,
        "detail": event.detail,
        "agent": "You",
        "lead_id": event.lead_id,
        "deal_id": None,
        "listing_id": event.listing_id,
        "owner_id": None,
        "context": None,
        "record": (
            {"kind": "lead", "id": str(event.lead_id), "label": event.title}
            if event.lead_id is not None
            else None
        ),
        "outcome": "Done" if event.done else None,
        "rescheduled_from": event.rescheduled_from,
        "google_sync_status": event.google_sync_status,
    }


async def list_events(
    db: AsyncSession, *, user_id: str, organization_id: str, start: date, end: date
) -> list[dict]:
    connection = await db.get(CrmCalendarConnection, (organization_id, user_id))
    if connection:
        await sync_google_events(db, user_id=user_id, organization_id=organization_id)
        connection = await db.get(CrmCalendarConnection, (organization_id, user_id))
        if connection:
            await _sync_pending(db, connection=connection, token=await _access_token(connection))
    rows = await db.exec(
        select(CrmCalendarEvent)
        .where(
            CrmCalendarEvent.organization_id == organization_id,
            CrmCalendarEvent.user_id == user_id,
            or_(
                and_(
                    CrmCalendarEvent.event_date <= end,
                    or_(
                        func.coalesce(CrmCalendarEvent.event_end_date, CrmCalendarEvent.event_date)
                        >= start,
                        CrmCalendarEvent.repeat != "none",
                    ),
                ),
                # Moved out of the range, but its old slot is still drawn there (struck through).
                cast(CrmCalendarEvent.rescheduled_from, Text) != "[]",
            ),
            CrmCalendarEvent.done.is_(False),
        )
        .order_by(CrmCalendarEvent.event_date, CrmCalendarEvent.event_time)
    )
    output = []
    frequencies = {"daily": DAILY, "weekly": WEEKLY, "monthly": MONTHLY, "yearly": YEARLY}
    for row in rows.all():
        if row.repeat == "none":
            in_range = row.event_date <= end and (row.event_end_date or row.event_date) >= start
            if in_range or any(
                start.isoformat() <= slot["date"] <= end.isoformat()
                for slot in row.rescheduled_from
            ):
                output.append(serialize_event(row))
            continue
        frequency = frequencies.get(row.repeat)
        if frequency:
            duration = (row.event_end_date or row.event_date) - row.event_date
            occurrences = rrule(
                frequency, dtstart=datetime.combine(row.event_date, time.min)
            ).between(
                datetime.combine(start - duration, time.min),
                datetime.combine(end, time.max),
                inc=True,
            )
            output.extend(
                {
                    **serialize_event(row),
                    "date": occurrence.date().isoformat(),
                    "end_date": (occurrence.date() + duration).isoformat(),
                }
                for occurrence in occurrences
            )
    return sorted(output, key=lambda event: (event["date"], event["time"] or ""))


async def events_between(
    db: AsyncSession, *, user_id: str, organization_id: str, start: date, end: date, limit: int
) -> list[CrmCalendarEvent]:
    """Stored events touching [start, end], oldest first; no Google call."""
    event = CrmCalendarEvent
    return list(
        (
            await db.exec(
                select(event)
                .where(
                    col(event.organization_id) == organization_id,
                    col(event.user_id) == user_id,
                    col(event.event_date) <= end,
                    func.coalesce(col(event.event_end_date), col(event.event_date)) >= start,
                )
                .order_by(col(event.event_date), col(event.event_time))
                .limit(limit)
            )
        ).all()
    )


async def create_event(
    db: AsyncSession,
    *,
    user_id: str,
    organization_id: str,
    title: str,
    event_date: date,
    event_time: str | None,
    kind: str,
    detail: str = "",
    lead_id: int | None = None,
    listing_id: str | None = None,
    end_date: date | None = None,
    end_time: str | None = None,
    all_day: bool = False,
    repeat: str = "none",
    meet: bool = False,
    location: str = "",
    reminders: list[int] | None = None,
    reminders_use_default: bool = False,
    guests: list[str] | None = None,
    guests_can_modify: bool = False,
    guests_can_invite_others: bool = True,
    guests_can_see_other_guests: bool = True,
    show_as: str = "busy",
    visibility: str = "default",
) -> dict:
    now = datetime.now(timezone.utc)
    connection = await db.get(CrmCalendarConnection, (organization_id, user_id))
    event = CrmCalendarEvent(
        organization_id=organization_id,
        user_id=user_id,
        title=title,
        event_date=event_date,
        event_time=event_time,
        event_end_date=end_date or event_date,
        event_end_time=end_time,
        all_day=all_day or event_time is None,
        repeat=repeat,
        meet=meet,
        meet_request_id=secrets.token_urlsafe(20) if meet else None,
        location=location,
        reminders=reminders if reminders is not None else [30],
        reminders_use_default=reminders_use_default,
        guests=guests or [],
        guests_can_modify=guests_can_modify,
        guests_can_invite_others=guests_can_invite_others,
        guests_can_see_other_guests=guests_can_see_other_guests,
        show_as=show_as,
        visibility=visibility,
        kind=kind,
        detail=detail,
        lead_id=lead_id,
        listing_id=listing_id,
        google_sync_status="pending" if connection else "local",
        updated_at=now,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    if connection:
        try:
            await _sync_pending(db, connection=connection, token=await _access_token(connection))
        except (httpx.HTTPError, RuntimeError, KeyError):
            event.google_sync_status = "error"
            await db.commit()
    return serialize_event(event)


async def get_event(db: AsyncSession, *, id: int, user_id: str, organization_id: str):
    result = await db.exec(
        select(CrmCalendarEvent).where(
            CrmCalendarEvent.id == id,
            CrmCalendarEvent.organization_id == organization_id,
            CrmCalendarEvent.user_id == user_id,
        )
    )
    return result.first()


async def update_event(
    db: AsyncSession,
    *,
    event: CrmCalendarEvent,
    connection: CrmCalendarConnection | None,
) -> dict:
    event.updated_at = datetime.now(timezone.utc)
    event.google_sync_status = "pending" if connection else "local"
    await db.commit()
    if connection:
        try:
            await _sync_pending(db, connection=connection, token=await _access_token(connection))
        except (httpx.HTTPError, RuntimeError, KeyError):
            event.google_sync_status = "error"
            await db.commit()
    return serialize_event(event)


async def delete_event(db: AsyncSession, *, event: CrmCalendarEvent, connection) -> None:
    google_id = event.google_event_id
    if google_id and connection:
        try:
            await _google(
                "DELETE",
                f"{GOOGLE_API}/calendars/primary/events/{google_id}",
                token=await _access_token(connection),
            )
        except httpx.HTTPStatusError as exc:
            # Already deleted in Google (404/410): just remove our copy.
            if exc.response.status_code not in (404, 410):
                raise
    await db.delete(event)
    await db.commit()
