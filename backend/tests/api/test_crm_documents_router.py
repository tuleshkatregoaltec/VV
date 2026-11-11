from unittest.mock import AsyncMock


async def test_unknown_company_listing_is_404(client, monkeypatch):
    monkeypatch.setattr("app.crm.router.get_company_listing", AsyncMock(return_value=None))

    response = await client.get("/api/v1/crm/company-listings/123")

    assert response.status_code == 404
    assert response.json() == {"detail": "Listing not found"}


async def test_company_listing_key_must_be_digits(client, monkeypatch):
    service = AsyncMock()
    monkeypatch.setattr("app.crm.router.get_company_listing", service, raising=False)

    response = await client.get("/api/v1/crm/company-listings/PF-1x")

    assert response.status_code == 422
    service.assert_not_awaited()


async def test_document_info_uses_the_signed_in_organization(client, monkeypatch):
    from crm_document_helpers import listing

    from app.crm.document_models import DocumentFields, ListingDocumentInfoResponse

    service = AsyncMock(
        return_value=ListingDocumentInfoResponse(
            listing=listing(), fields=DocumentFields(), revision=0
        )
    )
    monkeypatch.setattr("app.crm.router.get_document_info", service)

    response = await client.get(
        "/api/v1/crm/listing-document-info",
        params={"source": "property_finder", "listing_key": "123"},
    )

    assert response.status_code == 200
    assert service.await_args.kwargs["organization_id"] == "1"
    assert service.await_args.kwargs["listing_key"] == "123"


async def test_saving_document_info_rejects_a_body_organization(client, monkeypatch):
    service = AsyncMock()
    monkeypatch.setattr("app.crm.router.save_document_info", service)

    response = await client.put(
        "/api/v1/crm/listing-document-info",
        json={
            "source": "property_finder",
            "listing_key": "123",
            "fields": {},
            "expected_revision": 0,
            "organization_id": "someone-else",
        },
    )

    assert response.status_code == 422
    service.assert_not_awaited()


def _generated():
    from datetime import datetime, timezone
    from uuid import UUID

    from app.crm.document_models import GeneratedDocumentResponse

    return GeneratedDocumentResponse(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        source="property_finder",
        listing_key="123",
        listing_title="Marina Gate 2BR",
        doc_type="noc",
        template_version="draft-1",
        status="ready",
        failure_code=None,
        size_bytes=10,
        created_by_user_id="test-user-id",
        created_at=datetime(2026, 11, 11, tzinfo=timezone.utc),
    )


GENERATE = {
    "source": "property_finder",
    "listing_key": "123",
    "doc_type": "noc",
    "expected_revision": 1,
    "idempotency_key": "6f1d3c1e-8a7b-4c33-9b1a-2f0e5d4c3b2a",
}


async def test_new_document_is_201_and_a_replayed_key_is_200(client, monkeypatch):
    service = AsyncMock(side_effect=[(_generated(), True), (_generated(), False)])
    monkeypatch.setattr("app.crm.router.generate_document", service)

    first = await client.post("/api/v1/crm/documents", json=GENERATE)
    again = await client.post("/api/v1/crm/documents", json=GENERATE)

    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["id"] == again.json()["id"]
    assert service.await_args.kwargs["organization_id"] == "1"
    assert "snapshot" not in first.json() and "object_key" not in first.json()


async def test_unknown_document_type_is_rejected(client, monkeypatch):
    service = AsyncMock()
    monkeypatch.setattr("app.crm.router.generate_document", service)

    response = await client.post("/api/v1/crm/documents", json={**GENERATE, "doc_type": "invoice"})

    assert response.status_code == 422
    service.assert_not_awaited()


async def test_download_link_is_never_cached(client, monkeypatch):
    from datetime import datetime, timezone

    from app.crm.document_models import DocumentDownloadResponse

    service = AsyncMock(
        return_value=DocumentDownloadResponse(
            url="https://storage.example/signed",
            expires_at=datetime(2026, 11, 11, tzinfo=timezone.utc),
        )
    )
    monkeypatch.setattr("app.crm.router.download_document", service)

    response = await client.post(
        "/api/v1/crm/documents/00000000-0000-0000-0000-000000000001/download"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert service.await_args.kwargs["organization_id"] == "1"


async def test_document_list_limit_is_bounded(client, monkeypatch):
    service = AsyncMock()
    monkeypatch.setattr("app.crm.router.list_documents", service)

    response = await client.get("/api/v1/crm/documents", params={"limit": 101})

    assert response.status_code == 422
    service.assert_not_awaited()


REAL_KEY = "E4PE3H23YAHTAQDKRCMSMVTDK4"  # Property Finder ids are 26 letters/digits


async def test_real_property_finder_listing_ids_are_accepted(client, monkeypatch):
    from crm_document_helpers import listing

    service = AsyncMock(return_value=listing(REAL_KEY))
    monkeypatch.setattr("app.crm.router.get_company_listing", service)

    response = await client.get(f"/api/v1/crm/company-listings/{REAL_KEY}")

    assert response.status_code == 200
    assert service.await_args.args[2] == REAL_KEY


async def test_preview_asks_for_an_inline_link(client, monkeypatch):
    from datetime import datetime, timezone

    from app.crm.document_models import DocumentDownloadResponse

    service = AsyncMock(
        return_value=DocumentDownloadResponse(
            url="https://storage.example/signed",
            expires_at=datetime(2026, 11, 11, tzinfo=timezone.utc),
        )
    )
    monkeypatch.setattr("app.crm.router.download_document", service)

    response = await client.post(
        "/api/v1/crm/documents/00000000-0000-0000-0000-000000000001/download",
        params={"inline": "true"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert service.await_args.kwargs["inline"] is True
