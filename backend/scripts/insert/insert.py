import os
import time
from clickhouse_driver import Client
from prepare_chunks import prepare_latest_csvs


CH_HOST = os.environ.get("CLICKHOUSE_HOST", "localhost")
CH_USER = os.environ.get("CLICKHOUSE_USER", "default")
CH_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "")
CH_DB = os.environ.get("CLICKHOUSE_DB", "default")

S3_BASE_URL = os.environ.get("S3_BASE_URL", "https://s3.amazonaws.com/your-bucket")
S3_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY_ID", "")
S3_SECRET_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")

SETTINGS = {
    "input_format_null_as_default": 1,
    "input_format_csv_empty_as_default": 1,
    "format_csv_null_representation": "null",
    "max_insert_threads": 8,
    "max_partitions_per_insert_block": 0,
}


def get_client():
    """Create ClickHouse client."""
    return Client(host=CH_HOST, user=CH_USER, password=CH_PASSWORD, database=CH_DB)


def run_query(client, query, settings=None):
    """Execute query and log duration."""
    start = time.time()
    client.execute(query, settings=settings or {})
    dur = time.time() - start
    print(f"Completed in {dur:.2f}s")


def atomic_exchange_load(
    client, table_name: str, s3_path: str, insert_select_query: str
):
    staging = f"{table_name}_staging"
    print(f"Loading {table_name}...")

    client.execute(f"DROP TABLE IF EXISTS {staging}")
    client.execute(f"CREATE TABLE {staging} AS {table_name}")

    url = (
        s3_path
        if s3_path.startswith("http")
        else f"{S3_BASE_URL}/{s3_path.lstrip('/')}"
    )
    s3_src = f"s3('{url}', '{S3_ACCESS_KEY}', '{S3_SECRET_KEY}', 'CSVWithNames')"
    q = insert_select_query.replace("__S3_SOURCE__", s3_src)

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
# LOAD QUERIES (MATCH YOUR DDL)
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
    toString(master_project_en) AS master_project_en,
    toString(master_project_ar) AS master_project_ar,
    toString(nearest_landmark_ar) AS nearest_landmark_ar,
    toString(nearest_landmark_en) AS nearest_landmark_en,
    toString(nearest_metro_ar) AS nearest_metro_ar,
    toString(nearest_metro_en) AS nearest_metro_en,
    toString(nearest_mall_ar) AS nearest_mall_ar,
    toString(nearest_mall_en) AS nearest_mall_en,
    toString(rooms_ar) AS rooms_ar,
    toString(rooms_en) AS rooms_en,
    toUInt8OrZero(has_parking) AS has_parking,
    toDecimal64OrZero(replaceRegexpAll(procedure_area, '[^0-9.]', ''), 2) AS procedure_area,
    toDecimal64OrNull(replaceRegexpAll(actual_worth, '[^0-9.]', ''), 2) AS actual_worth,
    toDecimal64OrNull(replaceRegexpAll(meter_sale_price, '[^0-9.]', ''), 2) AS meter_sale_price,
    toDecimal64OrNull(replaceRegexpAll(rent_value, '[^0-9.]', ''), 2) AS rent_value,
    toDecimal64OrNull(replaceRegexpAll(meter_rent_price, '[^0-9.]', ''), 2) AS meter_rent_price,
    toUInt16OrZero(no_of_parties_role_1) AS no_of_parties_role_1,
    toUInt16OrZero(no_of_parties_role_2) AS no_of_parties_role_2,
    toUInt16OrZero(no_of_parties_role_3) AS no_of_parties_role_3
FROM __S3_SOURCE__
"""

Q_RENT = """
INSERT INTO ch_rent_contracts_staging
SELECT
    toString(contract_id) AS contract_id,
    toInt32OrZero(contract_reg_type_id) AS contract_reg_type_id,
    toString(contract_reg_type_ar) AS contract_reg_type_ar,
    toString(contract_reg_type_en) AS contract_reg_type_en,
    toDate(parseDateTimeBestEffortOrNull(contract_start_date)) AS contract_start_date,
    toDate(parseDateTimeBestEffortOrNull(contract_end_date)) AS contract_end_date,
    toDecimal64OrNull(replaceRegexpAll(contract_amount, '[^0-9.]', ''), 2) AS contract_amount,
    toDecimal64OrNull(replaceRegexpAll(annual_amount, '[^0-9.]', ''), 2) AS annual_amount,
    toUInt16OrZero(no_of_prop) AS no_of_prop,
    toUInt16OrZero(line_number) AS line_number,
    toUInt8OrZero(is_free_hold) AS is_free_hold,
    toInt32OrZero(ejari_bus_property_type_id) AS ejari_bus_property_type_id,
    toString(ejari_bus_property_type_ar) AS ejari_bus_property_type_ar,
    toString(ejari_bus_property_type_en) AS ejari_bus_property_type_en,
    toInt32OrZero(ejari_property_type_id) AS ejari_property_type_id,
    toString(ejari_property_type_en) AS ejari_property_type_en,
    toString(ejari_property_type_ar) AS ejari_property_type_ar,
    toInt32OrZero(ejari_property_sub_type_id) AS ejari_property_sub_type_id,
    toString(ejari_property_sub_type_en) AS ejari_property_sub_type_en,
    toString(ejari_property_sub_type_ar) AS ejari_property_sub_type_ar,
    toString(property_usage_en) AS property_usage_en,
    toString(property_usage_ar) AS property_usage_ar,
    toString(project_number) AS project_number,
    toString(project_name_ar) AS project_name_ar,
    toString(project_name_en) AS project_name_en,
    toString(master_project_ar) AS master_project_ar,
    toString(master_project_en) AS master_project_en,
    toInt32OrZero(area_id) AS area_id,
    toString(area_name_ar) AS area_name_ar,
    toString(area_name_en) AS area_name_en,
    toDecimal64OrZero(replaceRegexpAll(actual_area, '[^0-9.]', ''), 2) AS actual_area,
    toString(nearest_landmark_ar) AS nearest_landmark_ar,
    toString(nearest_landmark_en) AS nearest_landmark_en,
    toString(nearest_metro_ar) AS nearest_metro_ar,
    toString(nearest_metro_en) AS nearest_metro_en,
    toString(nearest_mall_ar) AS nearest_mall_ar,
    toString(nearest_mall_en) AS nearest_mall_en,
    toInt32OrZero(tenant_type_id) AS tenant_type_id,
    toString(tenant_type_ar) AS tenant_type_ar,
    toString(tenant_type_en) AS tenant_type_en
FROM __S3_SOURCE__
"""

Q_PROJECTS = """
INSERT INTO ch_projects_staging
SELECT
    toInt32OrZero(p.project_id) AS project_id,
    toString(p.project_number) AS project_number,
    toString(p.project_name) AS project_name_ar,
    COALESCE(lookup.project_name_en, '') AS project_name_en,
    toInt32OrZero(p.developer_id) AS developer_id,
    toString(p.developer_number) AS developer_number,
    toString(p.developer_name) AS developer_name,
    toInt32OrZero(p.master_developer_id) AS master_developer_id,
    toString(p.master_developer_number) AS master_developer_number,
    toString(p.master_developer_name) AS master_developer_name,
    toDate(parseDateTimeBestEffortOrNull(p.project_start_date)) AS project_start_date,
    toDate(parseDateTimeBestEffortOrNull(p.project_end_date)) AS project_end_date,
    toInt32OrZero(p.project_type_id) AS project_type_id,
    toString(p.project_type_ar) AS project_type_ar,
    toInt32OrZero(p.project_classification_id) AS project_classification_id,
    toString(p.project_classification_ar) AS project_classification_ar,
    toInt32OrZero(p.escrow_agent_id) AS escrow_agent_id,
    toString(p.escrow_agent_name) AS escrow_agent_name,
    toString(p.project_status) AS project_status,
    toString(p.project_status_ar) AS project_status_ar,
    toFloat32OrZero(p.percent_completed) AS percent_completed,
    toDate(parseDateTimeBestEffortOrNull(p.completion_date)) AS completion_date,
    toDate(parseDateTimeBestEffortOrNull(p.cancellation_date)) AS cancellation_date,
    toString(p.project_description_ar) AS project_description_ar,
    toString(p.project_description_en) AS project_description_en,
    toInt32OrNull(p.property_id) AS property_id,
    toInt32OrZero(p.area_id) AS area_id,
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
FROM __S3_SOURCE__ AS p
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
    toUInt8OrZero(is_free_hold) AS is_free_hold,
    toUInt8OrZero(is_lease_hold) AS is_lease_hold,
    toUInt8OrZero(is_registered) AS is_registered,
    toString(pre_registration_number) AS pre_registration_number,
    toInt32OrZero(master_project_id) AS master_project_id,
    toString(master_project_en) AS master_project_en,
    toString(master_project_ar) AS master_project_ar,
    toInt32OrZero(project_id) AS project_id,
    toString(project_name_ar) AS project_name_ar,
    toString(project_name_en) AS project_name_en,
    toInt32OrZero(land_type_id) AS land_type_id,
    toString(land_type_ar) AS land_type_ar,
    toString(land_type_en) AS land_type_en
FROM __S3_SOURCE__
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
    toDecimal64OrZero(replaceRegexpAll(unit_balcony_area, '[^0-9.]', ''), 2) AS unit_balcony_area,
    toString(unit_parking_number) AS unit_parking_number,
    toString(parking_allocation_type) AS parking_allocation_type,
    toString(parking_allocation_type_ar) AS parking_allocation_type_ar,
    toString(parking_allocation_type_en) AS parking_allocation_type_en,
    toDecimal64OrZero(replaceRegexpAll(common_area, '[^0-9.]', ''), 2) AS common_area,
    toDecimal64OrZero(replaceRegexpAll(actual_common_area, '[^0-9.]', ''), 2) AS actual_common_area,
    toString(floor) AS floor,
    toString(rooms) AS rooms,
    toString(rooms_ar) AS rooms_ar,
    toString(rooms_en) AS rooms_en,
    toDecimal64OrZero(replaceRegexpAll(actual_area, '[^0-9.]', ''), 2) AS actual_area,
    toInt32OrZero(property_type_id) AS property_type_id,
    toString(property_type_ar) AS property_type_ar,
    toString(property_type_en) AS property_type_en,
    toInt32OrZero(property_sub_type_id) AS property_sub_type_id,
    toString(property_sub_type_ar) AS property_sub_type_ar,
    toString(property_sub_type_en) AS property_sub_type_en,
    toInt32OrNull(parent_property_id) AS parent_property_id,
    toInt32OrNull(grandparent_property_id) AS grandparent_property_id,
    toDate(parseDateTimeBestEffortOrNull(creation_date)) AS creation_date,
    toString(munc_zip_code) AS munc_zip_code,
    toString(munc_number) AS munc_number,
    toString(parcel_id) AS parcel_id,
    toUInt8OrZero(is_free_hold) AS is_free_hold,
    toUInt8OrZero(is_lease_hold) AS is_lease_hold,
    toUInt8OrZero(is_registered) AS is_registered,
    toString(pre_registration_number) AS pre_registration_number,
    toInt32OrZero(master_project_id) AS master_project_id,
    toString(master_project_en) AS master_project_en,
    toString(master_project_ar) AS master_project_ar,
    toInt32OrZero(project_id) AS project_id,
    toString(project_name_ar) AS project_name_ar,
    toString(project_name_en) AS project_name_en,
    toInt32OrZero(land_type_id) AS land_type_id,
    toString(land_type_ar) AS land_type_ar,
    toString(land_type_en) AS land_type_en
FROM __S3_SOURCE__
"""

Q_LAND_REGISTRY = """
INSERT INTO ch_land_registry_staging
SELECT
    toInt32OrZero(property_id) AS property_id,
    toInt32OrZero(area_id) AS area_id,
    toInt32OrZero(zone_id) AS zone_id,
    toString(area_name_ar) AS area_name_ar,
    toString(area_name_en) AS area_name_en,
    toString(land_number) AS land_number,
    toString(land_sub_number) AS land_sub_number,
    toDecimal64OrZero(replaceRegexpAll(actual_area, '[^0-9.]', ''), 2) AS actual_area,
    toInt32OrZero(property_type_id) AS property_type_id,
    toString(property_type_ar) AS property_type_ar,
    toString(property_type_en) AS property_type_en,
    toInt32OrZero(property_sub_type_id) AS property_sub_type_id,
    toString(property_sub_type_ar) AS property_sub_type_ar,
    toString(property_sub_type_en) AS property_sub_type_en,
    toString(munc_zip_code) AS munc_zip_code,
    toString(munc_number) AS munc_number,
    toString(parcel_id) AS parcel_id,
    toUInt8OrZero(is_free_hold) AS is_free_hold,
    toUInt8OrZero(is_registered) AS is_registered,
    toString(pre_registration_number) AS pre_registration_number,
    toInt32OrZero(separated_from) AS separated_from,
    toString(separated_reference) AS separated_reference,
    toInt32OrZero(project_id) AS project_id,
    toString(project_name_ar) AS project_name_ar,
    toString(project_name_en) AS project_name_en,
    toInt32OrZero(master_project_id) AS master_project_id,
    toString(master_project_en) AS master_project_en,
    toString(master_project_ar) AS master_project_ar,
    toInt32OrZero(land_type_id) AS land_type_id,
    toString(land_type_ar) AS land_type_ar,
    toString(land_type_en) AS land_type_en
FROM __S3_SOURCE__
"""

Q_DEVELOPERS = """
INSERT INTO ch_developers_staging
SELECT
    toInt32OrZero(developer_id) AS developer_id,
    toString(participant_id) AS participant_id,
    toString(developer_number) AS developer_number,
    toString(developer_name_ar) AS developer_name_ar,
    toString(developer_name_en) AS developer_name_en,
    toDate(parseDateTimeBestEffortOrNull(registration_date)) AS registration_date,
    toInt32OrZero(license_source_id) AS license_source_id,
    toString(license_source_ar) AS license_source_ar,
    toString(license_source_en) AS license_source_en,
    toInt32OrZero(license_type_id) AS license_type_id,
    toString(license_type_ar) AS license_type_ar,
    toString(license_type_en) AS license_type_en,
    toString(license_number) AS license_number,
    toDate(parseDateTimeBestEffortOrNull(license_issue_date)) AS license_issue_date,
    toDate(parseDateTimeBestEffortOrNull(license_expiry_date)) AS license_expiry_date,
    toString(chamber_of_commerce_no) AS chamber_of_commerce_no,
    toString(legal_status) AS legal_status,
    toString(legal_status_ar) AS legal_status_ar,
    toString(legal_status_en) AS legal_status_en,
    toString(webpage) AS webpage,
    toString(phone) AS phone,
    toString(fax) AS fax
FROM __S3_SOURCE__
"""


def build_project_name_lookup(client, prepared):
    """
    Build temporary lookup table for project English names from Units and Buildings CSVs.

    Args:
        client: ClickHouse client
        prepared: Dict of prepared CSV S3 paths
    """
    print("Building project name lookup table...")

    # Drop if exists
    client.execute("DROP TABLE IF EXISTS ch_project_names_lookup")

    # Create temporary table
    client.execute("""
        CREATE TABLE ch_project_names_lookup (
            project_number String,
            project_name_en String
        ) ENGINE = Memory
    """)

    # Helper to build S3 URL
    def get_s3_url(s3_path):
        url = (
            s3_path
            if s3_path.startswith("http")
            else f"{S3_BASE_URL}/{s3_path.lstrip('/')}"
        )
        return f"s3('{url}', '{S3_ACCESS_KEY}', '{S3_SECRET_KEY}', 'CSVWithNames')"

    # Populate from Units.csv
    units_s3 = get_s3_url(prepared["Units.csv"])
    q_units = f"""
        INSERT INTO ch_project_names_lookup
        SELECT DISTINCT
            toString(project_number) AS project_number,
            toString(project_name_en) AS project_name_en
        FROM {units_s3}
        WHERE project_number != '' AND project_name_en != ''
    """

    print("Extracting project names from Units.csv...")
    run_query(client, q_units, settings=SETTINGS)

    # Populate from Buildings.csv (will add any missing ones)
    buildings_s3 = get_s3_url(prepared["Buildings.csv"])
    q_buildings = f"""
        INSERT INTO ch_project_names_lookup
        SELECT DISTINCT
            toString(project_number) AS project_number,
            toString(project_name_en) AS project_name_en
        FROM {buildings_s3}
        WHERE project_number != ''
          AND project_name_en != ''
          AND project_number NOT IN (
              SELECT project_number FROM ch_project_names_lookup
          )
    """

    print("Extracting project names from Buildings.csv...")
    run_query(client, q_buildings, settings=SETTINGS)

    # Log count
    count = client.execute("SELECT count() FROM ch_project_names_lookup")[0][0]
    print(f"Loaded {count:,} unique project name mappings")


def main():
    prepared = prepare_latest_csvs(
        bucket=os.environ["S3_BUCKET"],
        region=os.environ["S3_REGION"],
        access_key=os.environ["AWS_ACCESS_KEY_ID"],
        secret_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        s3_base_url=S3_BASE_URL,
    )

    client = get_client()

    # Build project name lookup table before loading projects
    build_project_name_lookup(client, prepared)

    atomic_exchange_load(
        client, "ch_transactions", prepared["Transactions.csv"], Q_TRANSACTIONS
    )
    atomic_exchange_load(
        client, "ch_rent_contracts", prepared["Rent_Contracts.csv"], Q_RENT
    )
    atomic_exchange_load(client, "ch_projects", prepared["Projects.csv"], Q_PROJECTS)
    atomic_exchange_load(client, "ch_buildings", prepared["Buildings.csv"], Q_BUILDINGS)
    atomic_exchange_load(client, "ch_units", prepared["Units.csv"], Q_UNITS)
    atomic_exchange_load(
        client, "ch_land_registry", prepared["Land_Registry.csv"], Q_LAND_REGISTRY
    )
    atomic_exchange_load(
        client, "ch_developers", prepared["Developers.csv"], Q_DEVELOPERS
    )

    # Clean up lookup table (Memory engine, but good practice)
    client.execute("DROP TABLE IF EXISTS ch_project_names_lookup")


if __name__ == "__main__":
    main()
