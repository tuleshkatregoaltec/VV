import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.crm import company_listings


async def test_company_inventory_uses_current_broker_rows_and_annual_prices(
    warehouse, install_serving, monkeypatch
):
    await install_serving(tables=("pf_listings_bronze",), views=())
    fields = [
        "property_key",
        "listing_id",
        "run_id",
        "scraped_at",
        "category_id",
        "title",
        "price_json",
        "size_json",
        "bedrooms",
        "listing_location_names_json",
        "broker_json",
        "agent_json",
        "raw_property_json",
        "is_available",
    ]

    def row(key, price, *, broker="agency", category=1, period="sale", available=1, day="02"):
        return [
            key,
            key,
            f"run-{day}",
            f"2026-11-{day}T10:00:00Z",
            category,
            f"Marina {key}",
            json.dumps({"value": price, "period": period}),
            json.dumps({"value": 1200}),
            "2",
            json.dumps(["Dubai", "Dubai Marina", "Marina Gate"]),
            json.dumps({"id": broker, "name": broker}),
            json.dumps({"id": "agent", "name": "Sample Agent", "email": "agent@example.com"}),
            json.dumps(
                {
                    "property_type": "Apartment",
                    "listed_date": "2026-11-01T10:00:00Z",
                    "contact_options": [{"type": "phone", "value": "+971500000001"}],
                }
            ),
            available,
        ]

    await warehouse.insert(
        "pf_listings_bronze",
        [
            row("sale", 1700000, day="01"),
            row("sale", 1900000),
            row("other", 1900000, broker="other-agency"),
            row("rent", 10000, category=2, period="monthly"),
            row("removed", 1800000, day="01"),
            row("removed", 1800000, available=0),
        ],
        column_names=fields,
    )
    companies = await company_listings.list_property_finder_companies()
    assert {company.broker_id: company.listings for company in companies} == {
        "agency": 2,
        "other-agency": 1,
    }
    agents = await company_listings._agent_inventory("agency")
    assert agents[0].phone == "+971500000001" and agents[0].listings == 2
    monkeypatch.setattr(
        company_listings,
        "_selected_source",
        AsyncMock(return_value=SimpleNamespace(broker_id="agency")),
    )
    rows = await company_listings.find_matching_company_listings(
        None,
        "tenant",
        mode="sale",
        locations=["Dubai Marina"],
        band=(1800000, 2000000),
        property_type="Apartment",
        bedrooms=["2"],
    )
    assert [(item.reference, item.price_aed) for item in rows] == [("PF-sale", 1900000)]
    rows = await company_listings.find_matching_company_listings(
        None,
        "tenant",
        mode="rent",
        locations=["Dubai Marina"],
        band=(119999, 120001),
        property_type="Apartment",
        bedrooms=["2"],
    )
    assert [(item.reference, item.price_aed) for item in rows] == [("PF-rent", 120000)]
    assert await company_listings._company_rows("agency' OR 1=1 --", limit=100, offset=0) == []
