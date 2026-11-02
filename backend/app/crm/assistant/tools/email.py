"""Email tools for the CRM Assistant: the organisation's Email connector (Brevo).

Reading goes through email_pipeline, scoped to this organisation. Sending only proposes; on
Confirm, actions.py calls email_pipeline.send_emails, so the email is tracked on the Email page
and on the lead's Conversation tab like one sent from there. Email addresses are never returned
to the model, and text people outside the company wrote is fenced as <lead_data>.
"""

import logging
from typing import Any

from pydantic_ai import RunContext

from app.crm import brevo, email_pipeline
from app.crm.assistant.actions import create_pending_action
from app.crm.assistant.deps import AssistantDeps
from app.crm.assistant.scope import lead_link
from app.crm.assistant.tools.leads import DO_NOT_CONTACT, NOT_FOUND, _lead_for_change, lead_name

logger = logging.getLogger(__name__)

RECENT = 5
BODY_CHARS = 800
NOT_CONNECTED = {
    "error": "Email is not connected for this organisation. Offer an email draft instead "
    "(propose_share with channel email)."
}


def _log(tool: str, deps: AssistantDeps) -> None:
    logger.info("assistant tool=%s org=%s", tool, deps.organization_id)


def _fence(text: str) -> str:
    return f"<lead_data>\n{text}\n</lead_data>"


async def email_overview(ctx: RunContext[AssistantDeps]) -> dict[str, Any]:
    """Whether email is connected, how sent emails are doing (sent, delivered, opened, replied,
    bounced, failed) and the latest emails received from leads."""
    deps = ctx.deps
    _log("email_overview", deps)
    sends = await email_pipeline.list_sends(
        organization_id=deps.organization_id, status=None, limit=RECENT, offset=0
    )
    received = await email_pipeline.list_inbound(
        deps.db, organization_id=deps.organization_id, limit=RECENT, offset=0
    )
    return {
        "connected": brevo.is_configured(),
        "sent_counts": sends.counts,
        "recent_sent": [
            {
                "subject": send.subject,
                "status": send.status,
                "sent_at": (send.sent_at or send.created_at).isoformat(),
                "lead_link": lead_link(send.enquiry_id) if send.enquiry_id else None,
            }
            for send in sends.items
        ],
        "received_total": received.total,
        "recent_received": [
            {
                "lead": mail.lead_name,
                "lead_link": lead_link(mail.enquiry_id) if mail.enquiry_id else None,
                "subject": _fence(mail.subject),
                "received_at": mail.received_at.isoformat(),
            }
            for mail in received.items
        ],
    }


async def lead_email_thread(ctx: RunContext[AssistantDeps], lead_id: int) -> dict[str, Any]:
    """Every email sent to and received from one lead, oldest first.

    Args:
        lead_id: The lead's id.
    """
    deps = ctx.deps
    _log("lead_email_thread", deps)
    if await _lead_for_change(deps, lead_id) is None:
        return NOT_FOUND
    thread = await email_pipeline.lead_thread(
        organization_id=deps.organization_id, enquiry_id=lead_id
    )
    return {
        "lead_link": lead_link(lead_id),
        "emails": [
            {
                "direction": "sent" if item.direction == "out" else "received",
                "at": item.at.isoformat(),
                "status": item.status,
                "content": _fence(f"Subject: {item.subject}\n{item.body[:BODY_CHARS]}"),
            }
            for item in thread
        ],
    }


async def list_email_templates(ctx: RunContext[AssistantDeps]) -> dict[str, Any]:
    """The organisation's saved email templates (name, subject, body, lead types)."""
    deps = ctx.deps
    _log("list_email_templates", deps)
    templates = await email_pipeline.list_templates(organization_id=deps.organization_id)
    return {
        "templates": [
            {
                "id": t.id,
                "name": t.name,
                "subject": t.subject,
                "body": t.body,
                "lead_types": t.lead_types or ["all"],
            }
            for t in templates
        ]
    }


async def propose_send_email(
    ctx: RunContext[AssistantDeps],
    lead_id: int,
    subject: str | None = None,
    body: str | None = None,
    template_id: int | None = None,
) -> dict[str, Any]:
    """Propose emailing one lead through the Email connector. Nothing is sent until the user
    confirms. Give a subject and body, or a template_id (its subject and body are used unless
    you give your own). {{first_name}}, {{name}} and {{email}} are filled in per lead.

    Args:
        lead_id: The lead's id.
        subject: The email subject.
        body: The email text, plain text with blank lines between paragraphs.
        template_id: A saved template's id from list_email_templates.
    """
    deps = ctx.deps
    _log("propose_send_email", deps)
    if not brevo.is_configured():
        return NOT_CONNECTED
    lead = await _lead_for_change(deps, lead_id)
    if lead is None:
        return NOT_FOUND
    contact = lead.contact
    if contact.do_not_contact or contact.consent_status == "withdrawn":
        return DO_NOT_CONTACT
    if not (contact.email or "").strip():
        return {"error": "This lead has no email address"}
    if template_id is not None:
        templates = await email_pipeline.list_templates(organization_id=deps.organization_id)
        template = next((t for t in templates if t.id == template_id), None)
        if template is None:
            return {"error": "Template not found"}
        subject = subject or template.subject
        body = body or template.body
    subject, body = (subject or "").strip()[:300], (body or "").strip()[:20000]
    if not subject or not body:
        return {"error": "Write a subject and a message, or pick a template"}
    # The name the pipeline fills {{first_name}} with, so the card's preview matches the email.
    name = contact.full_name or lead_name(lead)
    return await create_pending_action(
        deps,
        enquiry_id=lead_id,
        action_type="email_send",
        payload={"subject": subject, "body": body},
        summary=f"Email {name}: {brevo.render_template(subject, name=name, email='')}",
        before={},
        after={"to": name, "subject": subject, "message": body},
    )
