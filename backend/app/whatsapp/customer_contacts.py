"""Agent address book synced from the WhatsApp Business app, and the block list."""

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlmodel import select

from app.whatsapp import customer_repository as repository
from app.whatsapp.customer_models import WhatsAppContact
from app.whatsapp.customer_queue import bsuid_of
from app.whatsapp.models import utcnow


def normalize_phone(value):
    """Meta sends `from` as bare digits; address-book numbers may carry + and spaces."""
    if not isinstance(value, str) or len(value) > 40:
        return None
    digits = "".join(ch for ch in value if ch.isascii() and ch.isdigit())
    stripped = value.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if stripped.lstrip("+") != digits or not 6 <= len(digits) <= 20:
        return None
    return digits


def contact_name(contact):
    name = contact.get("full_name") or contact.get("first_name")
    if not isinstance(name, str):
        return None
    name = " ".join(name.split())[:200]
    return name if name and name.isprintable() else None


async def apply_state_sync(db, connection, items):
    """Apply smb_app_state_sync contact add/edit/remove for one routed connection."""
    if not isinstance(items, list):
        return 0
    now = utcnow()
    applied = 0
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "contact":
            continue
        contact = item.get("contact")
        action = item.get("action")
        if not isinstance(contact, dict) or action not in ("add", "edit", "remove"):
            continue
        wa_id = normalize_phone(contact.get("phone_number"))
        bsuid = bsuid_of(contact.get("user_id"))
        if not (wa_id or bsuid):
            continue
        row = await repository.contact_for(db, connection.id, wa_id, bsuid)
        if action == "remove":
            if row is None:
                continue
            if row.blocked:
                # The agent's block decision outlives the address-book entry.
                row.in_address_book = False
                row.updated_at = now
            else:
                await db.delete(row)
        else:
            name = contact_name(contact)
            if row is None:
                row = WhatsAppContact(
                    connection_id=connection.id, wa_id=wa_id, bsuid=bsuid, name=name
                )
                db.add(row)
            else:
                row.wa_id = row.wa_id or wa_id
                row.bsuid = row.bsuid or bsuid
                row.name = name or row.name
                row.in_address_book = True
                row.updated_at = now
        await db.flush()
        applied += 1
    connection.contacts_synced_at = now
    connection.updated_at = now
    return applied


async def list_contacts(db, connection, *, search=None, blocked=None, limit=50, offset=0):
    query = select(WhatsAppContact).where(WhatsAppContact.connection_id == connection.id)
    if blocked is not None:
        query = query.where(WhatsAppContact.blocked == blocked)
    if search:
        pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        digits = "".join(ch for ch in search if ch.isdigit())
        conditions = [WhatsAppContact.name.ilike(pattern, escape="\\")]
        if digits:
            conditions.append(WhatsAppContact.wa_id.like(f"%{digits}%"))
        query = query.where(or_(*conditions))
    total = (await db.exec(select(func.count()).select_from(query.order_by(None).subquery()))).one()
    rows = (
        await db.exec(
            query.order_by(
                WhatsAppContact.blocked.desc(),
                func.lower(func.coalesce(WhatsAppContact.name, WhatsAppContact.wa_id)),
                WhatsAppContact.id,
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return total, rows


async def set_blocked(db, connection, *, contact_ids, phone_numbers, blocked):
    """Bulk block/unblock. Blocking cancels unsent work and erases unclassified text."""
    from app.whatsapp.customer_service import cancel_unsent

    now = utcnow()
    rows = []
    if contact_ids:
        rows = list(
            (
                await db.exec(
                    select(WhatsAppContact)
                    .where(
                        WhatsAppContact.connection_id == connection.id,
                        WhatsAppContact.id.in_(contact_ids),
                    )
                    .order_by(WhatsAppContact.id)
                    .with_for_update()
                )
            ).all()
        )
        if len(rows) != len(set(contact_ids)):
            raise HTTPException(404, "WhatsApp contact not found")
    for phone in phone_numbers:
        wa_id = normalize_phone(phone)
        if wa_id is None:
            raise HTTPException(422, "Invalid phone number")
        row = await repository.contact_for(db, connection.id, wa_id, None)
        if row is None:
            if not blocked:
                continue
            row = WhatsAppContact(connection_id=connection.id, wa_id=wa_id, in_address_book=False)
            db.add(row)
            await db.flush()
        rows.append(row)
    for row in {row.id: row for row in rows}.values():
        row.blocked = blocked
        row.blocked_at = now if blocked else None
        row.updated_at = now
        if blocked and row.wa_id:
            thread = await repository.thread_for_sender(db, connection.id, row.wa_id)
            if thread is not None:
                await cancel_unsent(db, thread, "contact_blocked")
    return len({row.id for row in rows})
