from datetime import datetime, timezone

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


# ── generation (Task 7) ──────────────────────────────────────────────────────

from datetime import timedelta  # noqa: E402
from uuid import uuid4  # noqa: E402

from sqlmodel import select  # noqa: E402

from app.crm.document_models import CrmGeneratedDocument, GenerateDocumentRequest  # noqa: E402
from app.crm.document_rendering import RenderError  # noqa: E402

NOC_READY = {
    "owner": {"full_name": "Aisha Khan", "title_deed_number": "TD-1", "id_number": "784-1"}
}


@pytest.fixture
def pipeline(monkeypatch):
    """Fake renderer and storage; records what reached them."""
    calls = {"render": 0, "stored": []}

    async def fake_render(doc_type, snapshot):
        calls["render"] += 1
        calls["last_snapshot"] = snapshot
        return b"%PDF-1.7 fake"

    async def fake_store(organization_id, document_id, filename, data):
        calls["stored"].append((organization_id, document_id, filename))
        return f"crm-documents/{organization_id}/{document_id}.pdf"

    monkeypatch.setattr(documents, "_render", fake_render)
    monkeypatch.setattr(documents, "store_pdf", fake_store)
    return calls


async def _saved(db, fields=NOC_READY, org="org-a"):
    payload = ListingDocumentInfoUpdate(
        source="property_finder",
        listing_key="123",
        fields=DocumentFields.model_validate(fields),
        expected_revision=0,
    )
    return await documents.save_document_info(
        db, organization_id=org, user_id="u1", payload=payload
    )


def generate_request(doc_type="noc", revision=1, key=None):
    return GenerateDocumentRequest(
        source="property_finder",
        listing_key="123",
        doc_type=doc_type,
        expected_revision=revision,
        idempotency_key=key or uuid4(),
    )


async def _generate(db, request, org="org-a"):
    return await documents.generate_document(db, organization_id=org, user_id="u1", payload=request)


async def _rows(db):
    return (await db.exec(select(CrmGeneratedDocument))).all()


async def test_generated_document_is_ready_with_its_snapshot(db, listings, pipeline):
    await _saved(db)
    document, created = await _generate(db, generate_request())
    assert created and document.status == "ready" and document.template_version == "draft-1"
    row = (await _rows(db))[0]
    assert row.object_key == f"crm-documents/org-a/{row.id}.pdf"
    assert row.snapshot["owner"]["full_name"] == "Aisha Khan"
    assert row.size_bytes == len(b"%PDF-1.7 fake") and len(row.sha256) == 64
    assert pipeline["stored"][0][2] == "noc-123.pdf"


async def test_missing_legal_fields_block_generation_and_store_nothing(db, listings, pipeline):
    await _saved(db, fields={"owner": {"full_name": "Aisha Khan"}})
    with pytest.raises(HTTPException) as error:
        await _generate(db, generate_request())
    assert error.value.status_code == 422
    assert error.value.detail == {
        "code": "missing_fields",
        "fields": ["owner.title_deed_number", "owner.id_number"],
    }
    assert await _rows(db) == [] and pipeline["render"] == 0


async def test_generation_needs_saved_information_at_the_expected_revision(db, listings, pipeline):
    with pytest.raises(HTTPException) as error:
        await _generate(db, generate_request())
    assert error.value.status_code == 409
    await _saved(db)
    with pytest.raises(HTTPException) as error:
        await _generate(db, generate_request(revision=2))
    # The agent generated from a form someone else has since changed.
    assert (error.value.status_code, error.value.detail) == (409, "stale_revision")


async def test_same_idempotency_key_returns_the_same_document(db, listings, pipeline):
    await _saved(db)
    request = generate_request()
    first, created_first = await _generate(db, request)
    again, created_again = await _generate(db, request)
    assert (first.id, created_first, created_again) == (again.id, True, False)
    assert pipeline["render"] == 1 and len(await _rows(db)) == 1


async def test_concurrent_duplicates_create_one_document(tmp_path, listings, pipeline):
    import asyncio

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'docs.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        setup.add(Organization(id="org-a", name="org-a"))
        await setup.commit()
        await _saved(setup)
    request = generate_request()
    async with (
        AsyncSession(engine, expire_on_commit=False) as one,
        AsyncSession(engine, expire_on_commit=False) as two,
    ):
        results = await asyncio.gather(_generate(one, request), _generate(two, request))
    async with AsyncSession(engine) as check:
        rows = await _rows(check)
    await engine.dispose()
    assert len(rows) == 1
    assert {document.id for document, _ in results} == {rows[0].id}


async def test_new_key_after_editing_keeps_the_old_pdf_input(db, listings, pipeline):
    await _saved(db)
    await _generate(db, generate_request())
    edited = {"owner": {**NOC_READY["owner"], "full_name": "Aisha K. Rahman"}}
    await documents.save_document_info(
        db,
        organization_id="org-a",
        user_id="u1",
        payload=ListingDocumentInfoUpdate(
            source="property_finder",
            listing_key="123",
            fields=DocumentFields.model_validate(edited),
            expected_revision=1,
        ),
    )
    await _generate(db, generate_request(revision=2))
    names = sorted(row.snapshot["owner"]["full_name"] for row in await _rows(db))
    assert names == ["Aisha K. Rahman", "Aisha Khan"]


@pytest.mark.parametrize(
    ("failure", "code"),
    [("render", "render_failed"), ("timeout", "render_timeout"), ("storage", "storage_failed")],
)
async def test_failures_are_recorded_without_a_file(
    db, listings, pipeline, monkeypatch, failure, code
):
    async def broken_render(doc_type, snapshot):
        raise RenderError("boom") if failure == "render" else TimeoutError()

    async def broken_store(*args):
        raise OSError("bucket unavailable")

    if failure == "storage":
        monkeypatch.setattr(documents, "store_pdf", broken_store)
    else:
        monkeypatch.setattr(documents, "_render", broken_render)
    await _saved(db)
    with pytest.raises(HTTPException) as error:
        await _generate(db, generate_request())
    row = (await _rows(db))[0]
    assert error.value.status_code == 502
    assert error.value.detail == {"code": code, "document_id": str(row.id)}
    assert (row.status, row.failure_code, row.object_key) == ("failed", code, None)


async def test_generation_for_another_companys_listing_is_not_found(db, listings, pipeline):
    await _saved(db)
    listings["123"] = listing(managed=False)  # the organization switched company
    with pytest.raises(HTTPException) as error:
        await _generate(db, generate_request())
    assert error.value.status_code == 404 and pipeline["render"] == 0


async def test_stale_generating_rows_are_reconciled(db, listings, pipeline, monkeypatch):
    await _saved(db)

    async def crash(doc_type, snapshot):
        raise KeyboardInterrupt  # stand-in for a process dying mid-render

    monkeypatch.setattr(documents, "_render", crash)
    with pytest.raises(KeyboardInterrupt):
        await _generate(db, generate_request())
    await db.rollback()
    assert await documents.reconcile_stale_documents(db, older_than=timedelta(minutes=10)) == 0
    assert await documents.reconcile_stale_documents(db, older_than=timedelta(seconds=-1)) == 1
    row = (await _rows(db))[0]
    assert (row.status, row.failure_code) == ("failed", "interrupted")


async def test_rendering_runs_in_a_worker_thread_and_respects_the_deadline(monkeypatch):
    import threading
    import time as clock

    loop_thread = threading.get_ident()
    seen = {}

    def slow_render(doc_type, snapshot):
        seen["thread"] = threading.get_ident()
        clock.sleep(0.2)
        return b"%PDF"

    monkeypatch.setattr(documents, "render_pdf", slow_render)
    assert await documents._render("noc", {}) == b"%PDF"
    assert seen["thread"] != loop_thread  # the event loop keeps serving other requests
    monkeypatch.setattr(documents, "RENDER_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(TimeoutError):
        await documents._render("noc", {})


# ── listing and downloading (Task 8) ─────────────────────────────────────────


@pytest.fixture
def signer(monkeypatch):
    signed = []

    async def fake_sign(object_key, *, inline=False):
        signed.append(object_key)
        return "https://storage.example/signed", datetime(2026, 11, 11, tzinfo=timezone.utc)

    monkeypatch.setattr(documents, "signed_pdf_url", fake_sign)
    return signed


async def _ready_noc(db, org="org-a"):
    await _saved(db, org=org)
    document, _ = await _generate(db, generate_request(), org=org)
    return document


async def test_documents_survive_the_listing_leaving_property_finder(
    db, listings, pipeline, signer
):
    made = await _ready_noc(db)
    listings.clear()  # no longer published
    page = await documents.list_documents(db, organization_id="org-a")
    assert [item.id for item in page.items] == [made.id]
    assert page.items[0].listing_title == "Marina Gate 2BR"
    assert (await documents.get_document(db, organization_id="org-a", document_id=made.id)).id
    link = await documents.download_document(db, organization_id="org-a", document_id=made.id)
    assert link.url == "https://storage.example/signed"


async def test_documents_stay_with_the_organization_after_switching_company(db, listings, pipeline):
    made = await _ready_noc(db)
    listings["123"] = listing(managed=False)
    page = await documents.list_documents(db, organization_id="org-a")
    assert [item.id for item in page.items] == [made.id]
    assert (await documents.list_documents(db, organization_id="org-b")).items == []


async def test_another_organization_gets_the_same_404_as_a_missing_document(
    db, listings, pipeline, signer
):
    made = await _ready_noc(db)
    details = []
    for org, document_id in (("org-b", made.id), ("org-a", uuid4())):
        for call in (documents.get_document, documents.download_document):
            with pytest.raises(HTTPException) as error:
                await call(db, organization_id=org, document_id=document_id)
            details.append((error.value.status_code, error.value.detail))
    assert set(details) == {(404, "Document not found")}
    assert signer == []  # no link is ever signed before the access check passes


async def test_failed_document_has_no_download(db, listings, pipeline, signer, monkeypatch):
    async def broken(*args):
        raise RenderError("boom")

    monkeypatch.setattr(documents, "_render", broken)
    await _saved(db)
    with pytest.raises(HTTPException) as failure:
        await _generate(db, generate_request())
    from uuid import UUID

    document_id = UUID(failure.value.detail["document_id"])
    with pytest.raises(HTTPException) as error:
        await documents.download_document(db, organization_id="org-a", document_id=document_id)
    assert (error.value.status_code, error.value.detail) == (409, "not_ready")
    assert signer == []


async def test_list_filters_by_listing_type_and_search_newest_first(db, listings, pipeline):
    listings["456"] = listing("456", title="Palm Villa")
    await _saved(db)
    noc, _ = await _generate(db, generate_request())
    brochure, _ = await _generate(db, generate_request("brochure"))
    await documents.save_document_info(
        db,
        organization_id="org-a",
        user_id="u1",
        payload=ListingDocumentInfoUpdate(
            source="property_finder",
            listing_key="456",
            fields=DocumentFields(),
            expected_revision=0,
        ),
    )
    palm, _ = await _generate(
        db,
        GenerateDocumentRequest(
            source="property_finder",
            listing_key="456",
            doc_type="brochure",
            expected_revision=1,
            idempotency_key=uuid4(),
        ),
    )

    def ids(page):
        return [item.id for item in page.items]

    everything = await documents.list_documents(db, organization_id="org-a")
    assert ids(everything) == [palm.id, brochure.id, noc.id] and everything.total == 3
    assert ids(await documents.list_documents(db, organization_id="org-a", listing_key="123")) == [
        brochure.id,
        noc.id,
    ]
    assert ids(await documents.list_documents(db, organization_id="org-a", doc_type="noc")) == [
        noc.id
    ]
    assert ids(await documents.list_documents(db, organization_id="org-a", search="palm")) == [
        palm.id
    ]
    second = await documents.list_documents(db, organization_id="org-a", limit=2, offset=2)
    assert (ids(second), second.total) == ([noc.id], 3)


async def test_preview_link_is_signed_inline_after_the_access_check(
    db, listings, pipeline, monkeypatch
):
    made = await _ready_noc(db)
    seen = []

    async def fake_sign(object_key, *, inline=False):
        seen.append(inline)
        return "https://storage.example/signed", datetime(2026, 11, 11, tzinfo=timezone.utc)

    monkeypatch.setattr(documents, "signed_pdf_url", fake_sign)
    await documents.download_document(db, organization_id="org-a", document_id=made.id, inline=True)
    with pytest.raises(HTTPException):
        await documents.download_document(
            db, organization_id="org-b", document_id=made.id, inline=True
        )
    assert seen == [True]


async def test_list_names_the_company_and_area_each_document_was_made_for(db, listings, pipeline):
    await _ready_noc(db)
    # Even if the listing later changes or leaves Property Finder, the list keeps showing
    # the company and area printed on the PDF.
    listings.clear()

    item = (await documents.list_documents(db, organization_id="org-a")).items[0]

    assert (item.company_name, item.listing_area) == ("Big Firm", "Dubai Marina")
