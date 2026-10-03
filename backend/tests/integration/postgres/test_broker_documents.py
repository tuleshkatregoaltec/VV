"""Real migrated PostgreSQL document state and lease fencing; no model or production data."""

from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import pytest
from pypdf import PdfReader

from app.config import settings
from app.core.object_storage import ObjectStorageClient
from app.crm import document_repository, documents
from app.crm.document_models import BrokerDocumentCreate
from app.crm.inbound_models import CrmInboundContact, CrmInboundEnquiry, CrmInboundMatch
from app.market.evidence import MarketAccessContext
from app.organization.models import Organization, OrganizationMembership


@pytest.fixture
async def private_document_storage():
    endpoint = str(settings.OBJECT_STORAGE_ENDPOINT_URL)
    assert urlparse(endpoint).hostname in {"localhost", "127.0.0.1", "::1"}
    bucket = "vv-broker-document-test-" + uuid4().hex
    storage = ObjectStorageClient(
        endpoint,
        settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        bucket,
        settings.OBJECT_STORAGE_REGION,
        settings.OBJECT_STORAGE_USE_PATH_STYLE,
    )
    async with storage.client() as client:
        await client.create_bucket(Bucket=bucket)
    try:
        yield storage
    finally:
        async with storage.client() as client:
            listed = await client.list_objects_v2(Bucket=bucket)
            keys = [item["Key"] for item in listed.get("Contents", [])]
            if keys:
                await storage.delete_many(keys)
            await client.delete_bucket(Bucket=bucket)


async def test_migrated_document_job_snapshot_and_reclaimed_lease(
    pg_session, private_document_storage
):
    stamp = datetime.now(timezone.utc)
    org, user = str(uuid4()), str(uuid4())
    context = MarketAccessContext(user, org, date(2026, 10, 3), "document-pg-fixture")
    pg_session.add(Organization(id=org, name="Fixture Brokerage", subscription_status="active"))
    await pg_session.flush()
    pg_session.add(OrganizationMembership(organization_id=org, user_id=user))
    contact = CrmInboundContact(
        organization_id=org, full_name="Fixture Client", created_at=stamp, updated_at=stamp
    )
    pg_session.add(contact)
    await pg_session.flush()
    enquiry = CrmInboundEnquiry(
        organization_id=org,
        contact_id=contact.id,
        created_by_user_id=user,
        assigned_user_id=user,
        record_kind="opportunity",
        intent="buy",
        status="qualified",
        enquiry_date=stamp,
        criteria={
            "locations": ["Dubai Marina"],
            "budget_max_aed": 1200000,
            "budget_max_inclusive": False,
        },
        created_at=stamp,
        updated_at=stamp,
    )
    pg_session.add(enquiry)
    await pg_session.flush()
    match = CrmInboundMatch(
        organization_id=org,
        enquiry_id=enquiry.id,
        target_type="listing",
        target_key="FIXTURE-PROPERTY",
        title="Source title",
        subtitle="",
        score=90,
        fit="exact",
        snapshot={
            "area_name": "Dubai Marina",
            "property_type": "Apartment",
            "price_value": 1100000,
            "price_currency": "AED",
            "price_period": "sell",
        },
        generated_at=stamp,
        updated_at=stamp,
    )
    pg_session.add(match)
    await pg_session.commit()
    request = BrokerDocumentCreate(
        enquiry_id=enquiry.id,
        kind="quotation",
        match_ids=[match.id],
        reference="PG-Q1",
        idempotency_key="pg-doc",
        charges=[{"label": "Brokerage", "amount": "22000", "status": "known"}],
        missing_charges=["Transfer charge"],
    )
    created = await documents.create_document(pg_session, request, context)
    assert created.document.quotation.known_total == "1122000.00"
    assert (await documents.create_document(pg_session, request, context)).id == created.id
    first = await document_repository.claim_document(pg_session, stamp)
    old_token = first.claim_token
    assert (
        await document_repository.claim_document(pg_session, stamp + timedelta(seconds=20)) is None
    )
    second = await document_repository.claim_document(pg_session, stamp + timedelta(seconds=100))
    assert second.id == created.id and second.claim_token != old_token
    assert not await document_repository.finish_document(
        pg_session, created.id, old_token, now=stamp, object_key="stale", checksum="stale"
    )
    # Simulate another interrupted renderer; the ordinary worker reclaims its expired lease.
    second.lease_until = stamp - timedelta(seconds=1)
    pg_session.add(second)
    await pg_session.commit()

    storage = private_document_storage
    assert await documents.process_document_job(pg_session, storage)
    pdf = await documents.document_download(pg_session, context, created.id, storage)
    assert "1122000.00" in "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
    loaded = await documents.authorized_document(pg_session, context, created.id)
    assert loaded.attempt_count == 3 and loaded.status == "completed"
    assert loaded.document_json == created.document.model_dump(mode="json")
    async with httpx.AsyncClient() as http:
        anonymous = await http.get(
            f"{str(settings.OBJECT_STORAGE_ENDPOINT_URL).rstrip('/')}/{storage.bucket_name}/{loaded.object_key}"
        )
    assert anonymous.status_code == 403  # An object key is never a public download permission.
