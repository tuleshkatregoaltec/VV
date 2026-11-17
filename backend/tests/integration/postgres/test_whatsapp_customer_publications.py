from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.whatsapp import customer_access as access
from app.whatsapp import customer_service as service
from app.whatsapp.customer_evidence import ListingSearch, listing_evidence
from app.whatsapp.customer_models import (
    ConnectionUpdate,
    PublishedListingCreate,
    PublishedListingUpdate,
    RevisionDecision,
    WhatsAppConnection,
    WhatsAppCustomerMessage,
    WhatsAppCustomerThread,
)
from app.whatsapp.models import utcnow


def request(**changes):
    return PublishedListingCreate(
        title="Approved apartment",
        location="Dubai Marina",
        property_type="apartment",
        transaction="rent",
        bedrooms=2,
        price_aed=150_000,
        availability="available",
        expires_at=utcnow() + timedelta(hours=1),
        approved_for_customer=True,
        **changes,
    )


async def connected(db, user, org):
    row = WhatsAppConnection(
        user_id=user,
        organization_id=org,
        phone_number_id=str(uuid4()),
        account_id=str(uuid4()),
        display_name="Broker",
        enabled=True,
    )
    db.add(row)
    await db.commit()
    return row


async def published(db, connection):
    return await service.publish_listing(
        db,
        connection_id=connection.id,
        user_id=connection.user_id,
        organization_id=connection.organization_id,
        request=request(),
    )


async def test_publications_are_scoped_to_broker_and_connection_even_for_same_org(pg_session):
    broker, other, org = str(uuid4()), str(uuid4()), str(uuid4())
    own = await connected(pg_session, broker, org)
    sibling = await connected(pg_session, other, org)
    other_org = await connected(pg_session, broker, str(uuid4()))
    own_listing = await published(pg_session, own)
    sibling_listing = await published(pg_session, sibling)
    await published(pg_session, other_org)
    rows = await service.list_published_listings(
        pg_session, connection_id=own.id, user_id=broker, organization_id=org
    )
    assert [row.id for row in rows] == [own_listing.id]
    for connection in (sibling, other_org):
        with pytest.raises(HTTPException) as error:
            await service.list_published_listings(
                pg_session, connection_id=connection.id, user_id=broker, organization_id=org
            )
        assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        await service.revoke_listing(
            pg_session,
            connection_id=own.id,
            listing_id=sibling_listing.id,
            user_id=broker,
            organization_id=org,
            request=RevisionDecision(expected_revision=1),
        )
    assert error.value.status_code == 404
    evidence = await access.retrieve(
        pg_session,
        ListingSearch(operation="published_listings"),
        connection_id=own.id,
        user_id=broker,
        organization_id=org,
    )
    assert [item.listing_id for item in evidence] == [own_listing.id]


async def test_expired_and_revoked_listing_filters_execute_in_database(pg_session):
    connection = await connected(pg_session, str(uuid4()), str(uuid4()))
    row = await published(pg_session, connection)
    identity = dict(
        connection_id=connection.id,
        user_id=connection.user_id,
        organization_id=connection.organization_id,
    )
    query = ListingSearch(operation="published_listings", location="Dubai Marina")
    assert len(await access.retrieve(pg_session, query, **identity)) == 1
    assert (
        await access.retrieve(
            pg_session, ListingSearch(operation="published_listings", location="%"), **identity
        )
        == []
    )
    row.expires_at = utcnow() - timedelta(seconds=1)
    await pg_session.commit()
    assert await access.retrieve(pg_session, query, **identity) == []
    row.expires_at = utcnow() + timedelta(hours=1)
    row.revoked_at = utcnow()
    await pg_session.commit()
    assert await access.retrieve(pg_session, query, **identity) == []


async def test_price_renewal_requires_revision_and_cancels_pending_evidence(pg_session):
    connection = await connected(pg_session, str(uuid4()), str(uuid4()))
    row = await published(pg_session, connection)
    item = listing_evidence(row)
    thread = WhatsAppCustomerThread(connection_id=connection.id, sender="971501111111")
    pg_session.add(thread)
    await pg_session.flush()
    message = WhatsAppCustomerMessage(
        id=str(uuid4()),
        thread_id=thread.id,
        sent_at=utcnow(),
        status="auto_pending",
        reply=item.text,
        evidence_ids=[item.id],
        evidence_snapshots=[item.model_dump(mode="json")],
        send_after=utcnow(),
    )
    pg_session.add(message)
    await pg_session.commit()
    identity = dict(
        connection_id=connection.id,
        user_id=connection.user_id,
        organization_id=connection.organization_id,
    )
    renewed = PublishedListingUpdate(**request().model_dump(), expected_revision=1)
    renewed.price_aed = 160_000
    await service.publish_listing(pg_session, listing_id=row.id, request=renewed, **identity)
    assert row.revision == 2 and row.price_aed == 160_000
    await pg_session.refresh(message)
    assert message.status == "cancelled"
    assert not await access.valid_evidence(
        pg_session, connection, [item.id], [item.model_dump(mode="json")], item.text
    )
    with pytest.raises(HTTPException) as error:
        await service.publish_listing(pg_session, listing_id=row.id, request=renewed, **identity)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        await service.revoke_listing(
            pg_session, listing_id=row.id, request=RevisionDecision(expected_revision=1), **identity
        )
    assert error.value.status_code == 409
    await service.revoke_listing(
        pg_session, listing_id=row.id, request=RevisionDecision(expected_revision=2), **identity
    )
    assert row.revoked_at is not None and row.revision == 3


async def test_permission_revocation_cancels_pending_but_refuses_a_send_in_progress(pg_session):
    connection = await connected(pg_session, str(uuid4()), str(uuid4()))
    row = await published(pg_session, connection)
    thread = WhatsAppCustomerThread(connection_id=connection.id, sender="971501111111")
    pg_session.add(thread)
    await pg_session.flush()
    message = WhatsAppCustomerMessage(
        id=str(uuid4()),
        thread_id=thread.id,
        sent_at=utcnow(),
        status="sending",
        reply="Already crossing the send boundary",
    )
    pg_session.add(message)
    connection.market_data_enabled = True
    await pg_session.commit()
    identity = dict(
        connection_id=connection.id,
        user_id=connection.user_id,
        organization_id=connection.organization_id,
    )
    with pytest.raises(HTTPException) as error:
        await service.revoke_listing(
            pg_session, listing_id=row.id, request=RevisionDecision(expected_revision=1), **identity
        )
    assert error.value.status_code == 409
    await pg_session.rollback()
    await pg_session.refresh(message)
    message.status = "auto_pending"
    await pg_session.commit()
    await service.update_connection(
        pg_session, request=ConnectionUpdate(market_data_enabled=False), **identity
    )
    await pg_session.refresh(message)
    assert message.status == "cancelled"
