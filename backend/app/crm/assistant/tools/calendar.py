"""Calendar tools for the CRM Assistant: the signed-in agent's own calendar.

Reading goes through calendar_service.list_events (scoped to this user in this organisation).
Booking only proposes; on Confirm, actions.py calls calendar_service.create_event, so the event
appears on the Calendar page and syncs to Google like one made there.
"""

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic_ai import RunContext

from app.crm import calendar_service
from app.crm.assistant.actions import create_pending_action
from app.crm.assistant.deps import AssistantDeps
from app.crm.assistant.scope import lead_link, today
from app.crm.assistant.tools.leads import NOT_FOUND, _lead_for_change, lead_name

logger = logging.getLogger(__name__)

MAX_DAYS = 60
TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
KIND_LABELS = {"viewing": "Viewing", "call": "Call", "follow_up": "Follow-up"}


def _end_time(start: str, minutes: int) -> str:
    started = datetime.combine(date.today(), datetime.strptime(start, "%H:%M").time())
    ended = started + timedelta(minutes=minutes)
    # An event that would run past midnight ends at 23:59 on the same day.
    return "23:59" if ended.date() != started.date() else ended.strftime("%H:%M")


async def list_calendar_events(
    ctx: RunContext[AssistantDeps], start_date: date | None = None, days: int = 7
) -> dict[str, Any]:
    """List the signed-in agent's own calendar events.

    Args:
        start_date: First day to include (YYYY-MM-DD); today when not given.
        days: How many days to include, starting at start_date (at most 60).
    """
    deps = ctx.deps
    logger.info("assistant tool=list_calendar_events org=%s", deps.organization_id)
    start = start_date or today()
    end = start + timedelta(days=max(1, min(days, MAX_DAYS)) - 1)
    try:
        events = await calendar_service.list_events(
            deps.db,
            user_id=deps.user_id,
            organization_id=deps.organization_id,
            start=start,
            end=end,
        )
    except Exception as error:
        logger.warning(
            "assistant calendar unavailable org=%s error=%s",
            deps.organization_id,
            type(error).__name__,
        )
        return {"error": "The calendar could not be loaded right now"}
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "events": [
            {
                "id": event["id"],
                "date": event["date"],
                "time": event["time"],
                "end_time": event.get("end_time"),
                "kind": event["kind"],
                "title": event["title"],
                "lead_link": lead_link(event["lead_id"]) if event.get("lead_id") else None,
            }
            for event in events[: MAX_DAYS * 4]
        ],
    }


async def propose_calendar_event(
    ctx: RunContext[AssistantDeps],
    lead_id: int,
    kind: Literal["viewing", "call", "follow_up"],
    date: date,
    time: str,
    duration_minutes: int = 60,
    note: str | None = None,
) -> dict[str, Any]:
    """Propose booking a viewing, call or follow-up with a lead in the agent's calendar.
    The user must confirm it.

    Args:
        lead_id: The lead's id.
        kind: viewing, call or follow_up.
        date: The day (YYYY-MM-DD).
        time: Start time, 24-hour HH:MM (e.g. 15:00).
        duration_minutes: Length in minutes (15 to 240).
        note: Optional detail to put on the event.
    """
    deps = ctx.deps
    logger.info("assistant tool=propose_calendar_event org=%s", deps.organization_id)
    if not TIME.match(time or ""):
        return {"error": "Use a 24-hour time like 15:00"}
    if date < today():
        return {"error": "That date is in the past"}
    lead = await _lead_for_change(deps, lead_id)
    if lead is None:
        return NOT_FOUND
    minutes = max(15, min(duration_minutes, 240))
    end = _end_time(time, minutes)
    title = f"{KIND_LABELS[kind]} · {lead_name(lead)}"
    when = f"{date.strftime('%a %d %b %Y')}, {time}–{end}"
    return await create_pending_action(
        deps,
        enquiry_id=lead_id,
        action_type="calendar_event",
        payload={
            "kind": kind,
            "title": title,
            "date": date.isoformat(),
            "time": time,
            "end_time": end,
            "detail": (note or "").strip()[:2000],
        },
        summary=f"Book {title}",
        before={},
        after={"event": title, "when": when},
    )
