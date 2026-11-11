import pytest
from crm_document_helpers import listing
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import app.postgres.models  # noqa: F401 - registers every table
from app.crm import documents
from app.crm.document_models import DocumentFields, ListingDocumentInfoUpdate
from app.crm.models import CrmCompanyListingDetail
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


@pytest.fixture
def listings(monkeypatch):
    """Listings Property Finder currently publishes, keyed by listing id."""
    current: dict[str, CrmCompanyListingDetail] = {"123": listing()}

    async def fake_get(db, organization_id, listing_key):
        return current.get(listing_key)

    monkeypatch.setattr(documents, "get_company_listing", fake_get)
    return current


def update(name: str, revision: int, key: str = "123") -> ListingDocumentInfoUpdate:
    return ListingDocumentInfoUpdate(
        source="property_finder",
        listing_key=key,
        fields=DocumentFields.model_validate({"owner": {"full_name": name}}),
        expected_revision=revision,
    )


async def _save(db, org, user, payload):
    return await documents.save_document_info(
        db, organization_id=org, user_id=user, payload=payload
    )


async def test_unmanaged_listing_is_not_found_like_a_missing_one(db, listings):
    listings["777"] = listing("777", managed=False)
    errors = []
    for key in ("777", "999"):
        with pytest.raises(HTTPException) as error:
            await documents.get_document_info(db, organization_id="org-a", listing_key=key)
        errors.append((error.value.status_code, error.value.detail))
    # Another company's listing must not be distinguishable from one that does not exist.
    assert errors == [(404, "Listing not found"), (404, "Listing not found")]


async def test_unmanaged_listing_information_cannot_be_saved(db, listings):
    listings["777"] = listing("777", managed=False)
    with pytest.raises(HTTPException) as error:
        await _save(db, "org-a", "u1", update("Owner", 0, key="777"))
    assert error.value.status_code == 404


async def test_nothing_saved_yet_is_revision_0_with_the_listing_prefilled(db, listings):
    info = await documents.get_document_info(db, organization_id="org-a", listing_key="123")
    assert info.revision == 0
    assert info.fields.owner.full_name is None
    assert info.listing.title == "Marina Gate 2BR"


async def test_first_save_creates_revision_1_and_survives_reload(db, listings):
    saved = await _save(db, "org-a", "u1", update("Aisha Khan", 0))
    loaded = await documents.get_document_info(db, organization_id="org-a", listing_key="123")
    assert (saved.revision, loaded.revision) == (1, 1)
    assert loaded.fields.owner.full_name == "Aisha Khan"


async def test_saving_with_an_old_revision_conflicts_and_keeps_the_newer_data(db, listings):
    await _save(db, "org-a", "agent-a", update("First", 0))
    await _save(db, "org-a", "agent-b", update("Agent B's edit", 1))
    with pytest.raises(HTTPException) as error:
        await _save(db, "org-a", "agent-a", update("Agent A's late edit", 1))
    assert (error.value.status_code, error.value.detail) == (409, "stale_revision")
    loaded = await documents.get_document_info(db, organization_id="org-a", listing_key="123")
    assert (loaded.revision, loaded.fields.owner.full_name) == (2, "Agent B's edit")


async def test_creating_again_when_someone_already_saved_conflicts(db, listings):
    await _save(db, "org-a", "agent-a", update("First", 0))
    with pytest.raises(HTTPException) as error:
        await _save(db, "org-a", "agent-b", update("Second", 0))
    assert error.value.status_code == 409


async def test_another_organization_never_sees_saved_information(db, listings):
    await _save(db, "org-a", "u1", update("Aisha Khan", 0))
    other = await documents.get_document_info(db, organization_id="org-b", listing_key="123")
    assert (other.revision, other.fields.owner.full_name) == (0, None)


async def test_saving_refreshes_the_listing_title(db, listings):
    await _save(db, "org-a", "u1", update("A", 0))
    listings["123"] = listing(title="Marina Gate 2BR (renovated)")
    await _save(db, "org-a", "u1", update("A", 1))
    record = await documents.info_record(db, organization_id="org-a", listing_key="123")
    assert record.listing_title == "Marina Gate 2BR (renovated)"
