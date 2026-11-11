from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import app.postgres.models  # noqa: F401 - registers every table, incl. organizations
from app.crm.document_models import (
    CrmGeneratedDocument,
    CrmListingDocumentInfo,
    DocumentFields,
    LeaseFields,
    ListingDocumentInfoUpdate,
)
from app.organization.models import Organization


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        for org in ("org-a", "org-b"):
            session.add(Organization(id=org, name=org))
        await session.commit()
        yield session
    await engine.dispose()


def _now():
    return datetime.now(timezone.utc)


def _info(org: str, key: str = "123") -> CrmListingDocumentInfo:
    return CrmListingDocumentInfo(
        organization_id=org,
        source="property_finder",
        listing_key=key,
        listing_title="Marina Gate 2BR",
        fields={},
        created_by_user_id="u1",
        updated_by_user_id="u1",
        created_at=_now(),
        updated_at=_now(),
    )


def _document(info: CrmListingDocumentInfo, key) -> CrmGeneratedDocument:
    return CrmGeneratedDocument(
        organization_id=info.organization_id,
        info_id=info.id,
        source=info.source,
        listing_key=info.listing_key,
        listing_title=info.listing_title,
        doc_type="noc",
        template_version="draft-1",
        snapshot={},
        input_revision=1,
        idempotency_key=key,
        status="generating",
        created_by_user_id="u1",
        created_at=_now(),
        updated_at=_now(),
    )


def test_unknown_fields_are_rejected():
    # Stored JSON is validated input, not an arbitrary payload (e.g. an ID scan nobody asked for).
    with pytest.raises(ValidationError):
        DocumentFields.model_validate({"owner": {"full_name": "A", "passport_scan": "x"}})


def test_lease_cheques_are_bounded():
    with pytest.raises(ValidationError):
        LeaseFields(cheques=13)


def test_owner_email_must_be_an_email():
    with pytest.raises(ValidationError):
        DocumentFields.model_validate({"owner": {"email": "not-an-email"}})


def test_update_cannot_name_an_organization():
    # The organization always comes from the signed-in user, never the request body.
    with pytest.raises(ValidationError):
        ListingDocumentInfoUpdate.model_validate(
            {
                "source": "property_finder",
                "listing_key": "123",
                "fields": {},
                "expected_revision": 0,
                "organization_id": "org-b",
            }
        )


def test_listing_key_is_a_property_finder_id():
    with pytest.raises(ValidationError):
        ListingDocumentInfoUpdate(
            source="property_finder", listing_key="Marina Gate", fields={}, expected_revision=0
        )


async def test_one_information_record_per_listing_per_organization(db):
    db.add(_info("org-a"))
    await db.commit()
    db.add(_info("org-a"))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_same_listing_in_two_organizations_is_two_records(db):
    db.add(_info("org-a"))
    db.add(_info("org-b"))
    await db.commit()


async def test_idempotency_key_is_unique_per_organization(db):
    info = _info("org-a")
    db.add(info)
    await db.commit()
    key = uuid4()
    db.add(_document(info, key))
    await db.commit()
    db.add(_document(info, key))
    with pytest.raises(IntegrityError):
        await db.commit()


def test_real_property_finder_listing_ids_are_valid_keys():
    update = ListingDocumentInfoUpdate(
        source="property_finder",
        listing_key="E4PE3H23YAHTAQDKRCMSMVTDK4",
        fields={},
        expected_revision=0,
    )
    assert update.listing_key == "E4PE3H23YAHTAQDKRCMSMVTDK4"
