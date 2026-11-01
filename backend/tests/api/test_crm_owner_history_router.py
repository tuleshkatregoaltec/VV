from unittest.mock import AsyncMock

import pytest

from app.crm.import_models import (
    CrmOwnerHistoryResponse,
    CrmOwnerHistorySummary,
    CrmOwnerRegistryResponse,
    CrmOwnerRegistrySummary,
)


def _summary():
    return CrmOwnerHistorySummary(
        source_event_count=0,
        identifiable_property_count=0,
        owner_property_count=0,
        verified_current_count=0,
        probable_current_count=0,
        former_count=0,
        unresolved_count=0,
        invalid_identity_source_count=0,
        legacy_source_event_count=0,
        resolver_versions={},
    )


@pytest.mark.parametrize(
    "path, import_id",
    [
        ("/owner-history/summary", None),
        ("/owner-history/summary?import_id=3", 3),
        ("/contact-imports/3/owner-summary", 3),
    ],
)
async def test_history_summary_uses_authenticated_tenant(client, monkeypatch, path, import_id):
    service = AsyncMock(return_value=_summary())
    monkeypatch.setattr("app.crm.router.get_owner_history_summary", service)
    response = await client.get("/api/v1/crm" + path)
    assert response.status_code == 200
    assert service.await_args.kwargs == {"organization_id": "1", "import_id": import_id}


async def test_history_pagination_and_import_scope_reach_the_service(client, monkeypatch):
    service = AsyncMock(
        return_value=CrmOwnerHistoryResponse(
            owner_key="owner",
            summary=_summary(),
            events=[],
            total=0,
            limit=2,
            offset=4,
        )
    )
    monkeypatch.setattr("app.crm.router.get_owner_history", service)
    response = await client.get("/api/v1/crm/owners/owner/history?import_id=3&limit=2&offset=4")
    assert response.status_code == 200
    assert service.await_args.kwargs == {
        "organization_id": "1",
        "owner_key": "owner",
        "import_id": 3,
        "limit": 2,
        "offset": 4,
    }


@pytest.mark.parametrize(
    "path", ["/owner-history/summary", "/owners/owner/history", "/contact-imports/3/owner-summary"]
)
async def test_history_requires_subscription(client_no_auth, path):
    response = await client_no_auth.get("/api/v1/crm" + path)
    assert response.status_code in {401, 403}


async def test_history_rejects_unbounded_pages(client):
    response = await client.get("/api/v1/crm/owners/owner/history?limit=501")
    assert response.status_code == 422


async def test_review_queue_accepts_unverified_sellers_with_authenticated_tenant(
    client, monkeypatch
):
    service = AsyncMock(
        return_value=CrmOwnerRegistryResponse(
            scope="needs_review",
            owners=[],
            total=0,
            limit=25,
            offset=0,
            summary=CrmOwnerRegistrySummary(),
        )
    )
    monkeypatch.setattr("app.crm.router.get_owner_registry", service)
    response = await client.get(
        "/api/v1/crm/owner-registry?scope=needs_review&status=unverified_former_owner&limit=25"
    )
    assert response.status_code == 200
    assert service.await_args.kwargs["organization_id"] == "1"
    assert service.await_args.kwargs["scope"] == "needs_review"
    assert service.await_args.kwargs["status"] == "unverified_former_owner"


async def test_review_queue_requires_subscription(client_no_auth):
    response = await client_no_auth.get("/api/v1/crm/owner-registry?scope=needs_review")
    assert response.status_code in {401, 403}


async def test_transaction_match_filter_reaches_service_with_authenticated_tenant(
    client, monkeypatch
):
    service = AsyncMock(
        return_value=CrmOwnerRegistryResponse(
            scope="prior_owners",
            owners=[],
            total=0,
            limit=10,
            offset=20,
            summary=CrmOwnerRegistrySummary(),
        )
    )
    monkeypatch.setattr("app.crm.router.get_owner_registry", service)
    response = await client.get(
        "/api/v1/crm/owner-registry?scope=prior_owners&transaction_match_status=unmatched&limit=10&offset=20"
    )
    assert response.status_code == 200
    assert service.await_args.kwargs["organization_id"] == "1"
    assert service.await_args.kwargs["transaction_match_status"] == "unmatched"
    assert service.await_args.kwargs["scope"] == "prior_owners"
    assert service.await_args.kwargs["offset"] == 20
    response = await client.get("/api/v1/crm/owner-registry?transaction_match_status=verified")
    assert response.status_code == 422
