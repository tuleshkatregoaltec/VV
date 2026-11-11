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
