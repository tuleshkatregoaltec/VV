from datetime import date

from app.crm import owner_queries
from app.market.reference import unit_lookup_key, unit_lookup_key_sql


async def test_crm_unit_normalization_matches_python_in_clickhouse(warehouse):
    values = [
        "FLAT 00415",
        "415",
        "Unit No. 415",
        "Unit415",
        "Apartment 415",
        "A-0101",
        "A 101",
        "a101",
        "A–٠١٠١",
        "A\u00a0۱۰۱",
        "١٠١.٠",
        "101.0",
        "101",
        "０１０１",
        "2510 (Q 3)",
        "2510 (Q 4)",
        "2510",
        "DH2-XR1139B",
        "XR1139B",
        "DL-K138",
        "K138",
        "Flat Unit101",
        "Flatiron 001",
        "null",
        " N/A ",
        "-",
        "",
        "000",
        "A000",
    ]
    result = await warehouse.query(
        f"SELECT value, {unit_lookup_key_sql('value')} AS unit_key "
        "FROM (SELECT arrayJoin({values:Array(String)}) AS value)",
        parameters={"values": values},
    )
    assert result.result_rows == [(value, unit_lookup_key(value)) for value in values]


async def test_crm_unit_lookup_queries_keep_source_unit_and_scope(warehouse, install_serving):
    await install_serving(
        tables=("dxbi_sales_unit_events", "analytics_building_keys", "dxbi_places"), views=()
    )
    await warehouse.insert(
        "dxbi_sales_unit_events",
        [
            ["sale-one", date(2024, 1, 1), "FLAT ٠١٠١", "Apartment"],
            ["sale-two", date(2024, 1, 2), "TAG-AL2-٠٠٦", "Villa"],
        ],
        column_names=["sale_key", "transaction_date", "unit_number", "property_type"],
    )
    rows = await owner_queries.fetch_unit_sales({"unit_keys": ["101"]})
    assert [(row["unit_key"], row["unit_number"]) for row in rows] == [("101", "FLAT ٠١٠١")]
    short_rows = await owner_queries.fetch_unit_sales_by_short_key({"unit_keys": ["6"]})
    assert [
        (row["short_unit_key"], row["unit_number"], row["property_type"]) for row in short_rows
    ] == [("6", "TAG-AL2-٠٠٦", "Villa")]
    await warehouse.insert(
        "analytics_building_keys",
        [
            ["historicname", "businessbay", "", "building-one"],
            ["historicname", "dubaimarina", "", "building-two"],
        ],
        column_names=["name_key", "community_key", "project_key", "building_id"],
    )
    aliases = await owner_queries.fetch_canonical_building_keys(
        {"name_keys": ["historicname"], "community_keys": ["businessbay"]}
    )
    assert [row["building_id"] for row in aliases] == ["building-one"]


async def test_assessment_external_keys_do_not_mix_same_unit_across_buildings(
    warehouse, install_serving
):
    await install_serving(tables=("dxbi_sales_unit_events", "dxbi_places"), views=())
    await warehouse.insert(
        "dxbi_sales_unit_events",
        [
            ["wanted", date(2024, 1, 1), "FLAT ٠١٠١", "Example Tower"],
            ["other-building", date(2025, 1, 1), "101", "Unrelated Tower"],
            ["other-unit", date(2025, 1, 1), "102", "Example Tower"],
        ],
        column_names=["sale_key", "transaction_date", "unit_number", "building_name"],
    )
    rows = await owner_queries.fetch_assessment_sales({"properties": [("exampletower", "101")]})
    assert [row["sale_key"] for row in rows] == ["wanted"]


async def test_owner_retrieval_pairs_numeric_ids_with_named_scope_and_keeps_alias_history(
    warehouse, install_serving
):
    await install_serving(
        tables=("dxbi_sales_unit_events", "dxbi_rental_events", "dxbi_places"), views=()
    )
    await warehouse.insert(
        "dxbi_sales_unit_events",
        [
            [
                "wanted",
                date(2024, 1, 1),
                "1",
                "Tower 1",
                "Alpha",
                "Business Bay",
                "Apartment",
                1000000,
            ],
            [
                "other-project",
                date(2024, 1, 1),
                "1",
                "Tower 1",
                "Beta",
                "Business Bay",
                "Apartment",
                1000000,
            ],
            [
                "other-unit",
                date(2024, 1, 1),
                "2",
                "Tower 1",
                "Alpha",
                "Business Bay",
                "Apartment",
                1000000,
            ],
            [
                "old-prefix",
                date(2024, 1, 1),
                "R3 Sun-V-141",
                "Sun",
                "Arabian Ranches III",
                "Arabian Ranches III",
                "Villa",
                1000000,
            ],
            [
                "later-numeric",
                date(2025, 1, 1),
                "141",
                "Sun",
                "Arabian Ranches III",
                "Arabian Ranches III",
                "Villa",
                2000000,
            ],
        ],
        column_names=[
            "sale_key",
            "transaction_date",
            "unit_number",
            "building_name",
            "project_name",
            "area_name",
            "property_type",
            "sale_amount_aed",
        ],
    )
    scopes = [("alpha", "1")]
    amount_rows = await owner_queries.fetch_transaction_signatures(
        {"prices": ["1000000.50"], "scopes": scopes}
    )
    assert [row["sale_key"] for row in amount_rows] == ["wanted"]
    property_rows = await owner_queries.fetch_property_identity_candidates(
        {"identifiers": ["1"], "scopes": scopes}
    )
    assert [row["event_key"] for row in property_rows] == ["wanted"]
    history = await owner_queries.fetch_unit_sales({"unit_keys": ["1"], "scopes": scopes})
    assert [row["sale_key"] for row in history] == ["wanted"]
    assert not await owner_queries.fetch_property_identity_candidates(
        {"identifiers": ["1"], "scopes": []}
    )
    alias_history = await owner_queries.fetch_unit_sales(
        {"unit_keys": ["141", "r3sunv141"], "scopes": [("sun", "141")]}
    )
    assert {row["sale_key"] for row in alias_history} == {"old-prefix", "later-numeric"}


async def test_large_building_lookup_preserves_community_scope(warehouse, install_serving):
    await install_serving(tables=("analytics_building_keys",), views=())
    await warehouse.insert(
        "analytics_building_keys",
        [["wanted", "community", "", "right"], ["wanted", "elsewhere", "", "wrong"]],
        column_names=["name_key", "community_key", "project_key", "building_id"],
    )
    # This payload exceeded the old bound-array HTTP field limit on real imports.
    names = [f"synthetic-building-{index:06}" for index in range(20000)] + ["wanted"]
    rows = await owner_queries.fetch_canonical_building_keys(
        {"name_keys": names, "community_keys": ["community"]}
    )
    assert [row["building_id"] for row in rows] == ["right"]
    assert (
        await owner_queries.fetch_canonical_building_keys(
            {"name_keys": names, "community_keys": []}
        )
        == []
    )
