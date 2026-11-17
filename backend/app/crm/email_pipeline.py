"""CRM › Connectors › Email: emailing leads through Brevo, templates, and tracking what happened.

Leads are only read from Postgres. Everything this pipeline writes (sends, templates, received
emails) goes to the local JSON store (email_store), so nothing here changes the database.
"""

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.crm import brevo, email_store
from app.crm.email_models import (
    CrmEmailInbound,
    CrmEmailSend,
    CrmEmailTemplate,
    EmailInboundListResponse,
    EmailInboundResponse,
    EmailLeadListResponse,
    EmailLeadResponse,
    EmailSendBatchResponse,
    EmailSendCreate,
    EmailSendListResponse,
    EmailSendResponse,
    EmailSendResult,
    EmailStatusResponse,
    EmailStoreData,
    EmailSyncResponse,
    EmailTemplateResponse,
    EmailTemplateWrite,
    EmailThreadItem,
)
from app.crm.inbound_models import CrmInboundContact, CrmInboundEnquiry

TIMEOUT = httpx.Timeout(20.0)
logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def email_status() -> EmailStatusResponse:
    return EmailStatusResponse(
        configured=brevo.is_configured(),
        sender_name=settings.BREVO_SENDER_NAME,
        sender_email=settings.BREVO_SENDER_EMAIL,
        webhook_configured=bool(settings.BREVO_WEBHOOK_SECRET),
    )


def _check_secret(secret: str | None) -> None:
    """Brevo's webhooks are public; a missing BREVO_WEBHOOK_SECRET refuses everything."""
    expected = settings.BREVO_WEBHOOK_SECRET
    if not expected:
        raise HTTPException(status_code=503, detail="Webhook not configured")
    if secret != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── leads (read only) ──


def _has_email():
    return func.length(func.trim(func.coalesce(CrmInboundContact.email, ""))) > 0


def _lead_rows(organization_id: str):
    return (
        select(CrmInboundEnquiry, CrmInboundContact)
        .join(CrmInboundContact, CrmInboundContact.id == CrmInboundEnquiry.contact_id)
        .where(CrmInboundEnquiry.organization_id == organization_id, _has_email())
    )


async def list_email_leads(
    db: AsyncSession,
    *,
    organization_id: str,
    search: str | None,
    intent: str | None,
    source: str | None,
    limit: int,
    offset: int,
    ids: list[int] | None = None,
) -> EmailLeadListResponse:
    """Leads of any type whose contact has an email, newest first, with their email history."""
    sources = (
        await db.exec(
            select(CrmInboundEnquiry.source)
            .join(CrmInboundContact, CrmInboundContact.id == CrmInboundEnquiry.contact_id)
            .where(CrmInboundEnquiry.organization_id == organization_id, _has_email())
            .distinct()
            .order_by(CrmInboundEnquiry.source)
        )
    ).all()

    query = _lead_rows(organization_id)
    term = _clean(search)
    if term:
        like = f"%{term.lower()}%"
        query = query.where(
            or_(
                func.lower(CrmInboundContact.full_name).like(like),
                func.lower(CrmInboundContact.email).like(like),
                func.coalesce(CrmInboundContact.phone, "").like(like),
            )
        )
    if intent:
        query = query.where(CrmInboundEnquiry.intent == intent)
    if source:
        query = query.where(CrmInboundEnquiry.source == source)
    if ids:
        query = query.where(col(CrmInboundEnquiry.id).in_(ids))

    total = (await db.exec(select(func.count()).select_from(query.subquery()))).one()
    rows = (
        await db.exec(
            query.order_by(
                col(CrmInboundEnquiry.enquiry_date).desc(), col(CrmInboundEnquiry.id).desc()
            )
            .offset(offset)
            .limit(limit)
        )
    ).all()

    store = await email_store.read()
    latest: dict[int, CrmEmailSend] = {}
    totals: Counter[int] = Counter()
    for send in sorted(store.sends, key=lambda s: s.created_at, reverse=True):
        if send.organization_id == organization_id and send.enquiry_id is not None:
            latest.setdefault(send.enquiry_id, send)
            totals[send.enquiry_id] += 1

    items = []
    for enquiry, contact in rows:
        last = latest.get(enquiry.id)
        items.append(
            EmailLeadResponse(
                id=enquiry.id,
                name=contact.full_name,
                email=contact.email.strip(),
                phone=contact.phone,
                intent=enquiry.intent,
                source=enquiry.source,
                status=enquiry.status,
                do_not_contact=contact.do_not_contact,
                last_status=last.status if last else None,
                last_sent_at=(last.sent_at or last.created_at) if last else None,
                sends=totals[enquiry.id],
            )
        )
    return EmailLeadListResponse(items=items, total=total, sources=list(sources))


# ── templates ──


def _template_response(t: CrmEmailTemplate) -> EmailTemplateResponse:
    return EmailTemplateResponse(
        id=t.id,
        name=t.name,
        subject=t.subject,
        body=t.body,
        lead_types=t.lead_types,
        updated_by_user_id=t.updated_by_user_id,
        updated_at=t.updated_at,
    )


def _lead_types(payload: EmailTemplateWrite) -> list[str]:
    """Distinct, in a fixed order; all five types is the same as none (every type)."""
    chosen = [t for t in ("buy", "rent", "sell", "let", "unknown") if t in payload.lead_types]
    return [] if len(chosen) == 5 else chosen


def _org_template(data: EmailStoreData, organization_id: str, template_id: int) -> CrmEmailTemplate:
    for t in data.templates:
        if t.id == template_id and t.organization_id == organization_id:
            return t
    raise HTTPException(status_code=404, detail="Template not found")


async def list_templates(*, organization_id: str) -> list[EmailTemplateResponse]:
    store = await email_store.read()
    mine = [t for t in store.templates if t.organization_id == organization_id]
    return [_template_response(t) for t in sorted(mine, key=lambda t: t.name.lower())]


async def create_template(
    *, organization_id: str, user_id: str, payload: EmailTemplateWrite
) -> EmailTemplateResponse:
    now = _now()
    async with email_store.edit() as data:
        template = CrmEmailTemplate(
            id=data.next_id("templates"),
            organization_id=organization_id,
            name=payload.name.strip(),
            subject=payload.subject.strip(),
            body=payload.body,
            lead_types=_lead_types(payload),
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
            created_at=now,
            updated_at=now,
        )
        data.templates.append(template)
    return _template_response(template)


async def update_template(
    *, organization_id: str, user_id: str, template_id: int, payload: EmailTemplateWrite
) -> EmailTemplateResponse:
    async with email_store.edit() as data:
        template = _org_template(data, organization_id, template_id)
        template.name = payload.name.strip()
        template.subject = payload.subject.strip()
        template.body = payload.body
        template.lead_types = _lead_types(payload)
        template.updated_by_user_id = user_id
        template.updated_at = _now()
    return _template_response(template)


async def delete_template(*, organization_id: str, template_id: int) -> None:
    async with email_store.edit() as data:
        template = _org_template(data, organization_id, template_id)
        data.templates.remove(template)


# ── sending ──


async def _send_one(
    client: httpx.AsyncClient,
    *,
    organization_id: str,
    user_id: str,
    enquiry_id: int | None,
    to_email: str,
    to_name: str | None,
    subject: str,
    body: str,
) -> CrmEmailSend:
    """Record the send (queued), call Brevo, then record how it went. Never raises for Brevo."""
    now = _now()
    to_email = to_email.strip().lower()
    fill = {"name": to_name or to_email.split("@")[0], "email": to_email}
    async with email_store.edit() as data:
        send = CrmEmailSend(
            id=data.next_id("sends"),
            organization_id=organization_id,
            enquiry_id=enquiry_id,
            to_email=to_email,
            to_name=to_name,
            subject=brevo.render_template(subject, **fill),
            body=brevo.render_template(body, **fill),
            sent_by_user_id=user_id,
            created_at=now,
            updated_at=now,
        )
        # Import historical feedback too, including stores written before suppression existed.
        suppressed = to_email in data.suppressed_addresses.get(organization_id, []) or any(
            old.organization_id == organization_id
            and old.to_email.strip().lower() == to_email
            and any(
                brevo.canonical_event(e.get("event")) in {"spam", "complaint", "unsubscribed"}
                for e in old.events
            )
            for old in data.sends
        )
        if suppressed:
            send.status, send.error = (
                "failed",
                "Email address suppressed by unsubscribe or spam feedback",
            )
            addresses = data.suppressed_addresses.setdefault(organization_id, [])
            if to_email not in addresses:
                addresses.append(to_email)
        # Stored before Brevo is called: its id is the tag events come back with.
        data.sends.append(send)
    if send.error:
        return send

    message_id = error = None
    try:
        message_id = await brevo.send_email(
            client,
            to=send.to_email,
            to_name=send.to_name,
            subject=send.subject,
            text=send.body,
            tag=str(send.id),
        )
    except brevo.BrevoError as exc:
        error = str(exc)

    async with email_store.edit() as data:
        stored = next(s for s in data.sends if s.id == send.id)
        if error is None:
            brevo.apply_event(stored, "sent")
            stored.message_id = message_id
            stored.sent_at = stored.sent_at or _now()
        elif stored.status == "queued":
            # A provider callback is stronger evidence than a failed/lost HTTP response.
            brevo.apply_event(stored, "error")
            stored.error = error
        stored.updated_at = _now()
    return stored


async def send_emails(
    db: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    payload: EmailSendCreate,
    client: httpx.AsyncClient | None = None,
) -> EmailSendBatchResponse:
    """One personalised email per lead. A failed send is kept, with Brevo's error.

    The thread on the lead's Conversation tab comes from the store; the lead row is not changed.
    """
    if not brevo.is_configured():
        raise HTTPException(status_code=409, detail="Email sending is not available yet")
    leads = (
        await db.exec(
            _lead_rows(organization_id).where(col(CrmInboundEnquiry.id).in_(payload.enquiry_ids))
        )
    ).all()
    if not leads:
        raise HTTPException(status_code=404, detail="No leads with an email found")

    results: list[EmailSendResult] = []
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        for enquiry, contact in leads:
            email = contact.email.strip()
            if contact.do_not_contact:
                results.append(
                    EmailSendResult(
                        enquiry_id=enquiry.id, email=email, ok=False, error="Marked do not contact"
                    )
                )
                continue
            send = await _send_one(
                client,
                organization_id=organization_id,
                user_id=user_id,
                enquiry_id=enquiry.id,
                to_email=email,
                to_name=contact.full_name,
                subject=payload.subject,
                body=payload.body,
            )
            results.append(
                EmailSendResult(
                    enquiry_id=enquiry.id,
                    email=email,
                    ok=send.status not in {"queued", "failed"},
                    error=send.error,
                )
            )
    finally:
        if owns_client:
            await client.aclose()

    sent = sum(r.ok for r in results)
    return EmailSendBatchResponse(sent=sent, failed=len(results) - sent, results=results)


async def send_to_address(
    *,
    organization_id: str,
    user_id: str,
    to_email: str,
    to_name: str | None,
    subject: str,
    body: str,
    client: httpx.AsyncClient | None = None,
) -> CrmEmailSend:
    """Send straight to an address that is not a lead (a test send); tracked like any other."""
    if not brevo.is_configured():
        raise HTTPException(status_code=409, detail="Email sending is not available yet")
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        return await _send_one(
            client,
            organization_id=organization_id,
            user_id=user_id,
            enquiry_id=None,
            to_email=to_email.strip().lower(),
            to_name=to_name,
            subject=subject,
            body=body,
        )
    finally:
        if owns_client:
            await client.aclose()


# ── tracking ──


def _send_response(send: CrmEmailSend) -> EmailSendResponse:
    opens, clicks = brevo.count_events(send)
    return EmailSendResponse(
        id=send.id,
        enquiry_id=send.enquiry_id,
        to_email=send.to_email,
        to_name=send.to_name,
        subject=send.subject,
        body=send.body,
        status=send.status,
        error=send.error,
        sent_at=send.sent_at,
        delivered_at=send.delivered_at,
        opened_at=send.opened_at,
        clicked_at=send.clicked_at,
        bounced_at=send.bounced_at,
        opens=opens,
        clicks=clicks,
        events=send.events,
        created_at=send.created_at,
    )


async def list_sends(
    *, organization_id: str, status: str | None, limit: int, offset: int
) -> EmailSendListResponse:
    store = await email_store.read()
    mine = [s for s in store.sends if s.organization_id == organization_id]
    counts = dict(Counter(s.status for s in mine))
    shown = sorted(
        (s for s in mine if not status or s.status == status),
        key=lambda s: s.created_at,
        reverse=True,
    )
    return EmailSendListResponse(
        items=[_send_response(s) for s in shown[offset : offset + limit]], counts=counts
    )


async def delete_send(*, organization_id: str, send_id: int) -> None:
    """Remove a send from Tracking. Replies to it stay in the Inbox, no longer linked to it."""
    async with email_store.edit() as data:
        send = next(
            (s for s in data.sends if s.id == send_id and s.organization_id == organization_id),
            None,
        )
        if send is None:
            raise HTTPException(status_code=404, detail="Email not found")
        # Backfill feedback from stores written before address suppression existed.
        for event in send.events:
            if brevo.canonical_event(event.get("event")) in {"spam", "complaint", "unsubscribed"}:
                _apply_delivery_event(
                    data, send, event.get("event"), event.get("at"), event.get("link")
                )
        data.sends.remove(send)
        for m in data.inbound:
            if m.send_id == send_id:
                m.send_id = None


def _find_send(
    data: EmailStoreData, *, tag: Any, message_id: Any, organization_id: str | None = None
) -> CrmEmailSend | None:
    """Tag first (our own id), message-id second."""
    sends = [s for s in data.sends if not organization_id or s.organization_id == organization_id]
    tag_id = str(tag or "").strip()
    if tag_id.isdigit():
        found = next((s for s in sends if s.id == int(tag_id)), None)
        if found:
            return found
    variants = set(brevo.message_id_variants(message_id))
    if not variants:
        return None
    return next((s for s in sends if s.message_id in variants), None)


async def sync_events(
    *, organization_id: str, client: httpx.AsyncClient | None = None
) -> EmailSyncResponse:
    """Pull events from Brevo's statistics API: works on localhost, where the webhook cannot."""
    store = await email_store.read()
    mine = [s.created_at for s in store.sends if s.organization_id == organization_id]
    if not mine:
        return EmailSyncResponse(fetched=0, applied=0, unmatched=0)

    events: list[dict[str, Any]] = []
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        async for event in brevo.fetch_events(client, start=min(mine).date(), end=_now().date()):
            events.append(event)
    except brevo.BrevoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        if owns_client:
            await client.aclose()

    applied = unmatched = 0
    async with email_store.edit() as data:
        for event in events:
            if brevo.canonical_event(event.get("event")) is None:
                continue
            send = _find_send(
                data,
                tag=event.get("tag"),
                message_id=event.get("messageId"),
                organization_id=organization_id,
            )
            if send is None:
                unmatched += 1
            elif _apply_delivery_event(
                data, send, event.get("event"), event.get("date"), event.get("link")
            ):
                applied += 1
    return EmailSyncResponse(fetched=len(events), applied=applied, unmatched=unmatched)


def _apply_delivery_event(
    data: EmailStoreData, send: CrmEmailSend, event: Any, at: Any = None, link: str | None = None
) -> bool:
    if brevo.canonical_event(event) in {"spam", "complaint", "unsubscribed"}:
        addresses = data.suppressed_addresses.setdefault(send.organization_id, [])
        address = send.to_email.strip().lower()
        if address not in addresses:
            addresses.append(address)
    return brevo.apply_event(send, event, at, link)


async def receive_webhook(*, secret: str | None, payload: Any) -> int:
    """Apply Brevo's pushed delivery events to the sends they belong to."""
    _check_secret(secret)
    applied = 0
    async with email_store.edit() as data:
        for event in payload if isinstance(payload, list) else [payload]:
            if not isinstance(event, dict):
                continue
            tags = event.get("tags")
            send = _find_send(
                data,
                tag=tags[0] if isinstance(tags, list) and tags else event.get("tag"),
                message_id=event.get("message-id") or event.get("messageId"),
            )
            at = event.get("ts_event") or event.get("ts") or event.get("date")
            link = event.get("link") or event.get("URL")
            if send and _apply_delivery_event(data, send, event.get("event"), at, link):
                applied += 1
    return applied


# ── inbound ──


def _send_for_reply(data: EmailStoreData, mail: brevo.InboundEmail) -> CrmEmailSend | None:
    """Route only authenticated addresses/thread headers from the original recipient."""
    candidates = [
        s for s in data.sends if s.to_email.strip().lower() == mail.from_email.strip().lower()
    ]
    for address in mail.recipients:
        send = next((s for s in candidates if brevo.matches_reply_address(address, s.id)), None)
        if send is not None:
            return send
    variants = set(brevo.message_id_variants(mail.in_reply_to))
    return next((s for s in candidates if variants and s.message_id in variants), None)


async def _lead_for_sender(
    db: AsyncSession, organization_id: str, email: str
) -> CrmInboundEnquiry | None:
    """The newest lead whose contact has this email (read only)."""
    return (
        await db.exec(
            select(CrmInboundEnquiry)
            .join(CrmInboundContact, CrmInboundContact.id == CrmInboundEnquiry.contact_id)
            .where(
                CrmInboundEnquiry.organization_id == organization_id,
                func.lower(func.trim(CrmInboundContact.email)) == email,
            )
            .order_by(col(CrmInboundEnquiry.enquiry_date).desc(), col(CrmInboundEnquiry.id).desc())
        )
    ).first()


async def receive_inbound(db: AsyncSession, *, secret: str | None, payload: Any) -> int:
    """Store Brevo inbound parsing items. Returns how many were new.

    Matching, in order: our authenticated reply address, the In-Reply-To header, the sender's email
    on a lead. An unknown sender is kept without a lead (no lead is created: nothing is written
    to the database) and shows as such on the Inbox tab. A message id already stored is skipped.
    """
    _check_secret(secret)
    items = payload.get("items") if isinstance(payload, dict) else payload
    mails = [
        mail
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, dict) and (mail := brevo.parse_inbound(item)) is not None
    ]

    snapshot = await email_store.read()
    matched: list[tuple[brevo.InboundEmail, int | None, int | None, str]] = []
    for mail in mails:
        send = _send_for_reply(snapshot, mail)
        organization_id = send.organization_id if send else settings.BREVO_INBOUND_ORGANIZATION_ID
        if not organization_id:
            logger.warning(
                "Inbound email from %s matched no send and no organization is set",
                mail.from_email,
            )
            continue
        enquiry_id = send.enquiry_id if send else None
        if enquiry_id is None:
            lead = await _lead_for_sender(db, organization_id, mail.from_email)
            enquiry_id = lead.id if lead else None
        matched.append((mail, send.id if send else None, enquiry_id, organization_id))

    stored = 0
    async with email_store.edit() as data:
        for mail, send_id, enquiry_id, organization_id in matched:
            if mail.message_id and any(
                m.organization_id == organization_id and m.message_id == mail.message_id
                for m in data.inbound
            ):
                continue
            data.inbound.append(
                CrmEmailInbound(
                    id=data.next_id("inbound"),
                    organization_id=organization_id,
                    enquiry_id=enquiry_id,
                    send_id=send_id,
                    message_id=mail.message_id,
                    from_email=mail.from_email,
                    from_name=mail.from_name,
                    to_email=mail.recipients[0] if mail.recipients else None,
                    subject=mail.subject,
                    body=mail.body,
                    attachments=mail.attachments,
                    received_at=mail.received_at,
                    created_at=_now(),
                )
            )
            send = next((s for s in data.sends if s.id == send_id), None)
            if send:
                brevo.apply_event(send, "replied", mail.received_at.isoformat())
            stored += 1
    return stored


async def list_inbound(
    db: AsyncSession, *, organization_id: str, limit: int, offset: int
) -> EmailInboundListResponse:
    """The Email page's Inbox tab: received emails, newest first, with the lead each landed on."""
    store = await email_store.read()
    mine = sorted(
        (m for m in store.inbound if m.organization_id == organization_id),
        key=lambda m: m.received_at,
        reverse=True,
    )
    page = mine[offset : offset + limit]
    lead_ids = {m.enquiry_id for m in page if m.enquiry_id is not None}
    names: dict[int, str] = {}
    if lead_ids:
        names = dict(
            (
                await db.exec(
                    select(CrmInboundEnquiry.id, CrmInboundContact.full_name)
                    .join(CrmInboundContact, CrmInboundContact.id == CrmInboundEnquiry.contact_id)
                    .where(col(CrmInboundEnquiry.id).in_(lead_ids))
                )
            ).all()
        )
    return EmailInboundListResponse(
        items=[
            EmailInboundResponse(
                id=m.id,
                enquiry_id=m.enquiry_id,
                lead_name=names.get(m.enquiry_id) if m.enquiry_id is not None else None,
                send_id=m.send_id,
                from_email=m.from_email,
                from_name=m.from_name,
                subject=m.subject,
                body=m.body,
                attachments=m.attachments,
                created_lead=m.created_lead,
                received_at=m.received_at,
            )
            for m in page
        ],
        total=len(mine),
    )


async def lead_thread(*, organization_id: str, enquiry_id: int) -> list[EmailThreadItem]:
    """Every email to and from one lead, oldest first: the lead's Conversation tab."""
    store = await email_store.read()
    items = [
        EmailThreadItem(
            direction="out",
            id=s.id,
            subject=s.subject,
            body=s.body,
            at=s.sent_at or s.created_at,
            status=s.status,
            counterpart=s.to_email,
        )
        for s in store.sends
        if s.organization_id == organization_id and s.enquiry_id == enquiry_id
    ] + [
        EmailThreadItem(
            direction="in",
            id=m.id,
            subject=m.subject,
            body=m.body,
            at=m.received_at,
            counterpart=m.from_email,
        )
        for m in store.inbound
        if m.organization_id == organization_id and m.enquiry_id == enquiry_id
    ]
    return sorted(items, key=lambda x: x.at)
