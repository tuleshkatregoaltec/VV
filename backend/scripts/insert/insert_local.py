import os
import time
from clickhouse_driver import Client


CH_HOST = os.environ.get("CLICKHOUSE_HOST", "localhost")
CH_PORT = int(os.environ.get("CLICKHOUSE_PORT", "9001"))
CH_USER = os.environ.get("CLICKHOUSE_USER", "vitevue")
CH_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "vitevue_dev")
CH_DB = os.environ.get("CLICKHOUSE_DB", "vitevue")

LOCAL_DATA_PATH = "/var/lib/clickhouse/user_files"

SETTINGS = {
    "input_format_null_as_default": 1,
    "input_format_csv_empty_as_default": 1,
    "format_csv_null_representation": "null",
    "max_insert_threads": 8,
    "max_partitions_per_insert_block": 0,
}


def get_client():
    """Create ClickHouse client."""
    return Client(
        host=CH_HOST, port=CH_PORT, user=CH_USER, password=CH_PASSWORD, database=CH_DB
    )


def run_query(client, query, settings=None):
    """Execute query and log duration."""
    start = time.time()
    client.execute(query, settings=settings or {})
    dur = time.time() - start
    print(f"Completed in {dur:.2f}s")


def atomic_exchange_load(
    client, table_name: str, local_filename: str, insert_select_query: str
):
    staging = f"{table_name}_staging"
    print(f"Loading {table_name} from {local_filename}...")

    client.execute(f"DROP TABLE IF EXISTS {staging}")
    client.execute(f"CREATE TABLE {staging} AS {table_name}")

    file_src = f"file('{local_filename}', 'CSVWithNames')"
    q = insert_select_query.replace("__FILE_SOURCE__", file_src)

    run_query(client, q, settings=SETTINGS)

    cnt = client.execute(f"SELECT count() FROM {staging}")[0][0]
    if cnt == 0:
        print(f"Warning: {staging} is empty, skipping exchange")
        return

    print(f"Loaded {cnt:,} rows")
    client.execute(f"EXCHANGE TABLES {table_name} AND {staging}")
    client.execute(f"DROP TABLE {staging}")
    print(f"Done: {table_name}")


# --------------------
# LOAD QUERIES
# --------------------
Q_TRANSACTIONS = """
INSERT INTO ch_transactions_staging
SELECT
    toString(transaction_id) AS transaction_id,
    toString(procedure_id) AS procedure_id,
    toInt32OrZero(trans_group_id) AS trans_group_id,
    toString(trans_group_ar) AS trans_group_ar,
    toString(trans_group_en) AS trans_group_en,
    toString(procedure_name_ar) AS procedure_name_ar,
    toString(procedure_name_en) AS procedure_name_en,
    toDate(parseDateTimeBestEffortOrNull(instance_date)) AS instance_date,
    toInt32OrZero(property_type_id) AS property_type_id,
    toString(property_type_ar) AS property_type_ar,
    toString(property_type_en) AS property_type_en,
    toInt32OrZero(property_sub_type_id) AS property_sub_type_id,
    toString(property_sub_type_ar) AS property_sub_type_ar,
    toString(property_sub_type_en) AS property_sub_type_en,
    toString(property_usage_ar) AS property_usage_ar,
    toString(property_usage_en) AS property_usage_en,
    toInt32OrZero(reg_type_id) AS reg_type_id,
    toString(reg_type_ar) AS reg_type_ar,
    toString(reg_type_en) AS reg_type_en,
    toInt32OrZero(area_id) AS area_id,
    toString(area_name_ar) AS area_name_ar,
    toString(area_name_en) AS area_name_en,
    toString(building_name_ar) AS building_name_ar,
    toString(building_name_en) AS building_name_en,
    toString(project_number) AS project_number,
    toString(project_name_ar) AS project_name_ar,
    toString(project_name_en) AS project_name_en,
    toInt32OrNull(master_project_id) AS master_project_id,
    toString(master_project_ar) AS master_project_ar,
    toString(master_project_en) AS master_project_en,
    toFloat64OrZero(amount) AS amount,
    toFloat64OrZero(actual_worth) AS actual_worth,
    toFloat64OrZero(trans_value) AS trans_value,
    toUInt32OrZero(meter_sale_price) AS meter_sale_price,
    toUInt32OrZero(meter_rent_price) AS meter_rent_price,
    toInt32OrZero(rooms_id) AS rooms_id,
    toString(rooms_ar) AS rooms_ar,
    toString(rooms_en) AS rooms_en,
    toFloat64OrZero(procedure_area) AS procedure_area,
    toFloat64OrZero(actual_area) AS actual_area,
    toString(parking) AS parking,
    toString(nearest_landmark_ar) AS nearest_landmark_ar,
    toString(nearest_landmark_en) AS nearest_landmark_en,
    toString(nearest_metro_ar) AS nearest_metro_ar,
    toString(nearest_metro_en) AS nearest_metro_en,
    toString(nearest_mall_ar) AS nearest_mall_ar,
    toString(nearest_mall_en) AS nearest_mall_en,
    toInt32OrZero(no_of_parties_role_1) AS no_of_parties_role_1,
    toInt32OrZero(no_of_parties_role_2) AS no_of_parties_role_2,
    toInt32OrNull(is_offplan_x) AS is_offplan_x,
    toString(is_offplan_text) AS is_offplan_text,
    toInt32OrNull(is_free_hold_x) AS is_free_hold_x,
    toString(is_free_hold_text) AS is_free_hold_text
FROM __FILE_SOURCE__
"""

Q_RENT_CONTRACTS = """
INSERT INTO ch_rent_contracts_staging
SELECT
    toString(contract_number) AS contract_number,
    toDate(parseDateTimeBestEffortOrNull(contract_start_date)) AS contract_start_date,
    toDate(parseDateTimeBestEffortOrNull(contract_end_date)) AS contract_end_date,
    toDate(parseDateTimeBestEffortOrNull(registration_date)) AS registration_date,
    toInt32OrZero(is_free_hold) AS is_free_hold,
    toInt32OrZero(version_number) AS version_number,
    toString(ejari_property_id) AS ejari_property_id,
    toString(ejari_property_sub_type_id) AS ejari_property_sub_type_id,
    toString(ejari_property_type_id) AS ejari_property_type_id,
    toFloat64OrZero(annual_amount) AS annual_amount,
    toInt32OrNull(area_id) AS area_id,
    toString(area_name_en) AS area_name_en,
    toString(area_name_ar) AS area_name_ar,
    toString(property_type_en) AS property_type_en,
    toString(property_type_ar) AS property_type_ar,
    toString(property_sub_type_en) AS property_sub_type_en,
    toString(property_sub_type_ar) AS property_sub_type_ar,
    toString(property_usage_en) AS property_usage_en,
    toString(property_usage_ar) AS property_usage_ar,
    toString(nearest_landmark_en) AS nearest_landmark_en,
    toString(nearest_landmark_ar) AS nearest_landmark_ar,
    toString(nearest_metro_en) AS nearest_metro_en,
    toString(nearest_metro_ar) AS nearest_metro_ar,
    toString(nearest_mall_en) AS nearest_mall_en,
    toString(nearest_mall_ar) AS nearest_mall_ar,
    toString(project_number) AS project_number,
    toString(project_name_en) AS project_name_en,
    toString(project_name_ar) AS project_name_ar,
    toInt32OrZero(rooms_en) AS rooms_en,
    toString(rooms_ar) AS rooms_ar,
    toFloat64OrZero(actual_area) AS actual_area,
    toFloat64OrZero(parking) AS parking,
    toString(contract_amount_currency) AS contract_amount_currency
FROM __FILE_SOURCE__
"""

Q_PROJECTS = """
INSERT INTO ch_projects_staging
SELECT
    toString(lookup.cleaned_project_name_en) AS project_name_en,
    toString(p.project_number) AS project_number,
    toString(p.project_name_en) AS original_project_name_en,
    toString(p.project_name_ar) AS project_name_ar,
    toString(p.project_status_ar) AS project_status_ar,
    toString(p.project_status_en) AS project_status_en,
    toString(p.developer_name_ar) AS developer_name_ar,
    toString(p.developer_name_en) AS developer_name_en,
    toString(p.consultant_name_ar) AS consultant_name_ar,
    toString(p.consultant_name_en) AS consultant_name_en,
    toString(p.contractor_name_ar) AS contractor_name_ar,
    toString(p.contractor_name_en) AS contractor_name_en,
    toString(p.project_type_ar) AS project_type_ar,
    toString(p.project_type_en) AS project_type_en,
    toInt32OrZero(p.project_area_id) AS project_area_id,
    toString(p.area_name_ar) AS area_name_ar,
    toString(p.area_name_en) AS area_name_en,
    toString(p.master_project_ar) AS master_project_ar,
    toString(p.master_project_en) AS master_project_en,
    toInt32OrZero(p.zoning_authority_id) AS zoning_authority_id,
    toString(p.zoning_authority_ar) AS zoning_authority_ar,
    toString(p.zoning_authority_en) AS zoning_authority_en,
    toUInt32OrZero(p.no_of_lands) AS no_of_lands,
    toUInt16OrZero(p.no_of_buildings) AS no_of_buildings,
    toUInt16OrZero(p.no_of_villas) AS no_of_villas,
    toUInt32OrZero(p.no_of_units) AS no_of_units
FROM __FILE_SOURCE__ AS p
LEFT JOIN ch_project_names_lookup AS lookup
    ON p.project_number = lookup.project_number
"""

Q_BUILDINGS = """
INSERT INTO ch_buildings_staging
SELECT
    toInt32OrZero(property_id) AS property_id,
    toInt32OrZero(area_id) AS area_id,
    toInt32OrZero(zone_id) AS zone_id,
    toString(area_name_ar) AS area_name_ar,
    toString(area_name_en) AS area_name_en,
    toString(land_number) AS land_number,
    toString(land_sub_number) AS land_sub_number,
    toString(building_number) AS building_number,
    toDecimal64OrZero(replaceRegexpAll(common_area, '[^0-9.]', ''), 2) AS common_area,
    toDecimal64OrZero(replaceRegexpAll(actual_common_area, '[^0-9.]', ''), 2) AS actual_common_area,
    toUInt16OrZero(floors) AS floors,
    toString(rooms) AS rooms,
    toString(rooms_ar) AS rooms_ar,
    toString(rooms_en) AS rooms_en,
    toUInt16OrZero(car_parks) AS car_parks,
    toDecimal64OrZero(replaceRegexpAll(built_up_area, '[^0-9.]', ''), 2) AS built_up_area,
    toUInt16OrZero(bld_levels) AS bld_levels,
    toUInt16OrZero(shops) AS shops,
    toUInt16OrZero(flats) AS flats,
    toUInt16OrZero(offices) AS offices,
    toUInt16OrZero(swimming_pools) AS swimming_pools,
    toUInt16OrZero(elevators) AS elevators,
    toDecimal64OrZero(replaceRegexpAll(actual_area, '[^0-9.]', ''), 2) AS actual_area,
    toInt32OrZero(property_type_id) AS property_type_id,
    toString(property_type_ar) AS property_type_ar,
    toString(property_type_en) AS property_type_en,
    toInt32OrZero(property_sub_type_id) AS property_sub_type_id,
    toString(property_sub_type_ar) AS property_sub_type_ar,
    toString(property_sub_type_en) AS property_sub_type_en,
    toInt32OrNull(parent_property_id) AS parent_property_id,
    toDate(parseDateTimeBestEffortOrNull(creation_date)) AS creation_date,
    toString(parcel_id) AS parcel_id,
    toString(building_name_ar) AS building_name_ar,
    toString(building_name_en) AS building_name_en,
    toString(project_number) AS project_number,
    toString(project_name_ar) AS project_name_ar,
    toString(project_name_en) AS project_name_en,
    toString(master_project_en) AS master_project_en
FROM __FILE_SOURCE__
"""

Q_UNITS = """
INSERT INTO ch_units_staging
SELECT
    toInt32OrZero(property_id) AS property_id,
    toInt32OrZero(area_id) AS area_id,
    toInt32OrZero(zone_id) AS zone_id,
    toString(area_name_ar) AS area_name_ar,
    toString(area_name_en) AS area_name_en,
    toString(land_number) AS land_number,
    toString(land_sub_number) AS land_sub_number,
    toString(building_number) AS building_number,
    toString(unit_number) AS unit_number,
    toString(rooms) AS rooms,
    toString(rooms_ar) AS rooms_ar,
    toString(rooms_en) AS rooms_en,
    toUInt16OrZero(bld_levels) AS bld_levels,
    toDecimal64OrZero(replaceRegexpAll(actual_area, '[^0-9.]', ''), 2) AS actual_area,
    toInt32OrZero(property_type_id) AS property_type_id,
    toString(property_type_ar) AS property_type_ar,
    toString(property_type_en) AS property_type_en,
    toInt32OrZero(property_sub_type_id) AS property_sub_type_id,
    toString(property_sub_type_ar) AS property_sub_type_ar,
    toString(property_sub_type_en) AS property_sub_type_en,
    toInt32OrNull(parent_property_id) AS parent_property_id,
    toString(parcel_id) AS parcel_id,
    toString(building_name_ar) AS building_name_ar,
    toString(building_name_en) AS building_name_en,
    toString(project_number) AS project_number,
    toString(project_name_ar) AS project_name_ar,
    toString(project_name_en) AS project_name_en,
    toString(master_project_en) AS master_project_en
FROM __FILE_SOURCE__
"""

Q_LAND_REGISTRY = """
INSERT INTO ch_land_registry_staging
SELECT
    toInt32OrZero(property_id) AS property_id,
    toInt32OrZero(area_id) AS area_id,
    toString(area_name_ar) AS area_name_ar,
    toString(area_name_en) AS area_name_en,
    toString(land_number) AS land_number,
    toString(land_sub_number) AS land_sub_number,
    toString(building_number) AS building_number,
    toString(unit_number) AS unit_number,
    toDecimal64OrZero(replaceRegexpAll(total_land_area, '[^0-9.]', ''), 2) AS total_land_area,
    toInt32OrZero(property_type_id) AS property_type_id,
    toString(property_type_ar) AS property_type_ar,
    toString(property_type_en) AS property_type_en,
    toInt32OrZero(property_sub_type_id) AS property_sub_type_id,
    toString(property_sub_type_ar) AS property_sub_type_ar,
    toString(property_sub_type_en) AS property_sub_type_en,
    toInt32OrNull(parent_property_id) AS parent_property_id,
    toDate(parseDateTimeBestEffortOrNull(creation_date)) AS creation_date,
    toString(project_number) AS project_number,
    toString(project_name_ar) AS project_name_ar,
    toString(project_name_en) AS project_name_en,
    toString(master_project_en) AS master_project_en
FROM __FILE_SOURCE__
"""

Q_DEVELOPERS = """
INSERT INTO ch_developers_staging
SELECT
    toString(developer_id) AS developer_id,
    toString(developer_name_ar) AS developer_name_ar,
    toString(developer_name_en) AS developer_name_en
FROM __FILE_SOURCE__
"""


def main():
    print("Connecting to ClickHouse...")
    client = get_client()

    # Build project name lookup table
    print("\n=== Building project lookup table ===")
    client.execute("DROP TABLE IF EXISTS ch_project_names_lookup")
    client.execute("""
        CREATE TABLE ch_project_names_lookup (
            project_number String,
            cleaned_project_name_en String
        ) ENGINE = Memory
    """)

    print("Populating lookup from units...")
    run_query(
        client,
        f"""
        INSERT INTO ch_project_names_lookup
        SELECT DISTINCT
            project_number,
            project_name_en AS cleaned_project_name_en
        FROM file('units.csv', 'CSVWithNames')
        WHERE project_number != '' AND project_name_en != ''
        """,
        settings=SETTINGS,
    )

    print("Populating lookup from buildings...")
    run_query(
        client,
        f"""
        INSERT INTO ch_project_names_lookup
        SELECT DISTINCT
            project_number,
            project_name_en AS cleaned_project_name_en
        FROM file('buildings.csv', 'CSVWithNames')
        WHERE project_number != '' AND project_name_en != ''
          AND project_number NOT IN (SELECT project_number FROM ch_project_names_lookup)
        """,
        settings=SETTINGS,
    )

    # Load main tables
    print("\n=== Loading main tables ===")
    atomic_exchange_load(client, "ch_transactions", "transactions.csv", Q_TRANSACTIONS)
    atomic_exchange_load(
        client, "ch_rent_contracts", "rent_contracts.csv", Q_RENT_CONTRACTS
    )
    atomic_exchange_load(client, "ch_projects", "projects.csv", Q_PROJECTS)
    atomic_exchange_load(client, "ch_buildings", "buildings.csv", Q_BUILDINGS)
    atomic_exchange_load(client, "ch_units", "units.csv", Q_UNITS)
    atomic_exchange_load(
        client, "ch_land_registry", "land_registry.csv", Q_LAND_REGISTRY
    )
    atomic_exchange_load(client, "ch_developers", "developers.csv", Q_DEVELOPERS)

    print("\n=== All done! ===")


if __name__ == "__main__":
    main()
