"""Scoped customer review reads and canonical connection → thread → message locks."""

from sqlalchemy import func
from sqlmodel import select

from app.whatsapp.customer_models import (
    WhatsAppConnection,
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
                    WhatsAppCustomerMessage.topic == "real_estate",
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
