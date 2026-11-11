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
