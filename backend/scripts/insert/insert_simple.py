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
    "date_time_input_format": "best_effort",
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


def atomic_exchange_load_simple(client, table_name: str, csv_filename: str):
    """Load data from CSV into table using atomic exchange with simple SELECT *."""
    staging = f"{table_name}_staging"
    print(f"Loading {table_name} from {csv_filename}...")

    # Create staging table
    client.execute(f"DROP TABLE IF EXISTS {staging}")
    client.execute(f"CREATE TABLE {staging} AS {table_name}")

    # Insert data from CSV - simple SELECT * since columns match
    query = f"""
    INSERT INTO {staging}
    SELECT * FROM file('{csv_filename}', 'CSVWithNames')
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


def atomic_exchange_load_projects(client):
    """Load projects with lookup join for project_name_en."""
    staging = "ch_projects_staging"
    print(f"Loading ch_projects from projects.csv with name augmentation...")

    # Create staging table
    client.execute(f"DROP TABLE IF EXISTS {staging}")
    client.execute(f"CREATE TABLE {staging} AS ch_projects")

    # Insert with lookup join to get cleaned project_name_en
    # CSV has 'project_name' which goes to 'project_name_ar'
    # We join with lookup to get 'project_name_en'
    query = f"""
    INSERT INTO {staging}
    SELECT
        p.project_id,
        p.project_number,
        p.project_name AS project_name_ar,
        COALESCE(lookup.cleaned_project_name_en, p.project_name) AS project_name_en,
        p.developer_id,
        p.developer_number,
        p.developer_name,
        p.master_developer_id,
        p.master_developer_number,
        p.master_developer_name,
        p.project_start_date,
        p.project_end_date,
        p.project_type_id,
        p.project_type_ar,
        p.project_classification_id,
        p.project_classification_ar,
        p.escrow_agent_id,
        p.escrow_agent_name,
        p.project_status,
        p.project_status_ar,
        p.percent_completed,
        p.completion_date,
        p.cancellation_date,
        p.project_description_ar,
        p.project_description_en,
        p.property_id,
        p.area_id,
        p.area_name_ar,
        p.area_name_en,
        p.master_project_ar,
        p.master_project_en,
        p.zoning_authority_id,
        p.zoning_authority_ar,
        p.zoning_authority_en,
        p.no_of_lands,
        p.no_of_buildings,
        p.no_of_villas,
        p.no_of_units
    FROM file('projects.csv', 'CSVWithNames') AS p
    LEFT JOIN ch_project_names_lookup AS lookup
        ON p.project_number = lookup.project_number
    """

    run_query(client, query, settings=SETTINGS)

    # Check row count
    cnt = client.execute(f"SELECT count() FROM {staging}")[0][0]
    if cnt == 0:
        print(f"Warning: {staging} is empty, skipping exchange")
        return

    print(f"Loaded {cnt:,} rows")

    # Atomic exchange
    client.execute(f"EXCHANGE TABLES ch_projects AND {staging}")
    client.execute(f"DROP TABLE {staging}")
    print(f"Done: ch_projects")


def build_project_lookup(client):
    """Build project name lookup table from units and buildings."""
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
        """
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
        """
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

    cnt = client.execute("SELECT count() FROM ch_project_names_lookup")[0][0]
    print(f"Lookup table has {cnt:,} entries")


def main():
    print("Connecting to ClickHouse...")
    client = get_client()

    # Build project name lookup table first
    build_project_lookup(client)

    # Load tables with simple SELECT *
    print("\n=== Loading tables with simple inserts ===")
    simple_tables = [
        ("ch_transactions", "transactions.csv"),
        ("ch_rent_contracts", "rent_contracts.csv"),
        ("ch_buildings", "buildings.csv"),
        ("ch_units", "units.csv"),
        ("ch_land_registry", "land_registry.csv"),
        ("ch_developers", "developers.csv"),
    ]

    for table_name, csv_file in simple_tables:
        atomic_exchange_load_simple(client, table_name, csv_file)

    # Load projects with special handling
    print("\n=== Loading projects with name augmentation ===")
    atomic_exchange_load_projects(client)

    print("\n=== All done! ===")


if __name__ == "__main__":
    main()
