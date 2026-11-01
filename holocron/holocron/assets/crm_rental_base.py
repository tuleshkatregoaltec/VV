"""Publish the shared CRM ranking once, with its readiness marker in the same table.

The metadata revision is conservative (merges invalidate it). Source publishers must be
quiescent for this downstream build: individual dataset releases are not a global snapshot.
No schedule or upstream pipeline is enabled by registering this asset.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from crm_rental_sql import (
    AREA_IDENTITY_VALIDATION_SQL,
    BASE_ORDER_BY,
    BASE_TABLE,
    DEPENDENCY_STATE_SQL,
    RANKED_BASE_SELECT,
    PUBLICATION_POLICY,
    TRANSFORM_REVISION,
    dependency_revision,
    schema_revision,
    schema_sql,
)

from holocron.platform.clickhouse import ClickHouseClient, sql_string

BUILD_LIMITS = " SETTINGS max_threads=2, max_memory_usage=3000000000, max_execution_time=60"


def _rows(client: ClickHouseClient, sql: str) -> list[dict[str, Any]]:
    result = client.query(sql)
    return [dict(zip(result.column_names, row)) for row in result.result_rows]


def publish_rental_base(client: ClickHouseClient) -> dict[str, Any]:
    """Build privately, validate stable dependencies, then atomically publish rows + marker.

    Unique staging names prevent overlapping attempts from deleting each other's work. A
    ClickHouse DDL guard excludes overlapping publishers; crashes leave the old base intact.
    The guard is deliberately persistent on crash and must be removed only by an operator
    after confirming the interrupted run is no longer active.
    """
    guard = BASE_TABLE + "_publish_guard"
    # Atomic DDL acquisition uses the warehouse itself, so independent ingestion hosts agree.
    client.command(f"CREATE TABLE {guard} (holder UInt8) ENGINE=MergeTree ORDER BY tuple()")
    staging = BASE_TABLE + "_staging_" + uuid4().hex
    exchanged = False
    try:
        before = dependency_revision(_rows(client, DEPENDENCY_STATE_SQL))
        unsafe = _rows(client, AREA_IDENTITY_VALIDATION_SQL + BUILD_LIMITS)[0]["unsafe_identities"]
        if unsafe:
            raise ValueError(
                "Rental identity spans distinct exact display areas; retaining the previous base"
            )
        client.command(
            f"CREATE TABLE {staging} ENGINE=MergeTree ORDER BY {BASE_ORDER_BY} AS "
            + RANKED_BASE_SELECT
            + BUILD_LIMITS
        )
        summary = _rows(
            client,
            f"SELECT count() AS rows, uniqExact(property_identity_key) AS identities, "
            f"countIf(identity_rank != 1) AS invalid FROM {staging}" + BUILD_LIMITS,
        )[0]
        if not summary["rows"] or summary["rows"] != summary["identities"] or summary["invalid"]:
            raise ValueError("Refusing empty or invalid rental ranking publication")
        columns = _rows(client, schema_sql(staging))
        marker = {
            "kind": PUBLICATION_POLICY,
            "transform": TRANSFORM_REVISION,
            "source": before,
            "schema": schema_revision(columns),
            "rows": summary["rows"],
        }
        # Set ready only on the private, validated table. EXCHANGE moves this marker with rows.
        client.command(f"ALTER TABLE {staging} MODIFY COMMENT " + sql_string(json.dumps(marker)))
        if dependency_revision(_rows(client, DEPENDENCY_STATE_SQL)) != before:
            raise ValueError("Rental inputs changed during build; retaining the previous base")
        exists = _rows(
            client,
            f"SELECT count() AS count FROM system.tables "
            f"WHERE database=currentDatabase() AND name='{BASE_TABLE}'",
        )[0]["count"]
        if exists:
            client.command(f"EXCHANGE TABLES {BASE_TABLE} AND {staging}")
            exchanged = True
            # Staging now holds the previous validated artifact and its original marker.
            previous = BASE_TABLE + "_previous"
            client.command(f"DROP TABLE IF EXISTS {previous}")
            client.command(f"RENAME TABLE {staging} TO {previous}")
        else:
            client.command(f"RENAME TABLE {staging} TO {BASE_TABLE}")
            exchanged = True
        return marker
    finally:
        if not exchanged:
            client.command(f"DROP TABLE IF EXISTS {staging}")
        client.command(f"DROP TABLE {guard}")
