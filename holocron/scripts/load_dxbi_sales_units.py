#!/usr/bin/env python3
"""Load DXB sales rows and match the unit-bearing ones to rental candidates."""

from __future__ import annotations

import argparse
import gzip
import logging
import os
from collections import Counter
from datetime import date
from pathlib import Path

import clickhouse_connect

from holocron.sources.dxbi.agent_names import repair_agent_names
from holocron.sources.dxbi.sales_units import compact_payload, normalize_sales_row

logger = logging.getLogger("dxbi_sales_unit_loader")

SALES_TABLE = "dxbi_sales_unit_events"
MATCH_TABLE = "dxbi_rental_sale_matches"
CREATE_SALES_SQL = """
CREATE TABLE IF NOT EXISTS dxbi_sales_unit_events (
    sale_key String,
    transaction_date Date,
    unit_number String,
    building_name String DEFAULT '',
    building_key String DEFAULT '',
    project_name String DEFAULT '',
    area_name LowCardinality(String) DEFAULT '',
    area_key String DEFAULT '',
    address_normalization_version UInt8 DEFAULT 5,
    property_type LowCardinality(String) DEFAULT '',
    market_status LowCardinality(String) DEFAULT '',
    bedrooms LowCardinality(String) DEFAULT '',
    size_sqft Float64 DEFAULT 0,
    size_key UInt32 DEFAULT 0,
    built_up_area_sqft Nullable(Float64),
    balcony_sqft Nullable(Float64),
    sale_amount_aed UInt64 DEFAULT 0,
    price_per_sqft_aed Nullable(Float64),
    capital_gain_pct Nullable(Float64),
    ltv_pct Nullable(Float64),
    seller_type LowCardinality(String) DEFAULT '',
    seller_transaction_count Nullable(UInt16),
    agent_side LowCardinality(String) DEFAULT '',
    detail_url String DEFAULT '',
    source_file String DEFAULT '',
    loaded_at DateTime64(3, 'UTC') DEFAULT now64(3)
) ENGINE = ReplacingMergeTree(loaded_at)
ORDER BY (building_key, bedrooms, size_key, transaction_date, sale_key)
"""
CREATE_MATCH_SQL = """
CREATE TABLE IF NOT EXISTS dxbi_rental_sale_matches (
    unit_candidate_key String,
    unit_number String DEFAULT '',
    identity_sale_date Nullable(Date),
    identity_sale_price Nullable(UInt64),
    last_purchase_date Date,
    matched_sale_price UInt64 DEFAULT 0,
    latest_property_type LowCardinality(String) DEFAULT '',
    latest_price_per_sqft_aed Nullable(Float64),
    latest_capital_gain_pct Nullable(Float64),
    latest_ltv_pct Nullable(Float64),
    latest_seller_type LowCardinality(String) DEFAULT '',
    latest_seller_transaction_count Nullable(UInt16),
    latest_market_status LowCardinality(String) DEFAULT '',
    latest_detail_url String DEFAULT '',
    matching_sales UInt32 DEFAULT 0,
    matching_units UInt32 DEFAULT 0,
    match_status LowCardinality(String) DEFAULT '',
    loaded_at DateTime64(3, 'UTC') DEFAULT now64(3)
) ENGINE = ReplacingMergeTree(loaded_at)
ORDER BY unit_candidate_key
"""
REFRESH_MATCH_SQL = """
INSERT INTO dxbi_rental_sale_matches (
    unit_candidate_key,
    unit_number,
    identity_sale_date,
    identity_sale_price,
    last_purchase_date,
    matched_sale_price,
    latest_property_type,
    latest_price_per_sqft_aed,
    latest_capital_gain_pct,
    latest_ltv_pct,
    latest_seller_type,
    latest_seller_transaction_count,
    latest_market_status,
    latest_detail_url,
    matching_sales,
    matching_units,
    match_status,
    loaded_at
)
WITH candidates AS (
    SELECT
        unit_candidate_key,
        bedrooms,
        toUInt32(round(size_sqft)) AS size_key,
        purchase_price_aed,
        replaceRegexpAll(
            replaceAll(
                replaceAll(
                    replaceAll(
                        lowerUTF8(coalesce(nullIf(building_name, ''), project_name)),
                        'jumeriah',
                        'jumeirah'
                    ),
                    'residences',
                    'residence'
                ),
                'apartments',
                'apartment'
            ),
            '[^a-z0-9]+',
            ''
        ) AS building_key,
        replaceRegexpAll(
            replaceAll(lowerUTF8(area_name), 'jumeriah', 'jumeirah'),
            '[^a-z0-9]+',
            ''
        ) AS area_key
    FROM dxbi_rental_unit_candidates FINAL
    WHERE
        purchase_price_aed > 0
        AND coalesce(nullIf(building_name, ''), nullIf(project_name, '')) IS NOT NULL
        AND area_name != ''
),
matched AS (
    SELECT
        c.unit_candidate_key,
        c.building_key,
        c.area_key,
        s.unit_number,
        s.transaction_date,
        s.sale_amount_aed,
        s.sale_key
    FROM candidates AS c
    INNER JOIN dxbi_sales_unit_events AS s FINAL
        ON s.building_key = c.building_key
        AND s.area_key = c.area_key
        AND s.bedrooms = c.bedrooms
        AND s.size_key = c.size_key
    WHERE
        s.unit_number != ''
        AND s.sale_amount_aed BETWEEN c.purchase_price_aed * 0.985 AND c.purchase_price_aed * 1.015
),
grouped AS (
    SELECT
        unit_candidate_key,
        any(building_key) AS building_key,
        any(area_key) AS area_key,
        argMax(unit_number, tuple(transaction_date, sale_amount_aed, sale_key))
            AS identity_unit_number,
        max(transaction_date) AS identity_sale_date,
        argMax(sale_amount_aed, tuple(transaction_date, sale_amount_aed, sale_key))
            AS identity_sale_price,
        toUInt32(count()) AS identity_matching_sales,
        toUInt32(uniqExact(unit_number)) AS matching_units
    FROM matched
    GROUP BY unit_candidate_key
),
latest AS (
    SELECT
        g.unit_candidate_key,
        g.identity_unit_number AS unit_number,
        g.identity_sale_date,
        g.identity_sale_price,
        argMax(s.transaction_date, tuple(s.transaction_date, s.sale_key))
            AS last_purchase_date,
        argMax(s.sale_amount_aed, tuple(s.transaction_date, s.sale_key))
            AS matched_sale_price,
        argMax(s.property_type, tuple(s.transaction_date, s.sale_key))
            AS latest_property_type,
        tupleElement(
            argMax(tuple(s.price_per_sqft_aed), tuple(s.transaction_date, s.sale_key)),
            1
        )
            AS latest_price_per_sqft_aed,
        tupleElement(
            argMax(tuple(s.capital_gain_pct), tuple(s.transaction_date, s.sale_key)),
            1
        )
            AS latest_capital_gain_pct,
        tupleElement(
            argMax(tuple(s.ltv_pct), tuple(s.transaction_date, s.sale_key)),
            1
        )
            AS latest_ltv_pct,
        argMax(s.seller_type, tuple(s.transaction_date, s.sale_key))
            AS latest_seller_type,
        tupleElement(
            argMax(
                tuple(s.seller_transaction_count),
                tuple(s.transaction_date, s.sale_key)
            ),
            1
        )
            AS latest_seller_transaction_count,
        argMax(s.market_status, tuple(s.transaction_date, s.sale_key))
            AS latest_market_status,
        argMax(s.detail_url, tuple(s.transaction_date, s.sale_key))
            AS latest_detail_url,
        toUInt32(count()) AS matching_sales,
        g.matching_units
    FROM grouped AS g
    INNER JOIN dxbi_sales_unit_events AS s FINAL
        ON s.building_key = g.building_key
        AND s.area_key = g.area_key
        AND s.unit_number = g.identity_unit_number
    WHERE g.matching_units = 1
    GROUP BY
        g.unit_candidate_key,
        g.identity_unit_number,
        g.identity_sale_date,
        g.identity_sale_price,
        g.matching_units
)
SELECT
    unit_candidate_key,
    unit_number,
    identity_sale_date,
    identity_sale_price,
    last_purchase_date,
    matched_sale_price,
    latest_property_type,
    latest_price_per_sqft_aed,
    latest_capital_gain_pct,
    latest_ltv_pct,
    latest_seller_type,
    latest_seller_transaction_count,
    latest_market_status,
    latest_detail_url,
    matching_sales,
    matching_units,
    'unique' AS match_status,
    now64(3)
FROM latest
UNION ALL
SELECT
    unit_candidate_key,
    '',
    identity_sale_date,
    identity_sale_price,
    identity_sale_date,
    identity_sale_price,
    '',
    NULL,
    NULL,
    NULL,
    '',
    NULL,
    '',
    '',
    identity_matching_sales,
    matching_units,
    'ambiguous',
    now64(3)
FROM grouped
WHERE matching_units > 1
"""
# Older loads of a sale that a later load re-normalised. The table's sort key holds the building
# and size, so FINAL keeps both versions when a later load changes them (DXBI's own building name
# replacing one with an agent's name glued to it, for example), and anything that counts rows
# would count the sale twice.
SUPERSEDED_SALES_SQL = """
SELECT sale_key, arrayJoin(arrayPopFront(arrayReverseSort(groupUniqArray(loaded_at)))) AS older
FROM dxbi_sales_unit_events
GROUP BY sale_key
HAVING uniqExact(loaded_at) > 1
"""
SALES_ALTERS = [
    "ALTER TABLE dxbi_sales_unit_events ADD COLUMN IF NOT EXISTS address_normalization_version UInt8 DEFAULT 0 AFTER area_key",
    "ALTER TABLE dxbi_sales_unit_events ADD COLUMN IF NOT EXISTS market_status LowCardinality(String) DEFAULT '' AFTER property_type",
    "ALTER TABLE dxbi_sales_unit_events ADD COLUMN IF NOT EXISTS built_up_area_sqft Nullable(Float64) AFTER size_key",
    "ALTER TABLE dxbi_sales_unit_events ADD COLUMN IF NOT EXISTS balcony_sqft Nullable(Float64) AFTER built_up_area_sqft",
    "ALTER TABLE dxbi_sales_unit_events ADD COLUMN IF NOT EXISTS price_per_sqft_aed Nullable(Float64) AFTER sale_amount_aed",
    "ALTER TABLE dxbi_sales_unit_events ADD COLUMN IF NOT EXISTS capital_gain_pct Nullable(Float64) AFTER price_per_sqft_aed",
    "ALTER TABLE dxbi_sales_unit_events ADD COLUMN IF NOT EXISTS ltv_pct Nullable(Float64) AFTER capital_gain_pct",
    "ALTER TABLE dxbi_sales_unit_events ADD COLUMN IF NOT EXISTS seller_type LowCardinality(String) DEFAULT '' AFTER ltv_pct",
    "ALTER TABLE dxbi_sales_unit_events ADD COLUMN IF NOT EXISTS seller_transaction_count Nullable(UInt16) AFTER seller_type",
    "ALTER TABLE dxbi_sales_unit_events ADD COLUMN IF NOT EXISTS agent_side LowCardinality(String) DEFAULT '' AFTER seller_transaction_count",
]
MATCH_ALTERS = [
    "ALTER TABLE dxbi_rental_sale_matches ADD COLUMN IF NOT EXISTS identity_sale_date Nullable(Date) AFTER unit_number",
    "ALTER TABLE dxbi_rental_sale_matches ADD COLUMN IF NOT EXISTS identity_sale_price Nullable(UInt64) AFTER identity_sale_date",
    "ALTER TABLE dxbi_rental_sale_matches ADD COLUMN IF NOT EXISTS latest_property_type LowCardinality(String) DEFAULT '' AFTER matched_sale_price",
    "ALTER TABLE dxbi_rental_sale_matches ADD COLUMN IF NOT EXISTS latest_price_per_sqft_aed Nullable(Float64) AFTER matched_sale_price",
    "ALTER TABLE dxbi_rental_sale_matches ADD COLUMN IF NOT EXISTS latest_capital_gain_pct Nullable(Float64) AFTER latest_price_per_sqft_aed",
    "ALTER TABLE dxbi_rental_sale_matches ADD COLUMN IF NOT EXISTS latest_ltv_pct Nullable(Float64) AFTER latest_capital_gain_pct",
    "ALTER TABLE dxbi_rental_sale_matches ADD COLUMN IF NOT EXISTS latest_seller_type LowCardinality(String) DEFAULT '' AFTER latest_ltv_pct",
    "ALTER TABLE dxbi_rental_sale_matches ADD COLUMN IF NOT EXISTS latest_seller_transaction_count Nullable(UInt16) AFTER latest_seller_type",
    "ALTER TABLE dxbi_rental_sale_matches ADD COLUMN IF NOT EXISTS latest_market_status LowCardinality(String) DEFAULT '' AFTER latest_seller_transaction_count",
    "ALTER TABLE dxbi_rental_sale_matches ADD COLUMN IF NOT EXISTS latest_detail_url String DEFAULT '' AFTER latest_market_status",
]
COLUMNS = [
    "sale_key",
    "transaction_date",
    "unit_number",
    "building_name",
    "building_key",
    "project_name",
    "area_name",
    "area_key",
    "address_normalization_version",
    "property_type",
    "market_status",
    "bedrooms",
    "size_sqft",
    "size_key",
    "built_up_area_sqft",
    "balcony_sqft",
    "sale_amount_aed",
    "price_per_sqft_aed",
    "capital_gain_pct",
    "ltv_pct",
    "seller_type",
    "seller_transaction_count",
    "agent_side",
    "detail_url",
    "source_file",
]


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


def load_files(files: list[Path], *, client, batch_size: int) -> dict[str, int]:
    """Load sales rows; the counts say how many were loaded, without a unit, skipped or bad.

    A sale DXBI lists without its unit or link is keyed by its terms. Two such sales with the
    same date, building, price and size in one search result are two sales, so the second and
    later ones get their position as a suffix. The scraper splits a day by price, so one sale can
    appear in two neighbouring searches; counting within a search keeps it one sale.
    """
    loaded = skipped = errors = without_unit = 0
    batch: list[list[object]] = []
    for index, path in enumerate(files, start=1):
        opener = gzip.open if path.name.endswith(".gz") else open
        seen_in_search: Counter[tuple[object, ...]] = Counter()
        try:
            with opener(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        payload = compact_payload(line)
                        event = normalize_sales_row(payload, source_file=path.name)
                    except (TypeError, ValueError):
                        errors += 1
                        continue
                    if not event:
                        skipped += 1
                        continue
                    if not event["unit_number"]:
                        without_unit += 1
                        if not event["detail_url"]:
                            search = (
                                payload.get("bucket_date"),
                                payload.get("bucket_min_price"),
                                payload.get("bucket_max_price"),
                                event["sale_key"],
                            )
                            seen_in_search[search] += 1
                            if seen_in_search[search] > 1:
                                event["sale_key"] += f"-{seen_in_search[search]}"
                    batch.append([event[column] for column in COLUMNS])
                    if len(batch) >= batch_size:
                        client.insert(SALES_TABLE, batch, column_names=COLUMNS)
                        loaded += len(batch)
                        batch.clear()
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Skipping unreadable file %s: %s", path, exc)
            errors += 1
        if index % 100 == 0:
            logger.info(
                "files=%s/%s loaded=%s skipped=%s errors=%s",
                index,
                len(files),
                loaded,
                skipped,
                errors,
            )
    if batch:
        client.insert(SALES_TABLE, batch, column_names=COLUMNS)
        loaded += len(batch)
    return {"loaded": loaded, "skipped": skipped, "errors": errors, "without_unit": without_unit}


def load_clock(client) -> str:
    """The server's time to the millisecond, as text so no client time zone touches it."""
    return str(client.query("SELECT toString(now64(3, 'UTC'))").result_rows[0][0])


def replace_window(client, *, loaded_since: str, first: date, last: date) -> int:
    """Delete rows loaded before ``loaded_since`` dated ``first`` to ``last`` (inclusive).

    For a complete re-scrape of those dates: DXBI's latest listing replaces what was loaded for
    them before. That includes rows no key ties to the new ones (a CSV-export row without a
    unit, or a sale without a DXBI link whose building or unit DXBI has since corrected), and
    sales DXBI has since moved to another day: a day DXBI now lists nothing on is emptied too
    (2026-09-13: 29 Sunday sales DXBI now dates Monday). Return how many rows were removed.
    """
    older = (
        "loaded_at < toDateTime64({loaded_since:String}, 3, 'UTC') "
        "AND transaction_date BETWEEN {first:Date} AND {last:Date}"
    )
    parameters = {"loaded_since": loaded_since, "first": first, "last": last}
    stale = int(
        client.query(
            f"SELECT count() FROM {SALES_TABLE} WHERE {older}", parameters=parameters
        ).result_rows[0][0]
    )
    if stale:
        client.command(f"DELETE FROM {SALES_TABLE} WHERE {older}", parameters=parameters)
    return stale


def remove_superseded_sales(client) -> int:
    """Delete the older loads of re-normalised sales; return how many rows were removed."""
    stale = int(client.query(f"SELECT count() FROM ({SUPERSEDED_SALES_SQL})").result_rows[0][0])
    if stale:
        client.command(
            f"DELETE FROM {SALES_TABLE} WHERE (sale_key, loaded_at) IN ({SUPERSEDED_SALES_SQL})"
        )
    return stale


def refresh_matches(
    client,
    *,
    candidate_table: str = "dxbi_rental_unit_candidates",
    match_table: str = MATCH_TABLE,
) -> None:
    if candidate_table not in {"dxbi_rental_unit_candidates", "dxbi_rental_unit_candidates_v2"}:
        raise ValueError("Unsupported rental candidate table")
    if match_table not in {MATCH_TABLE, MATCH_TABLE + "_v2"}:
        raise ValueError("Unsupported rental match table")
    logger.info("Refreshing %s", match_table)
    client.command(CREATE_MATCH_SQL.replace(MATCH_TABLE, match_table))
    for statement in MATCH_ALTERS:
        client.command(statement.replace(MATCH_TABLE, match_table))
    has_unit = bool(
        client.query(
            "SELECT count() FROM system.columns WHERE database=currentDatabase() "
            "AND table={table:String} AND name='unit_number'",
            parameters={"table": candidate_table},
        ).result_rows[0][0]
    )
    sql = REFRESH_MATCH_SQL.replace("dxbi_rental_unit_candidates", candidate_table)
    if has_unit:
        sql = sql.replace(
            "        bedrooms,\n        toUInt32(round(size_sqft))",
            "        bedrooms,\n        unit_number AS source_unit_number,\n"
            "        toUInt32(round(size_sqft))",
        ).replace(
            "s.sale_amount_aed BETWEEN c.purchase_price_aed * 0.985 AND c.purchase_price_aed * 1.015",
            "s.sale_amount_aed BETWEEN c.purchase_price_aed * 0.985 AND c.purchase_price_aed * 1.015 "
            "AND (c.source_unit_number = '' OR "
            "upperUTF8(trimBoth(s.unit_number)) = upperUTF8(trimBoth(c.source_unit_number)))",
        )
    staging = match_table + "_refresh"
    client.command(f"DROP TABLE IF EXISTS {staging}")
    client.command(f"CREATE TABLE {staging} AS {match_table}")
    client.command(
        sql.replace(f"INSERT INTO {MATCH_TABLE}", f"INSERT INTO {staging}")
        + " SETTINGS max_threads=2, max_bytes_before_external_group_by=100000000, "
        "max_memory_usage=3000000000"
    )
    client.command(f"EXCHANGE TABLES {match_table} AND {staging}")
    client.command(f"DROP TABLE {staging}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="*", type=Path)
    parser.add_argument("--host", default=os.getenv("CLICKHOUSE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CLICKHOUSE_PORT", "8123")))
    parser.add_argument("--database", default=os.getenv("CLICKHOUSE_DATABASE", "vitevue"))
    parser.add_argument("--username", default=os.getenv("CLICKHOUSE_USER", "default"))
    parser.add_argument("--password", default=os.getenv("CLICKHOUSE_PASSWORD", ""))
    parser.add_argument("--batch-size", type=int, default=10_000)
    parser.add_argument("--refresh-matches-only", action="store_true")
    parser.add_argument(
        "--replace-window",
        nargs=2,
        type=date.fromisoformat,
        metavar=("FIRST", "LAST"),
        help="The inputs are a complete scrape of these dates: replace earlier rows on them.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    client = clickhouse_connect.get_client(
        host=args.host,
        port=args.port,
        database=args.database,
        username=args.username,
        password=args.password,
    )
    client.command(CREATE_SALES_SQL)
    for statement in SALES_ALTERS:
        client.command(statement)
    if not args.refresh_matches_only:
        files = discover_files(args.inputs)
        if not files:
            raise SystemExit("No DXB sales JSONL files found")
        logger.info("Discovered %s sales files", len(files))
        load_started = load_clock(client)
        totals = load_files(files, client=client, batch_size=args.batch_size)
        if not totals["errors"]:
            if args.replace_window and not totals["loaded"]:
                raise SystemExit("--replace-window with nothing loaded would empty the window")
            if args.replace_window:
                first, last = args.replace_window
                totals["replaced"] = replace_window(
                    client, loaded_since=load_started, first=first, last=last
                )
            client.command(f"OPTIMIZE TABLE {SALES_TABLE} FINAL")
            totals["superseded"] = remove_superseded_sales(client)
            # An agent's name glued to a building must never reach a table, page or export.
            totals.update(repair_agent_names(client))
        logger.info(
            "Sales load complete %s", " ".join(f"{name}={value}" for name, value in totals.items())
        )
        if totals["errors"]:
            raise SystemExit("Sales import had errors; completed-run markers must not advance")
    refresh_matches(client)


if __name__ == "__main__":
    main()
