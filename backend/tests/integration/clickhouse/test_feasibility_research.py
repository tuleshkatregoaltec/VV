"""Feasibility pricing, area lookups, rental bands and chat tools read DXBI's listed records."""

import pytest
from test_transactions import (  # noqa: F401
    dxbi,
    lease,
    sale,
)

from app.feasibility import research


async def test_research_prices_from_dxbi_with_floors_stage_and_rental_band_minimum(dxbi):  # noqa: F811
    await dxbi(
        sales=[
            sale("ready", unit_number="101"),
            sale("ready-two", unit_number="102", sale_amount_aed=1_800_000),
            sale("offplan", unit_number="103", market_status="Offplan"),
            # AED 40,000 is below the price floor: not a market price.
            sale("below-floor", unit_number="104", sale_amount_aed=40_000),
        ],
        leases=[
            *[
                lease(
                    f"studio-{i}",
                    unit_number=str(i),
                    location_name="Iris Blue, Downtown Dubai",
                    area_name="Downtown Dubai",
                    bedrooms="Studio",
                    size_sqft=592.0,
                    annual_rent_aed=55_000,
                )
                for i in range(5)
            ],
            *[
                lease(
                    f"one-bed-{i}",
                    unit_number=f"2{i}",
                    location_name="Iris Blue, Downtown Dubai",
                    area_name="Downtown Dubai",
                    bedrooms="1 Bed",
                    size_sqft=968.0,
                    annual_rent_aed=90_000,
                )
                for i in range(4)
            ],
        ],
    )
    assert await research.resolve_market_area("Downtown") == "Downtown Dubai"
    assert "Downtown Dubai" in await research.get_areas()

    existing = await research.get_market_pricing("downtown dubai", "residential")
    assert [(r.unit_type, r.transaction_count) for r in existing] == [("1br", 2)]
    assert existing[0].last_transaction_date is not None
    off_plan = await research.get_market_pricing("downtown dubai", "residential", stage="off_plan")
    assert [(r.unit_type, r.transaction_count) for r in off_plan] == [("1br", 1)]

    payload = await research.fetch_chat_research(
        "show_transactions", {"area": "Downtown", "limit": 200}
    )
    assert sorted(r["transaction_id"] for r in payload["rows"]) == ["ready", "ready-two"]
    analytics = await research.fetch_chat_research("show_analytics", {"area": "Downtown"})
    assert analytics["by_rooms"][0]["txn_count"] == 2

    rates = await research.get_rental_rates_by_size_band("downtown dubai")
    assert [(r.unit_type_proxy, r.contract_count) for r in rates] == [("studio", 5)]
    assert rates[0].median_rent_psm_annual == pytest.approx(1000, rel=0.01)
