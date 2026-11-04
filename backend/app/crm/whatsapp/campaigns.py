"""Connectors › WhatsApp › Campaigns: one approved template, once, to each chosen opted-in lead,
from the campaign number. Organization owners only.

Sending is durable without a job system: every recipient is a row. Sending claims a batch of
pending rows under SKIP LOCKED (so two servers never take the same person), sends each, and
records the outcome before moving on. If the server stops mid-way, pending rows wait for Resume;
a row caught in `sending` becomes `unknown` instead of being sent again, because a duplicate
promotion is worse than a missed one.
"""

import logging
from datetime import datetime, timedelta

import httpx
from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.inbound_models import CrmInboundContact, CrmInboundEnquiry
from app.crm.whatsapp import meta, service
from app.crm.whatsapp.models import (
    CrmWhatsAppCampaign,
    CrmWhatsAppCampaignRecipient,
    CrmWhatsAppMessage,
    CrmWhatsAppNumber,
    CrmWhatsAppOptOut,
    WhatsAppAudienceLead,
    WhatsAppAudienceResponse,
    WhatsAppCampaignCounts,
    WhatsAppCampaignCreate,
    WhatsAppCampaignDetail,
    WhatsAppCampaignRecipientResponse,
    WhatsAppCampaignResponse,
    WhatsAppChatResponse,
    WhatsAppThreadResponse,
)
from app.postgres import get_db_session

logger = logging.getLogger(__name__)

# A value that becomes each recipient's own first name.
FIRST_NAME = "{first_name}"
CLAIM_BATCH = 25
# A row claimed this long ago and still `sending` was interrupted.
STALE = timedelta(minutes=10)
NO_CAMPAIGN_NUMBER = "There is no active campaign number. Register one first."


async def campaign_number(db: AsyncSession, *, organization_id: str) -> CrmWhatsAppNumber | None:
    return (
        await db.exec(
            select(CrmWhatsAppNumber).where(
                CrmWhatsAppNumber.organization_id == organization_id,
                CrmWhatsAppNumber.purpose == "campaign",
                col(CrmWhatsAppNumber.active).is_(True),
            )
        )
    ).first()


async def _opted_out_ids(db: AsyncSession, *, organization_id: str) -> set[str]:
    return set(
        (
            await db.exec(
                select(CrmWhatsAppOptOut.wa_id).where(
                    CrmWhatsAppOptOut.organization_id == organization_id
                )
            )
        ).all()
    )


def _why_not(contact: CrmInboundContact, wa_id: str | None, opted_out: set[str]) -> str | None:
    """Why a lead may not get promotions; None when they may."""
    if wa_id is None:
        return "No WhatsApp number"
    if contact.do_not_contact or wa_id in opted_out:
        return "Opted out"
    if contact.consent_status != "provided":
        return "No marketing consent recorded"
    return None


async def audience(
    db: AsyncSession,
    *,
    organization_id: str,
    search: str | None = None,
    intent: str | None = None,
    limit: int = 1000,
) -> WhatsAppAudienceResponse:
    """Leads with recorded consent who have not opted out, one per WhatsApp number."""
    query = (
        select(CrmInboundEnquiry, CrmInboundContact)
        .join(CrmInboundContact, CrmInboundContact.id == CrmInboundEnquiry.contact_id)
        .where(CrmInboundEnquiry.organization_id == organization_id)
        .order_by(col(CrmInboundEnquiry.created_at).desc())
    )
    if intent:
        query = query.where(CrmInboundEnquiry.intent == intent)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(
            or_(
                col(CrmInboundContact.full_name).ilike(term),
                col(CrmInboundContact.phone).ilike(term),
            )
        )
    opted_out = await _opted_out_ids(db, organization_id=organization_id)
    out = WhatsAppAudienceResponse(items=[], no_consent=0, opted_out=0, no_number=0)
    seen: set[str] = set()
    for enquiry, contact in (await db.exec(query)).all():
        wa_id = service._contact_wa_id(contact)
        reason = _why_not(contact, wa_id, opted_out)
        if reason == "No WhatsApp number":
            out.no_number += 1
        elif reason == "Opted out":
            out.opted_out += 1
        elif reason:
            out.no_consent += 1
        elif wa_id not in seen and len(out.items) < limit:
            seen.add(wa_id)
            out.items.append(
                WhatsAppAudienceLead(
                    id=enquiry.id,
                    name=contact.full_name,
                    wa_number=f"+{wa_id}",
                    intent=enquiry.intent,
                    source=enquiry.source,
                )
            )
    return out


def _counts(
    recipients: list[CrmWhatsAppCampaignRecipient],
    messages: dict[int, CrmWhatsAppMessage],
    replied: set[str],
) -> WhatsAppCampaignCounts:
    counts = WhatsAppCampaignCounts(total=len(recipients))
    for r in recipients:
        status = _shown_status(r, messages)
        if status in {"pending", "sending"}:
            counts.pending += 1
        elif status in {"sent", "queued"}:
            counts.sent += 1
        else:
            setattr(counts, status, getattr(counts, status) + 1)
    counts.replies = len(replied & {r.wa_id for r in recipients if r.status == "sent"})
    return counts


def _shown_status(r: CrmWhatsAppCampaignRecipient, messages: dict[int, CrmWhatsAppMessage]) -> str:
    """Once sent, what Meta later reported (delivered, read, failed) is what counts."""
    if r.status == "sent" and r.message_id in messages:
        return messages[r.message_id].status or "sent"
    return r.status


async def _details(
    db: AsyncSession, campaigns: list[CrmWhatsAppCampaign]
) -> dict[int, tuple[list[CrmWhatsAppCampaignRecipient], dict[int, CrmWhatsAppMessage], set[str]]]:
    if not campaigns:
        return {}
    ids = [c.id for c in campaigns]
    recipients = (
        await db.exec(
            select(CrmWhatsAppCampaignRecipient)
            .where(col(CrmWhatsAppCampaignRecipient.campaign_id).in_(ids))
            .order_by(col(CrmWhatsAppCampaignRecipient.id))
        )
    ).all()
    message_ids = [r.message_id for r in recipients if r.message_id]
    messages = (
        {
            m.id: m
            for m in (
                await db.exec(
                    select(CrmWhatsAppMessage).where(col(CrmWhatsAppMessage.id).in_(message_ids))
                )
            ).all()
        }
        if message_ids
        else {}
    )
    out = {}
    for c in campaigns:
        mine = [r for r in recipients if r.campaign_id == c.id]
        replied = set(
            (
                await db.exec(
                    select(CrmWhatsAppMessage.wa_id).where(
                        CrmWhatsAppMessage.number_id == c.number_id,
                        CrmWhatsAppMessage.direction == "in",
                        CrmWhatsAppMessage.created_at >= c.created_at,
                    )
                )
            ).all()
        )
        out[c.id] = (mine, messages, replied)
    return out


def _response(
    c: CrmWhatsAppCampaign,
    detail: tuple[list[CrmWhatsAppCampaignRecipient], dict[int, CrmWhatsAppMessage], set[str]],
) -> WhatsAppCampaignResponse:
    return WhatsAppCampaignResponse(
        id=c.id,
        name=c.name,
        template_name=c.template_name,
        template_language=c.template_language,
        status=c.status,  # type: ignore[arg-type]
        created_at=c.created_at,
        completed_at=c.completed_at,
        counts=_counts(*detail),
    )


async def list_campaigns(
    db: AsyncSession, *, organization_id: str
) -> list[WhatsAppCampaignResponse]:
    campaigns = list(
        (
            await db.exec(
                select(CrmWhatsAppCampaign)
                .where(CrmWhatsAppCampaign.organization_id == organization_id)
                .order_by(col(CrmWhatsAppCampaign.created_at).desc())
            )
        ).all()
    )
    details = await _details(db, campaigns)
    return [_response(c, details[c.id]) for c in campaigns]


async def _campaign(
    db: AsyncSession, *, organization_id: str, campaign_id: int
) -> CrmWhatsAppCampaign:
    campaign = await db.get(CrmWhatsAppCampaign, campaign_id)
    if campaign is None or campaign.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


async def campaign_detail(
    db: AsyncSession, *, organization_id: str, campaign_id: int
) -> WhatsAppCampaignDetail:
    campaign = await _campaign(db, organization_id=organization_id, campaign_id=campaign_id)
    detail = (await _details(db, [campaign]))[campaign.id]
    recipients, messages, _ = detail
    return WhatsAppCampaignDetail(
        **_response(campaign, detail).model_dump(),
        template_body=campaign.template_body,
        params=campaign.params,
        recipients=[
            WhatsAppCampaignRecipientResponse(
                enquiry_id=r.enquiry_id,
                name=r.name,
                wa_number=f"+{r.wa_id}",
                status=_shown_status(r, messages),
                error=(messages[r.message_id].error if r.message_id in messages else None)
                or r.error,
            )
            for r in recipients
        ],
    )


async def create_campaign(
    db: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    payload: WhatsAppCampaignCreate,
    client: httpx.AsyncClient | None = None,
) -> WhatsAppCampaignDetail:
    """Check everything, then record the campaign and one row per recipient. Sending happens
    afterwards (`run_campaign`), so nothing has gone out if this raises."""
    if not meta.is_configured():
        raise HTTPException(status_code=409, detail=meta.NOT_AVAILABLE)
    number = await campaign_number(db, organization_id=organization_id)
    if number is None:
        raise HTTPException(status_code=409, detail=NO_CAMPAIGN_NUMBER)
    templates = await service.list_templates(client)
    template = next(
        (
            t
            for t in templates
            if t.name == payload.template_name
            and t.language == payload.language
            and t.review == "approved"
        ),
        None,
    )
    if template is None:
        raise HTTPException(status_code=422, detail="That message is not approved by WhatsApp")
    params = [p.strip() for p in payload.params]
    needed = meta.variable_count(template.body)
    if len(params) != needed or not all(params):
        raise HTTPException(
            status_code=422,
            detail=f"This message needs {needed} value{'s' if needed != 1 else ''} filled in",
        )

    rows = (
        await db.exec(
            select(CrmInboundEnquiry, CrmInboundContact)
            .join(CrmInboundContact, CrmInboundContact.id == CrmInboundEnquiry.contact_id)
            .where(
                CrmInboundEnquiry.organization_id == organization_id,
                col(CrmInboundEnquiry.id).in_(payload.enquiry_ids),
            )
        )
    ).all()
    opted_out = await _opted_out_ids(db, organization_id=organization_id)
    now = service._now()
    campaign = CrmWhatsAppCampaign(
        organization_id=organization_id,
        number_id=number.id,
        name=payload.name.strip(),
        template_name=template.name,
        template_language=template.language,
        template_body=template.body,
        params=params,
        created_by_user_id=user_id,
        created_at=now,
        updated_at=now,
    )
    recipients: dict[str, CrmWhatsAppCampaignRecipient] = {}
    for enquiry, contact in rows:
        wa_id = service._contact_wa_id(contact)
        # Leads that may not get promotions are not added at all; the audience screen shows why.
        if _why_not(contact, wa_id, opted_out) or wa_id in recipients:
            continue
        recipients[wa_id] = CrmWhatsAppCampaignRecipient(
            campaign_id=0,
            organization_id=organization_id,
            enquiry_id=enquiry.id,
            wa_id=wa_id,
            name=contact.full_name,
            updated_at=now,
        )
    if not recipients:
        raise HTTPException(
            status_code=422,
            detail="None of these leads can receive promotions (consent, opt-out or number)",
        )
    db.add(campaign)
    await db.flush()
    for r in recipients.values():
        r.campaign_id = campaign.id
        db.add(r)
    await db.commit()
    return await campaign_detail(db, organization_id=organization_id, campaign_id=campaign.id)


async def _claim(db: AsyncSession, campaign_id: int) -> list[CrmWhatsAppCampaignRecipient]:
    rows = list(
        (
            await db.exec(
                select(CrmWhatsAppCampaignRecipient)
                .where(
                    CrmWhatsAppCampaignRecipient.campaign_id == campaign_id,
                    CrmWhatsAppCampaignRecipient.status == "pending",
                )
                .order_by(col(CrmWhatsAppCampaignRecipient.id))
                .limit(CLAIM_BATCH)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    now = service._now()
    for r in rows:
        r.status = "sending"
        r.claimed_at = now
        r.updated_at = now
        db.add(r)
    await db.commit()
    return rows


async def _still_open(db: AsyncSession, campaign_id: int) -> int:
    return (
        await db.exec(
            select(func.count())
            .select_from(CrmWhatsAppCampaignRecipient)
            .where(
                CrmWhatsAppCampaignRecipient.campaign_id == campaign_id,
                col(CrmWhatsAppCampaignRecipient.status).in_(["pending", "sending"]),
            )
        )
    ).one()


async def _send_one(
    db: AsyncSession,
    client: httpx.AsyncClient,
    *,
    campaign: CrmWhatsAppCampaign,
    number: CrmWhatsAppNumber,
    r: CrmWhatsAppCampaignRecipient,
) -> None:
    now = service._now()
    # Someone can opt out between the campaign being made and their turn coming.
    contact = None
    if r.enquiry_id is not None:
        enquiry = await db.get(CrmInboundEnquiry, r.enquiry_id)
        contact = await db.get(CrmInboundContact, enquiry.contact_id) if enquiry else None
    if await service._opted_out(
        db, organization_id=campaign.organization_id, wa_id=r.wa_id, contact=contact
    ):
        r.status, r.error = "skipped", "Opted out before sending"
    else:
        first = service._first_name(None, r.name) or ""
        params = [first if p == FIRST_NAME else p for p in campaign.params]
        message = CrmWhatsAppMessage(
            organization_id=campaign.organization_id,
            number_id=number.id,
            wa_id=r.wa_id,
            direction="out",
            body=meta.fill_template(campaign.template_body, params),
            template_name=campaign.template_name,
            template_language=campaign.template_language,
            contact_name=None,
            sent_by_user_id=campaign.created_by_user_id,
            created_at=now,
            updated_at=now,
        )
        try:
            message.wamid = await meta.send_template(
                client,
                phone_number_id=number.phone_number_id,
                to=r.wa_id,
                name=campaign.template_name,
                language=campaign.template_language,
                params=params,
            )
            message.status = "sent"
            db.add(message)
            await db.flush()
            r.status, r.message_id = "sent", message.id
        except meta.MetaError as exc:
            r.status, r.error = "failed", str(exc)
    r.updated_at = now
    db.add(r)
    # One commit per person: progress survives a crash, so nobody is sent to twice.
    await db.commit()


async def process_campaign(
    db: AsyncSession, campaign_id: int, client: httpx.AsyncClient | None = None
) -> None:
    """Send to every pending recipient, batch by batch, then mark the campaign completed."""
    campaign = await db.get(CrmWhatsAppCampaign, campaign_id)
    if campaign is None:
        return
    number = await db.get(CrmWhatsAppNumber, campaign.number_id)
    if number is None or not number.active or not meta.is_configured():
        logger.warning(
            "WhatsApp campaign %s cannot send: no active number or not configured", campaign_id
        )
        return
    owns = client is None
    client = service._client(client)
    try:
        while batch := await _claim(db, campaign_id):
            for r in batch:
                await _send_one(db, client, campaign=campaign, number=number, r=r)
    finally:
        if owns:
            await client.aclose()
    if not await _still_open(db, campaign_id):
        campaign.status = "completed"
        campaign.completed_at = campaign.updated_at = service._now()
        db.add(campaign)
        await db.commit()


async def run_campaign(campaign_id: int) -> None:
    """Background entry point: its own session, so it outlives the request that started it."""
    try:
        async for db in get_db_session():
            await process_campaign(db, campaign_id)
    except Exception:
        # Pending rows stay pending; Resume picks them up.
        logger.exception("WhatsApp campaign %s stopped while sending", campaign_id)


async def resume_campaign(
    db: AsyncSession, *, organization_id: str, campaign_id: int
) -> WhatsAppCampaignDetail:
    """Make an interrupted campaign ready to send its pending recipients again. Rows caught
    mid-send become `unknown`: they may or may not have received it."""
    campaign = await _campaign(db, organization_id=organization_id, campaign_id=campaign_id)
    cutoff: datetime = service._now() - STALE
    stuck = (
        await db.exec(
            select(CrmWhatsAppCampaignRecipient).where(
                CrmWhatsAppCampaignRecipient.campaign_id == campaign.id,
                CrmWhatsAppCampaignRecipient.status == "sending",
                col(CrmWhatsAppCampaignRecipient.claimed_at) < cutoff,
            )
        )
    ).all()
    for r in stuck:
        r.status = "unknown"
        r.error = "Interrupted while sending; check the chat before sending again"
        r.updated_at = service._now()
        db.add(r)
    if await _still_open(db, campaign.id):
        campaign.status = "sending"
        campaign.completed_at = None
    campaign.updated_at = service._now()
    db.add(campaign)
    await db.commit()
    return await campaign_detail(db, organization_id=organization_id, campaign_id=campaign.id)


# ── Campaign inbox: replies to the campaign number ──


async def campaign_chats(
    db: AsyncSession, *, organization_id: str, user_id: str
) -> list[WhatsAppChatResponse]:
    number = await campaign_number(db, organization_id=organization_id)
    return await service._chats(db, number=number, user_id=user_id)


async def campaign_chat(
    db: AsyncSession, *, organization_id: str, user_id: str, wa_id: str
) -> WhatsAppThreadResponse:
    lead = await service._lead_for(
        db, organization_id=organization_id, wa_id=wa_id, user_id=user_id
    )
    return await service._thread(
        db,
        organization_id=organization_id,
        number=await campaign_number(db, organization_id=organization_id),
        wa_id=wa_id,
        contact=lead[1] if lead else None,
    )


async def campaign_reply(
    db: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    wa_id: str,
    body: str,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Answer someone who replied to a campaign, from the campaign number, inside the window."""
    if not meta.is_configured():
        raise HTTPException(status_code=409, detail=meta.NOT_AVAILABLE)
    number = await campaign_number(db, organization_id=organization_id)
    if number is None:
        raise HTTPException(status_code=409, detail=NO_CAMPAIGN_NUMBER)
    lead = await service._lead_for(
        db, organization_id=organization_id, wa_id=wa_id, user_id=user_id
    )
    await service._send_reply(
        db,
        number=number,
        user_id=user_id,
        wa_id=wa_id,
        contact=lead[1] if lead else None,
        body=body,
        client=client,
    )
