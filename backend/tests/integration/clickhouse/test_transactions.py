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
    "dld_transaction_number",
    "transaction_date",
    "unit_number",
    "building_name",
    "building_key",
    "project_name",
    "area_name",
    "area_key",
    "property_type",
    "market_status",
    "bedrooms",
    "size_sqft",
    "sale_amount_aed",
    "price_per_sqft_aed",
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
        "dld_transaction_number": "",
        "transaction_date": TODAY - timedelta(days=1),
        "unit_number": "101",
        "building_name": "Tower A",
        "building_key": "towera",
        "project_name": "",
        "area_name": "Downtown Dubai",
        "area_key": "",
        "property_type": "Apartment",
        "market_status": "Ready",
        "bedrooms": "1 Bed",
        "size_sqft": 800.0,
        "sale_amount_aed": 1_600_000,
        "price_per_sqft_aed": None,
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


_LISTED_FILLS = {
    "dxbi_sales_listed": """
        INSERT INTO dxbi_sales_listed
        SELECT x.sale_key, x.transaction_date, x.unit_number, x.building_name, x.project_name,
               x.area_name, x.property_type, x.bedrooms, x.market_status, x.size_sqft,
               x.sale_amount_aed, if(x.price_per_sqft_aed > 0, x.price_per_sqft_aed, NULL),
               p.area_name, p.master_project, p.project_name, p.project_source, p.bedrooms,
               p.completion_status, p.size_sqft, now64(3)
        FROM (SELECT * FROM dxbi_sales_unit_events FINAL ORDER BY sale_key, loaded_at DESC
              LIMIT 1 BY sale_key) AS x
        LEFT JOIN dxbi_sale_profile AS p ON p.sale_key = x.sale_key""",
    "dxbi_leases_listed": """
        INSERT INTO dxbi_leases_listed
        SELECT x.contract_key, x.lease_start, x.lease_end, x.unit_number, x.building_name,
               x.project_name, x.area_name,
               if(p.property_type_source = 'dld_pair', p.property_type, x.property_type),
               x.bedrooms, x.size_sqft,
               x.annual_rent_aed, x.contract_amount_aed, x.contract_term_months,
               x.contract_state, p.area_name, p.master_project, p.project_name,
               p.project_source, p.bedrooms, p.size_sqft, now64(3)
        FROM dxbi_rental_events AS x FINAL
        LEFT JOIN dxbi_rental_profile AS p ON p.contract_key = x.contract_key""",
}


@pytest.fixture
async def dxbi(warehouse, install_serving):
    await install_serving(
        tables=(
            "dxbi_sales_unit_events",
            "dxbi_rental_events",
            "dxbi_locations",
            "dxbi_places",
            "dxbi_location_members",
            "dxbi_location_lease_members",
            "dxbi_sale_profile",
            "dxbi_rental_profile",
            "dxbi_sales_listed",
            "dxbi_leases_listed",
            "dxbi_heatmap_buildings_bronze",
        ),
        views=(),
    )

    async def insert(*, sales=(), leases=(), sale_profiles=(), lease_profiles=()):
        if sales:
            await warehouse.insert(
                "dxbi_sales_unit_events", list(sales), column_names=list(SALE_COLUMNS)
            )
        if leases:
            await warehouse.insert(
                "dxbi_rental_events", list(leases), column_names=list(RENTAL_COLUMNS)
            )
        for table, rows in (
            ("dxbi_sale_profile", sale_profiles),
            ("dxbi_rental_profile", lease_profiles),
        ):
            # Each profile row names only the columns it sets; the rest take their defaults.
            for row in rows:
                await warehouse.insert(table, [list(row.values())], column_names=list(row))
        # Holocron's listed records (holocron.market.dxbi_profile), each sale and lease once
        # with its profile; the identity rules are Holocron's and tested there.
        for table, statement in _LISTED_FILLS.items():
            await warehouse.command(f"TRUNCATE TABLE {table}")
            await warehouse.command(statement)

    return insert


async def test_each_dxbi_sale_appears_once_with_its_unit_in_square_feet(dxbi):
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
            # DXBI lists a day's sales before their units (no unit, no sale page): shown as DXBI
            # lists it, and the morning re-scrape reads the unit.
            sale("provisional", unit_number="", detail_url="", building_key="towerd"),
            # Outside the last 30 days, today included: 30 days ago and in the future.
            sale("old", transaction_date=TODAY - timedelta(days=30)),
            sale("future", transaction_date=TODAY + timedelta(days=3)),
        ]
    )

    page = await service.fetch_sales_transactions(SalesFilters(timeframe_days=30), 30, 0)

    ids = sorted(row.transaction_id for row in page.transactions)
    assert ids == ["block-1", "block-2", "from-scrape", "moved", "plain", "provisional"]
    assert page.total == 6
    provisional = next(row for row in page.transactions if row.transaction_id == "provisional")
    assert provisional.unit_number is None
    plain = next(row for row in page.transactions if row.transaction_id == "plain")
    # DXBI's own size; AED 1,600,000 over 800 sq ft is AED 2,000 per sq ft (price / size).
    assert plain.model_dump() == {
        "transaction_id": "plain",
        "transaction_date": TODAY - timedelta(days=1),
        "unit_number": "1904",
        "building_name": "Tower A",
        "project_name": None,
        "master_project": None,
        "dld_area": None,
        "location": None,
        "map_url": None,
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
    assert second_page.total == 6
    assert not {r.transaction_id for r in second_page.transactions} & {
        r.transaction_id for r in first_two.transactions
    }


async def test_size_and_price_per_sqft_are_the_figures_dxbi_shows(dxbi):
    # The page mirrors DXBInteract: DXBI prices this villa per sq ft of built-up area (AED 3,710),
    # not per sq ft of the 20,224 sq ft it shows (AED 2,225), and lists a Ciel hotel room at
    # 86 sq ft. Both are shown as DXBI shows them; a sale without DXBI's figure gets price / size.
    await dxbi(
        sales=[
            sale(
                "villa",
                building_key="frondo",
                property_type="Villa",
                size_sqft=20_224.0,
                sale_amount_aed=45_000_000,
                price_per_sqft_aed=3_710.0,
            ),
            sale("hotel-room", building_key="ciel", size_sqft=86.0, sale_amount_aed=675_000),
            sale("no-size", building_key="plot", size_sqft=0.0),
        ]
    )

    page = await service.fetch_sales_transactions(SalesFilters(timeframe_days=30), 30, 0)

    shown = {
        row.transaction_id: (row.size_sqft, row.price_per_sqft_aed) for row in page.transactions
    }
    assert shown == {
        "villa": (20_224.0, 3_710),
        "hotel-room": (86.0, 7_849),  # 675,000 / 86
        "no-size": (None, None),
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


async def test_sales_facets_offer_alternatives_without_losing_other_constraints(dxbi):
    """An agent can replace any one selection without first clearing the whole search."""
    changes = [
        {},
        {"property_type": "Villa"},
        {"bedrooms": "2 Beds"},
        {"market_status": "Offplan"},
        {"area_name": "Dubai Marina"},
        {"building_name": "Tower B", "building_key": "towerb"},
        {"project_name": "Development B"},
        {"property_type": "Townhouse", "sale_amount_aed": 5_000_000},
        {"property_type": "Townhouse", "transaction_date": TODAY - timedelta(days=90)},
    ]
    await dxbi(
        sales=[
            sale(f"facet-{i}", **{"unit_number": str(i), "project_name": "Development A", **change})
            for i, change in enumerate(changes)
        ]
    )
    selected = SalesFilters(
        timeframe_days=30,
        property_usage="Residential",
        property_type="Apartment",
        bedrooms="1 Bed",
        status="Ready",
        location="Downtown Dubai",
        building="Tower A",
        project="Development A",
        price_max=2_000_000,
    )
    result = await service.fetch_sales_transactions(selected, 100, 0)
    assert result.total == 1
    assert [row.transaction_id for row in result.transactions] == ["facet-0"]
    options = await facets.get_sales_filter_options(selected)
    assert options.property_types == ["Apartment", "Villa"]
    assert options.bedrooms == ["1 Bed", "2 Beds"]
    assert options.statuses == ["Off-Plan", "Ready"]
    assert options.locations == ["Downtown Dubai", "Dubai Marina"]
    assert options.buildings == ["Tower A", "Tower B"]
    assert options.projects == ["Development A", "Development B"]

    # Even an obsolete selection must permit recovery; don't claim it is an available option.
    missing = selected.model_copy(update={"bedrooms": "99 Beds"})
    assert (await service.fetch_sales_transactions(missing, 100, 0)).total == 0
    assert (await facets.get_sales_filter_options(missing)).bedrooms == ["1 Bed", "2 Beds"]


async def test_rental_facets_allow_replacing_contract_and_bedroom_selections(dxbi):
    await dxbi(
        leases=[
            lease("base", unit_number="1", contract_state="New"),
            lease("renew", unit_number="2", contract_state="Renewed"),
            lease("beds", unit_number="3", bedrooms="3 Beds", contract_state="New"),
            lease("expensive", unit_number="4", bedrooms="4 Beds", annual_rent_aed=900_000),
        ]
    )
    selected = RentalFilters(
        timeframe_days=30,
        property_usage="Residential",
        location="Dubai Marina",
        property_type="Apartment",
        bedrooms="2 Beds",
        contract_type="New",
        rent_max=200_000,
    )
    result = await service.fetch_rental_contracts(selected, 100, 0)
    assert result.total == 1
    options = await facets.get_rental_filter_options(selected)
    assert options.contract_types == ["New", "Renewed"]
    assert options.bedrooms == ["2 Beds", "3 Beds"]


async def test_building_and_project_are_what_dxbi_location_list_says(dxbi, warehouse):
    """DXBI prints a record's location as one place's path; its first part is a building, a
    project or an area, and only DXBI's location list says which (2026-10-08: 46% of sales
    showed a project as their building, 90% had no project). A path the list does not hold keeps
    the parsed names."""
    place = ["building_key", "area_key", "path_key", "flag", "building_label", "project_label",
             "area_label"]  # fmt: skip
    await warehouse.insert(
        "dxbi_places",
        [
            ["mog197", "discoverygardens", "mog197mogulclusterdiscoverygardens", "B",
             "Mog 197", "Mogul Cluster", "Discovery Gardens"],
            ["damacriverlink", "dubaiinvestmentpark2", "damacriverlinkdubaiinvestmentparksecond",
             "P", "", "Damac Riverlink", "Dubai Investment Park 2"],
            ["horalanz", "", "horalanz", "A", "", "", "Hor Al Anz"],
        ],
        column_names=place,
    )  # fmt: skip
    riverlink = {"building_name": "Damac Riverlink", "building_key": "damacriverlink",
                 "area_name": "Dubai Investment Park 2", "area_key": "dubaiinvestmentpark2"}  # fmt: skip
    await dxbi(
        sales=[
            sale("in-building", building_name="Mog 197", building_key="mog197",
                 area_name="Discovery Gardens", area_key="discoverygardens"),
            sale("whole-project", **riverlink),
            # A single name DXBI lists as an area is the sale's area, not its building.
            sale("area-only", building_name="Hor Al Anz", building_key="horalanz", area_name=""),
            sale("unlisted", project_name="Parsed Project"),
        ],
        leases=[
            lease("lease-in-project", location_name="Damac Riverlink, Dubai Investment Park Second",
                  building_name="Damac Riverlink", area_name="Dubai Investment Park 2"),
        ],
    )  # fmt: skip

    page = await service.fetch_sales_transactions(SalesFilters(timeframe_days=7), 30, 0)
    labels = {
        row.transaction_id: (row.building_name, row.project_name, row.location_name)
        for row in page.transactions
    }
    assert labels == {
        "in-building": ("Mog 197", "Mogul Cluster", "Discovery Gardens"),
        "whole-project": (None, "Damac Riverlink", "Dubai Investment Park 2"),
        "area-only": (None, None, "Hor Al Anz"),
        "unlisted": ("Tower A", "Parsed Project", "Downtown Dubai"),
    }

    by_project = await service.fetch_sales_transactions(
        SalesFilters(timeframe_days=7, project="Damac Riverlink"), 30, 0
    )
    assert [row.transaction_id for row in by_project.transactions] == ["whole-project"]
    options = await facets.get_sales_filter_options(SalesFilters(timeframe_days=7))
    assert options.projects == ["Damac Riverlink", "Mogul Cluster", "Parsed Project"]
    assert options.buildings == ["Mog 197", "Tower A"]

    leases = await service.fetch_rental_contracts(
        RentalFilters(timeframe_days=7, project="Damac Riverlink"), 30, 0
    )
    assert [(r.contract_id, r.building_name) for r in leases.contracts] == [
        ("lease-in-project", None)
    ]


async def test_a_location_holds_what_dxbi_area_page_counts(dxbi, warehouse):
    """Location choices are DXBI's own areas and communities, holding what DXBI's area pages
    count (decision 2026-10-07: totals match the website). Those pages can count a sale under a
    different place than the area printed on it: JVC's page counts buildings printed only
    "Al Barsha South 4", and Dubai Marina's leaves out some sales printed "Dubai Marina". A JVC
    sale is on the page of JVC's DLD area too."""
    await warehouse.insert(
        "dxbi_locations",
        [
            [31498, "Al Barsha South Fourth", "albarshasouth4", ["Al Barsha South Fourth"]],
            [36510, "Jumeirah Village Circle", "jumeirahvillagecircle",
             ["Jumeirah Village Circle", "Al Barsha South Fourth"]],
            [31385, "Marsa Dubai", "marsadubai", ["Marsa Dubai"]],
            [31987, "Dubai Marina", "dubaimarina", ["Dubai Marina", "Marsa Dubai"]],
        ],
        column_names=["location_id", "name", "name_key", "lineage"],
    )  # fmt: skip
    swept = [
        # (location, sale, building key, area key) as the last sweep found them.
        (36510, "Jumeirah Village Circle", "royale-1", "binghattiroyale", "albarshasouth4"),
        (31498, "Al Barsha South Fourth", "royale-1", "binghattiroyale", "albarshasouth4"),
        (31385, "Marsa Dubai", "shores", "marinashores", "dubaimarina"),
    ]
    await warehouse.insert(
        "dxbi_location_members",
        [
            [location_id, name, key, TODAY, building, area, TODAY, TODAY]
            for location_id, name, key, building, area in swept
        ],
        column_names=["location_id", "location_name", "sale_key", "transaction_date",
                      "building_key", "area_key", "window_start", "window_end"],
    )  # fmt: skip
    royale = {"building_name": "Binghatti Royale", "building_key": "binghattiroyale",
              "area_name": "Al Barsha South 4", "area_key": "albarshasouth4"}  # fmt: skip
    await dxbi(
        sales=[
            sale("royale-1", unit_number="1203", **royale),
            # Not swept (a later sale): its building's swept sales place it.
            sale("royale-2", unit_number="1204", **royale),
            # Printed "Dubai Marina", but DXBI's Dubai Marina page does not count it.
            sale("shores", unit_number="5", building_name="Marina Shores",
                 building_key="marinashores", area_name="Dubai Marina", area_key="dubaimarina"),
            # A building the sweep never saw: its printed area and the areas above it.
            sale("iris", unit_number="6", building_name="Iris Blue", building_key="irisblue",
                 area_name="Dubai Marina", area_key="dubaimarina"),
            # A place DXBI's list does not name keeps its printed area.
            sale("arjan", unit_number="7", area_name="Arjan", area_key="arjan"),
        ],
        leases=[lease("royale-lease", building_name="Binghatti Royale",
                      area_name="Al Barsha South 4", location_name="Binghatti Royale")],
    )  # fmt: skip

    async def ids(**filters):
        page = await service.fetch_sales_transactions(
            SalesFilters(timeframe_days=7, **filters), 100, 0
        )
        assert page.total == len(page.transactions)
        return sorted(row.transaction_id for row in page.transactions)

    assert await ids(location="Jumeirah Village Circle") == ["royale-1", "royale-2"]
    assert await ids(location="Al Barsha South Fourth") == ["royale-1", "royale-2"]
    assert await ids(location="Dubai Marina") == ["iris"]
    assert await ids(location="Marsa Dubai") == ["iris", "shores"]
    assert await ids(location="Arjan") == ["arjan"]
    # The row still shows the area DXBI prints on it.
    rows = await service.fetch_sales_transactions(SalesFilters(location="Marsa Dubai"), 100, 0)
    assert {row.location_name for row in rows.transactions} == {"Dubai Marina"}

    options = await facets.get_sales_filter_options(SalesFilters(timeframe_days=7))
    assert options.locations == [
        "Al Barsha South Fourth", "Arjan", "Dubai Marina", "Jumeirah Village Circle",
        "Marsa Dubai",
    ]  # fmt: skip

    # A lease takes its building's locations from the sales sweep.
    leases = await service.fetch_rental_contracts(
        RentalFilters(timeframe_days=7, location="Jumeirah Village Circle"), 100, 0
    )
    assert [row.contract_id for row in leases.contracts] == ["royale-lease"]


async def test_a_swept_lease_takes_the_locations_dxbi_rental_pages_count_it_in(dxbi, warehouse):
    """DXBI's rental area pages group leases with their own search, as the sales pages do; a
    lease the lease sweep returned takes those locations over its building's and printed area's."""
    await warehouse.insert(
        "dxbi_locations",
        [
            [31385, "Marsa Dubai", "marsadubai", ["Marsa Dubai"]],
            [31987, "Dubai Marina", "dubaimarina", ["Dubai Marina", "Marsa Dubai"]],
        ],
        column_names=["location_id", "name", "name_key", "lineage"],
    )
    await warehouse.insert(
        "dxbi_location_lease_members",
        [[31385, "Marsa Dubai", "swept", TODAY, TODAY, TODAY]],
        column_names=["location_id", "location_name", "contract_key", "lease_start",
                      "window_start", "window_end"],
    )  # fmt: skip
    # Both print "Dubai Marina"; DXBI's Dubai Marina rental page does not count the swept one.
    await dxbi(leases=[lease("swept"), lease("printed", unit_number="1102")])

    async def ids(location: str) -> list[str]:
        page = await service.fetch_rental_contracts(
            RentalFilters(timeframe_days=7, location=location), 100, 0
        )
        return sorted(row.contract_id for row in page.contracts)

    assert await ids("Dubai Marina") == ["printed"]
    assert await ids("Marsa Dubai") == ["printed", "swept"]


async def test_numbered_units_hold_one_copy_of_a_lease_and_unnumbered_rows_all_count(dxbi):
    await dxbi(
        leases=[
            lease("lease-1"),
            # The report repeated the row while paging: same unit, dates, amount and state.
            lease("lease-1-repeat", occurrence_index=2),
            # DXBI's other report view lists the same lease without its unit: it is lease-1.
            lease("lease-1-unitless", unit_number="", filter_profile_id="default"),
            # Another unit on the same lease terms is another lease.
            lease("lease-2", unit_number="1102"),
            # Identical rows without a unit number that match no numbered lease cannot be told
            # apart: all are kept.
            lease("hidden-1", unit_number="", size_sqft=900.0),
            lease("hidden-2", unit_number="", size_sqft=900.0, occurrence_index=2),
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
        "master_project": None,
        "dld_area": None,
        "location": None,
        "map_url": None,
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


async def test_the_dld_profile_fills_what_dxbi_left_empty_and_never_overrides_it(dxbi):
    # The profile carries DLD's official area and master project and fills an empty project,
    # bedroom count or status; DXBI's own values stay. A copy of DXBI's raw path in the profile
    # (source 'dxbi') must not undo the location list's labelling.
    await dxbi(
        sales=[
            sale("blank", project_name="", bedrooms="", market_status="", unit_number="1"),
            sale("own", project_name="Burj Views", unit_number="2"),
            sale("raw", project_name="", unit_number="3"),
        ],
        leases=[lease("lease-1")],
        sale_profiles=[
            {
                "sale_key": "blank",
                "project_name": "Burj Royale",
                "project_source": "dld_pair",
                "master_project": "Burj Khalifa",
                "area_name": "Burj Khalifa",
                "bedrooms": "2 Bed",
                "completion_status": "Off-Plan",
            },
            {
                "sale_key": "own",
                "project_name": "Other",
                "project_source": "dld_pair",
                "master_project": "Burj Khalifa",
                "area_name": "Burj Khalifa",
                "bedrooms": "3 Bed",
                "completion_status": "Off-Plan",
            },
            {"sale_key": "raw", "project_name": "Tower A", "project_source": "dxbi"},
        ],
        lease_profiles=[
            {
                "contract_key": "lease-1",
                "building_name": "Sale Tower",
                "building_source": "dxbi_sale",
                "master_project": "Dubai Marina",
                "area_name": "Marsa Dubai",
            }
        ],
    )

    page = await service.fetch_sales_transactions(SalesFilters(timeframe_days=7), 10, 0)
    rows = {row.transaction_id: row for row in page.transactions}
    blank = rows["blank"]
    assert (blank.project_name, blank.bedrooms, blank.status) == (
        "Burj Royale",
        "2 Beds",
        "Off-Plan",
    )
    assert (blank.master_project, blank.dld_area) == ("Burj Khalifa", "Burj Khalifa")
    own = rows["own"]
    assert (own.project_name, own.bedrooms, own.status) == ("Burj Views", "1 Bed", "Ready")
    assert rows["raw"].project_name is None

    leases = await service.fetch_rental_contracts(RentalFilters(timeframe_days=7), 10, 0)
    lease_row = leases.contracts[0]
    assert (lease_row.master_project, lease_row.dld_area) == ("Dubai Marina", "Marsa Dubai")


async def test_same_named_towers_in_different_areas_keep_both_sales(dxbi):
    # Unit numbers and tower names are only unique within a location. Two source detail
    # URLs establish distinct sales even when their date, price and unit happen to match.
    await dxbi(
        sales=[
            sale(
                "area-a",
                building_name="Tower 1",
                building_key="tower1",
                area_name="Dubai Marina",
                area_key="dubaimarina",
            ),
            sale(
                "area-b",
                building_name="Tower 1",
                building_key="tower1",
                area_name="Business Bay",
                area_key="businessbay",
            ),
        ]
    )
    page = await service.fetch_sales_transactions(SalesFilters(timeframe_days=30), 30, 0)
    assert {row.transaction_id for row in page.transactions} == {"area-a", "area-b"}
    assert page.total == 2


async def test_missing_unit_in_other_building_is_not_a_duplicate_lease(dxbi):
    # Equal commercial terms do not identify a property: another tower's lease with an
    # unknown unit must remain visible, rather than being mistaken for a numbered unit.
    await dxbi(
        leases=[
            lease("tower-a", building_name="Tower A", location_name="Tower A, Dubai Marina"),
            lease(
                "tower-b",
                unit_number="",
                building_name="Tower B",
                location_name="Tower B, Dubai Marina",
            ),
        ]
    )
    page = await service.fetch_rental_contracts(RentalFilters(timeframe_days=30), 30, 0)
    assert {row.contract_id for row in page.contracts} == {"tower-a", "tower-b"}
    assert page.total == 2


async def test_unknown_building_does_not_prove_a_unitless_lease_is_a_copy(dxbi):
    await dxbi(
        leases=[
            lease("numbered", building_name="", location_name="Dubai Marina"),
            lease("unknown", unit_number="", building_name="", location_name="Dubai Marina"),
        ]
    )
    page = await service.fetch_rental_contracts(RentalFilters(timeframe_days=30), 30, 0)
    assert {row.contract_id for row in page.contracts} == {"numbered", "unknown"}


async def test_project_context_resolves_repeated_towers_without_guessing(dxbi, warehouse):
    from app.transaction.queries import _sales_source

    await warehouse.insert(
        "dxbi_places",
        [
            [
                1,
                "tower1",
                "jvc",
                "Tower 1, May Residence, JVC",
                "B",
                "Tower 1",
                "May Residence",
                "JVC",
                "catalogue-1",
            ],
            [
                2,
                "tower1",
                "jvc",
                "Tower 1, Elitz, JVC",
                "B",
                "Tower 1",
                "Elitz",
                "JVC",
                "catalogue-1",
            ],
        ],
        column_names=[
            "location_id",
            "building_key",
            "area_key",
            "path",
            "flag",
            "building_label",
            "project_label",
            "area_label",
            "source_run_id",
        ],
    )
    common = dict(building_name="Tower 1", building_key="tower1", area_name="JVC", area_key="jvc")
    await dxbi(
        sales=[
            sale("may", project_name="May Residence", **common),
            sale("elitz", project_name="Elitz", **common),
            sale("unknown", project_name="", **common),
        ]
    )
    page = await service.fetch_sales_transactions(SalesFilters(), 10, 0)
    assert page.total == 3  # Equal unit/date/price in different projects cannot prove duplication.
    rows = {r.transaction_id: r for r in page.transactions}
    assert rows["may"].project_name == "May Residence"
    assert rows["elitz"].project_name == "Elitz"
    assert rows["unknown"].project_name is None
    assert rows["unknown"].building_name == "Tower 1"  # Agreed fields remain usable.
    scoped = await service.fetch_sales_transactions(SalesFilters(project="Elitz"), 10, 0)
    assert [r.transaction_id for r in scoped.transactions] == ["elitz"]
    options = await facets.get_sales_filter_options(SalesFilters())
    assert options.projects == ["Elitz", "May Residence"]
    exported = await exports.export_sales_transactions(
        SalesFilters(project="Elitz"), file_format="csv"
    )
    records = list(csv.DictReader(io.StringIO(exported.getvalue().decode("utf-8-sig"))))
    assert [r["Transaction ID"] for r in records] == ["elitz"]
    evidence = await warehouse.query(
        f"SELECT location_resolution, location_candidate_count, location_evidence "
        f"FROM ({_sales_source('1=1')}) WHERE transaction_id='unknown'"
    )
    assert evidence.result_rows[0][:2] == ("ambiguous", 2)
    assert {e[1] for e in evidence.result_rows[0][2]} == {"catalogue-1"}
    # A second read is idempotent, and the source has not acquired our derived values.
    assert (await service.fetch_sales_transactions(SalesFilters(), 10, 0)) == page
    original = await warehouse.query(
        "SELECT project_name FROM dxbi_sales_unit_events WHERE sale_key='unknown'"
    )
    assert original.result_rows == [("",)]


async def test_conflicting_catalogue_context_never_selects_lowest_id(dxbi, warehouse):
    await warehouse.insert(
        "dxbi_places",
        [
            [i, "towera", "area", "Tower A, Source Project, Area", "B", "Tower A", project, "Area"]
            for i, project in [(1, "Wrong Project"), (2, "Other Project")]
        ],
        column_names=[
            "location_id",
            "building_key",
            "area_key",
            "path",
            "flag",
            "building_label",
            "project_label",
            "area_label",
        ],
    )
    await dxbi(
        sales=[sale("conflict", project_name="Source Project", area_name="Area", area_key="area")]
    )
    result = await service.fetch_sales_transactions(SalesFilters(), 10, 0)
    assert result.transactions[0].project_name == "Source Project"


async def test_distinct_provider_links_survive_identical_terms(dxbi):
    await dxbi(sales=[sale("first", area_key="downtown"), sale("second", area_key="downtown")])
    page = await service.fetch_sales_transactions(SalesFilters(), 10, 0)
    assert page.total == 2
    assert {row.transaction_id for row in page.transactions} == {"first", "second"}
    assert sum(row.price_aed for row in page.transactions) == 3_200_000


@pytest.mark.parametrize(
    "conflict",
    [
        {"size_sqft": 900},
        {"project_name": "Different project"},
        {"dld_transaction_number": "11-2-2026"},
    ],
)
async def test_csv_pair_with_conflicting_evidence_stays_unresolved(dxbi, conflict):
    await dxbi(
        sales=[
            sale("scraped", area_key="downtown", dld_transaction_number="11-1-2026"),
            sale("csv", area_key="downtown", detail_url="", **conflict),
        ]
    )
    assert (await service.fetch_sales_transactions(SalesFilters(), 10, 0)).total == 2


async def test_unidentified_equal_term_sales_are_not_forced_into_one(dxbi):
    await dxbi(
        sales=[
            sale("csv-a", area_key="downtown", detail_url=""),
            sale("csv-b", area_key="downtown", detail_url=""),
        ]
    )
    assert (await service.fetch_sales_transactions(SalesFilters(), 10, 0)).total == 2


async def test_area_only_address_uses_exact_existing_location_catalogue(dxbi, warehouse):
    await warehouse.insert(
        "dxbi_locations",
        [[42, "Um Suqaim First", "A", "catalogue-2"]],
        column_names=["location_id", "name", "flag", "source_run_id"],
    )
    await dxbi(
        sales=[
            sale(
                "plot",
                building_name="Um Suqaim First",
                building_key="umsuqaimfirst",
                area_name="",
                area_key="",
                property_type="Plot",
            ),
            sale(
                "elsewhere",
                building_name="Um Suqaim First",
                building_key="umsuqaimfirst",
                area_name="Another Area",
                area_key="anotherarea",
            ),
        ]
    )
    page = await service.fetch_sales_transactions(SalesFilters(), 10, 0)
    rows = {row.transaction_id: row for row in page.transactions}
    assert rows["plot"].location_name == "Um Suqaim First"
    assert rows["plot"].building_name is None
    assert rows["elsewhere"].location_name == "Another Area"
    assert rows["elsewhere"].building_name == "Um Suqaim First"
    matched = await service.fetch_sales_transactions(
        SalesFilters(location="Um Suqaim First"), 10, 0
    )
    assert [r.transaction_id for r in matched.transactions] == ["plot"]


async def test_location_keywords_match_across_fields_without_merging_numbers(dxbi, warehouse):
    """One location search must reconcile lists, counts, facets and filtered exports."""
    await warehouse.insert(
        "dxbi_sales_unit_events",
        [
            sale(
                "numbered-02",
                building_name="02 Residence",
                project_name="Ned Al Ghurair",
                area_name="Jumeirah Village Triangle",
                building_key="02residence",
            ),
            sale(
                "numbered-03",
                building_name="03 Residence",
                project_name="Ned Al Ghurair",
                area_name="Jumeirah Village Triangle",
                building_key="03residence",
            ),
        ],
        column_names=SALE_COLUMNS,
    )
    from app.transaction import queries

    filters = SalesFilters(location_search="02 RESIDENCE triangle")
    rows, total = await queries.fetch_sales_rows(filters, 10, 0)
    assert total == 1
    assert [r["transaction_id"] for r in rows] == ["numbered-02"]
    exported = await queries.export_sales_rows(filters, None, 100)
    assert [r["transaction_id"] for r in exported] == ["numbered-02"]
    assert set((await queries.fetch_sales_facets(filters))["building_options"]) == {
        "02 Residence",
        "03 Residence",
    }
    assert (await queries.fetch_sales_rows(SalesFilters(location_search="02%' OR 1=1"), 10, 0))[
        1
    ] == 0


async def test_rental_location_keywords_reconcile_export_and_count(dxbi):
    from app.transaction import queries

    await dxbi(
        leases=[
            lease(
                "location-rent",
                building_name="09 Life Residences",
                location_name="09 Life Residences, Wadi Al Safa 5",
                area_name="Wadi Al Safa 5",
            )
        ]
    )
    filters = RentalFilters(location_search="09 life safA")
    rows, total = await queries.fetch_rental_rows(filters, 10, 0)
    assert total == 1
    assert rows[0]["contract_id"] == "location-rent"
    assert len(await queries.export_rental_rows(filters, None, 100)) == total
    assert (await queries.fetch_rental_rows(RentalFilters(location_search="08 life"), 10, 0))[
        1
    ] == 0
