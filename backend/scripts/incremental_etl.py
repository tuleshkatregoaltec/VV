#!/usr/bin/env python3
"""
Incremental ETL Pipeline

Efficiently loads new and updated data by comparing current CSVs against previous CSVs.
Designed for daily runs with ~200k transactions/year volume.

Features:
- CSV-based diff detection (no database reads for deduplication)
- Upsert support (INSERT or UPDATE on conflict)
- Resumable on failure
- Detailed logging and metadata tracking
- Initial load support (when no previous CSV exists)

Directory Structure Expected:
    data/
    ├── current/       # Today's CSVs (you place files here)
    │   ├── Transactions.csv
    │   ├── Rent_Contracts.csv
    │   └── ...
    └── previous/      # Yesterday's CSVs (for comparison)
        ├── Transactions.csv
        └── ...

Usage:
    # Full incremental run (all tables)
    python -m backend.scripts.incremental_etl

    # Single table only
    python -m backend.scripts.incremental_etl --table transactions

    # Resume a failed run
    python -m backend.scripts.incremental_etl --resume

    # Dry run (show what would change)
    python -m backend.scripts.incremental_etl --dry-run

    # Force full refresh (ignore previous CSV)
    python -m backend.scripts.incremental_etl --table transactions --full-refresh
"""

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd
from sqlalchemy import text
from sqlmodel import Session
from tqdm import tqdm

from backend.app.db.session import engine
from backend.app.db.models import (
    Area,
    TransactionGroup,
    TransactionProcedure,
    PropertyType,
    PropertySubType,
    MasterProject,
    Developer,
    Project,
    LandRegistry,
    Building,
    Unit,
    Transaction,
    RentContract,
    ETLMetadata,
)
from backend.scripts.db_utils.utils import (
    rename_columns,
    clean_value,
    parse_int,
    parse_date,
    parse_bool,
    parse_decimal,
)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_BATCH_SIZE = 10000
STATE_FILE = "etl_state.json"


# Configure logging
def setup_logging(log_dir: Path) -> logging.Logger:
    """Set up logging to both file and console."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"etl_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.log"

    # Create logger
    logger = logging.getLogger("incremental_etl")
    logger.setLevel(logging.DEBUG)

    # File handler (detailed)
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)

    # Console handler (summary)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.info(f"Logging to: {log_file}")
    return logger


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class TableConfig:
    """Configuration for a single table's ETL process."""

    name: str
    model: type
    csv_file: str
    primary_keys: list[str]
    column_parsers: dict[str, Callable]  # column_name -> parser function
    column_renames: dict[str, str] = field(default_factory=dict)  # csv_col -> db_col


@dataclass
class DiffResult:
    """Result of comparing current vs previous CSV."""

    new_rows: pd.DataFrame
    updated_rows: pd.DataFrame
    total_current: int
    total_previous: int
    is_initial_load: bool


@dataclass
class LoadResult:
    """Result of loading a table."""

    table_name: str
    rows_scanned: int
    rows_inserted: int
    rows_updated: int
    rows_skipped: int
    rows_errored: int
    errors: list[str]
    duration_seconds: float


# =============================================================================
# CSV DIFF ENGINE
# =============================================================================


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def compute_row_hash(row: pd.Series) -> str:
    """Compute hash of a row for change detection."""
    # Convert row to string representation and hash
    row_str = "|".join(str(v) if pd.notna(v) else "" for v in row.values)
    return hashlib.md5(row_str.encode()).hexdigest()


def diff_csvs(
    current_path: Path,
    previous_path: Path | None,
    primary_keys: list[str],
    logger: logging.Logger,
) -> DiffResult:
    """
    Compare current CSV against previous CSV to find new and updated rows.

    Args:
        current_path: Path to today's CSV
        previous_path: Path to yesterday's CSV (None for initial load)
        primary_keys: Column(s) that uniquely identify a row
        logger: Logger instance

    Returns:
        DiffResult with new_rows, updated_rows DataFrames
    """
    logger.info(f"  Loading current CSV: {current_path.name}")
    current_df = pd.read_csv(current_path, dtype=str, low_memory=False)
    current_df = rename_columns(current_df)
    total_current = len(current_df)
    logger.debug(f"  Current CSV has {total_current:,} rows")

    # Initial load case - no previous file
    if previous_path is None or not previous_path.exists():
        logger.info("  No previous CSV found - treating as initial load")
        return DiffResult(
            new_rows=current_df,
            updated_rows=pd.DataFrame(),
            total_current=total_current,
            total_previous=0,
            is_initial_load=True,
        )

    logger.info(f"  Loading previous CSV: {previous_path.name}")
    previous_df = pd.read_csv(previous_path, dtype=str, low_memory=False)
    previous_df = rename_columns(previous_df)
    total_previous = len(previous_df)
    logger.debug(f"  Previous CSV has {total_previous:,} rows")

    # Compute row hashes for change detection
    logger.debug("  Computing row hashes for change detection...")

    # Get non-key columns for hashing
    non_key_cols = [c for c in current_df.columns if c not in primary_keys]

    current_df["_row_hash"] = current_df[non_key_cols].apply(compute_row_hash, axis=1)
    previous_df["_row_hash"] = previous_df[non_key_cols].apply(compute_row_hash, axis=1)

    # Create composite key for matching
    if len(primary_keys) == 1:
        current_df["_pk"] = current_df[primary_keys[0]].astype(str)
        previous_df["_pk"] = previous_df[primary_keys[0]].astype(str)
    else:
        current_df["_pk"] = current_df[primary_keys].astype(str).agg("|".join, axis=1)
        previous_df["_pk"] = previous_df[primary_keys].astype(str).agg("|".join, axis=1)

    # Find new rows (in current but not in previous)
    previous_keys = set(previous_df["_pk"].dropna())
    new_mask = ~current_df["_pk"].isin(previous_keys)
    new_rows = current_df[new_mask].drop(columns=["_row_hash", "_pk"])

    # Find updated rows (same key but different hash)
    common_mask = current_df["_pk"].isin(previous_keys)
    common_current = current_df[common_mask].set_index("_pk")
    common_previous = previous_df.set_index("_pk")

    # Compare hashes for common rows
    updated_keys = []
    for pk in common_current.index:
        if pk in common_previous.index:
            if (
                common_current.loc[pk, "_row_hash"]
                != common_previous.loc[pk, "_row_hash"]
            ):
                updated_keys.append(pk)

    updated_rows = current_df[current_df["_pk"].isin(updated_keys)].drop(
        columns=["_row_hash", "_pk"]
    )

    logger.info(
        f"  Diff complete: {len(new_rows):,} new, {len(updated_rows):,} updated, {total_current - len(new_rows) - len(updated_rows):,} unchanged"
    )

    return DiffResult(
        new_rows=new_rows,
        updated_rows=updated_rows,
        total_current=total_current,
        total_previous=total_previous,
        is_initial_load=False,
    )


# =============================================================================
# UPSERT ENGINE
# =============================================================================


def build_upsert_statement(
    table_name: str, columns: list[str], primary_keys: list[str]
) -> str:
    """Build PostgreSQL upsert (INSERT ON CONFLICT UPDATE) statement."""
    cols_str = ", ".join(columns)
    placeholders = ", ".join(f":{c}" for c in columns)
    pk_str = ", ".join(primary_keys)

    # Build UPDATE SET clause (exclude primary keys from update)
    update_cols = [c for c in columns if c not in primary_keys]
    update_str = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)

    if update_str:
        return f"""
            INSERT INTO {table_name} ({cols_str})
            VALUES ({placeholders})
            ON CONFLICT ({pk_str}) DO UPDATE SET {update_str}
        """
    else:
        # No columns to update (only PKs) - just insert or ignore
        return f"""
            INSERT INTO {table_name} ({cols_str})
            VALUES ({placeholders})
            ON CONFLICT ({pk_str}) DO NOTHING
        """


def parse_row(row: dict, parsers: dict[str, Callable], renames: dict[str, str]) -> dict:
    """Parse and rename columns in a row."""
    result = {}
    for col, value in row.items():
        # Apply parser if defined
        if col in parsers:
            value = parsers[col](value)
        elif pd.isna(value) or value == "":
            value = None

        # Apply rename if defined
        db_col = renames.get(col, col)
        result[db_col] = value

    return result


def upsert_batch(
    session: Session,
    table_name: str,
    records: list[dict],
    primary_keys: list[str],
    logger: logging.Logger,
) -> tuple[int, int, list[str]]:
    """
    Upsert a batch of records.

    Returns:
        Tuple of (inserted_count, updated_count, errors)
    """
    if not records:
        return 0, 0, []

    columns = list(records[0].keys())
    stmt = build_upsert_statement(table_name, columns, primary_keys)

    errors = []
    success_count = 0

    for record in records:
        try:
            session.execute(text(stmt), record)
            success_count += 1
        except Exception as e:
            pk_vals = {k: record.get(k) for k in primary_keys}
            error_msg = f"Row {pk_vals}: {str(e)[:200]}"
            errors.append(error_msg)
            logger.debug(f"  Error upserting row: {error_msg}")

    return (
        success_count,
        0,
        errors,
    )  # We can't easily distinguish insert vs update with ON CONFLICT


# =============================================================================
# TABLE CONFIGURATIONS
# =============================================================================


def get_table_configs() -> dict[str, TableConfig]:
    """Define ETL configuration for each table."""

    # Common parsers
    int_parser = parse_int
    date_parser = parse_date
    bool_parser = parse_bool
    decimal_parser = parse_decimal
    str_parser = clean_value

    configs = {}

    # Areas
    configs["areas"] = TableConfig(
        name="areas",
        model=Area,
        csv_file="Lkp_Areas.csv",
        primary_keys=["area_id"],
        column_parsers={
            "area_id": int_parser,
            "name_ar": str_parser,
            "name_en": str_parser,
            "municipality_number": str_parser,
        },
        column_renames={"name_en": "name"},
    )

    # Transaction Groups (extracted from Transactions.csv)
    configs["transaction_groups"] = TableConfig(
        name="transaction_groups",
        model=TransactionGroup,
        csv_file="Transactions.csv",
        primary_keys=["group_id"],
        column_parsers={
            "trans_group_id": int_parser,
            "trans_group_ar": str_parser,
            "trans_group_en": str_parser,
        },
        column_renames={
            "trans_group_id": "group_id",
            "trans_group_ar": "group_name_ar",
            "trans_group_en": "group_name",
        },
    )

    # Transaction Procedures
    configs["transaction_procedures"] = TableConfig(
        name="transaction_procedures",
        model=TransactionProcedure,
        csv_file="Lkp_Transaction_Procedures.csv",
        primary_keys=["procedure_id"],
        column_parsers={
            "procedure_id": int_parser,
            "group_id": int_parser,
            "is_pre_registration": bool_parser,
            "name_ar": str_parser,
            "name_en": str_parser,
        },
        column_renames={
            "name_ar": "procedure_name_ar",
            "name_en": "procedure_name",
        },
    )

    # Property Types (extracted from property files)
    configs["property_types"] = TableConfig(
        name="property_types",
        model=PropertyType,
        csv_file="Units.csv",  # We'll extract unique types
        primary_keys=["property_type_id"],
        column_parsers={
            "property_type_id": int_parser,
            "property_type_ar": str_parser,
            "property_type_en": str_parser,
        },
        column_renames={"property_type_en": "property_type"},
    )

    # Property Sub-Types
    configs["property_sub_types"] = TableConfig(
        name="property_sub_types",
        model=PropertySubType,
        csv_file="Units.csv",
        primary_keys=["property_sub_type_id"],
        column_parsers={
            "property_sub_type_id": int_parser,
            "property_type_id": int_parser,
            "property_sub_type_ar": str_parser,
            "property_sub_type_en": str_parser,
        },
        column_renames={"property_sub_type_en": "property_sub_type"},
    )

    # Master Projects
    configs["master_projects"] = TableConfig(
        name="master_projects",
        model=MasterProject,
        csv_file="Units.csv",
        primary_keys=["master_project_id"],
        column_parsers={
            "master_project_id": int_parser,
            "master_project_ar": str_parser,
            "master_project_en": str_parser,
        },
        column_renames={
            "master_project_ar": "master_project_name_ar",
            "master_project_en": "master_project_name",
        },
    )

    # Developers
    configs["developers"] = TableConfig(
        name="developers",
        model=Developer,
        csv_file="Developers.csv",
        primary_keys=["developer_id"],
        column_parsers={
            "developer_id": int_parser,
            "participant_id": int_parser,
            "developer_number": int_parser,
            "developer_name_ar": str_parser,
            "developer_name_en": str_parser,
            "registration_date": date_parser,
            "license_source_id": int_parser,
            "license_source_ar": str_parser,
            "license_source_en": str_parser,
            "license_type_id": int_parser,
            "license_type_ar": str_parser,
            "license_type_en": str_parser,
            "license_number": str_parser,
            "license_issue_date": date_parser,
            "license_expiry_date": date_parser,
            "chamber_of_commerce_no": str_parser,
            "legal_status": str_parser,
            "legal_status_ar": str_parser,
            "legal_status_en": str_parser,
            "webpage": str_parser,
            "phone": str_parser,
            "fax": str_parser,
        },
        column_renames={
            "developer_name_en": "developer_name",
            "license_source_en": "license_source",
            "license_type_en": "license_type",
            "legal_status_en": "legal_status_description",
        },
    )

    # Projects
    configs["projects"] = TableConfig(
        name="projects",
        model=Project,
        csv_file="Projects.csv",
        primary_keys=["project_id"],
        column_parsers={
            "project_id": int_parser,
            "project_number": int_parser,
            "project_name": str_parser,
            "developer_id": int_parser,
            "master_developer_id": int_parser,
            "project_start_date": date_parser,
            "project_end_date": date_parser,
            "project_type_id": int_parser,
            "project_type_ar": str_parser,
            "project_classification_id": int_parser,
            "project_classification_ar": str_parser,
            "escrow_agent_id": int_parser,
            "escrow_agent_name": str_parser,
            "project_status": str_parser,
            "project_status_ar": str_parser,
            "percent_completed": int_parser,
            "completion_date": date_parser,
            "cancellation_date": date_parser,
            "project_description_ar": str_parser,
            "project_description_en": str_parser,
            "property_id": int_parser,
            "area_id": int_parser,
            "zoning_authority_id": int_parser,
            "zoning_authority_ar": str_parser,
            "zoning_authority_en": str_parser,
            "no_of_lands": int_parser,
            "no_of_buildings": int_parser,
            "no_of_villas": int_parser,
            "no_of_units": int_parser,
        },
        column_renames={
            "project_description_en": "project_description",
            "zoning_authority_en": "zoning_authority",
        },
    )

    # Land Registry
    configs["land_registry"] = TableConfig(
        name="land_registry",
        model=LandRegistry,
        csv_file="Land_Registry.csv",
        primary_keys=["property_id"],
        column_parsers={
            "property_id": int_parser,
            "area_id": int_parser,
            "zone_id": int_parser,
            "land_number": str_parser,
            "land_sub_number": str_parser,
            "actual_area": decimal_parser,
            "property_type_id": int_parser,
            "property_sub_type_id": int_parser,
            "parcel_id": str_parser,
            "munc_zip_code": str_parser,
            "munc_number": str_parser,
            "is_free_hold": bool_parser,
            "is_registered": bool_parser,
            "pre_registration_number": str_parser,
            "separated_from": int_parser,
            "separated_reference": int_parser,
            "project_id": int_parser,
            "master_project_id": int_parser,
            "land_type_id": int_parser,
            "land_type_ar": str_parser,
            "land_type": str_parser,
        },
        column_renames={},
    )

    # Buildings
    configs["buildings"] = TableConfig(
        name="buildings",
        model=Building,
        csv_file="Buildings.csv",
        primary_keys=["property_id"],
        column_parsers={
            "property_id": int_parser,
            "area_id": int_parser,
            "zone_id": int_parser,
            "land_number": str_parser,
            "land_sub_number": str_parser,
            "building_number": str_parser,
            "floors": int_parser,
            "bld_levels": int_parser,
            "rooms": int_parser,
            "rooms_ar": str_parser,
            "rooms_en": str_parser,
            "car_parks": int_parser,
            "common_area": decimal_parser,
            "actual_common_area": decimal_parser,
            "built_up_area": decimal_parser,
            "actual_area": decimal_parser,
            "shops": int_parser,
            "flats": int_parser,
            "offices": int_parser,
            "swimming_pools": int_parser,
            "elevators": int_parser,
            "property_type_id": int_parser,
            "property_sub_type_id": int_parser,
            "parent_property_id": int_parser,
            "creation_date": date_parser,
            "parcel_id": str_parser,
            "is_free_hold": bool_parser,
            "is_lease_hold": bool_parser,
            "is_registered": bool_parser,
            "pre_registration_number": str_parser,
            "project_id": int_parser,
            "master_project_id": int_parser,
            "land_type_id": int_parser,
            "land_type_ar": str_parser,
            "land_type": str_parser,
        },
        column_renames={"rooms_en": "rooms_description"},
    )

    # Units
    configs["units"] = TableConfig(
        name="units",
        model=Unit,
        csv_file="Units.csv",
        primary_keys=["property_id"],
        column_parsers={
            "property_id": int_parser,
            "area_id": int_parser,
            "zone_id": int_parser,
            "land_number": str_parser,
            "land_sub_number": str_parser,
            "building_number": str_parser,
            "unit_number": str_parser,
            "floor": str_parser,
            "rooms": int_parser,
            "rooms_ar": str_parser,
            "rooms_en": str_parser,
            "unit_balcony_area": decimal_parser,
            "common_area": decimal_parser,
            "actual_common_area": decimal_parser,
            "actual_area": decimal_parser,
            "unit_parking_number": str_parser,
            "parking_allocation_type": str_parser,
            "parking_allocation_type_ar": str_parser,
            "parking_allocation_type_en": str_parser,
            "property_type_id": int_parser,
            "property_sub_type_id": int_parser,
            "parent_property_id": int_parser,
            "grandparent_property_id": int_parser,
            "creation_date": date_parser,
            "munc_zip_code": str_parser,
            "munc_number": str_parser,
            "parcel_id": str_parser,
            "is_free_hold": bool_parser,
            "is_lease_hold": bool_parser,
            "is_registered": bool_parser,
            "pre_registration_number": str_parser,
            "project_id": int_parser,
            "master_project_id": int_parser,
            "land_type_id": int_parser,
            "land_type_ar": str_parser,
            "land_type": str_parser,
        },
        column_renames={
            "rooms_en": "rooms_description",
            "parking_allocation_type_en": "parking_allocation_type_description",
        },
    )

    # Transactions
    configs["transactions"] = TableConfig(
        name="transactions",
        model=Transaction,
        csv_file="Transactions.csv",
        primary_keys=["transaction_id"],
        column_parsers={
            "transaction_id": str_parser,
            "procedure_id": int_parser,
            "trans_group_id": int_parser,
            "trans_group_ar": str_parser,
            "trans_group_en": str_parser,
            "procedure_name_ar": str_parser,
            "procedure_name_en": str_parser,
            "instance_date": date_parser,
            "property_type_id": int_parser,
            "property_type_ar": str_parser,
            "property_type_en": str_parser,
            "property_sub_type_id": int_parser,
            "property_sub_type_ar": str_parser,
            "property_sub_type_en": str_parser,
            "property_usage_ar": str_parser,
            "property_usage_en": str_parser,
            "reg_type_id": int_parser,
            "reg_type_ar": str_parser,
            "reg_type_en": str_parser,
            "area_id": int_parser,
            "area_name_ar": str_parser,
            "area_name_en": str_parser,
            "building_name_ar": str_parser,
            "building_name_en": str_parser,
            "project_number": str_parser,
            "project_name_ar": str_parser,
            "project_name_en": str_parser,
            "master_project_ar": str_parser,
            "master_project_en": str_parser,
            "nearest_landmark_ar": str_parser,
            "nearest_landmark_en": str_parser,
            "nearest_metro_ar": str_parser,
            "nearest_metro_en": str_parser,
            "nearest_mall_ar": str_parser,
            "nearest_mall_en": str_parser,
            "rooms_ar": str_parser,
            "rooms_en": str_parser,
            "has_parking": bool_parser,
            "procedure_area": decimal_parser,
            "actual_worth": decimal_parser,
            "meter_sale_price": decimal_parser,
            "rent_value": decimal_parser,
            "meter_rent_price": decimal_parser,
            "no_of_parties_role_1": int_parser,
            "no_of_parties_role_2": int_parser,
            "no_of_parties_role_3": int_parser,
        },
        column_renames={
            "trans_group_en": "trans_group",
            "procedure_name_en": "procedure_name",
            "property_type_en": "property_type",
            "property_sub_type_en": "property_sub_type",
            "property_usage_en": "property_usage",
            "reg_type_en": "reg_type",
            "area_name_en": "area_name",
            "building_name_en": "building_name",
            "project_name_en": "project_name",
            "master_project_en": "master_project",
            "nearest_landmark_en": "nearest_landmark",
            "nearest_metro_en": "nearest_metro",
            "nearest_mall_en": "nearest_mall",
            "rooms_en": "rooms_description",
        },
    )

    # Rent Contracts
    configs["rent_contracts"] = TableConfig(
        name="rent_contracts",
        model=RentContract,
        csv_file="Rent_Contracts.csv",
        primary_keys=["contract_id", "line_number"],
        column_parsers={
            "contract_id": str_parser,
            "line_number": int_parser,
            "contract_reg_type_id": int_parser,
            "contract_reg_type_ar": str_parser,
            "contract_reg_type_en": str_parser,
            "contract_start_date": date_parser,
            "contract_end_date": date_parser,
            "contract_amount": decimal_parser,
            "annual_amount": decimal_parser,
            "no_of_prop": int_parser,
            "is_free_hold": bool_parser,
            "ejari_bus_property_type_id": int_parser,
            "ejari_bus_property_type_ar": str_parser,
            "ejari_bus_property_type_en": str_parser,
            "ejari_property_type_id": int_parser,
            "ejari_property_type_en": str_parser,
            "ejari_property_type_ar": str_parser,
            "ejari_property_sub_type_id": int_parser,
            "ejari_property_sub_type_en": str_parser,
            "ejari_property_sub_type_ar": str_parser,
            "property_usage_en": str_parser,
            "property_usage_ar": str_parser,
            "project_number": str_parser,
            "project_name_ar": str_parser,
            "project_name_en": str_parser,
            "master_project_ar": str_parser,
            "master_project_en": str_parser,
            "area_id": int_parser,
            "area_name_ar": str_parser,
            "area_name_en": str_parser,
            "actual_area": decimal_parser,
            "nearest_landmark_ar": str_parser,
            "nearest_landmark_en": str_parser,
            "nearest_metro_ar": str_parser,
            "nearest_metro_en": str_parser,
            "nearest_mall_ar": str_parser,
            "nearest_mall_en": str_parser,
            "tenant_type_id": int_parser,
            "tenant_type_ar": str_parser,
            "tenant_type_en": str_parser,
        },
        column_renames={
            "contract_reg_type_en": "contract_reg_type",
            "ejari_bus_property_type_en": "ejari_bus_property_type",
            "ejari_property_type_en": "ejari_property_type",
            "ejari_property_sub_type_en": "ejari_property_sub_type",
            "property_usage_en": "property_usage",
            "project_name_en": "project_name",
            "master_project_en": "master_project",
            "area_name_en": "area_name",
            "nearest_landmark_en": "nearest_landmark",
            "nearest_metro_en": "nearest_metro",
            "nearest_mall_en": "nearest_mall",
            "tenant_type_en": "tenant_type",
        },
    )

    return configs


# Processing order (respects FK dependencies)
PROCESSING_ORDER = [
    "areas",
    "transaction_groups",
    "transaction_procedures",
    "property_types",
    "property_sub_types",
    "master_projects",
    "developers",
    "projects",
    "land_registry",
    "buildings",
    "units",
    "transactions",
    "rent_contracts",
]


# =============================================================================
# STATE MANAGEMENT
# =============================================================================


def load_state(state_path: Path) -> dict | None:
    """Load ETL state from file."""
    if not state_path.exists():
        return None
    with open(state_path) as f:
        return json.load(f)


def save_state(state_path: Path, state: dict) -> None:
    """Save ETL state to file."""
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2, default=str)


def clear_state(state_path: Path) -> None:
    """Clear ETL state file."""
    if state_path.exists():
        state_path.unlink()


# =============================================================================
# SPECIAL LOADERS (for lookup tables extracted from other CSVs)
# =============================================================================


def extract_transaction_groups(
    current_dir: Path, previous_dir: Path, logger: logging.Logger
) -> DiffResult:
    """Extract unique transaction groups from Transactions.csv."""
    logger.info("  Extracting transaction groups from Transactions.csv...")

    current_path = current_dir / "Transactions.csv"
    current_df = pd.read_csv(
        current_path,
        dtype=str,
        low_memory=False,
        usecols=["trans_group_id", "trans_group_ar", "trans_group_en"],
    )
    current_df = rename_columns(current_df)
    current_df = current_df.drop_duplicates(subset=["trans_group_id"]).dropna(
        subset=["trans_group_id"]
    )

    previous_path = previous_dir / "Transactions.csv"
    if previous_path.exists():
        previous_df = pd.read_csv(
            previous_path,
            dtype=str,
            low_memory=False,
            usecols=["trans_group_id", "trans_group_ar", "trans_group_en"],
        )
        previous_df = rename_columns(previous_df)
        previous_df = previous_df.drop_duplicates(subset=["trans_group_id"]).dropna(
            subset=["trans_group_id"]
        )

        # Find new groups
        previous_ids = set(previous_df["trans_group_id"])
        new_rows = current_df[~current_df["trans_group_id"].isin(previous_ids)]

        return DiffResult(
            new_rows=new_rows,
            updated_rows=pd.DataFrame(),  # Groups don't really update
            total_current=len(current_df),
            total_previous=len(previous_df),
            is_initial_load=False,
        )

    return DiffResult(
        new_rows=current_df,
        updated_rows=pd.DataFrame(),
        total_current=len(current_df),
        total_previous=0,
        is_initial_load=True,
    )


def extract_lookup_from_csv(
    current_dir: Path,
    previous_dir: Path,
    csv_file: str,
    id_column: str,
    columns: list[str],
    logger: logging.Logger,
) -> DiffResult:
    """Extract unique lookup values from a CSV file."""
    logger.info(f"  Extracting {id_column} lookup from {csv_file}...")

    current_path = current_dir / csv_file
    current_df = pd.read_csv(current_path, dtype=str, low_memory=False, usecols=columns)
    current_df = rename_columns(current_df)
    current_df = current_df.drop_duplicates(subset=[id_column]).dropna(
        subset=[id_column]
    )

    previous_path = previous_dir / csv_file
    if previous_path.exists():
        previous_df = pd.read_csv(
            previous_path, dtype=str, low_memory=False, usecols=columns
        )
        previous_df = rename_columns(previous_df)
        previous_df = previous_df.drop_duplicates(subset=[id_column]).dropna(
            subset=[id_column]
        )

        previous_ids = set(previous_df[id_column])
        new_rows = current_df[~current_df[id_column].isin(previous_ids)]

        return DiffResult(
            new_rows=new_rows,
            updated_rows=pd.DataFrame(),
            total_current=len(current_df),
            total_previous=len(previous_df),
            is_initial_load=False,
        )

    return DiffResult(
        new_rows=current_df,
        updated_rows=pd.DataFrame(),
        total_current=len(current_df),
        total_previous=0,
        is_initial_load=True,
    )


# =============================================================================
# MAIN ETL LOGIC
# =============================================================================


def load_table(
    config: TableConfig,
    current_dir: Path,
    previous_dir: Path,
    run_id: str,
    logger: logging.Logger,
    dry_run: bool = False,
    full_refresh: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> LoadResult:
    """Load a single table with incremental diff."""
    start_time = datetime.now(timezone.utc)
    errors = []

    logger.info(f"\n{'=' * 60}")
    logger.info(f"Processing: {config.name}")
    logger.info(f"{'=' * 60}")

    # Record metadata
    metadata = ETLMetadata(
        run_id=run_id,
        table_name=config.name,
        status="running",
    )

    try:
        # Handle special lookup tables
        if config.name == "transaction_groups":
            diff = extract_transaction_groups(current_dir, previous_dir, logger)
        elif config.name == "property_types":
            diff = extract_lookup_from_csv(
                current_dir,
                previous_dir,
                "Units.csv",
                "property_type_id",
                ["property_type_id", "property_type_ar", "property_type_en"],
                logger,
            )
        elif config.name == "property_sub_types":
            diff = extract_lookup_from_csv(
                current_dir,
                previous_dir,
                "Units.csv",
                "property_sub_type_id",
                [
                    "property_sub_type_id",
                    "property_type_id",
                    "property_sub_type_ar",
                    "property_sub_type_en",
                ],
                logger,
            )
        elif config.name == "master_projects":
            diff = extract_lookup_from_csv(
                current_dir,
                previous_dir,
                "Units.csv",
                "master_project_id",
                ["master_project_id", "master_project_ar", "master_project_en"],
                logger,
            )
        else:
            # Regular table diff
            current_path = current_dir / config.csv_file
            previous_path = previous_dir / config.csv_file if not full_refresh else None

            if not current_path.exists():
                raise FileNotFoundError(f"CSV not found: {current_path}")

            diff = diff_csvs(current_path, previous_path, config.primary_keys, logger)

            # Compute file hash
            metadata.csv_file_hash = compute_file_hash(current_path)
            if previous_path and previous_path.exists():
                metadata.previous_csv_hash = compute_file_hash(previous_path)

        metadata.csv_row_count = diff.total_current
        metadata.rows_scanned = len(diff.new_rows) + len(diff.updated_rows)

        # Combine new and updated rows
        all_changes = pd.concat([diff.new_rows, diff.updated_rows], ignore_index=True)

        if len(all_changes) == 0:
            logger.info("  No changes detected - skipping")
            metadata.mark_completed(0, 0, diff.total_current)

            if not dry_run:
                with Session(engine) as session:
                    session.add(metadata)
                    session.commit()

            return LoadResult(
                table_name=config.name,
                rows_scanned=0,
                rows_inserted=0,
                rows_updated=0,
                rows_skipped=diff.total_current,
                rows_errored=0,
                errors=[],
                duration_seconds=(
                    datetime.now(timezone.utc) - start_time
                ).total_seconds(),
            )

        if dry_run:
            logger.info(
                f"  [DRY RUN] Would process {len(diff.new_rows):,} new, {len(diff.updated_rows):,} updated rows"
            )
            return LoadResult(
                table_name=config.name,
                rows_scanned=len(all_changes),
                rows_inserted=len(diff.new_rows),
                rows_updated=len(diff.updated_rows),
                rows_skipped=diff.total_current - len(all_changes),
                rows_errored=0,
                errors=[],
                duration_seconds=(
                    datetime.now(timezone.utc) - start_time
                ).total_seconds(),
            )

        # Process in batches
        total_success = 0
        total_errors = 0

        num_batches = (len(all_changes) + batch_size - 1) // batch_size

        with Session(engine) as session:
            # Disable FK constraints for performance
            session.execute(text("SET session_replication_role = 'replica';"))

            for batch_idx in tqdm(
                range(num_batches), desc=f"  Upserting {config.name}", unit="batch"
            ):
                start_idx = batch_idx * batch_size
                end_idx = min(start_idx + batch_size, len(all_changes))
                batch_df = all_changes.iloc[start_idx:end_idx]

                # Parse and transform rows
                records = []
                for _, row in batch_df.iterrows():
                    try:
                        parsed = parse_row(
                            row.to_dict(), config.column_parsers, config.column_renames
                        )
                        records.append(parsed)
                    except Exception as e:
                        pk_vals = {k: row.get(k) for k in config.primary_keys}
                        errors.append(f"Parse error {pk_vals}: {str(e)[:100]}")
                        total_errors += 1

                # Upsert batch
                success, _, batch_errors = upsert_batch(
                    session, config.name, records, config.primary_keys, logger
                )
                total_success += success
                total_errors += len(batch_errors)
                errors.extend(batch_errors)

                # Commit each batch
                session.commit()

            # Re-enable FK constraints
            session.execute(text("SET session_replication_role = 'origin';"))
            session.commit()

        # Update metadata
        metadata.mark_completed(
            inserted=len(diff.new_rows) - total_errors,
            updated=len(diff.updated_rows),
            skipped=diff.total_current - len(all_changes),
            errored=total_errors,
        )
        if errors:
            metadata.errors = json.dumps(errors[:100])  # Limit stored errors

        with Session(engine) as session:
            session.add(metadata)
            session.commit()

        logger.info(
            f"  ✓ Completed: {total_success:,} rows processed, {total_errors:,} errors"
        )

        return LoadResult(
            table_name=config.name,
            rows_scanned=len(all_changes),
            rows_inserted=len(diff.new_rows) - total_errors,
            rows_updated=len(diff.updated_rows),
            rows_skipped=diff.total_current - len(all_changes),
            rows_errored=total_errors,
            errors=errors,
            duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
        )

    except Exception as e:
        logger.error(f"  ✗ Failed: {str(e)}")
        metadata.mark_failed(str(e))

        with Session(engine) as session:
            session.add(metadata)
            session.commit()

        return LoadResult(
            table_name=config.name,
            rows_scanned=0,
            rows_inserted=0,
            rows_updated=0,
            rows_skipped=0,
            rows_errored=1,
            errors=[str(e)],
            duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
        )


def run_etl(
    current_dir: Path,
    previous_dir: Path,
    tables: list[str] | None = None,
    dry_run: bool = False,
    full_refresh: bool = False,
    resume: bool = False,
    logger: logging.Logger = None,
) -> list[LoadResult]:
    """Run the incremental ETL pipeline."""

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    state_path = current_dir / STATE_FILE

    configs = get_table_configs()

    # Determine which tables to process
    if tables:
        processing_order = [t for t in PROCESSING_ORDER if t in tables]
    else:
        processing_order = PROCESSING_ORDER

    # Handle resume
    start_from_idx = 0
    if resume:
        state = load_state(state_path)
        if state and state.get("status") == "in_progress":
            run_id = state["run_id"]
            completed = set(state.get("completed_tables", []))
            for i, table in enumerate(processing_order):
                if table not in completed:
                    start_from_idx = i
                    break
            logger.info(
                f"Resuming run {run_id} from {processing_order[start_from_idx]}"
            )

    # Initialize state
    state = {
        "run_id": run_id,
        "status": "in_progress",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_tables": [],
        "current_table": None,
        "errors": [],
    }
    save_state(state_path, state)

    results = []

    logger.info("=" * 70)
    logger.info("ViteVue Incremental ETL Pipeline")
    logger.info("=" * 70)
    logger.info(f"Run ID: {run_id}")
    logger.info(f"Current data: {current_dir}")
    logger.info(f"Previous data: {previous_dir}")
    logger.info(f"Tables: {', '.join(processing_order)}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    if full_refresh:
        logger.info("Full refresh enabled (ignoring previous CSV)")

    for i, table_name in enumerate(processing_order):
        if i < start_from_idx:
            continue

        config = configs.get(table_name)
        if not config:
            logger.warning(f"No config found for table: {table_name}")
            continue

        state["current_table"] = table_name
        save_state(state_path, state)

        result = load_table(
            config,
            current_dir,
            previous_dir,
            run_id,
            logger,
            dry_run=dry_run,
            full_refresh=full_refresh,
        )
        results.append(result)

        state["completed_tables"].append(table_name)
        if result.errors:
            state["errors"].extend(result.errors[:10])  # Keep first 10 errors per table
        save_state(state_path, state)

    # Mark complete
    state["status"] = "completed"
    state["completed_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state_path, state)

    # Print summary
    logger.info("\n" + "=" * 70)
    logger.info("ETL SUMMARY")
    logger.info("=" * 70)

    total_inserted = sum(r.rows_inserted for r in results)
    total_updated = sum(r.rows_updated for r in results)
    total_skipped = sum(r.rows_skipped for r in results)
    total_errors = sum(r.rows_errored for r in results)
    total_duration = sum(r.duration_seconds for r in results)

    for r in results:
        status = "✓" if r.rows_errored == 0 else "⚠"
        logger.info(
            f"  {status} {r.table_name:25} | "
            f"+{r.rows_inserted:>8,} | "
            f"~{r.rows_updated:>6,} | "
            f"={r.rows_skipped:>8,} | "
            f"✗{r.rows_errored:>4} | "
            f"{r.duration_seconds:>6.1f}s"
        )

    logger.info("-" * 70)
    logger.info(
        f"  TOTAL                        | "
        f"+{total_inserted:>8,} | "
        f"~{total_updated:>6,} | "
        f"={total_skipped:>8,} | "
        f"✗{total_errors:>4} | "
        f"{total_duration:>6.1f}s"
    )

    if total_errors > 0:
        logger.warning(f"\n⚠ {total_errors} errors occurred. Check logs for details.")
    else:
        logger.info("\n✓ ETL completed successfully!")

    return results


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Incremental ETL Pipeline for ViteVue Analytics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--current-dir",
        type=Path,
        default=Path("data/current"),
        help="Directory containing current CSVs (default: data/current)",
    )
    parser.add_argument(
        "--previous-dir",
        type=Path,
        default=Path("data/previous"),
        help="Directory containing previous CSVs (default: data/previous)",
    )
    parser.add_argument(
        "--table",
        type=str,
        action="append",
        dest="tables",
        help="Specific table(s) to process (can be repeated)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Ignore previous CSV and reload all rows",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a previously failed run",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path("logs"),
        help="Directory for log files (default: logs)",
    )

    args = parser.parse_args()

    # Resolve paths relative to project root
    project_root = Path(__file__).parent.parent.parent.parent
    current_dir = project_root / args.current_dir
    previous_dir = project_root / args.previous_dir
    log_dir = project_root / args.log_dir

    # Validate directories
    if not current_dir.exists():
        print(f"Error: Current data directory not found: {current_dir}")
        print("Please create it and place your CSV files there.")
        sys.exit(1)

    # Create previous dir if needed
    previous_dir.mkdir(parents=True, exist_ok=True)

    # Set up logging
    logger = setup_logging(log_dir)

    try:
        results = run_etl(
            current_dir=current_dir,
            previous_dir=previous_dir,
            tables=args.tables,
            dry_run=args.dry_run,
            full_refresh=args.full_refresh,
            resume=args.resume,
            logger=logger,
        )

        # Exit with error if any tables failed
        if any(r.rows_errored > 0 for r in results):
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("\n\nInterrupted by user. Run with --resume to continue.")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
