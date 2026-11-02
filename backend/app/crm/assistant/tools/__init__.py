"""CRM Assistant tool registry. Each CRM section adds one entry; the agent registers them all."""

from collections.abc import Callable

from app.crm.assistant.tools.calendar import list_calendar_events, propose_calendar_event
from app.crm.assistant.tools.email import (
    email_overview,
    lead_email_thread,
    list_email_templates,
    propose_send_email,
)
from app.crm.assistant.tools.leads import (
    get_lead,
    lead_pipeline_summary,
    list_org_members,
    propose_add_note,
    propose_assign,
    propose_follow_up,
    propose_share,
    propose_status_change,
    search_leads,
)

SECTION_TOOLS: dict[str, list[Callable]] = {
    "leads": [
        search_leads,
        get_lead,
        lead_pipeline_summary,
        list_org_members,
        propose_status_change,
        propose_add_note,
        propose_follow_up,
        propose_assign,
        propose_share,
    ],
    "calendar": [
        list_calendar_events,
        propose_calendar_event,
    ],
    "email": [
        email_overview,
        lead_email_thread,
        list_email_templates,
        propose_send_email,
    ],
}
