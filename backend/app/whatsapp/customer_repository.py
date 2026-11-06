"""Scoped customer review reads and canonical connection → thread → message locks."""

from sqlalchemy import delete, func, or_
from sqlmodel import select

from app.whatsapp.customer_models import (
    WhatsAppConnection,
    WhatsAppContact,
    WhatsAppCustomerMessage,
    WhatsAppCustomerThread,
)

UNSENT_STATUSES = (
    "queued",
    "classifying",
    "auto_pending",
    "grace_pending",
    "approval_required",
    "approved",
)
REVIEW_STATUSES = ("auto_pending", "grace_pending", "approval_required")
# Threads the agent sees: property enquiries, and content-free identity questions (the agent
# must know who asked to answer personally). Personal-only contacts stay invisible.
VISIBLE_TOPICS = ("real_estate", "identity")


def owner_scope(user_id, organization_id):
    return (
        WhatsAppConnection.user_id == user_id,
        WhatsAppConnection.organization_id == organization_id,
    )


async def lock_connection(db, connection_id, user_id=None, organization_id=None):
    query = select(WhatsAppConnection).where(WhatsAppConnection.id == connection_id)
    if user_id is not None or organization_id is not None:
        query = query.where(*owner_scope(user_id, organization_id))
    return (
        await db.exec(query.with_for_update().execution_options(populate_existing=True))
    ).first()


async def lock_thread(db, thread_id, connection_id):
    return (
        await db.exec(
            select(WhatsAppCustomerThread)
            .where(
                WhatsAppCustomerThread.id == thread_id,
                WhatsAppCustomerThread.connection_id == connection_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()


async def lock_message(db, message_id, thread_id):
    return (
        await db.exec(
            select(WhatsAppCustomerMessage)
            .where(
                WhatsAppCustomerMessage.id == message_id,
                WhatsAppCustomerMessage.thread_id == thread_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()


async def connections(db, user_id, organization_id):
    return (
        await db.exec(
            select(WhatsAppConnection)
            .where(*owner_scope(user_id, organization_id))
            .order_by(WhatsAppConnection.created_at, WhatsAppConnection.id)
        )
    ).all()


async def connection(db, connection_id, user_id, organization_id):
    return (
        await db.exec(
            select(WhatsAppConnection).where(
                WhatsAppConnection.id == connection_id, *owner_scope(user_id, organization_id)
            )
        )
    ).first()


async def threads(db, connection_id, *, limit=100, offset=0, lock=False):
    query = (
        select(WhatsAppCustomerThread)
        .where(WhatsAppCustomerThread.connection_id == connection_id)
        .order_by(WhatsAppCustomerThread.id)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    else:
        # Do not turn a personal-only contact into a visible brokerage lead.
        query = (
            query.where(
                select(WhatsAppCustomerMessage.id)
                .where(
                    WhatsAppCustomerMessage.thread_id == WhatsAppCustomerThread.id,
                    WhatsAppCustomerMessage.topic.in_(VISIBLE_TOPICS),
                )
                .exists()
            )
            .order_by(None)
            .order_by(WhatsAppCustomerThread.updated_at.desc(), WhatsAppCustomerThread.id)
        )
        query = query.limit(limit).offset(offset)
    return (await db.exec(query)).all()


async def thread_location(db, thread_id, user_id, organization_id):
    return (
        await db.exec(
            select(WhatsAppCustomerThread.connection_id)
            .join(WhatsAppConnection)
            .where(WhatsAppCustomerThread.id == thread_id, *owner_scope(user_id, organization_id))
        )
    ).first()


async def message_location(db, message_id, user_id, organization_id):
    return (
        await db.exec(
            select(WhatsAppCustomerThread.connection_id, WhatsAppCustomerThread.id)
            .join(WhatsAppConnection)
            .join(WhatsAppCustomerMessage)
            .where(WhatsAppCustomerMessage.id == message_id, *owner_scope(user_id, organization_id))
        )
    ).first()


async def messages(db, thread_id, *, limit=100, offset=0, lock=False):
    query = (
        select(WhatsAppCustomerMessage)
        .where(WhatsAppCustomerMessage.thread_id == thread_id)
        .order_by(WhatsAppCustomerMessage.created_at.desc(), WhatsAppCustomerMessage.id)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    else:
        query = query.limit(limit).offset(offset)
    return (await db.exec(query)).all()


async def notifications(db, user_id, organization_id, *, limit=100, offset=0):
    return (
        await db.exec(
            select(WhatsAppCustomerMessage)
            .join(WhatsAppCustomerThread)
            .join(WhatsAppConnection)
            .where(
                *owner_scope(user_id, organization_id),
                WhatsAppCustomerMessage.notification_created_at.is_not(None),
                WhatsAppCustomerMessage.status.in_(["approval_required", "failed", "unknown"]),
            )
            .order_by(
                WhatsAppCustomerMessage.notification_created_at.desc(), WhatsAppCustomerMessage.id
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()


async def published_listings(
    db,
    connection_id,
    user_id,
    organization_id,
    *,
    limit=100,
    offset=0,
    active_at=None,
    filters=None,
):
    from app.whatsapp.customer_models import WhatsAppPublishedListing as Listing

    query = (
        select(Listing)
        .join(WhatsAppConnection)
        .where(Listing.connection_id == connection_id, *owner_scope(user_id, organization_id))
    )
    if active_at is not None:
        query = query.where(Listing.revoked_at.is_(None), Listing.expires_at > active_at)
    if filters is not None:
        for key in ("transaction", "property_type", "bedrooms"):
            value = getattr(filters, key)
            if value is not None:
                query = query.where(getattr(Listing, key) == value)
        if filters.location:
            query = query.where(func.lower(Listing.location) == filters.location.lower())
        if filters.max_price_aed is not None:
            query = query.where(Listing.price_aed <= filters.max_price_aed)
        query = query.where(Listing.availability == "available")
    return (
        await db.exec(
            query.order_by(Listing.created_at.desc(), Listing.id).limit(limit).offset(offset)
        )
    ).all()


async def published_listing(db, listing_id, connection_id, user_id, organization_id):
    from app.whatsapp.customer_models import WhatsAppPublishedListing as Listing

    return (
        await db.exec(
            select(Listing)
            .join(WhatsAppConnection)
            .where(
                Listing.id == listing_id,
                Listing.connection_id == connection_id,
                *owner_scope(user_id, organization_id),
            )
            .execution_options(populate_existing=True)
        )
    ).first()


# Webhook routing and intake. Callers lock connection → thread → message.


async def routed_connection(db, account_id, phone_number_id):
    """The connected agent that owns this WABA *and* phone number, locked."""
    return (
        await db.exec(
            select(WhatsAppConnection)
            .where(
                WhatsAppConnection.phone_number_id == phone_number_id,
                WhatsAppConnection.account_id == account_id,
                WhatsAppConnection.status == "connected",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()


async def account_connections(db, account_id):
    return (
        await db.exec(
            select(WhatsAppConnection)
            .where(WhatsAppConnection.account_id == account_id)
            .order_by(WhatsAppConnection.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()


def _identity(connection_id, wa_id, bsuid):
    keys = []
    if wa_id:
        keys.append(WhatsAppContact.wa_id == wa_id)
    if bsuid:
        keys.append(WhatsAppContact.bsuid == bsuid)
    return WhatsAppContact.connection_id == connection_id, or_(*keys)


async def blocked_contact(db, connection_id, wa_id, bsuid):
    if not (wa_id or bsuid):
        return False
    return (
        await db.exec(
            select(WhatsAppContact.id)
            .where(*_identity(connection_id, wa_id, bsuid), WhatsAppContact.blocked)
            .limit(1)
        )
    ).first() is not None


async def contact_for(db, connection_id, wa_id, bsuid):
    if not (wa_id or bsuid):
        return None
    return (
        await db.exec(
            select(WhatsAppContact)
            .where(*_identity(connection_id, wa_id, bsuid))
            .order_by(WhatsAppContact.created_at, WhatsAppContact.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()


async def message_exists(db, message_id):
    return (
        await db.exec(
            select(WhatsAppCustomerMessage.id).where(WhatsAppCustomerMessage.id == message_id)
        )
    ).first() is not None


async def daily_counts(db, connection_id, since):
    return dict(
        (
            await db.exec(
                select(WhatsAppCustomerThread.sender, func.count())
                .select_from(WhatsAppCustomerMessage)
                .join(WhatsAppCustomerThread)
                .where(
                    WhatsAppCustomerThread.connection_id == connection_id,
                    WhatsAppCustomerMessage.created_at >= since,
                )
                .group_by(WhatsAppCustomerThread.sender)
            )
        ).all()
    )


async def thread_for_sender(db, connection_id, sender):
    return (
        await db.exec(
            select(WhatsAppCustomerThread)
            .where(
                WhatsAppCustomerThread.connection_id == connection_id,
                WhatsAppCustomerThread.sender == sender,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()


async def has_property_messages(db, thread_id):
    return (
        await db.exec(
            select(WhatsAppCustomerMessage.id)
            .where(
                WhatsAppCustomerMessage.thread_id == thread_id,
                WhatsAppCustomerMessage.topic == "real_estate",
            )
            .limit(1)
        )
    ).first() is not None


async def delete_contacts(db, connection_id):
    await db.exec(delete(WhatsAppContact).where(WhatsAppContact.connection_id == connection_id))


async def connection_by_phone(db, phone_number_id):
    return (
        await db.exec(
            select(WhatsAppConnection)
            .where(WhatsAppConnection.phone_number_id == phone_number_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).first()


async def agent_connections(db, user_id, organization_id):
    """The agent's connections, connected first then most recently updated; locked."""
    return (
        await db.exec(
            select(WhatsAppConnection)
            .where(*owner_scope(user_id, organization_id))
            .order_by(
                (WhatsAppConnection.status == "connected").desc(),
                WhatsAppConnection.updated_at.desc(),
                WhatsAppConnection.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()


async def contact_counts(db, connection_id):
    total, blocked = (
        await db.exec(
            select(
                func.count(WhatsAppContact.id),
                func.count(WhatsAppContact.id).filter(WhatsAppContact.blocked),
            ).where(WhatsAppContact.connection_id == connection_id)
        )
    ).one()
    return total, blocked


async def admin_overview(db):
    from app.organization.models import Organization

    contacts = (
        select(
            WhatsAppContact.connection_id,
            func.count(WhatsAppContact.id).label("total"),
            func.count(WhatsAppContact.id).filter(WhatsAppContact.blocked).label("blocked"),
        )
        .group_by(WhatsAppContact.connection_id)
        .subquery()
    )
    last_message = (
        select(
            WhatsAppCustomerThread.connection_id,
            func.max(WhatsAppCustomerMessage.created_at).label("at"),
        )
        .join(WhatsAppCustomerMessage)
        .group_by(WhatsAppCustomerThread.connection_id)
        .subquery()
    )
    rows = (
        await db.exec(
            select(
                WhatsAppConnection,
                Organization.name,
                func.coalesce(contacts.c.total, 0),
                func.coalesce(contacts.c.blocked, 0),
                last_message.c.at,
            )
            .outerjoin(Organization, Organization.id == WhatsAppConnection.organization_id)
            .outerjoin(contacts, contacts.c.connection_id == WhatsAppConnection.id)
            .outerjoin(last_message, last_message.c.connection_id == WhatsAppConnection.id)
            .order_by(
                (WhatsAppConnection.status == "connected").desc(),
                WhatsAppConnection.created_at,
                WhatsAppConnection.id,
            )
        )
    ).all()
    return [
        {
            "connection": connection,
            "organization_name": name,
            "contacts_total": total,
            "contacts_blocked": blocked,
            "last_message_at": at,
        }
        for connection, name, total, blocked, at in rows
    ]
