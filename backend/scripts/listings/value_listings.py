#!/usr/bin/env python3
"""Value ready residential sale listings from DLD sales into `listing_valuations` (11 Nov 2026).

--dry-run   value and print counts; create and write nothing
--limit N   value only the first N listings (for a quick check)
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import date

from app.clickhouse.client import close_clickhouse, get_client, query
from app.listings.queries import LISTINGS_TABLE, PRICE_VALUE_EXPR, SIZE_VALUE_EXPR
from app.listings.valuation import READY_STATUSES, RESIDENTIAL_SALE_CATEGORY
from app.listings.valuation_service import COLUMNS, CREATE_TABLE, TABLE, value_listing_rows


async def _rows(limit: int | None) -> list[dict]:
    return await query(
        f"""
        SELECT listing_id, category_id,
               JSONExtract(listing_location_names_json, 'Array(String)') AS location_names,
               JSON_VALUE(raw_property_json, '$.property_type') AS property_type,
               JSON_VALUE(raw_property_json, '$.completion_status') AS completion_status,
               bedrooms,
               {PRICE_VALUE_EXPR} AS price_aed,
               {SIZE_VALUE_EXPR} AS size_sqft
        FROM {LISTINGS_TABLE}
        WHERE category_id = {{category:UInt16}} AND is_available = 1
          AND JSON_VALUE(raw_property_json, '$.completion_status') IN {{ready:Array(String)}}
        ORDER BY listing_id
        {"LIMIT {limit:UInt32}" if limit else ""}
        """,
        {
            "category": RESIDENTIAL_SALE_CATEGORY,
            "ready": sorted(READY_STATUSES),
            "limit": limit or 0,
        },
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    try:
        rows = await _rows(args.limit)
        results = await value_listing_rows(rows, date.today())
        valued = sum(1 for r in results if r["estimate_aed"])
        print(f"{len(rows)} ready sale listings read, {len(results)} in scope, {valued} valued")
        print("position:", dict(Counter(r["market_position"] for r in results)))
        print("confidence:", dict(Counter(r["confidence"] for r in results)))
        print("level:", dict(Counter(r["level"] for r in results)))
        if args.dry_run or not results:
            return
        client = await get_client()
        await client.command(CREATE_TABLE)
        # A full rewrite each run retires listings that dropped out since the last one.
        await client.command(f"TRUNCATE TABLE {TABLE}")
        await client.insert(
            TABLE, [[r[c] for c in COLUMNS] for r in results], column_names=list(COLUMNS)
        )
        print(f"wrote {len(results)} rows to {TABLE}")
    finally:
        await close_clickhouse()


if __name__ == "__main__":
    asyncio.run(main())
