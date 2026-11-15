"""Listings are scraped third-party data: no personal contact details or source internals."""

import json
from unittest.mock import AsyncMock

import pytest

from app.listings import queries
from app.listings.models import ListingCardResponse, ListingDetailResponse
from app.listings.redaction import redact_contacts

SENTINELS = [
    "agent.person@example.com",
    "client.person@example.com",
    "broker.office@example.com",
    "+971501112233",
    "+971504445566",
    "971507778899",
    "Private Agent Name",
    "Private Client Name",
    "12 Hidden Street, Office 4",
    "run-secret-123",
    "agent-photo.example/face.jpg",
    "agent-slug-secret",
]

FORBIDDEN_KEYS = {
    "email",
    "phone",
    "whatsapp",
    "address",
    "client",
    "agent",
    "agent_name",
    "agent_image_url",
    "source_run_id",
    "source_manifest_key",
    "source_metadata",
    "scraped_at",
    "run_id",
}


def _party(prefix: str, name: str) -> dict:
    return {
        "id": f"{prefix}-id",
        "name": name,
        "email": f"{prefix}.person@example.com",
        "phone": "+971501112233",
        "whatsapp": "971507778899",
        "image": "https://agent-photo.example/face.jpg",
        "logo": "https://cdn.example/logo.png",
        "address": "12 Hidden Street, Office 4",
        "slug": "agent-slug-secret",
        "languages": ["English"],
    }


def _bronze_row() -> dict:
    agent = _party("agent", "Private Agent Name")
    broker = _party("broker", "Acme Realty")
    broker["email"] = "broker.office@example.com"
    broker["phone"] = "+971504445566"
    return {
        "listing_id": "L1",
        "category_id": 2,
        "title": "Two bed in Marina",
        "listing_location_names_json": json.dumps(["Dubai", "Dubai Marina", "Marina Tower"]),
        "price_json": json.dumps({"value": 120000, "currency": "AED", "period": "yearly"}),
        "size_json": json.dumps({"value": 1000, "unit": "sqft"}),
        "bedrooms": "2",
        "is_available": 1,
        "snapshot_at": "2026-05-27 08:00:00",
        "scraped_at": "2026-05-27 08:00:00",
        "run_id": "run-secret-123",
        "share_url": "https://www.propertyfinder.ae/en/plp/rent/x-1.html",
        "agent_json": json.dumps(agent),
        "broker_json": json.dumps(broker),
        "client_json": json.dumps(_party("client", "Private Client Name")),
        "raw_property_json": json.dumps(
            {"description": "Lovely flat. Call +971 50 123 4567 or mail me@example.com."}
        ),
        "images_json": json.dumps([{"medium_url": "https://cdn.example/1.jpg"}]),
    }


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _assert_clean(payload: dict) -> None:
    assert FORBIDDEN_KEYS.isdisjoint(set(_walk_keys(payload))), sorted(
        FORBIDDEN_KEYS & set(_walk_keys(payload))
    )
    body = json.dumps(payload)
    leaked = [value for value in SENTINELS if value in body]
    assert leaked == []


async def test_listing_detail_response_has_no_contact_or_source_fields(client, monkeypatch):
    monkeypatch.setattr(queries, "fetch_listing_detail", AsyncMock(return_value=[_bronze_row()]))

    response = await client.get("/api/v1/listings/L1")

    assert response.status_code == 200
    payload = response.json()
    _assert_clean(payload)
    assert payload["listing_id"] == "L1"
    assert payload["broker_name"] == "Acme Realty"
    assert payload["broker_logo_url"] == "https://cdn.example/logo.png"
    assert payload["share_url"].startswith("https://www.propertyfinder.ae/")


async def test_listing_list_response_has_no_contact_or_source_fields(client, monkeypatch):
    monkeypatch.setattr(queries, "fetch_listing_rows", AsyncMock(return_value=[_bronze_row()]))
    monkeypatch.setattr(queries, "fetch_listing_count", AsyncMock(return_value=[{"total": 1}]))
    monkeypatch.setattr(queries, "fetch_listing_benchmarks", AsyncMock(return_value=[]))

    response = await client.get("/api/v1/listings?mode=rent")

    assert response.status_code == 200
    payload = response.json()
    _assert_clean(payload)
    assert payload["listings"][0]["broker_name"] == "Acme Realty"


def test_response_schemas_declare_no_contact_or_source_fields():
    for model in (ListingCardResponse, ListingDetailResponse):
        assert FORBIDDEN_KEYS.isdisjoint(model.model_fields), model.__name__


def test_search_does_not_match_inside_contact_json():
    where, _ = queries._where_sql(
        mode="rent",
        search="gmail",
        area=None,
        property_type=None,
        bedrooms=None,
        bedrooms_in=None,
        price_min=None,
        price_max=None,
    )

    assert "agent_json" not in where
    assert "positionCaseInsensitive(broker_json" not in where


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Call +971 50 123 4567 now", "Call [contact removed] now"),
        ("WhatsApp 0501234567 today", "WhatsApp [contact removed] today"),
        ("mail me@example.com please", "mail [contact removed] please"),
        ("Unit 1204, 1,250 sqft, AED 120,000", "Unit 1204, 1,250 sqft, AED 120,000"),
        ("Built 2019, 2 bed, 3 baths, ref 12345", "Built 2019, 2 bed, 3 baths, ref 12345"),
        (None, None),
    ],
)
def test_redact_contacts_removes_phones_and_emails_only(raw, expected):
    assert redact_contacts(raw) == expected


async def test_listing_description_has_phones_and_emails_removed(client, monkeypatch):
    monkeypatch.setattr(queries, "fetch_listing_detail", AsyncMock(return_value=[_bronze_row()]))

    payload = (await client.get("/api/v1/listings/L1")).json()

    assert "4567" not in payload["description"]
    assert "me@example.com" not in payload["description"]
    assert "Lovely flat" in payload["description"]
