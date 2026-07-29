#!/usr/bin/env python3
"""Load DXB rental backfill shards into the ClickHouse CRM event table."""

from __future__ import annotations

import argparse
import gzip
import json
import logging
from datetime import date
from pathlib import Path

import clickhouse_connect

from holocron.sources.dxbi.rental_events import normalize_rental_row, source_account_from_path

logger = logging.getLogger("dxbi_rental_loader")

TABLE = "dxbi_rental_events"
INDEX_TABLE = "dxbi_rental_unit_candidates"
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS dxbi_rental_events (
    event_key String,
    unit_candidate_key String,
    unit_cohort_key String,
    location_name String DEFAULT '',
    building_name String DEFAULT '',
    project_name String DEFAULT '',
    area_name LowCardinality(String) DEFAULT '',
    property_type LowCardinality(String) DEFAULT '',
    bedrooms LowCardinality(String) DEFAULT '',
    size_sqft Float64 DEFAULT 0,
    annual_rent_aed UInt64 DEFAULT 0,
    purchase_price_aed UInt64 DEFAULT 0,
    lease_start Date,
    lease_end Date,
    contract_state LowCardinality(String) DEFAULT '',
    source_account LowCardinality(String) DEFAULT '',
    source_shard_date Date,
    source_file String DEFAULT '',
    scraped_at DateTime64(3, 'UTC'),
    loaded_at DateTime64(3, 'UTC') DEFAULT now64(3)
) ENGINE = ReplacingMergeTree(loaded_at)
ORDER BY (lease_start, unit_candidate_key, event_key)
"""
COLUMNS = [
    "event_key",
    "unit_candidate_key",
    "unit_cohort_key",
    "location_name",
    "building_name",
    "project_name",
    "area_name",
    "property_type",
    "bedrooms",
    "size_sqft",
    "annual_rent_aed",
    "purchase_price_aed",
    "lease_start",
    "lease_end",
    "contract_state",
    "source_account",
    "source_shard_date",
    "source_file",
    "scraped_at",
]
CREATE_INDEX_SQL = """
CREATE TABLE IF NOT EXISTS dxbi_rental_unit_candidates (
    unit_candidate_key String,
    event_key String,
    unit_cohort_key String,
    location_name String DEFAULT '',
    building_name String DEFAULT '',
    project_name String DEFAULT '',
    area_name LowCardinality(String) DEFAULT '',
    property_type LowCardinality(String) DEFAULT '',
    bedrooms LowCardinality(String) DEFAULT '',
    size_sqft Float64 DEFAULT 0,
    annual_rent_aed UInt64 DEFAULT 0,
    purchase_price_aed UInt64 DEFAULT 0,
    lease_start Date,
    lease_end Date,
    contract_state LowCardinality(String) DEFAULT '',
    observed_contracts UInt32 DEFAULT 0,
    last_scraped_at DateTime64(3, 'UTC'),
    loaded_at DateTime64(3, 'UTC') DEFAULT now64(3)
) ENGINE = ReplacingMergeTree(loaded_at)
ORDER BY unit_candidate_key
"""
REFRESH_INDEX_SQL = """
INSERT INTO dxbi_rental_unit_candidates (
    unit_candidate_key,
    event_key,
    unit_cohort_key,
    location_name,
    building_name,
    project_name,
    area_name,
    property_type,
    bedrooms,
    size_sqft,
    annual_rent_aed,
    purchase_price_aed,
    lease_start,
    lease_end,
    contract_state,
    observed_contracts,
    last_scraped_at,
    loaded_at
)
SELECT
    unit_candidate_key,
    argMax(event_key, tuple(lease_start, lease_end, scraped_at)),
    argMax(unit_cohort_key, tuple(lease_start, lease_end, scraped_at)),
    argMax(location_name, tuple(lease_start, lease_end, scraped_at)),
    argMax(building_name, tuple(lease_start, lease_end, scraped_at)),
    argMax(project_name, tuple(lease_start, lease_end, scraped_at)),
    argMax(area_name, tuple(lease_start, lease_end, scraped_at)),
    argMax(property_type, tuple(lease_start, lease_end, scraped_at)),
    argMax(bedrooms, tuple(lease_start, lease_end, scraped_at)),
    argMax(size_sqft, tuple(lease_start, lease_end, scraped_at)),
    argMax(annual_rent_aed, tuple(lease_start, lease_end, scraped_at)),
    argMax(purchase_price_aed, tuple(lease_start, lease_end, scraped_at)),
    argMax(lease_start, tuple(lease_start, lease_end, scraped_at)),
    argMax(lease_end, tuple(lease_start, lease_end, scraped_at)),
    argMax(contract_state, tuple(lease_start, lease_end, scraped_at)),
    toUInt32(count()),
    max(scraped_at),
    now64(3)
FROM dxbi_rental_events FINAL
WHERE lease_start >= toDate('2025-01-01')
GROUP BY unit_candidate_key
"""


def discover_files(inputs: list[Path]) -> list[Path]:
    files: set[Path] = set()
    for path in inputs:
        if path.is_file() and path.name.endswith((".jsonl", ".jsonl.gz")):
            files.add(path)
        elif path.is_dir():
            files.update(path.rglob("*.jsonl"))
            files.update(path.rglob("*.jsonl.gz"))
        else:
            raise FileNotFoundError(f"Input does not exist: {path}")
    return sorted(files)


def load_files(
    files: list[Path],
    *,
    client,
    min_start_date: date,
    batch_size: int,
) -> tuple[int, int, int]:
    loaded = skipped = errors = 0
    batch: list[list[object]] = []
    for index, path in enumerate(files, start=1):
        opener = gzip.open if path.name.endswith(".gz") else open
        try:
            with opener(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                        event = normalize_rental_row(
                            payload,
                            source_file=str(path),
                            source_account=source_account_from_path(path),
                        )
                    except (ValueError, TypeError, json.JSONDecodeError):
                        errors += 1
                        continue
                    if not event or event["lease_start"] < min_start_date:
                        skipped += 1
                        continue
                    batch.append([event[column] for column in COLUMNS])
                    if len(batch) >= batch_size:
                        client.insert(TABLE, batch, column_names=COLUMNS)
                        loaded += len(batch)
                        batch.clear()
        except (EOFError, OSError, UnicodeDecodeError) as exc:
            logger.warning("Skipping unreadable shard %s: %s", path, exc)
            errors += 1
        if index % 500 == 0:
            logger.info(
                "files=%s/%s loaded=%s skipped=%s errors=%s",
                index,
                len(files),
                loaded,
                skipped,
                errors,
            )
    if batch:
        client.insert(TABLE, batch, column_names=COLUMNS)
        loaded += len(batch)
    return loaded, skipped, errors


def refresh_candidate_index(client) -> None:
    """Publish one latest row per candidate so API requests avoid window scans."""
    logger.info("Refreshing %s", INDEX_TABLE)
    client.command(CREATE_INDEX_SQL)
    client.command(REFRESH_INDEX_SQL)
    client.command(f"OPTIMIZE TABLE {INDEX_TABLE} FINAL")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--database", default="vitevue")
    parser.add_argument("--username", default="default")
    parser.add_argument("--password", default="")
    parser.add_argument("--min-start-date", type=date.fromisoformat, default=date(2025, 1, 1))
    parser.add_argument("--batch-size", type=int, default=10_000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    files = discover_files(args.inputs)
    if not files:
        raise SystemExit("No JSONL rental shards found")
    logger.info("Discovered %s shards", len(files))
    client = clickhouse_connect.get_client(
        host=args.host,
        port=args.port,
        database=args.database,
        username=args.username,
        password=args.password,
    )
    client.command(CREATE_TABLE_SQL)
    loaded, skipped, errors = load_files(
        files,
        client=client,
        min_start_date=args.min_start_date,
        batch_size=args.batch_size,
    )
    refresh_candidate_index(client)
    logger.info("Complete loaded=%s skipped=%s errors=%s", loaded, skipped, errors)


if __name__ == "__main__":
    main()
