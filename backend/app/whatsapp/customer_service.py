"""Authenticated customer review operations; workers use the same row lock order."""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.whatsapp import customer_repository as repository
from app.whatsapp.customer_models import CustomerMessageResponse, WhatsAppConnection
from app.whatsapp.models import utcnow


def require_found(row):
    if row is None:
        raise HTTPException(404, "WhatsApp resource not found")
    return row


def configured_owner(user_id, organization_id, phone_number_id, account_id):
    expected = (
        settings.WHATSAPP_PILOT_USER_ID,
        settings.WHATSAPP_PILOT_ORGANIZATION_ID,
        getattr(settings, "WHATSAPP_CUSTOMER_PHONE_NUMBER_ID", None),
        getattr(settings, "WHATSAPP_CUSTOMER_ACCOUNT_ID", None),
    )
    if not all(expected) or expected != (user_id, organization_id, phone_number_id, account_id):
        raise HTTPException(403, "This WhatsApp asset is not configured for this account")


def message_response(row):
    response = CustomerMessageResponse.model_validate(row)
    if row.status == "ignored":
        response.content = None
        response.reply = None
        response.reason = None
        response.evidence_ids = []
    return response


async def list_connections(db, *, user_id, organization_id):
    return await repository.connections(db, user_id, organization_id)


async def get_connection(db, *, connection_id, user_id, organization_id):
    return require_found(await repository.connection(db, connection_id, user_id, organization_id))


async def create_connection(db, *, user_id, organization_id, request):
    configured_owner(user_id, organization_id, request.phone_number_id, request.account_id)
    row = WhatsAppConnection(
        user_id=user_id, organization_id=organization_id, **request.model_dump()
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "WhatsApp phone number is already connected") from None
    return row


async def cancel_unsent(db, thread, reason):
    # Caller already holds connection and thread locks. Lock messages in stable order.
    for message in await repository.messages(db, thread.id, lock=True):
        if message.status in repository.UNSENT_STATUSES:
            if message.status in ("queued", "classifying"):
                message.content = None
                message.reply = None
                message.evidence_ids = []
            message.status = "cancelled"
            message.reason = reason
            message.send_after = None
            message.revision += 1
            message.updated_at = utcnow()


async def invalidate_connection(db, connection_id, reason, *, reject_sending=False):
    for thread in await repository.threads(db, connection_id, lock=True):
        if reject_sending:
            rows = await repository.messages(db, thread.id, lock=True)
            if any(row.status == "sending" for row in rows):
                raise HTTPException(409, "A message is already sending")
        await cancel_unsent(db, thread, reason)


async def update_connection(db, *, connection_id, user_id, organization_id, request):
    row = require_found(
        await repository.lock_connection(db, connection_id, user_id, organization_id)
    )
    if request.enabled:
        configured_owner(user_id, organization_id, row.phone_number_id, row.account_id)
    if (
        request.market_data_enabled is not None
        and request.market_data_enabled != row.market_data_enabled
    ):
        await invalidate_connection(db, row.id, "market_permission_changed", reject_sending=True)
    if request.enabled is False:
        await invalidate_connection(db, row.id, "connection_disabled")
    for key, value in request.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    row.updated_at = utcnow()
    await db.commit()
    return row


async def update_knowledge(db, *, connection_id, user_id, organization_id, request):
    row = require_found(
        await repository.lock_connection(db, connection_id, user_id, organization_id)
    )
    await invalidate_connection(db, row.id, "knowledge_changed")
    row.approved_knowledge = [fact.model_dump() for fact in request.approved_knowledge]
    row.updated_at = utcnow()
    await db.commit()
    return row


async def delete_connection(db, *, connection_id, user_id, organization_id):
    row = require_found(
        await repository.lock_connection(db, connection_id, user_id, organization_id)
    )
    await invalidate_connection(db, row.id, "connection_deleted", reject_sending=True)
    await db.delete(row)
    await db.commit()


async def list_threads(db, *, connection_id, user_id, organization_id, limit=100, offset=0):
    await get_connection(
        db, connection_id=connection_id, user_id=user_id, organization_id=organization_id
    )
    return await repository.threads(db, connection_id, limit=limit, offset=offset)


async def locked_thread(db, thread_id, user_id, organization_id):
    connection_id = require_found(
        await repository.thread_location(db, thread_id, user_id, organization_id)
    )
    connection = require_found(
        await repository.lock_connection(db, connection_id, user_id, organization_id)
    )
    thread = require_found(await repository.lock_thread(db, thread_id, connection.id))
    return connection, thread


async def set_takeover(db, *, thread_id, user_id, organization_id, paused):
    _, thread = await locked_thread(db, thread_id, user_id, organization_id)
    if not paused and thread.opted_out:
        raise HTTPException(409, "Customer opt-out requires a new customer START message")
    thread.paused = paused
    thread.updated_at = utcnow()
    if paused:
        await cancel_unsent(db, thread, "human_takeover")
    await db.commit()
    return thread


async def list_messages(db, *, thread_id, user_id, organization_id, limit=100, offset=0):
    require_found(await repository.thread_location(db, thread_id, user_id, organization_id))
    return [
        message_response(row)
        for row in await repository.messages(db, thread_id, limit=limit, offset=offset)
    ]


async def list_notifications(db, *, user_id, organization_id, limit=100, offset=0):
    return [
        message_response(row)
        for row in await repository.notifications(
            db, user_id, organization_id, limit=limit, offset=offset
        )
    ]


async def decide(db, *, message_id, user_id, organization_id, request, action):
    connection_id, thread_id = require_found(
        await repository.message_location(db, message_id, user_id, organization_id)
    )
    connection = require_found(
        await repository.lock_connection(db, connection_id, user_id, organization_id)
    )
    thread = require_found(await repository.lock_thread(db, thread_id, connection.id))
    message = require_found(await repository.lock_message(db, message_id, thread.id))
    if message.revision != request.expected_revision:
        raise HTTPException(409, "Draft revision has changed")
    allowed = repository.REVIEW_STATUSES
    if action == "cancel":
        allowed = repository.UNSENT_STATUSES
    elif action == "edit":
        allowed = (*repository.REVIEW_STATUSES, "approved")
    if message.status not in allowed:
        raise HTTPException(409, "Message is no longer available for this decision")
    if action != "cancel" and (not connection.enabled or thread.opted_out):
        raise HTTPException(409, "Customer automation is disabled or the customer opted out")
    if action == "approve":
        configured_owner(
            user_id, organization_id, connection.phone_number_id, connection.account_id
        )
        if not message.reply:
            raise HTTPException(409, "No draft is available")
        if message.sent_at <= utcnow() - timedelta(hours=24):
            raise HTTPException(409, "Customer service window has expired")
        message.status = "approved"
        message.send_after = utcnow()
    elif action == "edit":
        message.reply = request.reply
        message.status = "approval_required"
        message.send_after = None
        message.reason = "human_edited"
        message.evidence_ids = []
        message.evidence_snapshots = []
        message.notification_created_at = message.notification_created_at or utcnow()
        thread.paused = True
        thread.updated_at = utcnow()
    else:
        if message.status in ("queued", "classifying"):
            message.content = None
            message.reply = None
            message.evidence_ids = []
        message.status = "cancelled"
        message.send_after = None
        message.reason = "human_cancelled"
    message.revision += 1
    message.updated_at = utcnow()
    await db.commit()
    return message_response(message)


async def mark_seen(db, *, message_id, user_id, organization_id, request):
    connection_id, thread_id = require_found(
        await repository.message_location(db, message_id, user_id, organization_id)
    )
    require_found(await repository.lock_connection(db, connection_id, user_id, organization_id))
    require_found(await repository.lock_thread(db, thread_id, connection_id))
    message = require_found(await repository.lock_message(db, message_id, thread_id))
    if message.revision != request.expected_revision:
        raise HTTPException(409, "Draft revision has changed")
    if message.notification_created_at is None or message.status == "ignored":
        raise HTTPException(404, "Notification not found")
    message.notification_seen_at = utcnow()
    await db.commit()
    return message_response(message)


async def list_published_listings(
    db, *, connection_id, user_id, organization_id, limit=100, offset=0
):
    await get_connection(
        db, connection_id=connection_id, user_id=user_id, organization_id=organization_id
    )
    return await repository.published_listings(
        db, connection_id, user_id, organization_id, limit=limit, offset=offset
    )


async def publish_listing(db, *, connection_id, user_id, organization_id, request, listing_id=None):
    from app.whatsapp.customer_models import WhatsAppPublishedListing
    from app.whatsapp.customer_policy import rejected_text

    connection = require_found(
        await repository.lock_connection(db, connection_id, user_id, organization_id)
    )
    if any(
        rejected_text(value) or "@" in value or "://" in value
        for value in (request.title, request.location)
    ):
        raise HTTPException(422, "Listing labels contain unsafe or private content")
    # All data changes are a new explicit approval. No private CRM fields are copied.
    data = request.model_dump(exclude={"approved_for_customer", "expected_revision"})
    if listing_id is None:
        row = WhatsAppPublishedListing(connection_id=connection.id, **data)
        db.add(row)
    else:
        row = require_found(
            await repository.published_listing(
                db, listing_id, connection.id, user_id, organization_id
            )
        )
        if row.revision != request.expected_revision:
            raise HTTPException(409, "Publication revision has changed")
        await invalidate_connection(db, connection.id, "publication_changed", reject_sending=True)
        for key, value in data.items():
            setattr(row, key, value)
        row.revoked_at = None
        row.revision += 1
        row.updated_at = utcnow()
    await db.commit()
    return row


async def revoke_listing(db, *, connection_id, listing_id, user_id, organization_id, request):
    connection = require_found(
        await repository.lock_connection(db, connection_id, user_id, organization_id)
    )
    row = require_found(
        await repository.published_listing(db, listing_id, connection.id, user_id, organization_id)
    )
    if row.revision != request.expected_revision:
        raise HTTPException(409, "Publication revision has changed")
    await invalidate_connection(db, connection.id, "publication_revoked", reject_sending=True)
    row.revoked_at = utcnow()
    row.revision += 1
    row.updated_at = utcnow()
    await db.commit()
    return row
