"""Smart diff logic for detecting changed rows."""

import csv
import logging
from pathlib import Path
from typing import Dict, Set, List, Any, Tuple
import clickhouse_connect

from .config import TableConfig
from .hasher import compute_row_hash

logger = logging.getLogger(__name__)


def fetch_current_state(
    client: clickhouse_connect.driver.Client,
    table_name: str,
    primary_key_cols: List[str],
) -> Dict[Tuple, int]:
    """
    Fetch current state from ClickHouse for smart diff.

    Returns:
        Dict mapping primary key tuple to row_hash
        Example: {("TXN123",): 12345678, ("TXN124",): 87654321}
    """
    pk_cols_str = ", ".join(primary_key_cols)

    sql = f"""
        SELECT {pk_cols_str}, row_hash
        FROM {table_name}
        FINAL
        WHERE is_deleted = 0
    """

    logger.info(f"Fetching current state from {table_name}...")

    result = client.query(sql)

    state = {}
    for row in result.result_rows:
        # Last column is row_hash, everything before is primary key
        pk_values = row[:-1]
        row_hash = row[-1]

        # Handle composite primary keys
        if len(pk_values) == 1:
            pk = pk_values[0]
        else:
            pk = tuple(pk_values)

        state[pk] = row_hash

    logger.info(f"Fetched {len(state):,} rows from {table_name}")

    return state


def stream_csv_and_diff(
    csv_file: Path,
    table_config: TableConfig,
    current_state: Dict[Tuple, int],
    run_id: str,
) -> Tuple[List[Dict[str, Any]], Set[Tuple]]:
    """
    Stream CSV, compute hashes, and detect changes.

    Args:
        csv_file: Path to CSV file
        table_config: Table configuration
        current_state: Current state from ClickHouse
        run_id: ETL run UUID

    Returns:
        Tuple of (changed_rows, seen_primary_keys)
    """
    changed_rows = []
    seen_pks = set()

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        # Apply column mappings
        fieldnames = reader.fieldnames or []
        mapped_fieldnames = [
            table_config.column_mappings.get(col, col) for col in fieldnames
        ]

        for row_num, row in enumerate(reader, start=2):
            # Apply column mappings to row
            mapped_row = {}
            for orig_col, mapped_col in zip(fieldnames, mapped_fieldnames):
                mapped_row[mapped_col] = row[orig_col]

            # Extract primary key
            pk_values = tuple(mapped_row[col] for col in table_config.primary_key_cols)
            if len(pk_values) == 1:
                pk = pk_values[0]
            else:
                pk = pk_values

            seen_pks.add(pk)

            # Compute hash
            row_hash = compute_row_hash(mapped_row, table_config.critical_cols)

            # Check if changed
            if pk not in current_state:
                # New row
                changed_rows.append(
                    {
                        **mapped_row,
                        "row_hash": row_hash,
                        "etl_run_id": run_id,
                        "is_deleted": 0,
                    }
                )
            elif current_state[pk] != row_hash:
                # Changed row
                changed_rows.append(
                    {
                        **mapped_row,
                        "row_hash": row_hash,
                        "etl_run_id": run_id,
                        "is_deleted": 0,
                    }
                )

            if row_num % 100000 == 0:
                logger.info(
                    f"Processed {row_num:,} rows, {len(changed_rows):,} changes detected"
                )

    logger.info(
        f"CSV diff complete: {len(changed_rows):,} changed/new rows, "
        f"{len(seen_pks):,} total rows in CSV"
    )

    return changed_rows, seen_pks


def detect_deletions(
    current_state: Dict[Tuple, int],
    seen_pks: Set[Tuple],
    table_config: TableConfig,
    run_id: str,
) -> List[Dict[str, Any]]:
    """
    Detect rows that exist in DB but not in CSV (deletions).

    Args:
        current_state: Current state from ClickHouse
        seen_pks: Primary keys seen in CSV
        table_config: Table configuration
        run_id: ETL run UUID

    Returns:
        List of deletion marker rows
    """
    missing_pks = set(current_state.keys()) - seen_pks

    if not missing_pks:
        logger.info("No deletions detected")
        return []

    logger.info(f"Detected {len(missing_pks):,} deletions")

    deleted_rows = []
    for pk in missing_pks:
        # Build deletion marker row
        row = {"etl_run_id": run_id, "is_deleted": 1, "row_hash": 0}

        # Add primary key values
        if isinstance(pk, tuple):
            for col, val in zip(table_config.primary_key_cols, pk):
                row[col] = val
        else:
            row[table_config.primary_key_cols[0]] = pk

        deleted_rows.append(row)

    return deleted_rows
