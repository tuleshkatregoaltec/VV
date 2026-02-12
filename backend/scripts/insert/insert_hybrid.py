import os
import time
from clickhouse_driver import Client


CH_HOST = os.environ.get("CLICKHOUSE_HOST", "localhost")
CH_PORT = int(os.environ.get("CLICKHOUSE_PORT", "9001"))
CH_USER = os.environ.get("CLICKHOUSE_USER", "vitevue")
CH_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "vitevue_dev")
CH_DB = os.environ.get("CLICKHOUSE_DB", "vitevue")

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


def atomic_exchange_load(client, table_name: str, csv_filename: str, select_query: str):
    """Load data from CSV into table using atomic exchange."""
    staging = f"{table_name}_staging"
    print(f"Loading {table_name} from {csv_filename}...")

    # Create staging table
    client.execute(f"DROP TABLE IF EXISTS {staging}")
    client.execute(f"CREATE TABLE {staging} AS {table_name}")

    # Insert data
    query = f"""
    INSERT INTO {staging}
    {select_query.replace("__CSV_FILE__", csv_filename)}
    """

    run_query(client, query, settings=SETTINGS)

    # Check row count
    cnt = client.execute(f"SELECT count() FROM {staging}")[0][0]
    if cnt == 0:
        print(f"Warning: {staging} is empty, skipping exchange")
        return

    print(f"Loaded {cnt:,} rows")

    # Atomic exchange
    client.execute(f"EXCHANGE TABLES {table_name} AND {staging}")
    client.execute(f"DROP TABLE {staging}")
    print(f"Done: {table_name}")


# Developers query with date parsing
Q_DEVELOPERS = """
SELECT
    participant_id, developer_id, developer_number, developer_name_ar, developer_name_en,
    toDate(parseDateTimeBestEffortOrNull(registration_date)) AS registration_date,
    license_source_id, license_source_ar, license_source_en, license_type_id, license_type_ar,
    license_type_en, license_number,
    toDate(parseDateTimeBestEffortOrNull(license_issue_date)) AS license_issue_date,
    toDate(parseDateTimeBestEffortOrNull(license_expiry_date)) AS license_expiry_date,
    chamber_of_commerce_no, legal_status, legal_status_ar, legal_status_en, webpage, phone, fax
FROM file('__CSV_FILE__', 'CSVWithNames')
"""

# Other tables need explicit column selection due to Date parsing
Q_TRANSACTIONS = """
SELECT
    transaction_id, procedure_id, trans_group_id, trans_group_ar, trans_group_en,
    procedure_name_ar, procedure_name_en,
    toDate(parseDateTimeBestEffortOrNull(instance_date)) AS instance_date,
    property_type_id, property_type_ar, property_type_en,
    property_sub_type_id, property_sub_type_ar, property_sub_type_en,
    property_usage_ar, property_usage_en, reg_type_id, reg_type_ar, reg_type_en,
    area_id, area_name_ar, area_name_en, building_name_ar, building_name_en,
    project_number, project_name_ar, project_name_en, master_project_en, master_project_ar,
    nearest_landmark_ar, nearest_landmark_en, nearest_metro_ar, nearest_metro_en,
    nearest_mall_ar, nearest_mall_en, rooms_ar, rooms_en, has_parking,
    procedure_area, actual_worth, meter_sale_price, rent_value, meter_rent_price,
    no_of_parties_role_1, no_of_parties_role_2, no_of_parties_role_3
FROM file('__CSV_FILE__', 'CSVWithNames')
"""

Q_RENT_CONTRACTS = """
SELECT
    contract_id, contract_reg_type_id, contract_reg_type_ar, contract_reg_type_en,
    toDate(parseDateTimeBestEffortOrNull(contract_start_date)) AS contract_start_date,
    toDate(parseDateTimeBestEffortOrNull(contract_end_date)) AS contract_end_date,
    contract_amount, annual_amount, no_of_prop, line_number, is_free_hold,
    ejari_bus_property_type_id, ejari_bus_property_type_ar, ejari_bus_property_type_en,
    ejari_property_type_id, ejari_property_type_en, ejari_property_type_ar,
    ejari_property_sub_type_id, ejari_property_sub_type_en, ejari_property_sub_type_ar,
    property_usage_en, property_usage_ar, project_number, project_name_ar, project_name_en,
    master_project_ar, master_project_en, area_id, area_name_ar, area_name_en,
    actual_area, nearest_landmark_ar, nearest_landmark_en, nearest_metro_ar, nearest_metro_en,
    nearest_mall_ar, nearest_mall_en, tenant_type_id, tenant_type_ar, tenant_type_en
FROM file('__CSV_FILE__', 'CSVWithNames')
"""

Q_BUILDINGS = """
SELECT
    property_id, area_id, zone_id, area_name_ar, area_name_en, land_number, land_sub_number,
    building_number, common_area, actual_common_area, floors, rooms, rooms_ar, rooms_en,
    car_parks, built_up_area, bld_levels, shops, flats, offices, swimming_pools, elevators,
    actual_area, property_type_id, property_type_ar, property_type_en,
    property_sub_type_id, property_sub_type_ar, property_sub_type_en, parent_property_id,
    toDate(parseDateTimeBestEffortOrNull(creation_date)) AS creation_date,
    parcel_id, is_free_hold, is_lease_hold, is_registered, pre_registration_number,
    master_project_id, master_project_en, master_project_ar, project_id, project_name_ar,
    project_name_en, land_type_id, land_type_ar, land_type_en
FROM file('__CSV_FILE__', 'CSVWithNames')
"""

Q_UNITS = """
SELECT
    property_id, area_id, zone_id, area_name_ar, area_name_en, land_number, land_sub_number,
    building_number, unit_number, unit_balcony_area, unit_parking_number, parking_allocation_type,
    parking_allocation_type_ar, parking_allocation_type_en, common_area, actual_common_area,
    floor, rooms, rooms_ar, rooms_en, actual_area, property_type_id, property_type_ar, property_type_en,
    property_sub_type_id, property_sub_type_ar, property_sub_type_en, parent_property_id,
    grandparent_property_id,
    toDate(parseDateTimeBestEffortOrNull(creation_date)) AS creation_date,
    munc_zip_code, munc_number, parcel_id, is_free_hold, is_lease_hold, is_registered,
    pre_registration_number, master_project_id, master_project_en, master_project_ar,
    project_id, project_name_ar, project_name_en, land_type_id, land_type_ar, land_type_en
FROM file('__CSV_FILE__', 'CSVWithNames')
"""

Q_LAND_REGISTRY = """
SELECT * FROM file('__CSV_FILE__', 'CSVWithNames')
"""

Q_PROJECTS = """
SELECT
    p.project_id, p.project_number,
    p.project_name AS project_name_ar,
    COALESCE(lookup.cleaned_project_name_en, p.project_name) AS project_name_en,
    p.developer_id, p.developer_number, p.developer_name, p.master_developer_id,
    p.master_developer_number, p.master_developer_name,
    toDate(parseDateTimeBestEffortOrNull(p.project_start_date)) AS project_start_date,
    toDate(parseDateTimeBestEffortOrNull(p.project_end_date)) AS project_end_date,
    p.project_type_id, p.project_type_ar, p.project_classification_id, p.project_classification_ar,
    p.escrow_agent_id, p.escrow_agent_name, p.project_status, p.project_status_ar, p.percent_completed,
    toDate(parseDateTimeBestEffortOrNull(p.completion_date)) AS completion_date,
    toDate(parseDateTimeBestEffortOrNull(p.cancellation_date)) AS cancellation_date,
    p.project_description_ar, p.project_description_en, p.property_id, p.area_id, p.area_name_ar, p.area_name_en,
    p.master_project_ar, p.master_project_en, p.zoning_authority_id, p.zoning_authority_ar, p.zoning_authority_en,
    p.no_of_lands, p.no_of_buildings, p.no_of_villas, p.no_of_units
FROM file('__CSV_FILE__', 'CSVWithNames') AS p
LEFT JOIN ch_project_names_lookup AS lookup ON p.project_id = lookup.project_id
"""


def build_project_lookup(client):
    """Build project name lookup table from units and buildings."""
    print("\n=== Building project lookup table ===")
    client.execute("DROP TABLE IF EXISTS ch_project_names_lookup")
    client.execute("""
        CREATE TABLE ch_project_names_lookup (
            project_id String,
            cleaned_project_name_en String
        ) ENGINE = Memory
    """)

    print("Populating lookup from units...")
    run_query(
        client,
        """
        INSERT INTO ch_project_names_lookup
        SELECT DISTINCT project_id, project_name_en AS cleaned_project_name_en
        FROM file('units.csv', 'CSVWithNames')
        WHERE length(project_id) > 0 AND length(project_name_en) > 0
        """,
        settings=SETTINGS,
    )

    print("Populating lookup from buildings...")
    run_query(
        client,
        """
        INSERT INTO ch_project_names_lookup
        SELECT DISTINCT project_id, project_name_en AS cleaned_project_name_en
        FROM file('buildings.csv', 'CSVWithNames')
        WHERE length(project_id) > 0 AND length(project_name_en) > 0
          AND project_id NOT IN (SELECT project_id FROM ch_project_names_lookup)
        """,
        settings=SETTINGS,
    )

    cnt = client.execute("SELECT count() FROM ch_project_names_lookup")[0][0]
    print(f"Lookup table has {cnt:,} entries")


def main():
    print("Connecting to ClickHouse...")
    client = get_client()

    # Build project name lookup table first
    build_project_lookup(client)

    # Load all tables
    print("\n=== Loading tables ===")
    atomic_exchange_load(client, "ch_transactions", "transactions.csv", Q_TRANSACTIONS)
    atomic_exchange_load(
        client, "ch_rent_contracts", "rent_contracts.csv", Q_RENT_CONTRACTS
    )
    atomic_exchange_load(client, "ch_buildings", "buildings.csv", Q_BUILDINGS)
    atomic_exchange_load(client, "ch_units", "units.csv", Q_UNITS)
    atomic_exchange_load(
        client, "ch_land_registry", "land_registry.csv", Q_LAND_REGISTRY
    )
    atomic_exchange_load(client, "ch_developers", "developers.csv", Q_DEVELOPERS)
    atomic_exchange_load(client, "ch_projects", "projects.csv", Q_PROJECTS)

    print("\n=== All done! ===")


if __name__ == "__main__":
    main()
