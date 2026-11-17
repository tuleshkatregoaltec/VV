"""Connectors › WhatsApp: who sends from which number, conversations, sending, and webhooks.

Agents only ever see and send from their own number (one active agent number each), so a customer
gets one chat per agent and replies land back with the same agent. Leads are matched to a
conversation by phone when read, preferring the lead assigned to that agent.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import func, or_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.inbound_models import CrmInboundContact, CrmInboundEnquiry
from app.crm.whatsapp import live, meta
from app.crm.whatsapp.models import (
    CrmWhatsAppMessage,
    CrmWhatsAppNumber,
    CrmWhatsAppOptOut,
    WhatsAppChatResponse,
    WhatsAppMessageResponse,
    WhatsAppMetaNumber,
    WhatsAppNumberResponse,
    WhatsAppNumberWrite,
    WhatsAppStatusResponse,
    WhatsAppTemplateResponse,
    WhatsAppTemplateSend,
    WhatsAppThreadResponse,
)
from app.organization.models import OrganizationMembership

TIMEOUT = 20.0
WINDOW = timedelta(hours=24)
NO_NUMBER = "You don't have a WhatsApp number yet. Ask your administrator to assign one."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _client(client: httpx.AsyncClient | None) -> httpx.AsyncClient:
    return client or httpx.AsyncClient(timeout=TIMEOUT)


async def agent_number(
    db: AsyncSession, *, organization_id: str, user_id: str
) -> CrmWhatsAppNumber | None:
    return (
        await db.exec(
            select(CrmWhatsAppNumber).where(
                CrmWhatsAppNumber.organization_id == organization_id,
                CrmWhatsAppNumber.user_id == user_id,
                CrmWhatsAppNumber.purpose == "agent",
                col(CrmWhatsAppNumber.active).is_(True),
            )
        )
    ).first()


async def whatsapp_status(
    db: AsyncSession, *, organization_id: str, user_id: str
) -> WhatsAppStatusResponse:
    number = await agent_number(db, organization_id=organization_id, user_id=user_id)
    return WhatsAppStatusResponse(
        configured=meta.is_configured() and number is not None,
        connected=meta.is_configured(),
        business_name=number.label if number else None,
        display_number=number.display_number if number else None,
    )


async def list_templates(
    client: httpx.AsyncClient | None = None,
) -> list[WhatsAppTemplateResponse]:
    """The business account's templates as Meta reviewed them; none until WhatsApp is set up."""
    if not meta.is_configured():
        return []
    owns = client is None
    client = _client(client)
    try:
        rows = await meta.list_templates(client)
    except meta.MetaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        if owns:
            await client.aclose()
    return [WhatsAppTemplateResponse.model_validate(r) for r in rows]


# ── Conversations ──


async def _lead(
    db: AsyncSession, *, organization_id: str, enquiry_id: int
) -> tuple[CrmInboundEnquiry, CrmInboundContact]:
    row = (
        await db.exec(
            select(CrmInboundEnquiry, CrmInboundContact)
            .join(CrmInboundContact, CrmInboundContact.id == CrmInboundEnquiry.contact_id)
            .where(
                CrmInboundEnquiry.id == enquiry_id,
                CrmInboundEnquiry.organization_id == organization_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return row


def _contact_wa_id(contact: CrmInboundContact) -> str | None:
    return meta.wa_id_from_phone(contact.whatsapp) or meta.wa_id_from_phone(contact.phone)


async def _lead_for(
    db: AsyncSession, *, organization_id: str, wa_id: str, user_id: str
) -> tuple[CrmInboundEnquiry, CrmInboundContact] | None:
    """The lead on this WhatsApp id: the one assigned to the agent first, else the newest."""
    # Phones are stored as typed ("050 123 4567"): narrow on the last digits, then compare exactly.
    tail = f"%{wa_id[-9:]}"

    def digits(column: Any) -> Any:
        return func.regexp_replace(func.coalesce(column, ""), r"\D", "", "g")

    rows = (
        await db.exec(
            select(CrmInboundEnquiry, CrmInboundContact)
            .join(CrmInboundContact, CrmInboundContact.id == CrmInboundEnquiry.contact_id)
            .where(
                CrmInboundEnquiry.organization_id == organization_id,
                digits(CrmInboundContact.phone).like(tail)
                | digits(CrmInboundContact.whatsapp).like(tail),
            )
            .order_by(col(CrmInboundEnquiry.created_at).desc())
        )
    ).all()
    matches = [(e, c) for e, c in rows if _contact_wa_id(c) == wa_id]
    mine = [(e, c) for e, c in matches if e.assigned_user_id == user_id]
    return (mine or matches or [None])[0]


async def _messages(db: AsyncSession, *, number_id: int, wa_id: str) -> list[CrmWhatsAppMessage]:
    return list(
        (
            await db.exec(
                select(CrmWhatsAppMessage)
                .where(CrmWhatsAppMessage.number_id == number_id, CrmWhatsAppMessage.wa_id == wa_id)
                .order_by(col(CrmWhatsAppMessage.created_at), col(CrmWhatsAppMessage.id))
            )
        ).all()
    )


def window_ends_at(messages: list[CrmWhatsAppMessage]) -> datetime | None:
    """24 hours after the customer's last message; free-form replies are allowed until then."""
    last_in = max((m.created_at for m in messages if m.direction == "in"), default=None)
    return last_in + WINDOW if last_in else None


async def _opted_out(
    db: AsyncSession,
    *,
    organization_id: str,
    wa_id: str,
    contact: CrmInboundContact | None,
) -> bool:
    if contact is not None and contact.do_not_contact:
        return True
    row = await db.get(CrmWhatsAppOptOut, (organization_id, wa_id))
    return row is not None


def _message(m: CrmWhatsAppMessage) -> WhatsAppMessageResponse:
    return WhatsAppMessageResponse(
        id=m.wamid or f"crm-{m.id}",
        direction="in" if m.direction == "in" else "out",
        body=m.body,
        at=m.created_at,
        status=m.status,  # type: ignore[arg-type]
        template=m.template_name,
        error=m.error,
    )


async def _thread(
    db: AsyncSession,
    *,
    organization_id: str,
    number: CrmWhatsAppNumber | None,
    wa_id: str | None,
    contact: CrmInboundContact | None,
) -> WhatsAppThreadResponse:
    if wa_id is None:
        return WhatsAppThreadResponse(
            wa_number=None, opted_out=False, window_ends_at=None, messages=[]
        )
    messages = await _messages(db, number_id=number.id, wa_id=wa_id) if number else []
    return WhatsAppThreadResponse(
        wa_number=f"+{wa_id}",
        opted_out=await _opted_out(
            db, organization_id=organization_id, wa_id=wa_id, contact=contact
        ),
        window_ends_at=window_ends_at(messages),
        messages=[_message(m) for m in messages],
    )


async def lead_thread(
    db: AsyncSession, *, organization_id: str, user_id: str, enquiry_id: int
) -> WhatsAppThreadResponse:
    """The signed-in agent's chat with a lead's number (Lead › Conversation)."""
    _, contact = await _lead(db, organization_id=organization_id, enquiry_id=enquiry_id)
    return await _thread(
        db,
        organization_id=organization_id,
        number=await agent_number(db, organization_id=organization_id, user_id=user_id),
        wa_id=_contact_wa_id(contact),
        contact=contact,
    )


async def chat_thread(
    db: AsyncSession, *, organization_id: str, user_id: str, wa_id: str
) -> WhatsAppThreadResponse:
    """The signed-in agent's chat with a WhatsApp id, on a lead or not."""
    lead = await _lead_for(db, organization_id=organization_id, wa_id=wa_id, user_id=user_id)
    return await _thread(
        db,
        organization_id=organization_id,
        number=await agent_number(db, organization_id=organization_id, user_id=user_id),
        wa_id=wa_id,
        contact=lead[1] if lead else None,
    )


async def list_chats(
    db: AsyncSession, *, organization_id: str, user_id: str
) -> list[WhatsAppChatResponse]:
    """Every conversation on the agent's number, newest first."""
    number = await agent_number(db, organization_id=organization_id, user_id=user_id)
    return await _chats(db, number=number, user_id=user_id)


async def _chats(
    db: AsyncSession, *, number: CrmWhatsAppNumber | None, user_id: str
) -> list[WhatsAppChatResponse]:
    """Every conversation on one number, newest first. `unread` counts the customer's messages
    since the business last wrote."""
    if number is None:
        return []
    organization_id = number.organization_id
    rows = (
        await db.exec(
            select(CrmWhatsAppMessage)
            .where(CrmWhatsAppMessage.number_id == number.id)
            .order_by(col(CrmWhatsAppMessage.created_at), col(CrmWhatsAppMessage.id))
        )
    ).all()
    by_wa: dict[str, list[CrmWhatsAppMessage]] = {}
    for m in rows:
        by_wa.setdefault(m.wa_id, []).append(m)

    chats: list[WhatsAppChatResponse] = []
    for wa_id, messages in by_wa.items():
        last = messages[-1]
        last_out = max((m.created_at for m in messages if m.direction == "out"), default=None)
        unread = sum(
            1
            for m in messages
            if m.direction == "in" and (last_out is None or m.created_at > last_out)
        )
        name = next((m.contact_name for m in reversed(messages) if m.contact_name), None)
        lead = await _lead_for(db, organization_id=organization_id, wa_id=wa_id, user_id=user_id)
        chats.append(
            WhatsAppChatResponse(
                wa_id=wa_id,
                contact_name=name,
                lead_id=lead[0].id if lead else None,
                lead_name=lead[1].full_name if lead else None,
                last_body=last.body,
                last_direction="in" if last.direction == "in" else "out",
                last_at=last.created_at,
                window_ends_at=window_ends_at(messages),
                unread=unread,
            )
        )
    return sorted(chats, key=lambda c: c.last_at, reverse=True)


# ── Sending ──


async def _sender(db: AsyncSession, *, organization_id: str, user_id: str) -> CrmWhatsAppNumber:
    if not meta.is_configured():
        raise HTTPException(status_code=409, detail=meta.NOT_AVAILABLE)
    number = await agent_number(db, organization_id=organization_id, user_id=user_id)
    if number is None:
        raise HTTPException(status_code=409, detail=NO_NUMBER)
    return number


def _first_name(contact: CrmInboundContact | None, fallback: str | None) -> str | None:
    name = (contact.full_name if contact else None) or fallback or ""
    word = name.strip().split()[0] if name.strip() else ""
    return word.capitalize() if word.isupper() else word or None


async def _record_send(
    db: AsyncSession,
    *,
    number: CrmWhatsAppNumber,
    wa_id: str,
    user_id: str,
    body: str,
    call: Any,
    template: WhatsAppTemplateSend | None = None,
) -> None:
    """Send, then keep the message either way: a refused send stays on the thread with Meta's
    reason, and the agent sees that reason too."""
    now = _now()
    message = CrmWhatsAppMessage(
        organization_id=number.organization_id,
        number_id=number.id,
        wa_id=wa_id,
        direction="out",
        body=body,
        template_name=template.name if template else None,
        template_language=template.language if template else None,
        sent_by_user_id=user_id,
        created_at=now,
        updated_at=now,
    )
    try:
        message.wamid = await call()
        message.status = "sent"
    except meta.MetaError as exc:
        message.status = "failed"
        message.error = str(exc)
    db.add(message)
    await db.commit()
    if message.status == "failed":
        raise HTTPException(status_code=502, detail=message.error)


async def _send_reply(
    db: AsyncSession,
    *,
    number: CrmWhatsAppNumber,
    user_id: str,
    wa_id: str | None,
    contact: CrmInboundContact | None,
    body: str,
    client: httpx.AsyncClient | None,
) -> None:
    organization_id = number.organization_id
    if wa_id is None:
        raise HTTPException(status_code=422, detail="No WhatsApp number on file for this lead")
    if await _opted_out(db, organization_id=organization_id, wa_id=wa_id, contact=contact):
        raise HTTPException(status_code=409, detail="This contact opted out of WhatsApp messages")
    ends = window_ends_at(await _messages(db, number_id=number.id, wa_id=wa_id))
    if ends is None or ends <= _now():
        raise HTTPException(
            status_code=409,
            detail="More than 24 hours since their last message: send an approved template",
        )
    owns = client is None
    client = _client(client)
    try:
        await _record_send(
            db,
            number=number,
            wa_id=wa_id,
            user_id=user_id,
            body=body,
            call=lambda: meta.send_text(
                client, phone_number_id=number.phone_number_id, to=wa_id, body=body
            ),
        )
    finally:
        if owns:
            await client.aclose()


async def _send_template(
    db: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    wa_id: str | None,
    contact: CrmInboundContact | None,
    contact_name: str | None,
    payload: WhatsAppTemplateSend,
    client: httpx.AsyncClient | None,
) -> None:
    number = await _sender(db, organization_id=organization_id, user_id=user_id)
    if wa_id is None:
        raise HTTPException(status_code=422, detail="No WhatsApp number on file for this lead")
    if await _opted_out(db, organization_id=organization_id, wa_id=wa_id, contact=contact):
        raise HTTPException(status_code=409, detail="This contact opted out of WhatsApp messages")
    owns = client is None
    client = _client(client)
    try:
        templates = await list_templates(client)
        template = next(
            (
                t
                for t in templates
                if t.name == payload.name
                and t.language == payload.language
                and t.review == "approved"
            ),
            None,
        )
        if template is None:
            raise HTTPException(status_code=422, detail="That message is not approved by WhatsApp")
        # Promotions need recorded marketing consent, whichever number sends them.
        if template.category == "marketing" and (
            contact is None or contact.consent_status != "provided"
        ):
            raise HTTPException(
                status_code=409,
                detail="This contact has not agreed to marketing messages; choose a utility message",
            )
        params = [p.strip() for p in payload.params]
        needed = meta.variable_count(template.body)
        if not params and needed:
            first = _first_name(contact, contact_name)
            params = [first] if first else []
        if len(params) != needed or not all(params):
            raise HTTPException(
                status_code=422,
                detail=f"This message needs {needed} value{'s' if needed != 1 else ''} filled in",
            )
        await _record_send(
            db,
            number=number,
            wa_id=wa_id,
            user_id=user_id,
            body=meta.fill_template(template.body, params),
            template=payload,
            call=lambda: meta.send_template(
                client,
                phone_number_id=number.phone_number_id,
                to=wa_id,
                name=payload.name,
                language=payload.language,
                params=params,
            ),
        )
    finally:
        if owns:
            await client.aclose()


async def reply_to_lead(
    db: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    enquiry_id: int,
    body: str,
    client: httpx.AsyncClient | None = None,
) -> None:
    _, contact = await _lead(db, organization_id=organization_id, enquiry_id=enquiry_id)
    await _send_reply(
        db,
        number=await _sender(db, organization_id=organization_id, user_id=user_id),
        user_id=user_id,
        wa_id=_contact_wa_id(contact),
        contact=contact,
        body=body,
        client=client,
    )


async def template_to_lead(
    db: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    enquiry_id: int,
    payload: WhatsAppTemplateSend,
    client: httpx.AsyncClient | None = None,
) -> None:
    _, contact = await _lead(db, organization_id=organization_id, enquiry_id=enquiry_id)
    await _send_template(
        db,
        organization_id=organization_id,
        user_id=user_id,
        wa_id=_contact_wa_id(contact),
        contact=contact,
        contact_name=None,
        payload=payload,
        client=client,
    )


async def _chat_contact(
    db: AsyncSession, *, organization_id: str, user_id: str, wa_id: str
) -> tuple[CrmInboundContact | None, str | None]:
    lead = await _lead_for(db, organization_id=organization_id, wa_id=wa_id, user_id=user_id)
    profile = (
        await db.exec(
            select(CrmWhatsAppMessage.contact_name)
            .where(
                CrmWhatsAppMessage.organization_id == organization_id,
                CrmWhatsAppMessage.wa_id == wa_id,
                col(CrmWhatsAppMessage.contact_name).is_not(None),
            )
            .order_by(col(CrmWhatsAppMessage.created_at).desc())
        )
    ).first()
    return (lead[1] if lead else None), profile


async def reply_to_chat(
    db: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    wa_id: str,
    body: str,
    client: httpx.AsyncClient | None = None,
) -> None:
    contact, _ = await _chat_contact(
        db, organization_id=organization_id, user_id=user_id, wa_id=wa_id
    )
    await _send_reply(
        db,
        number=await _sender(db, organization_id=organization_id, user_id=user_id),
        user_id=user_id,
        wa_id=wa_id,
        contact=contact,
        body=body,
        client=client,
    )


async def template_to_chat(
    db: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    wa_id: str,
    payload: WhatsAppTemplateSend,
    client: httpx.AsyncClient | None = None,
) -> None:
    contact, profile = await _chat_contact(
        db, organization_id=organization_id, user_id=user_id, wa_id=wa_id
    )
    await _send_template(
        db,
        organization_id=organization_id,
        user_id=user_id,
        wa_id=wa_id,
        contact=contact,
        contact_name=profile,
        payload=payload,
        client=client,
    )


# ── Webhook ──


async def receive_webhook(db: AsyncSession, payload: dict[str, Any]) -> dict[str, int]:
    """Store incoming messages, apply delivery statuses and opt-outs. The caller has already
    checked the signature. A number not registered in the CRM is ignored; a repeated message or
    an out-of-order status changes nothing."""
    inbound, statuses = meta.parse_webhook(payload)
    ids = {m.phone_number_id for m in inbound} | {s.phone_number_id for s in statuses}
    if not ids:
        return {"messages": 0, "statuses": 0}
    numbers = {
        n.phone_number_id: n
        for n in (
            await db.exec(
                select(CrmWhatsAppNumber).where(col(CrmWhatsAppNumber.phone_number_id).in_(ids))
            )
        ).all()
    }

    changed: dict[str, set[live.ChatChange]] = {}

    def touch(number: CrmWhatsAppNumber, wa_id: str) -> None:
        changed.setdefault(number.organization_id, set()).add(
            live.ChatChange(wa_id=wa_id, purpose=number.purpose, user_id=number.user_id)
        )

    stored = 0
    for m in inbound:
        number = numbers.get(m.phone_number_id)
        if number is None:
            continue
        now = _now()
        result = await db.execute(
            insert(CrmWhatsAppMessage)
            .values(
                organization_id=number.organization_id,
                number_id=number.id,
                wa_id=m.wa_id,
                direction="in",
                body=m.body,
                wamid=m.wamid,
                contact_name=m.contact_name,
                created_at=m.at,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["wamid"])
        )
        if not result.rowcount:
            continue
        stored += 1
        touch(number, m.wa_id)
        change = meta.opt_change(m.body)
        if change == "out":
            await db.execute(
                insert(CrmWhatsAppOptOut)
                .values(
                    organization_id=number.organization_id,
                    wa_id=m.wa_id,
                    reason=m.body.strip()[:120],
                    created_at=now,
                )
                .on_conflict_do_nothing()
            )
        elif change == "in":
            await db.execute(
                delete(CrmWhatsAppOptOut).where(
                    CrmWhatsAppOptOut.organization_id == number.organization_id,
                    CrmWhatsAppOptOut.wa_id == m.wa_id,
                )
            )

    applied = 0
    known = [s for s in statuses if s.phone_number_id in numbers]
    if known:
        for s in sorted(known, key=lambda s: s.at):
            number = numbers[s.phone_number_id]
            earlier = [
                status for status in meta.STATUS_RANK if meta.moves_forward(status, s.status)
            ]
            values = {"status": s.status, "updated_at": _now()}
            if s.error:
                values["error"] = s.error
            # The rank predicate is checked by the database after competing writes,
            # so two webhook workers cannot downgrade read to delivered.
            result = await db.execute(
                update(CrmWhatsAppMessage)
                .where(
                    CrmWhatsAppMessage.wamid == s.wamid,
                    CrmWhatsAppMessage.number_id == number.id,
                    CrmWhatsAppMessage.organization_id == number.organization_id,
                    CrmWhatsAppMessage.direction == "out",
                    or_(
                        CrmWhatsAppMessage.status.is_(None),
                        col(CrmWhatsAppMessage.status).in_(earlier),
                    ),
                )
                .values(**values)
                .returning(CrmWhatsAppMessage.wa_id)
                .execution_options(synchronize_session=False)
            )
            wa_id = result.scalar_one_or_none()
            if wa_id is not None:
                applied += 1
                touch(number, wa_id)

    await db.commit()
    for organization_id, changes in changed.items():
        await live.publish(organization_id, changes)
    return {"messages": stored, "statuses": applied}


# ── Numbers (owner) ──


def _number(n: CrmWhatsAppNumber) -> WhatsAppNumberResponse:
    return WhatsAppNumberResponse(
        phone_number_id=n.phone_number_id,
        display_number=n.display_number,
        label=n.label,
        purpose=n.purpose,  # type: ignore[arg-type]
        user_id=n.user_id,
        active=n.active,
    )


async def list_numbers(db: AsyncSession, *, organization_id: str) -> list[WhatsAppNumberResponse]:
    rows = (
        await db.exec(
            select(CrmWhatsAppNumber)
            .where(CrmWhatsAppNumber.organization_id == organization_id)
            .order_by(col(CrmWhatsAppNumber.purpose), col(CrmWhatsAppNumber.label))
        )
    ).all()
    return [_number(n) for n in rows]


async def save_number(
    db: AsyncSession,
    *,
    organization_id: str,
    phone_number_id: str,
    payload: WhatsAppNumberWrite,
) -> WhatsAppNumberResponse:
    """Register a number (by its Meta Phone Number ID) and say who sends from it."""
    if payload.purpose == "agent":
        if not payload.user_id:
            raise HTTPException(status_code=422, detail="An agent number needs the agent")
        member = (
            await db.exec(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == organization_id,
                    OrganizationMembership.user_id == payload.user_id,
                )
            )
        ).first()
        if member is None:
            raise HTTPException(status_code=422, detail="That user is not in your organization")
    elif payload.user_id:
        raise HTTPException(status_code=422, detail="The campaign number is not an agent's")
    elif payload.active:
        other = (
            await db.exec(
                select(func.count())
                .select_from(CrmWhatsAppNumber)
                .where(
                    CrmWhatsAppNumber.organization_id == organization_id,
                    CrmWhatsAppNumber.purpose == "campaign",
                    col(CrmWhatsAppNumber.active).is_(True),
                    CrmWhatsAppNumber.phone_number_id != phone_number_id,
                )
            )
        ).one()
        if other:
            raise HTTPException(
                status_code=409, detail="There is already an active campaign number"
            )

    number = (
        await db.exec(
            select(CrmWhatsAppNumber).where(CrmWhatsAppNumber.phone_number_id == phone_number_id)
        )
    ).first()
    if number is not None and number.organization_id != organization_id:
        raise HTTPException(status_code=409, detail="That number belongs to another organization")
    now = _now()
    if number is None:
        number = CrmWhatsAppNumber(
            organization_id=organization_id,
            phone_number_id=phone_number_id,
            created_at=now,
            display_number=payload.display_number,
            label=payload.label,
            updated_at=now,
        )
    number.display_number = payload.display_number
    number.label = payload.label
    number.purpose = payload.purpose
    number.user_id = payload.user_id if payload.purpose == "agent" else None
    number.active = payload.active
    number.updated_at = now
    db.add(number)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="That agent already has an active WhatsApp number"
        ) from exc
    return _number(number)


async def meta_numbers(client: httpx.AsyncClient | None = None) -> list[WhatsAppMetaNumber]:
    """The numbers Meta has under the business account, to copy their Phone Number IDs."""
    owns = client is None
    client = _client(client)
    try:
        rows = await meta.list_phone_numbers(client)
    except meta.MetaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        if owns:
            await client.aclose()
    return [WhatsAppMetaNumber.model_validate(r) for r in rows]


async def subscribe_app(client: httpx.AsyncClient | None = None) -> bool:
    owns = client is None
    client = _client(client)
    try:
        return await meta.subscribe_app(client)
    except meta.MetaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        if owns:
            await client.aclose()
