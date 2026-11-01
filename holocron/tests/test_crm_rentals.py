"""Publication failures must leave the previous rows and readiness marker together."""

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from crm_rental_sql import (
    AREA_IDENTITY_VALIDATION_SQL,
    BASE_TABLE,
    DEPENDENCIES,
    PUBLICATION_POLICY,
    VIEW_DEPENDENCIES,
)
from dagster import AssetKey

from holocron.assets.crm_rental_base import publish_rental_base
from holocron.assets.crm_rentals import crm_rental_ranked_base_asset
from holocron.orchestration.definitions import defs
from holocron.platform.clickhouse import ClickHouseClient


class FakeClient:
    def __init__(self, *, failure=None, rows=2):
        self.commands = []
        self.queries = []
        self.failure = failure
        self.row_count = rows
        self.source_reads = 0
        self.published = "old-rows-and-marker"
        self.staged_marker = None

    def command(self, sql):
        self.commands.append(sql)
        if self.failure == "overlap" and "CREATE TABLE" in sql and "publish_guard" in sql:
            raise RuntimeError("guard already exists")
        if self.failure == "build" and sql.startswith("CREATE TABLE") and "_staging_" in sql:
            raise RuntimeError("build failed")
        if "MODIFY COMMENT" in sql:
            self.staged_marker = sql.split("MODIFY COMMENT ", 1)[1]
        if sql.startswith("EXCHANGE"):
            self.published = self.staged_marker

    def query(self, sql):
        self.queries.append(sql)
        if "AS unsafe_identities" in sql:
            return SimpleNamespace(
                column_names=["unsafe_identities"],
                result_rows=[(1 if self.failure == "area_collision" else 0,)],
            )
        if "system.parts" in sql:
            self.source_reads += 1
            rows = [
                (
                    name,
                    "View" if name in VIEW_DEPENDENCIES else "ReplacingMergeTree",
                    name,
                    name,
                    "[]",
                    0,
                )
                for name in DEPENDENCIES
            ]
            if self.failure == "changed" and self.source_reads > 1:
                rows[0] = (*rows[0][:-2], "changed-part", 0)
            return SimpleNamespace(
                column_names=["name", "engine", "uuid", "ddl", "parts", "pending"],
                result_rows=rows,
            )
        if "system.columns" in sql:
            return SimpleNamespace(column_names=["name", "type"], result_rows=[("id", "String")])
        if "uniqExact" in sql:
            return SimpleNamespace(
                column_names=["rows", "identities", "invalid"],
                result_rows=[(self.row_count, self.row_count, 0)],
            )
        assert "system.tables" in sql
        return SimpleNamespace(column_names=["count"], result_rows=[(1,)])


def _publish(client: FakeClient):
    return publish_rental_base(cast(ClickHouseClient, cast(Any, client)))


def test_validated_marker_travels_atomically_with_rows():
    client = FakeClient()
    marker = _publish(client)
    commands = client.commands
    ready = next(i for i, sql in enumerate(commands) if "MODIFY COMMENT" in sql)
    exchange = next(i for i, sql in enumerate(commands) if sql.startswith("EXCHANGE"))
    assert ready < exchange
    assert client.published == client.staged_marker
    assert marker["rows"] == 2
    assert marker["kind"] == PUBLICATION_POLICY
    assert any(
        sql.startswith("RENAME") and sql.endswith(BASE_TABLE + "_previous") for sql in commands
    )
    assert commands[-1] == f"DROP TABLE {BASE_TABLE}_publish_guard"
    # Published metadata contains revision hashes, never source rows or user/tenant fields.
    assert set(marker) == {"kind", "transform", "source", "schema", "rows"}
    json.dumps(marker)


@pytest.mark.parametrize("failure, rows", [("build", 2), ("changed", 2), (None, 0)])
def test_failed_or_empty_build_never_changes_old_rows_or_revision(failure, rows):
    client = FakeClient(failure=failure, rows=rows)
    with pytest.raises((RuntimeError, ValueError)):
        _publish(client)
    assert client.published == "old-rows-and-marker"
    assert not any(sql.startswith("EXCHANGE") for sql in client.commands)
    assert any(
        sql.startswith("DROP TABLE IF EXISTS") and "_staging_" in sql for sql in client.commands
    )
    assert client.commands[-1] == f"DROP TABLE {BASE_TABLE}_publish_guard"


def test_overlapping_publisher_does_not_remove_the_other_runs_guard():
    client = FakeClient(failure="overlap")
    with pytest.raises(RuntimeError, match="already exists"):
        _publish(client)
    assert len(client.commands) == 1
    assert client.source_reads == 0


def test_asset_is_registered_downstream_without_enabling_source_jobs():
    assert crm_rental_ranked_base_asset.key == AssetKey(BASE_TABLE)
    assert crm_rental_ranked_base_asset.asset_deps[AssetKey(BASE_TABLE)] == {
        AssetKey(name)
        for name in (
            "dxbi_evidence_bronze",
            "geo_source_signatures",
            "geo_entity_links",
            "geo_location_nodes",
            "geo_location_closure",
        )
    }
    assert crm_rental_ranked_base_asset in (defs.assets or [])
    assert all(BASE_TABLE not in schedule.name for schedule in defs.schedules or [])


def test_distinct_exact_areas_are_validated_before_ranking_and_never_published():
    client = FakeClient(failure="area_collision")
    with pytest.raises(ValueError, match="distinct exact display areas"):
        _publish(client)
    assert client.published == "old-rows-and-marker"
    assert client.staged_marker is None
    assert not any("_staging_" in sql and sql.startswith("CREATE TABLE") for sql in client.commands)
    assert not any(sql.startswith("EXCHANGE") for sql in client.commands)
    assert any(
        "_staging_" in sql and sql.startswith("DROP TABLE IF EXISTS") for sql in client.commands
    )
    assert client.commands[-1] == f"DROP TABLE {BASE_TABLE}_publish_guard"
    validation = next(sql for sql in client.queries if "AS unsafe_identities" in sql)
    assert validation.startswith(AREA_IDENTITY_VALIDATION_SQL)
    assert "FROM identified_unit" in validation
    assert "ranked_unit AS (" not in validation
    assert "identity_rank = 1" not in validation
    assert validation.endswith(
        " SETTINGS max_threads=2, max_memory_usage=3000000000, max_execution_time=60"
    )
