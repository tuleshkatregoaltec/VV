"""Hash computation for ETL change detection."""

import clickhouse_connect
from typing import Dict, List, Any


def compute_row_hash(row: Dict[str, Any], critical_columns: List[str]) -> int:
    """
    Compute sipHash64 of critical columns for change detection.

    Critical columns = columns that matter for business logic.
    Excludes: etl_inserted_at, etl_run_id (metadata only).

    Args:
        row: Dictionary of column values
        critical_columns: List of column names to include in hash

    Returns:
        64-bit hash value (UInt64)
    """
    parts = []
    for col in sorted(critical_columns):
        val = row.get(col, "")
        if val is None:
            val = ""
        parts.append(f"{col}={val}")

    content = "|".join(parts)
    return clickhouse_connect.common.sip_hash(content.encode("utf-8"))
