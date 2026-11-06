import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.whatsapp import customer_repository as repository
from app.whatsapp import customer_service as service
from app.whatsapp.customer_models import (
    ConnectionCreate,
    ConnectionUpdate,
    KnowledgeUpdate,
    ReplyEdit,
    RevisionDecision,
    WhatsAppConnection,
    WhatsAppCustomerMessage,
    WhatsAppCustomerThread,
)
from app.whatsapp.models import utcnow


@pytest.fixture
async def customer(pg_session, monkeypatch):
    user, org, phone = (str(uuid4()) for _ in range(3))
    for name, value in {
        "WHATSAPP_PILOT_USER_ID": user,
        "WHATSAPP_PILOT_ORGANIZATION_ID": org,
        "WHATSAPP_CUSTOMER_PHONE_NUMBER_ID": phone,
        "WHATSAPP_CUSTOMER_ACCOUNT_ID": "account",
    }.items():
        monkeypatch.setattr(service.settings, name, value)
    connection = await service.create_connection(
        pg_session,
        user_id=user,
        organization_id=org,
        request=ConnectionCreate(phone_number_id=phone, account_id="account", display_name="Test"),
    )
    assert not connection.enabled
    connection.enabled = True
    connection.approved_knowledge = [{"id": "coverage", "text": "Dubai property enquiries."}]
    thread = WhatsAppCustomerThread(connection_id=connection.id, sender="971500000000")
    pg_session.add(thread)
    await pg_session.flush()
    message = WhatsAppCustomerMessage(
        id=str(uuid4()),
        thread_id=thread.id,
        content="Property details?",
        sent_at=utcnow(),
        status="approval_required",
        reply="Dubai property enquiries.",
        revision=1,
        send_after=None,
        notification_created_at=utcnow(),
    )
    pg_session.add(message)
    await pg_session.commit()
    return connection, thread, message, dict(user_id=user, organization_id=org)


async def test_whatsapp_customer_connection_binding_and_duplicate_phone(pg_session, customer):
    connection, _, _, identity = customer
    request = ConnectionCreate(
        phone_number_id=connection.phone_number_id, account_id="account", display_name="Other"
    )
    with pytest.raises(HTTPException) as denied:
        await service.create_connection(
            pg_session,
            user_id="attacker",
            organization_id=identity["organization_id"],
            request=request,
        )
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as duplicate:
        await service.create_connection(pg_session, **identity, request=request)
    assert duplicate.value.status_code == 409


@pytest.mark.parametrize("change", [{"user_id": "foreign"}, {"organization_id": "foreign"}])
async def test_whatsapp_customer_foreign_scope_cannot_read_or_decide(pg_session, customer, change):
    connection, thread, message, identity = customer
    identity = {**identity, **change}
    assert await service.list_connections(pg_session, **identity) == []
    assert await service.list_notifications(pg_session, **identity) == []
    operations = [
        service.get_connection(pg_session, **identity, connection_id=connection.id),
        service.list_messages(pg_session, **identity, thread_id=thread.id),
        service.set_takeover(pg_session, **identity, thread_id=thread.id, paused=True),
        service.decide(
            pg_session,
            **identity,
            message_id=message.id,
            request=RevisionDecision(expected_revision=1),
            action="approve",
        ),
    ]
    for operation in operations:
        with pytest.raises(HTTPException) as missing:
            await operation
        assert missing.value.status_code == 404


async def test_whatsapp_customer_edit_invalidates_old_approval_and_removes_timeout(
    pg_session, customer
):
    _, _, message, identity = customer
    edited = await service.decide(
        pg_session,
        **identity,
        message_id=message.id,
        request=ReplyEdit(expected_revision=1, reply="Reviewed property reply"),
        action="edit",
    )
    assert edited.status == "approval_required"
    assert edited.send_after is None
    assert edited.revision == 2
    with pytest.raises(HTTPException) as stale:
        await service.decide(
            pg_session,
            **identity,
            message_id=message.id,
            request=RevisionDecision(expected_revision=1),
            action="approve",
        )
    assert stale.value.status_code == 409
    approved = await service.decide(
        pg_session,
        **identity,
        message_id=message.id,
        request=RevisionDecision(expected_revision=2),
        action="approve",
    )
    assert approved.status == "approved"
    assert approved.revision == 3


async def test_owner_can_approve_single_handoff_without_resuming_automation(pg_session, customer):
    _, thread, message, identity = customer
    thread.paused = True
    message.status = "approval_required"
    message.send_after = None
    await pg_session.commit()
    approved = await service.decide(
        pg_session,
        **identity,
        message_id=message.id,
        request=RevisionDecision(expected_revision=message.revision),
        action="approve",
    )
    assert approved.status == "approved"
    await pg_session.refresh(thread)
    assert thread.paused


async def test_property_inbox_excludes_personal_contacts_and_resolved_notifications(
    pg_session, customer
):
    connection, thread, message, identity = customer
    assert await service.list_threads(pg_session, connection_id=connection.id, **identity) == []
    message.topic = "real_estate"
    await pg_session.commit()
    visible = await service.list_threads(pg_session, connection_id=connection.id, **identity)
    assert [row.id for row in visible] == [thread.id]
    assert len(await service.list_notifications(pg_session, **identity)) == 1
    message.status = "accepted"
    await pg_session.commit()
    assert await service.list_notifications(pg_session, **identity) == []


async def test_whatsapp_customer_takeover_cancels_queued_and_classifying_and_reviewed(
    pg_session, customer
):
    _, thread, message, identity = customer
    extras = [
        WhatsAppCustomerMessage(
            id=str(uuid4()), thread_id=thread.id, sent_at=utcnow(), status=status
        )
        for status in ("queued", "classifying", "approved")
    ]
    pg_session.add_all(extras)
    await pg_session.commit()
    result = await service.set_takeover(pg_session, **identity, thread_id=thread.id, paused=True)
    assert result.paused
    for row in [message, *extras]:
        await pg_session.refresh(row)
        assert row.status == "cancelled"
        assert row.send_after is None
        assert row.revision == 2
    thread.opted_out = True
    await pg_session.commit()
    with pytest.raises(HTTPException) as opted_out:
        await service.set_takeover(pg_session, **identity, thread_id=thread.id, paused=False)
    assert opted_out.value.status_code == 409


@pytest.mark.parametrize("operation", ["knowledge", "disable"])
async def test_whatsapp_customer_configuration_changes_revoke_old_drafts(
    pg_session, customer, operation
):
    connection, _, message, identity = customer
    if operation == "knowledge":
        await service.update_knowledge(
            pg_session,
            **identity,
            connection_id=connection.id,
            request=KnowledgeUpdate(approved_knowledge=[]),
        )
    else:
        await service.update_connection(
            pg_session,
            **identity,
            connection_id=connection.id,
            request=ConnectionUpdate(enabled=False),
        )
    await pg_session.refresh(message)
    assert message.status == "cancelled"
    assert message.revision == 2
    assert message.send_after is None
    with pytest.raises(HTTPException) as stale:
        await service.decide(
            pg_session,
            **identity,
            message_id=message.id,
            request=RevisionDecision(expected_revision=1),
            action="approve",
        )
    assert stale.value.status_code == 409


async def test_whatsapp_customer_inbox_survives_sessions_and_seen_is_persisted(
    pg_session, customer
):
    _, thread, message, identity = customer
    ignored = WhatsAppCustomerMessage(
        id=str(uuid4()),
        thread_id=thread.id,
        sent_at=utcnow(),
        status="ignored",
        content="PRIVATE",
        notification_created_at=utcnow(),
    )
    pg_session.add(ignored)
    await pg_session.commit()
    async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
        rows = await service.list_notifications(db, **identity)
        assert [row.id for row in rows] == [message.id]
        seen = await service.mark_seen(
            db, **identity, message_id=message.id, request=RevisionDecision(expected_revision=1)
        )
        assert seen.notification_seen_at is not None
        history = await service.list_messages(db, **identity, thread_id=thread.id)
        assert next(row for row in history if row.id == ignored.id).content is None
    await pg_session.refresh(message)
    assert message.notification_seen_at is not None


async def test_whatsapp_customer_two_reviewers_cannot_decide_the_same_revision(
    pg_session, customer
):
    _, _, message, identity = customer

    async def decision(action):
        async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
            try:
                return await service.decide(
                    db,
                    **identity,
                    message_id=message.id,
                    request=RevisionDecision(expected_revision=1),
                    action=action,
                )
            except HTTPException as error:
                return error.status_code

    results = await asyncio.gather(decision("approve"), decision("cancel"))
    assert sum(isinstance(result, int) and result == 409 for result in results) == 1
    assert sum(not isinstance(result, int) for result in results) == 1


async def test_whatsapp_customer_cancel_waits_for_send_claim_and_cannot_retract(
    pg_session, customer
):
    connection, thread, message, identity = customer
    locked = asyncio.Event()
    release = asyncio.Event()

    async def claim_send():
        async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
            await repository.lock_connection(db, connection.id)
            await repository.lock_thread(db, thread.id, connection.id)
            row = await repository.lock_message(db, message.id, thread.id)
            row.status = "sending"
            locked.set()
            await release.wait()
            await db.commit()

    async def cancel():
        async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
            with pytest.raises(HTTPException) as sending:
                await service.decide(
                    db,
                    **identity,
                    message_id=message.id,
                    request=RevisionDecision(expected_revision=1),
                    action="cancel",
                )
            assert sending.value.status_code == 409

    sender = asyncio.create_task(claim_send())
    await asyncio.wait_for(locked.wait(), timeout=5)
    reviewer = asyncio.create_task(cancel())
    await asyncio.sleep(0.05)
    assert not reviewer.done()
    release.set()
    await asyncio.wait_for(asyncio.gather(sender, reviewer), timeout=5)
    await pg_session.refresh(message)
    assert message.status == "sending"


async def test_whatsapp_customer_expired_window_cannot_be_approved(pg_session, customer):
    _, _, message, identity = customer
    message.sent_at = utcnow() - timedelta(hours=24, seconds=1)
    await pg_session.commit()
    with pytest.raises(HTTPException) as expired:
        await service.decide(
            pg_session,
            **identity,
            message_id=message.id,
            request=RevisionDecision(expected_revision=1),
            action="approve",
        )
    assert expired.value.status_code == 409


async def test_whatsapp_customer_delete_cascades_channel_data(pg_session, customer):
    connection, thread, message, identity = customer
    await service.delete_connection(pg_session, **identity, connection_id=connection.id)
    async with AsyncSession(pg_session.bind, expire_on_commit=False) as db:
        assert (
            await db.exec(select(WhatsAppConnection).where(WhatsAppConnection.id == connection.id))
        ).first() is None
        assert (
            await db.exec(
                select(WhatsAppCustomerThread).where(WhatsAppCustomerThread.id == thread.id)
            )
        ).first() is None
        assert (
            await db.exec(
                select(WhatsAppCustomerMessage).where(WhatsAppCustomerMessage.id == message.id)
            )
        ).first() is None


async def test_whatsapp_customer_edit_retracts_pending_approval_until_new_review(
    pg_session, customer
):
    _, _, message, identity = customer
    approved = await service.decide(
        pg_session,
        **identity,
        message_id=message.id,
        request=RevisionDecision(expected_revision=1),
        action="approve",
    )
    edited = await service.decide(
        pg_session,
        **identity,
        message_id=message.id,
        request=ReplyEdit(expected_revision=approved.revision, reply="Updated human reply"),
        action="edit",
    )
    assert edited.status == "approval_required"
    assert edited.send_after is None
    assert edited.revision == 3


@pytest.mark.parametrize("action", ["approve", "edit", "cancel"])
async def test_whatsapp_customer_sending_is_irreversible_for_review_actions(
    pg_session, customer, action
):
    _, _, message, identity = customer
    message.status = "sending"
    await pg_session.commit()
    request = (
        ReplyEdit(expected_revision=1, reply="Changed")
        if action == "edit"
        else RevisionDecision(expected_revision=1)
    )
    with pytest.raises(HTTPException) as sending:
        await service.decide(
            pg_session, **identity, message_id=message.id, request=request, action=action
        )
    assert sending.value.status_code == 409
    await pg_session.rollback()


@pytest.mark.parametrize("operation", ["takeover", "disable", "cancel"])
@pytest.mark.parametrize("status", ["queued", "classifying"])
async def test_whatsapp_customer_cancelled_unclassified_source_is_discarded(
    pg_session, customer, operation, status
):
    connection, thread, draft, identity = customer
    pending = WhatsAppCustomerMessage(
        id=str(uuid4()),
        thread_id=thread.id,
        sent_at=utcnow(),
        status=status,
        content="Private personal message awaiting classification",
        reply="Unconfirmed output",
        evidence_ids=["unconfirmed"],
    )
    pg_session.add(pending)
    await pg_session.commit()
    if operation == "takeover":
        await service.set_takeover(pg_session, **identity, thread_id=thread.id, paused=True)
    elif operation == "disable":
        await service.update_connection(
            pg_session,
            **identity,
            connection_id=connection.id,
            request=ConnectionUpdate(enabled=False),
        )
    else:
        await service.decide(
            pg_session,
            **identity,
            message_id=pending.id,
            request=RevisionDecision(expected_revision=1),
            action="cancel",
        )
    await pg_session.refresh(pending)
    assert pending.status == "cancelled"
    assert pending.content is None
    assert pending.reply is None
    assert pending.evidence_ids == []
    await pg_session.refresh(draft)
    assert draft.content == "Property details?"
    assert draft.reply == "Dubai property enquiries."
