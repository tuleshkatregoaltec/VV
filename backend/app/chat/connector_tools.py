"""Read tools for the calendar and email connectors: the signed-in user's own records only.

Both read stored rows (no Google or Brevo call), so a question never changes anything. The
evidence they record is re-checked by access, not by content (chat.service): a calendar or a
mail thread changes as it syncs, which must not hide an earlier answer that was allowed.
"""

from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Annotated

from pydantic import Field
from pydantic_ai import RunContext

from app.chat.dependencies import ChatDependencies
from app.chat.security import safe_tool
from app.postgres import get_db_session

MAX_DAYS = 62
MAX_EVENTS = 40
MAX_EMAILS = 10


@safe_tool
async def query_my_calendar(
    ctx: RunContext[ChatDependencies | None],
    start: date,
    end: date,
) -> dict:
    """Your own CRM calendar between start and end (inclusive, at most 62 days).

    Includes events made in the CRM and events synced from your Google Calendar: viewings,
    calls, follow-ups and meetings, with time, linked lead id, location, Meet link and whether
    Google has it. Use it for "what is on my calendar", free slots and clashes before booking.
    """
    from app.crm import calendar_service
    from app.crm.calendar_models import CrmCalendarConnection

    if ctx.deps is None:
        return {"available": False, "reason": "Authenticated CRM context is required"}
    if end < start:
        start, end = end, start
    if (end - start).days > MAX_DAYS:
        end = start + timedelta(days=MAX_DAYS)
    user_id, organization_id = ctx.deps.user_id, ctx.deps.organization_id
    async with asynccontextmanager(get_db_session)() as db:
        rows = await calendar_service.events_between(
            db,
            user_id=user_id,
            organization_id=organization_id,
            start=start,
            end=end,
            limit=MAX_EVENTS + 1,
        )
        connection = (
            await db.get(CrmCalendarConnection, (organization_id, user_id))
            if calendar_service.configured()
            else None
        )
    ctx.deps.evidence.append({"private": True, "type": "calendar_lookup"})
    return {
        "source": "Your CRM calendar",
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "google_calendar_connected": connection is not None,
        "truncated": len(rows) > MAX_EVENTS,
        "events": [
            {
                "id": e.id,
                "title": e.title,
                "date": e.event_date.isoformat(),
                "time": e.event_time,
                "end_date": (e.event_end_date or e.event_date).isoformat(),
                "end_time": e.event_end_time,
                "all_day": e.all_day,
                "kind": e.kind,
                "lead_id": e.lead_id,
                "location": e.location,
                "meet_link": e.meet_link,
                "done": e.done,
                "on_google": e.google_sync_status == "synced",
            }
            for e in rows[:MAX_EVENTS]
        ],
    }


@safe_tool
async def query_my_lead_emails(
    ctx: RunContext[ChatDependencies | None],
    lead_id: Annotated[int, Field(gt=0)],
) -> dict:
    """Emails sent to and received from a lead you can see, newest first (at most 10).

    Use the lead id from personal CRM retrieval. Shows subject, direction (out = sent from the
    CRM, in = the lead's reply), time, delivery status and the text. Leads your CRM role
    does not let you see return nothing.
    """
    from app.assistant_actions import repository
    from app.crm import brevo, email_pipeline

    if ctx.deps is None:
        return {"available": False, "reason": "Authenticated CRM context is required"}
    user_id, organization_id = ctx.deps.user_id, ctx.deps.organization_id
    async with asynccontextmanager(get_db_session)() as db:
        lead = await repository.visible_lead(
            db, user_id=user_id, organization_id=organization_id, lead_id=lead_id
        )
        if lead is None:
            return {"available": False, "reason": "Lead not found"}
    thread = await email_pipeline.lead_thread(organization_id=organization_id, enquiry_id=lead_id)
    ctx.deps.evidence.append({"private": True, "type": "lead_email_thread", "lead_id": lead_id})
    newest = sorted(thread, key=lambda item: item.at, reverse=True)[:MAX_EMAILS]
    return {
        "source": "Your lead's email conversation",
        "email_configured": brevo.is_configured(),
        "lead_id": lead_id,
        "total": len(thread),
        "emails": [
            {
                "direction": item.direction,
                "subject": item.subject,
                "at": item.at.isoformat(),
                "status": item.status,
                "text": item.body[:1500],
            }
            for item in newest
        ],
    }


async def evidence_still_accessible(db, reference: dict, *, user_id, organization_id) -> bool:
    """Re-check a connector evidence reference by access (see the module docstring)."""
    if reference.get("type") == "calendar_lookup":
        return True  # the caller already checked current organization access
    if reference.get("type") == "lead_email_thread":
        from app.assistant_actions import repository

        return (
            await repository.visible_lead(
                db,
                user_id=user_id,
                organization_id=organization_id,
                lead_id=int(reference["lead_id"]),
            )
            is not None
        )
    return False


CONNECTOR_EVIDENCE = {"calendar_lookup", "lead_email_thread"}
