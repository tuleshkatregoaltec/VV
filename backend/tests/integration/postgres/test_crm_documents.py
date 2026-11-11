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
