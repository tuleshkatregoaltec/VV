"""The Transactions pages read DXBI records only, once each, in DXBI's square feet."""

import csv
import io
from datetime import UTC, date, datetime, timedelta

import pytest

from app.transaction import exports, facets, service
from app.transaction.models import RentalFilters, SalesFilters

TODAY = date.today()
SALE_COLUMNS = (
    "sale_key",
    "transaction_date",
    "unit_number",
    "building_name",
    "building_key",
    "project_name",
    "area_name",
    "property_type",
    "market_status",
    "bedrooms",
    "size_sqft",
    "sale_amount_aed",
    "detail_url",
    "loaded_at",
)
RENTAL_COLUMNS = (
    "contract_key",
    "occurrence_index",
    "unit_number",
    "location_name",
    "building_name",
    "area_name",
    "property_type",
    "bedrooms",
    "size_sqft",
    "contract_amount_aed",
    "contract_term_days",
    "contract_term_months",
    "annual_rent_aed",
    "lease_start",
    "lease_end",
    "contract_state",
    "unit_candidate_key",
    "unit_cohort_key",
    "source_account",
    "source_run_id",
    "filter_profile_id",
    "source_location_id",
    "configuration_hash",
    "raw_row_fingerprint",
    "source_shard_date",
    "scraped_at",
)
LOADED = datetime(2026, 1, 1, tzinfo=UTC)


def sale(key: str, **values) -> list:
    row = {
        "sale_key": key,
        "transaction_date": TODAY - timedelta(days=1),
        "unit_number": "101",
        "building_name": "Tower A",
        "building_key": "towera",
        "project_name": "",
        "area_name": "Downtown Dubai",
        "property_type": "Apartment",
        "market_status": "Ready",
        "bedrooms": "1 Bed",
        "size_sqft": 800.0,
        "sale_amount_aed": 1_600_000,
        "detail_url": f"https://dxbinteract.com/sold/{key}",
        "loaded_at": LOADED,
        **values,
    }
    return [row[column] for column in SALE_COLUMNS]


def lease(key: str, **values) -> list:
    row = {
        "contract_key": key,
        "occurrence_index": 1,
        "unit_number": "1101",
        "location_name": "Iris Blue, Dubai Marina",
        "building_name": "Iris Blue",
        "area_name": "Dubai Marina",
        "property_type": "Apartment",
        "bedrooms": "2 Bed",
        "size_sqft": 1326.0,
        "contract_amount_aed": 320_000,
        "contract_term_days": 731,
        "contract_term_months": 24.0,
        "annual_rent_aed": 160_000,
        "lease_start": TODAY - timedelta(days=2),
        "lease_end": TODAY - timedelta(days=2) + timedelta(days=730),
        "contract_state": "New",
        "unit_candidate_key": key,
        "unit_cohort_key": key,
        "source_account": "account-b",
        "source_run_id": "run",
        "filter_profile_id": "broad",
        "source_location_id": "1",
        "configuration_hash": "c" * 20,
        "raw_row_fingerprint": "f" * 64,
        "source_shard_date": TODAY,
        "scraped_at": LOADED,
        **values,
    }
    return [row[column] for column in RENTAL_COLUMNS]


@pytest.fixture
async def dxbi(warehouse, install_serving):
    await install_serving(tables=("dxbi_sales_unit_events", "dxbi_rental_events"), views=())

    async def insert(*, sales=(), leases=()):
        if sales:
            await warehouse.insert(
                "dxbi_sales_unit_events", list(sales), column_names=list(SALE_COLUMNS)
            )
        if leases:
            await warehouse.insert(
                "dxbi_rental_events", list(leases), column_names=list(RENTAL_COLUMNS)
            )

    return insert


async def test_each_dxbi_sale_appears_once_with_its_unit_in_square_metres(dxbi):
    await dxbi(
        sales=[
            sale("plain", unit_number="1904"),
            # A re-normalised address leaves an older version of the same sale: the latest wins.
            sale("moved", building_key="tower b", building_name="Old name", unit_number="7"),
            sale(
                "moved",
                building_key="towerb",
                building_name="Tower B",
                unit_number="7",
                loaded_at=LOADED + timedelta(days=1),
            ),
            # The same sale loaded from a CSV export (no DXBI link) and from the scrape.
            sale("from-csv", building_key="towerc", unit_number="501", detail_url=""),
            sale("from-scrape", building_key="towerc", unit_number="501"),
            # 'D' is a block letter, not a unit: two DXBI records stay two sales.
            sale("block-1", building_key="sakura", unit_number="D"),
            sale("block-2", building_key="sakura", unit_number="D"),
            # Outside the last 30 days, today included: 30 days ago and in the future.
            sale("old", transaction_date=TODAY - timedelta(days=30)),
            sale("future", transaction_date=TODAY + timedelta(days=3)),
        ]
    )

    page = await service.fetch_sales_transactions(SalesFilters(timeframe_days=30), 30, 0)

    ids = sorted(row.transaction_id for row in page.transactions)
    assert ids == ["block-1", "block-2", "from-scrape", "moved", "plain"]
    assert page.total == 5
    plain = next(row for row in page.transactions if row.transaction_id == "plain")
    # DXBI's own size; AED 1,600,000 over 800 sq ft is AED 2,000 per sq ft (price / size).
    assert plain.model_dump() == {
        "transaction_id": "plain",
        "transaction_date": TODAY - timedelta(days=1),
        "unit_number": "1904",
        "building_name": "Tower A",
        "project_name": None,
        "location_name": "Downtown Dubai",
        "property_type": "Apartment",
        "bedrooms": "1 Bed",
        "status": "Ready",
        "size_sqft": 800.0,
        "price_aed": 1_600_000,
        "price_per_sqft_aed": 2_000,
    }
    moved = next(row for row in page.transactions if row.transaction_id == "moved")
    assert moved.building_name == "Tower B"

    second_page = await service.fetch_sales_transactions(SalesFilters(timeframe_days=30), 2, 2)
    first_two = await service.fetch_sales_transactions(SalesFilters(timeframe_days=30), 2, 0)
    assert second_page.total == 5
    assert not {r.transaction_id for r in second_page.transactions} & {
        r.transaction_id for r in first_two.transactions
    }


async def test_sales_filters_bands_usage_and_locations(dxbi):
    await dxbi(
        sales=[
            sale("villa", property_type="Villa", bedrooms="4 Beds", unit_number="V1"),
            sale("office", property_type="Office", bedrooms="", unit_number="O1"),
            sale("plot", property_type="Plot", bedrooms="", unit_number="P1"),
            # A 2026 plot row the loader misreads: its "area" is the plot number.
            sale("misread", property_type="", bedrooms="", area_name="No. 630", unit_number="630"),
            # 1,000 sq ft and AED 1,000,000 are each the top of one band only.
            sale("edge", size_sqft=1000.0, sale_amount_aed=1_000_000, unit_number="E1"),
            sale("no-size", size_sqft=0.0, unit_number="N1"),
            sale("arabia-1", area_name="City Of Arabia", unit_number="A1"),
            sale("arabia-2", area_name="City Of Arabia", unit_number="A2"),
            sale("arabia-3", area_name="City of Arabia", unit_number="A3"),
            sale("jvc", area_name="Jumeirah Village Circle", unit_number="J1"),
            sale("jvc-dubai", area_name="Jumeirah Village Circle Dubai", unit_number="J2"),
            sale("two-bed", bedrooms="2 Bed", unit_number="T1"),
        ]
    )

    async def ids(**filters):
        page = await service.fetch_sales_transactions(
            SalesFilters(timeframe_days=7, **filters), 100, 0
        )
        assert page.total == len(page.transactions)
        return sorted(row.transaction_id for row in page.transactions)

    residential = await ids(property_usage="Residential")
    assert "office" not in residential and "plot" not in residential
    assert await ids(property_usage="Commercial") == ["office"]
    # "All" is every DXBI record: plots and untyped rows included.
    assert {"plot", "misread"} <= set(await ids())

    assert "edge" in await ids(size_min=1000, size_max=2000)
    assert "edge" not in await ids(size_min=500, size_max=1000)
    assert "edge" in await ids(price_per_sqft_min=1000, price_per_sqft_max=2000)
    assert "edge" in await ids(price_min=1_000_000, price_max=2_000_000)
    assert "edge" not in await ids(price_min=500_000, price_max=1_000_000)
    # A sale with no size is in no size band, not in the smallest one.
    assert "no-size" not in await ids(size_max=500)

    assert await ids(location="City Of Arabia") == ["arabia-1", "arabia-2", "arabia-3"]
    assert await ids(location="Jumeirah Village Circle") == ["jvc", "jvc-dubai"]
    assert await ids(bedrooms="2 Beds") == ["two-bed"]

    options = await facets.get_sales_filter_options(SalesFilters(timeframe_days=7))
    assert "City of Arabia" not in options.locations
    assert "Jumeirah Village Circle Dubai" not in options.locations
    assert "No. 630" not in options.locations
    assert options.bedrooms == ["1 Bed", "2 Beds", "4 Beds"]
    assert options.statuses == ["Ready"]
    assert options.property_types == ["Apartment", "Office", "Plot", "Villa"]
    narrowed = await facets.get_sales_filter_options(
        SalesFilters(timeframe_days=7, property_usage="Commercial")
    )
    assert (narrowed.property_types, narrowed.buildings) == (["Office"], ["Tower A"])

    misread = await service.fetch_sales_transactions(
        SalesFilters(timeframe_days=7, building="Tower A"), 100, 0
    )
    row = next(r for r in misread.transactions if r.transaction_id == "misread")
    assert (row.location_name, row.property_type, row.unit_number) == (None, None, "630")


async def test_numbered_units_hold_one_copy_of_a_lease_and_unnumbered_rows_all_count(dxbi):
    await dxbi(
        leases=[
            lease("lease-1"),
            # The report repeated the row while paging: same unit, dates, amount and state.
            lease("lease-1-repeat", occurrence_index=2),
            # Another unit on the same lease terms is another lease.
            lease("lease-2", unit_number="1102"),
            # Identical rows without a unit number cannot be told apart: all are kept.
            lease("hidden-1", unit_number=""),
            lease("hidden-2", unit_number="", occurrence_index=2),
            lease("starts-today", lease_start=TODAY, unit_number="9"),
            lease("starts-30-days-ago", lease_start=TODAY - timedelta(days=30), unit_number="8"),
            lease("starts-next-week", lease_start=TODAY + timedelta(days=7), unit_number="7"),
        ]
    )

    page = await service.fetch_rental_contracts(RentalFilters(timeframe_days=30), 30, 0)

    assert sorted(row.contract_id for row in page.contracts) == [
        "hidden-1",
        "hidden-2",
        "lease-1",
        "lease-2",
        "starts-today",
    ]
    first = next(row for row in page.contracts if row.contract_id == "lease-1")
    # AED 320,000 over 24 months is AED 160,000 a year; DXBI's size stays in sq ft.
    assert first.model_dump() == {
        "contract_id": "lease-1",
        "lease_start": TODAY - timedelta(days=2),
        "lease_end": TODAY - timedelta(days=2) + timedelta(days=730),
        "unit_number": "1101",
        "building_name": "Iris Blue",
        "project_name": None,
        "location_name": "Dubai Marina",
        "property_type": "Apartment",
        "bedrooms": "2 Beds",
        "size_sqft": 1326.0,
        "annual_rent_aed": 160_000,
        "contract_amount_aed": 320_000,
        "term_months": 24.0,
        "contract_type": "New",
    }

    in_band = await service.fetch_rental_contracts(
        RentalFilters(timeframe_days=30, rent_min=100_000, rent_max=160_000), 30, 0
    )
    assert in_band.total == 0  # AED 160,000 opens the next band: 160k is not below 160k.
    options = await facets.get_rental_filter_options(RentalFilters(timeframe_days=30))
    assert (options.contract_types, options.bedrooms) == (["New"], ["2 Beds"])


async def test_exports_hold_the_page_rows_and_neutralise_formulas(dxbi):
    await dxbi(
        sales=[
            sale("kept", unit_number="1"),
            sale("formula", building_name="=HYPERLINK()", building_key="formula", unit_number="2"),
            sale("other-place", area_name="Dubai Marina", unit_number="3"),
        ],
        leases=[lease("lease-1")],
    )

    filtered = await exports.export_sales_transactions(
        SalesFilters(timeframe_days=7, location="Downtown Dubai"), file_format="csv"
    )
    rows = list(csv.DictReader(io.StringIO(filtered.getvalue().decode("utf-8-sig"))))
    assert sorted(r["Transaction ID"] for r in rows) == ["formula", "kept"]
    kept = next(r for r in rows if r["Transaction ID"] == "kept")
    assert (kept["Unit"], kept["Size (sq ft)"], kept["Price/sq ft (AED)"]) == ("1", "800.0", "2000")
    formula = next(r for r in rows if r["Transaction ID"] == "formula")
    assert formula["Building"] == "'=HYPERLINK()"

    selected = await exports.export_sales_transactions(
        SalesFilters(location="Elsewhere"), transaction_ids="other-place", file_format="csv"
    )
    rows = list(csv.DictReader(io.StringIO(selected.getvalue().decode("utf-8-sig"))))
    assert [r["Transaction ID"] for r in rows] == ["other-place"]

    rentals = await exports.export_rental_contracts(
        RentalFilters(timeframe_days=7), file_format="csv"
    )
    rows = list(csv.DictReader(io.StringIO(rentals.getvalue().decode("utf-8-sig"))))
    assert [(r["Unit"], r["Annual Rent (AED)"], r["Contract Amount (AED)"]) for r in rows] == [
        ("1101", "160000", "320000")
    ]
