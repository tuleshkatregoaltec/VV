"""Listing documents against the migrated PostgreSQL schema (constraints are the real ones)."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.crm.document_models import CrmGeneratedDocument, CrmListingDocumentInfo
from app.organization.models import Organization


def _now():
    return datetime.now(timezone.utc)


async def _org(session) -> str:
    org = str(uuid4())
    session.add(Organization(id=org, name=org))
    await session.commit()
    return org


def _info(org: str) -> CrmListingDocumentInfo:
    return CrmListingDocumentInfo(
        organization_id=org,
        source="property_finder",
        listing_key="123",
        listing_title="Marina Gate 2BR",
        fields={},
        created_by_user_id="u1",
        updated_by_user_id="u1",
        created_at=_now(),
        updated_at=_now(),
    )


async def test_one_information_record_per_listing_per_organization(pg_session):
    org = await _org(pg_session)
    pg_session.add(_info(org))
    await pg_session.commit()
    pg_session.add(_info(org))
    with pytest.raises(IntegrityError):
        await pg_session.commit()
    await pg_session.rollback()


async def test_unknown_document_type_is_rejected_by_the_database(pg_session):
    org = await _org(pg_session)
    info = _info(org)
    pg_session.add(info)
    await pg_session.commit()
    pg_session.add(
        CrmGeneratedDocument(
            organization_id=org,
            info_id=info.id,
            source="property_finder",
            listing_key="123",
            listing_title="Marina Gate 2BR",
            doc_type="invoice",
            template_version="draft-1",
            snapshot={},
            input_revision=1,
            idempotency_key=uuid4(),
            status="generating",
            created_by_user_id="u1",
            created_at=_now(),
            updated_at=_now(),
        )
    )
    with pytest.raises(IntegrityError):
        await pg_session.commit()
    await pg_session.rollback()


async def test_late_save_from_an_old_revision_is_refused(pg_session, monkeypatch):
    from crm_document_helpers import listing
    from fastapi import HTTPException

    from app.crm import documents
    from app.crm.document_models import DocumentFields, ListingDocumentInfoUpdate

    async def fake_get(db, organization_id, listing_key):
        return listing(listing_key)

    monkeypatch.setattr(documents, "get_company_listing", fake_get)
    org = await _org(pg_session)

    def payload(name, revision):
        return ListingDocumentInfoUpdate(
            source="property_finder",
            listing_key="123",
            fields=DocumentFields.model_validate({"owner": {"full_name": name}}),
            expected_revision=revision,
        )

    save = documents.save_document_info
    await save(pg_session, organization_id=org, user_id="a", payload=payload("First", 0))
    await save(pg_session, organization_id=org, user_id="b", payload=payload("B", 1))
    with pytest.raises(HTTPException) as error:
        await save(pg_session, organization_id=org, user_id="a", payload=payload("A late", 1))
    assert error.value.status_code == 409
    info = await documents.get_document_info(pg_session, organization_id=org, listing_key="123")
    assert (info.revision, info.fields.owner.full_name) == (2, "B")
