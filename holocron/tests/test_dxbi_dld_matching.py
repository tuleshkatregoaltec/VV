from __future__ import annotations

import re

from holocron.market import dxbi_profile, transforms
from holocron.platform.bronze import coerce_money
from holocron.platform.census import SCHEMA_SQL, parse_expected_schema
from tests.test_market_release import database, live, warehouse  # noqa: F401  (fixtures)
from holocron.sources.dld_open_data_orchestration import (
    DLD_OPEN_DATA_TRANSACTIONS_RESWEEP_DEFAULTS,
)


def test_dld_prices_round_to_the_dirham_dxbi_shows() -> None:
    # DLD sends fils (723,726.89) and DXBI shows 723,727. Truncating stored 723,726, and 21,285
    # DXBI sales then had no DLD sale at their price.
    assert coerce_money(723726.89) == 723727
    assert coerce_money("2574186.1") == 2574186
    assert coerce_money("1,199,999.50") == 1200000
    assert coerce_money(None) == 0
    assert coerce_money("n/a") == 0


def _sale_steps() -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], str]:
    """The candidate build, the pairing rounds, the late rounds and the unpaired ledger."""
    statements = transforms.SALE_MATCH_STATEMENTS
    setup = len(transforms._SALE_CANDIDATES_SQL)
    rounds = statements[setup : setup + transforms.SALE_MATCH_ROUNDS]
    late = statements[setup + transforms.SALE_MATCH_ROUNDS :][: transforms.SALE_LATE_ROUNDS]
    return statements[:setup], rounds, late, statements[-2]


def test_sale_pairing_runs_in_rounds_and_ends_with_the_ledger() -> None:
    # One round paired a launch day's identical sales one at a time: a DXBI sale whose first
    # choice went to another sale never tried its next one. Every round must skip pairs already
    # made on both sides, and only the last insert writes the unpaired ledger.
    _, rounds, _, ledger = _sale_steps()
    assert len(rounds) >= 2
    for sql in rounds:
        assert "sale_key NOT IN (SELECT dxbi_sale_key FROM `market_sale_matches`)" in sql
        assert "dld_key NOT IN (" in sql
        assert "LIMIT 1 BY sale_key" in sql and "LIMIT 1 BY dld_key" in sql
    assert "toInt16(-1)" in ledger
    statements = transforms.SALE_MATCH_STATEMENTS
    assert all("toInt16(-1)" not in sql for sql in statements if sql is not ledger)
    assert statements[-1] == f"DROP TABLE IF EXISTS {transforms.SALE_CANDIDATES_TABLE}"


def test_sale_candidates_are_computed_once_per_release() -> None:
    # Every round once recomputed the 61-day x 3-price join over a million DXBI sales.
    setup, rounds, _, ledger = _sale_steps()
    assert sum("same_price AS (" in sql for sql in transforms.SALE_MATCH_STATEMENTS) == 2
    assert "same_price AS (" in setup[-1]
    for sql in (*rounds, ledger):
        assert f"FROM {transforms.SALE_CANDIDATES_TABLE}" in sql
    assert all("same_price AS (" not in sql for sql in rounds)
    # The work table's name is not a staged table's, so the release does not rename it.
    from holocron.market.release import render

    staged = {"market_sale_matches": "market_sale_matches__staging_x"}
    assert transforms.SALE_CANDIDATES_TABLE in render(rounds[0], staged)


def test_sale_candidates_allow_one_dirham_and_prefer_the_exact_price() -> None:
    # Bronze rows loaded before rounding hold truncated prices; an exact price must still win.
    assert "ARRAY JOIN [0, -1, 1] AS price_offset" in transforms._SALE_MATCH_INPUTS
    round_sql = transforms._sale_pairing_round_sql()
    assert "ORDER BY sale_key, price_gap, project_gap, day_gap" in round_sql


def test_late_registration_rounds_need_the_same_price_and_size() -> None:
    # Older DXBI dates run weeks ahead of DLD's; across that gap only the exact price and the
    # exact floor area (to the square foot) identify the sale.
    sql = transforms._sale_late_round_sql()
    assert "s.price = x.price AND s.size_key = x.size_key" in sql
    assert "<= 365" in sql
    _, _, late, _ = _sale_steps()
    assert len(late) == transforms.SALE_LATE_ROUNDS
    assert all("size_key" in statement for statement in late)


def test_rental_area_evidence_is_computed_once_per_release() -> None:
    statements = transforms._RENTAL_MATCH_STATEMENTS
    evidence = [sql for sql in statements if "community_evidence AS (" in sql]
    assert len(evidence) == 1 and transforms.RENTAL_AREA_SETS_TABLE in evidence[0]
    readers = [sql for sql in statements if "area_sets AS (" in sql and sql not in evidence]
    assert len(readers) == 1 + transforms.RENTAL_AREA_SET_ROUNDS * len(
        transforms._RENTAL_AREA_SET_TIERS
    )
    assert all(transforms._RENTAL_AREA_SETS in sql for sql in readers)
    assert statements[-2] == f"DROP TABLE IF EXISTS {transforms.RENTAL_AREA_SETS_TABLE}"


def test_a_place_name_in_the_building_slot_adds_no_market_project() -> None:
    # DXBI lists villas and plots under a community's name ("Mirdif", "JVC"); filling that into
    # the market tables made Analytics list a project no source names. A standalone tower
    # ("HDS Tower") is its own project, as DLD registers them.
    assert "'place_name'" in dxbi_profile.SALE_PROFILE_SQL
    # A lease copies its project from its unit's DXBI sale: a place's name stays no project.
    assert "s.project_source IN ('dxbi', 'dxbi_sale')" in dxbi_profile.RENTAL_PROFILE_SQL
    assert "place_name" not in transforms._PROFILE_PROJECT_SOURCES
    assert "'own_building'" in transforms._PROFILE_PROJECT_SOURCES
    for fill in (transforms._SALE_PROFILE_FILL, transforms._RENTAL_PROFILE_FILL):
        assert f"if(project_source IN {transforms._PROFILE_PROJECT_SOURCES}, project_name, '')" in (
            fill
        )
    assert "(JVC)" not in dxbi_profile._place_key("x")  # the bracket is removed in SQL


def test_dld_lease_rows_of_one_multi_unit_contract_stay_separate() -> None:
    # Open data has no contract number; a multi-unit contract is one identical-looking row per
    # unit. A content-only identity collapsed 106k rows into fewer leases than DXBI lists.
    assert "run_id, page_index, row_index) AS dld_rent_key" in transforms.DLD_RENTS_BASE


def test_leases_pair_across_area_names_only_with_evidence() -> None:
    # Without evidence, a lease whose dates, rent and size recur elsewhere paired across the
    # city ("Al Thanyah 1" to "Mankhool"). An unmatched LEFT JOIN yields 0, which read as a
    # perfect name match, so "no community" must count as distance 1.
    evidence = transforms._RENTAL_AREA_EVIDENCE
    assert "if(ce.dld_area = '', 1, ce.distance) AS comm_d" in evidence
    assert "WHERE name_d <= 0.3 OR comm_d <= 0.4 OR sales_share >= 0.05" in evidence
    anchor = transforms._rental_anchor_pairing_sql(tier=4)
    assert (
        "b.loc = a.loc OR (a.dxbi_area, b.loc) IN (SELECT dxbi_area, dld_area FROM area_sets)"
        in (anchor)
    )
    # The ledger of unpaired leases stays last.
    assert "SELECT dx.contract_key, 0, 255" in transforms._RENTAL_MATCH_STATEMENTS[-1]


def test_numbered_areas_never_map_to_another_number() -> None:
    # "Trade Center 2" is not "Trade Center First": spellings may differ, ordinals may not.
    evidence = transforms._RENTAL_AREA_EVIDENCE
    assert transforms._ordinal("a.dxbi_area") in evidence
    assert "(first|second|third|fourth|fifth|sixth)" in transforms._ordinal("x")


def test_profile_tables_match_their_column_lists() -> None:
    schema = parse_expected_schema(SCHEMA_SQL.read_text(encoding="utf-8"))
    assert list(dxbi_profile.SALE_PROFILE_COLUMNS) == schema["dxbi_sale_profile"]
    assert list(dxbi_profile.RENTAL_PROFILE_COLUMNS) == schema["dxbi_rental_profile"]
    # The build selects the columns by name, so none can land in another's place.
    for sql, columns in (
        (dxbi_profile.SALE_PROFILE_SQL, dxbi_profile.SALE_PROFILE_COLUMNS),
        (dxbi_profile.RENTAL_PROFILE_SQL, dxbi_profile.RENTAL_PROFILE_COLUMNS),
    ):
        assert f"SELECT {', '.join(columns)}\nFROM (" in sql


def test_every_profile_value_names_its_source() -> None:
    # A reader must tell a DXBI value from a DLD fill; the bedrooms of an office are not missing.
    for columns in (dxbi_profile.SALE_PROFILE_COLUMNS, dxbi_profile.RENTAL_PROFILE_COLUMNS):
        for field in ("area", "master_project", "project", "building", "unit", "bedrooms"):
            assert f"{field}_source" in columns
    assert "'not_applicable'" in dxbi_profile.SALE_PROFILE_SQL
    assert "'not_applicable'" in dxbi_profile.RENTAL_PROFILE_SQL


def test_dld_room_text_reads_as_dxbi_bedrooms() -> None:
    expression = dxbi_profile._bedrooms_from_dld("r")
    assert "'Studio'" in expression
    assert re.search(r"b/r\|bed", expression)


def test_weekly_resweep_rereads_ninety_days_without_the_checkpoint() -> None:
    # Weekend registrations arrive after the daily 7-day overlap; the resweep must not resume
    # from the daily checkpoint, or it would read nothing older.
    assert int(DLD_OPEN_DATA_TRANSACTIONS_RESWEEP_DEFAULTS["lookback_days"]) >= 60
    assert DLD_OPEN_DATA_TRANSACTIONS_RESWEEP_DEFAULTS["checkpointed_incremental"] is False


def test_listed_tables_name_their_columns_as_the_schema_does() -> None:
    schema = parse_expected_schema(SCHEMA_SQL.read_text(encoding="utf-8"))
    assert list(dxbi_profile.SALES_LISTED_COLUMNS) == schema["dxbi_sales_listed"]
    assert list(dxbi_profile.LEASES_LISTED_COLUMNS) == schema["dxbi_leases_listed"]


@live
def test_listed_records_count_each_sale_and_lease_once(warehouse) -> None:  # noqa: F811
    # The Analytics pages read these tables; they must hold exactly the records the
    # Transactions pages list (backend/app/transaction/queries.py), or the two pages disagree.
    from datetime import UTC, date, datetime

    loaded = datetime(2026, 7, 1, tzinfo=UTC)
    sale = {
        "transaction_date": date(2026, 6, 1), "unit_number": "1203", "building_name": "Tower A",
        "building_key": "towera", "area_name": "Dubai Marina", "area_key": "dubaimarina",
        "size_sqft": 800.0, "sale_amount_aed": 1_000_000, "property_type": "Apartment",
        "bedrooms": "1 Bed", "market_status": "Ready", "loaded_at": loaded,
    }  # fmt: skip
    sales = [
        {**sale, "sale_key": "scraped", "detail_url": "https://dxbinteract.com/sold/t-1"},
        # A CSV-export copy of the same sale: same unit, date, price and facts, no link.
        {**sale, "sale_key": "csv-copy", "detail_url": ""},
        # Two DXBI links with the same terms are two sales (another unit's pair).
        {**sale, "sale_key": "link-a", "unit_number": "1204", "detail_url": "https://x/sold/t-a"},
        {**sale, "sale_key": "link-b", "unit_number": "1204", "detail_url": "https://x/sold/t-b"},
    ]
    columns = list(sales[0])
    warehouse.insert_rows(
        table="dxbi_sales_unit_events",
        rows=[[row.get(c, "") for c in columns] for row in sales],
        column_names=columns,
    )
    warehouse.insert_rows(
        table="dxbi_sale_profile",
        rows=[["scraped", "DUBAI MARINA", "MARSA DUBAI", "TOWER A", "dld_pair"]],
        column_names=["sale_key", "master_project", "area_name", "project_name", "project_source"],
    )
    lease = {
        "location_name": "Tower B, Business Bay", "building_name": "Tower B",
        "area_name": "Business Bay", "property_type": "Apartment", "bedrooms": "1 Bed",
        "size_sqft": 700.0, "contract_amount_aed": 90_000, "annual_rent_aed": 90_000,
        "lease_start": date(2026, 6, 1), "lease_end": date(2027, 5, 31), "contract_state": "New",
    }  # fmt: skip
    leases = [
        {**lease, "contract_key": "numbered", "unit_number": "501"},
        # The report repeated the same numbered row while paging.
        {**lease, "contract_key": "repeat", "unit_number": "501", "occurrence_index": 2},
        # The same lease in the view without units.
        {**lease, "contract_key": "unitless-copy", "unit_number": ""},
        # A lease without its unit and with other terms stays.
        {
            **lease,
            "contract_key": "unitless-other",
            "unit_number": "",
            "contract_amount_aed": 95_000,
        },
    ]
    columns = sorted({c for row in leases for c in row})
    warehouse.insert_rows(
        table="dxbi_rental_events",
        rows=[
            [row.get(c, 1 if c == "occurrence_index" else "") for c in columns] for row in leases
        ],
        column_names=columns,
    )
    dxbi_profile.create_tables(warehouse)
    for table in dxbi_profile.LISTED_TABLES:
        dxbi_profile.build_profile(warehouse, table)

    listed = warehouse.query(
        "SELECT sale_key, profile_master FROM dxbi_sales_listed ORDER BY sale_key"
    ).result_rows
    assert listed == [("link-a", ""), ("link-b", ""), ("scraped", "DUBAI MARINA")]
    leased = warehouse.query("SELECT contract_key FROM dxbi_leases_listed ORDER BY 1").result_rows
    assert [row[0] for row in leased] == ["numbered", "unitless-other"]


def test_a_commercial_lease_takes_its_dld_contracts_type_in_dxbis_words() -> None:
    # DXBI lists every office or shop lease as "Commercial"; its matched DLD contract says which,
    # so a tower's leases and sales line up as Office and Shop. A DLD "Flat" on a DXBI commercial
    # lease contradicts it and changes nothing.
    assert dxbi_profile.DLD_COMMERCIAL_TYPES["Office"] == ("office",)
    assert all("flat" not in names for names in dxbi_profile.DLD_COMMERCIAL_TYPES.values())
    sql = dxbi_profile.RENTAL_PROFILE_SQL
    assert "p.property_type = 'Commercial' AND p.ref_type != '', p.ref_type" in sql
    assert "'dld_pair'" in sql and "property_type_source" in dxbi_profile.RENTAL_PROFILE_COLUMNS
    # Every name maps to a type the Commercial view counts.
    from holocron.market.dxbi_profile import DLD_COMMERCIAL_TYPES

    commercial = {"Office", "Shop", "Show Rooms", "Warehouse", "Workshop", "Clinic", "Gymnasium",
                  "Hotel", "Sized Partition", "Building", "Commercial"}  # fmt: skip
    assert set(DLD_COMMERCIAL_TYPES) <= commercial


@live
def test_sister_buildings_let_at_one_rent_keep_their_own_leases(warehouse) -> None:  # noqa: F811
    # Damac Lagoons Nice 1 and Nice 2 let identical villas at one rent on one day. Paired by
    # floor-area order alone, Nice 2's smaller lease took Nice 1's DLD contract and the other way
    # round (34,568 leases sat in another project than their building's). A lease whose building's
    # paired records agree on a project (>= 80% of >= 10) pairs first inside that project.
    from datetime import UTC, date, datetime

    area, loaded = "Al Hebiah Fifth", datetime(2026, 7, 1, tzinfo=UTC)
    sales, profiles = [], []
    for building, project in (
        ("Nice 1", "DAMAC LAGOONS - NICE 1"),
        ("Nice 2", "DAMAC LAGOONS - NICE 2"),
    ):
        for i in range(10):
            key = f"{building}-{i}"
            sales.append([key, date(2025, 3, 1), f"V{i}", building, building.lower(), area,
                          area.lower(), 2000.0, 2_000_000, loaded])  # fmt: skip
            profiles.append([key, project, "dld_pair"])
    warehouse.insert_rows(
        table="dxbi_sales_unit_events",
        rows=sales,
        column_names=[
            "sale_key", "transaction_date", "unit_number", "building_name", "building_key",
            "area_name", "area_key", "size_sqft", "sale_amount_aed", "loaded_at",
        ],
    )  # fmt: skip
    warehouse.insert_rows(
        table="dxbi_sale_profile",
        rows=profiles,
        column_names=["sale_key", "project_name", "project_source"],
    )
    start, end = date(2025, 6, 1), date(2026, 5, 31)
    leases = [
        [key, key, key, building, area, sqft, 150_000, 150_000, start, end, "a", "r", "p", "l",
         b"0" * 20, b"0" * 64, start, loaded]
        for key, building, sqft in (
            ("lease-nice1", "Nice 1", 1400.0), ("lease-nice2", "Nice 2", 1390.0),
            # A 787 sqft lease at the same rent and dates as a 312 sqft office elsewhere.
            ("lease-oberoi", "Oberoi Centre", 787.0),
        )
    ]  # fmt: skip
    warehouse.insert_rows(
        table="dxbi_rental_events",
        rows=leases,
        column_names=[
            "contract_key", "unit_candidate_key", "unit_cohort_key", "building_name", "area_name",
            "size_sqft", "contract_amount_aed", "annual_rent_aed", "lease_start", "lease_end",
            "source_account", "source_run_id", "filter_profile_id", "source_location_id",
            "configuration_hash", "raw_row_fingerprint", "source_shard_date", "scraped_at",
        ],
    )  # fmt: skip
    rents = [
        [f"r{i}", "run", i, datetime(2025, 5, 20), datetime(2025, 6, 1), datetime(2026, 5, 31),
         150_000, 150_000, sqm, area, project]
        for i, (sqm, project) in enumerate(
            ((129.5, "DAMAC LAGOONS - NICE 1"), (130.0, "DAMAC LAGOONS - NICE 2"),
             (29.0, "TAMANI ARTS OFFICES"))
        )
    ]  # fmt: skip
    warehouse.insert_rows(
        table="dld_od_rents_bronze",
        rows=rents,
        column_names=[
            "row_key", "run_id", "row_index", "registration_date", "start_date", "end_date",
            "contract_amount", "annual_amount", "actual_area", "area_en", "project_en",
        ],
    )  # fmt: skip

    for statement in transforms._RENTAL_MATCH_STATEMENTS:
        warehouse.command(statement)

    pairs = dict(
        warehouse.query(
            "SELECT m.dxbi_contract_key, r.project_en FROM market_rental_matches AS m"
            f" INNER JOIN (SELECT dld_rent_key, project_en FROM ({transforms.DLD_RENTS_BASE})) AS r"
            " ON r.dld_rent_key = m.dld_rent_key"
        ).result_rows
    )
    # Floor areas within 5% of each other: by floor-area order alone Nice 2's 1,390 sqft lease
    # takes Nice 1's 1,394 sqft contract; the building's project keeps them apart. The 787 sqft
    # lease pairs with no 312 sqft office (it took Nice 2's 1,399 sqft contract before the size
    # rule, or the office).
    assert pairs == {
        "lease-nice1": "DAMAC LAGOONS - NICE 1",
        "lease-nice2": "DAMAC LAGOONS - NICE 2",
    }
