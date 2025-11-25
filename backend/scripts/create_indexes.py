"""
Create Performance Indexes for Dubai Real Estate Data Warehouse

Run this after initial data load to optimize query performance.
Indexes are designed for the dashboard use case: date-filtered,
sorted transaction lists with multiple filter options.
"""

import sys
from pathlib import Path
from datetime import datetime
from sqlalchemy import text

sys.path.append(str(Path(__file__).parent.parent))

from backend.database import engine

# Define all indexes
INDEXES = {
    "transactions": [
        # PRIMARY: Property Usage + Date (CRITICAL for instant commercial/residential switch!)
        {
            "name": "idx_transactions_usage_date_desc",
            "sql": """
                CREATE INDEX IF NOT EXISTS idx_transactions_usage_date_desc 
                ON transactions (property_usage, instance_date DESC, transaction_id)
            """,
            "description": "CRITICAL: Instant commercial/residential/rental switch + date sorting",
        },
        # COMPOSITE: Usage + Date + Property Type (common combination)
        {
            "name": "idx_transactions_usage_date_proptype",
            "sql": """
                CREATE INDEX IF NOT EXISTS idx_transactions_usage_date_proptype 
                ON transactions (property_usage, instance_date DESC, property_type_id, transaction_id)
            """,
            "description": "Residential/Commercial + Date + Property Type",
        },
        # COMPOSITE: Usage + Date + Area (common combination)
        {
            "name": "idx_transactions_usage_date_area",
            "sql": """
                CREATE INDEX IF NOT EXISTS idx_transactions_usage_date_area 
                ON transactions (property_usage, instance_date DESC, area_id, transaction_id)
            """,
            "description": "Residential/Commercial + Date + Area",
        },
        # LEGACY COMPOSITE: Date + Property Type (keep for backward compat)
        {
            "name": "idx_transactions_date_proptype",
            "sql": """
                CREATE INDEX IF NOT EXISTS idx_transactions_date_proptype 
                ON transactions (instance_date DESC, property_type_id, transaction_id)
            """,
            "description": "Date + property type filtering (without usage)",
        },
        # INDIVIDUAL FILTERS: For multi-filter queries
        {
            "name": "idx_transactions_property_usage",
            "sql": "CREATE INDEX IF NOT EXISTS idx_transactions_property_usage ON transactions (property_usage)",
            "description": "Property usage filter (commercial/residential/rental)",
        },
        {
            "name": "idx_transactions_property_type",
            "sql": "CREATE INDEX IF NOT EXISTS idx_transactions_property_type ON transactions (property_type_id)",
            "description": "Property type filter",
        },
        {
            "name": "idx_transactions_property_subtype",
            "sql": "CREATE INDEX IF NOT EXISTS idx_transactions_property_subtype ON transactions (property_sub_type_id)",
            "description": "Property sub-type filter",
        },
        {
            "name": "idx_transactions_area",
            "sql": "CREATE INDEX IF NOT EXISTS idx_transactions_area ON transactions (area_id)",
            "description": "Area filter",
        },
        {
            "name": "idx_transactions_trans_group",
            "sql": "CREATE INDEX IF NOT EXISTS idx_transactions_trans_group ON transactions (trans_group_id)",
            "description": "Transaction group filter",
        },
        {
            "name": "idx_transactions_procedure",
            "sql": "CREATE INDEX IF NOT EXISTS idx_transactions_procedure ON transactions (procedure_id)",
            "description": "Procedure filter",
        },
        {
            "name": "idx_transactions_rooms",
            "sql": "CREATE INDEX IF NOT EXISTS idx_transactions_rooms ON transactions (rooms_en)",
            "description": "Rooms filter",
        },
        {
            "name": "idx_transactions_has_parking",
            "sql": "CREATE INDEX IF NOT EXISTS idx_transactions_has_parking ON transactions (has_parking)",
            "description": "Parking filter",
        },
        # PRICE INDEXES: For analytics and range queries
        {
            "name": "idx_transactions_actual_worth",
            "sql": """
                CREATE INDEX IF NOT EXISTS idx_transactions_actual_worth 
                ON transactions (actual_worth) 
                WHERE actual_worth IS NOT NULL
            """,
            "description": "Price range queries (partial index)",
        },
        {
            "name": "idx_transactions_meter_sale_price",
            "sql": """
                CREATE INDEX IF NOT EXISTS idx_transactions_meter_sale_price 
                ON transactions (meter_sale_price) 
                WHERE meter_sale_price IS NOT NULL
            """,
            "description": "Price per sqm queries (partial index)",
        },
    ],
    "units": [
        # Property hierarchy
        {
            "name": "idx_units_parent",
            "sql": "CREATE INDEX IF NOT EXISTS idx_units_parent ON units (parent_property_id)",
            "description": "Building -> Units lookup",
        },
        {
            "name": "idx_units_grandparent",
            "sql": "CREATE INDEX IF NOT EXISTS idx_units_grandparent ON units (grandparent_property_id)",
            "description": "Land -> Units lookup",
        },
        # Common filters
        {
            "name": "idx_units_property_type",
            "sql": "CREATE INDEX IF NOT EXISTS idx_units_property_type ON units (property_type_id)",
            "description": "Property type filter",
        },
        {
            "name": "idx_units_property_subtype",
            "sql": "CREATE INDEX IF NOT EXISTS idx_units_property_subtype ON units (property_sub_type_id)",
            "description": "Property sub-type filter",
        },
        {
            "name": "idx_units_area",
            "sql": "CREATE INDEX IF NOT EXISTS idx_units_area ON units (area_id)",
            "description": "Area filter",
        },
        {
            "name": "idx_units_rooms",
            "sql": "CREATE INDEX IF NOT EXISTS idx_units_rooms ON units (rooms)",
            "description": "Rooms filter",
        },
        {
            "name": "idx_units_project",
            "sql": "CREATE INDEX IF NOT EXISTS idx_units_project ON units (project_id)",
            "description": "Project filter",
        },
        # Location lookups
        {
            "name": "idx_units_area_building",
            "sql": """
                CREATE INDEX IF NOT EXISTS idx_units_area_building 
                ON units (area_id, land_number, building_number)
            """,
            "description": "Area + building lookup",
        },
    ],
    "buildings": [
        {
            "name": "idx_buildings_parent",
            "sql": "CREATE INDEX IF NOT EXISTS idx_buildings_parent ON buildings (parent_property_id)",
            "description": "Land -> Buildings lookup",
        },
        {
            "name": "idx_buildings_area",
            "sql": "CREATE INDEX IF NOT EXISTS idx_buildings_area ON buildings (area_id)",
            "description": "Area filter",
        },
        {
            "name": "idx_buildings_project",
            "sql": "CREATE INDEX IF NOT EXISTS idx_buildings_project ON buildings (project_id)",
            "description": "Project filter",
        },
    ],
    "land_registry": [
        {
            "name": "idx_landregistry_area",
            "sql": "CREATE INDEX IF NOT EXISTS idx_landregistry_area ON land_registry (area_id)",
            "description": "Area filter",
        },
        {
            "name": "idx_landregistry_project",
            "sql": "CREATE INDEX IF NOT EXISTS idx_landregistry_project ON land_registry (project_id)",
            "description": "Project filter",
        },
    ],
}


def create_indexes(tables=None, phase=None):
    """
    Create indexes for specified tables or phase.

    Args:
        tables: List of table names (default: all)
        phase: 'core' for essential indexes only, or 'all' for everything
    """
    start_time = datetime.now()

    print("\n" + "=" * 70)
    print("CREATING PERFORMANCE INDEXES")
    print("=" * 70 + "\n")

    # Filter by phase if specified
    if phase == "core":
        # Only create the most critical indexes
        core_indexes = {
            "transactions": [
                idx
                for idx in INDEXES["transactions"]
                if idx["name"]
                in [
                    "idx_transactions_usage_date_desc",  # MOST CRITICAL!
                    "idx_transactions_property_usage",
                    "idx_transactions_property_type",
                    "idx_transactions_area",
                ]
            ]
        }
        indexes_to_create = core_indexes
        print("Creating CORE indexes only (Phase 1)...\n")
    else:
        indexes_to_create = INDEXES
        print("Creating ALL indexes...\n")

    # Filter by tables if specified
    if tables:
        indexes_to_create = {
            table: indexes_to_create[table]
            for table in tables
            if table in indexes_to_create
        }

    total_created = 0
    total_failed = 0

    with engine.begin() as conn:
        for table_name, indexes in indexes_to_create.items():
            print(f"Table: {table_name}")
            print("-" * 70)

            for idx in indexes:
                try:
                    print(f"  Creating {idx['name']}...")
                    print(f"    Purpose: {idx['description']}")

                    conn.execute(text(idx["sql"]))

                    print(f"    ✓ Success\n")
                    total_created += 1

                except Exception as e:
                    print(f"    ✗ Failed: {e}\n")
                    total_failed += 1

            print()

    elapsed = datetime.now() - start_time

    print("=" * 70)
    print(f"✓ Index creation complete!")
    print("=" * 70)
    print(f"  Created: {total_created}")
    print(f"  Failed: {total_failed}")
    print(f"  Time: {elapsed}")
    print()


def drop_indexes(tables=None):
    """Drop all indexes (useful for rebuilding)"""
    print("\n" + "=" * 70)
    print("DROPPING INDEXES")
    print("=" * 70 + "\n")

    indexes_to_drop = (
        INDEXES
        if not tables
        else {table: INDEXES[table] for table in tables if table in INDEXES}
    )

    with engine.begin() as conn:
        for table_name, indexes in indexes_to_drop.items():
            print(f"Table: {table_name}")
            for idx in indexes:
                try:
                    drop_sql = f"DROP INDEX IF EXISTS {idx['name']}"
                    conn.execute(text(drop_sql))
                    print(f"  ✓ Dropped {idx['name']}")
                except Exception as e:
                    print(f"  ✗ Failed to drop {idx['name']}: {e}")
            print()


def list_indexes():
    """List all defined indexes"""
    print("\n" + "=" * 70)
    print("DEFINED INDEXES")
    print("=" * 70 + "\n")

    for table_name, indexes in INDEXES.items():
        print(f"\n{table_name.upper()} ({len(indexes)} indexes)")
        print("-" * 70)
        for idx in indexes:
            print(f"  • {idx['name']}")
            print(f"    {idx['description']}")
        print()


def check_index_usage():
    """Check which indexes are being used"""
    print("\n" + "=" * 70)
    print("INDEX USAGE STATISTICS")
    print("=" * 70 + "\n")

    query = """
        SELECT 
            schemaname,
            tablename,
            indexname,
            idx_scan as scans,
            idx_tup_read as tuples_read,
            idx_tup_fetch as tuples_fetched,
            pg_size_pretty(pg_relation_size(indexrelid)) as size
        FROM pg_stat_user_indexes
        WHERE schemaname = 'public'
        ORDER BY idx_scan ASC, tablename, indexname;
    """

    with engine.connect() as conn:
        result = conn.execute(text(query))

        current_table = None
        for row in result:
            if row.tablename != current_table:
                current_table = row.tablename
                print(f"\n{current_table.upper()}")
                print("-" * 70)
                print(f"{'Index Name':<40} {'Scans':>10} {'Size':>10}")
                print("-" * 70)

            print(f"{row.indexname:<40} {row.scans:>10,} {row.size:>10}")

        print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage database indexes")
    parser.add_argument(
        "action", choices=["create", "drop", "list", "usage"], help="Action to perform"
    )
    parser.add_argument("--tables", nargs="+", help="Specific tables to operate on")
    parser.add_argument(
        "--phase",
        choices=["core", "all"],
        default="all",
        help="Create core indexes only or all indexes",
    )

    args = parser.parse_args()

    if args.action == "create":
        create_indexes(tables=args.tables, phase=args.phase)
    elif args.action == "drop":
        confirm = input("Are you sure you want to drop indexes? (yes/no): ")
        if confirm.lower() == "yes":
            drop_indexes(tables=args.tables)
    elif args.action == "list":
        list_indexes()
    elif args.action == "usage":
        check_index_usage()
