#!/usr/bin/env python3
"""Pick 10 valued sale listings for Kian to check by hand (read-only, 11 Nov 2026).

4 below value, 3 near and 3 above; at least 4 villas or townhouses; spread over areas. Each
comes with its estimate, range, confidence and the DLD sales behind it. Writes sheet.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from pathlib import Path

from app.clickhouse.client import close_clickhouse, query
from app.listings.service import get_listing_from_clickhouse

# (market position, villa?, how many)
QUOTA = [
    ("below_market", True, 2),
    ("below_market", False, 2),
    ("near_market", True, 1),
    ("near_market", False, 2),
    ("above_market", True, 1),
    ("above_market", False, 2),
]


async def _candidates() -> list[dict]:
    return await query(
        """
        SELECT v.listing_id AS listing_id, v.market_position AS market_position,
               v.value_gap_pct AS gap, v.basis AS basis,
               JSONExtract(l.listing_location_names_json, 'Array(String)')[2] AS area
        FROM listing_valuations AS v FINAL
        INNER JOIN pf_listings_bronze AS l ON l.listing_id = v.listing_id
        WHERE v.market_position IN ('below_market', 'near_market', 'above_market')
          AND v.value_gap_pct BETWEEN -0.25 AND 0.25
        ORDER BY v.listing_id
        LIMIT 1 BY v.building_key, v.bedrooms, round(log(v.size_sqft) * 100), v.asking_aed
        """,
        {},
    )


def pick(rows: list[dict], seed: int) -> list[dict]:
    rng = random.Random(seed)
    rows = rows[:]
    rng.shuffle(rows)
    chosen: list[dict] = []
    for position, villa, count in QUOTA:
        pool = [
            r
            for r in rows
            if r["market_position"] == position and (r["basis"] == "bedroom_price") == villa
        ]
        # Prefer an area not used yet, so the 10 cover several communities.
        pool.sort(key=lambda r: r["area"] in {c["area"] for c in chosen})
        chosen.extend(pool[:count])
    return chosen


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        picked = pick(await _candidates(), args.seed)
        sheet = []
        for row in picked:
            listing = await get_listing_from_clickhouse(row["listing_id"])
            sheet.append(
                {
                    "listing_id": listing.listing_id,
                    "reference": listing.reference,
                    "url": listing.share_url,
                    "area": listing.area_name,
                    "project": listing.subcommunity_name,
                    "building": listing.tower_name,
                    "property_type": listing.property_type,
                    "bedrooms": listing.bedrooms,
                    "size_sqft": listing.size_value,
                    "asking_aed": listing.price_value,
                    "listed": str(listing.listed_date.date()) if listing.listed_date else None,
                    "estimate_aed": listing.estimated_value_aed,
                    "low_aed": listing.estimated_value_low_aed,
                    "high_aed": listing.estimated_value_high_aed,
                    "confidence": listing.valuation_confidence,
                    "basis": row["basis"],
                    "market_position": listing.market_position,
                    "gap": listing.value_gap_pct,
                    "comparables": [
                        c.model_dump(mode="json") for c in listing.valuation_comparables
                    ],
                }
            )
        Path(args.out).write_text(json.dumps(sheet, indent=2))
        print(f"{len(sheet)} listings written to {args.out}")
        for s in sheet:
            name = s["building"] or s["project"]
            print(
                f"{s['market_position']:13} {s['area']:24} {name!s:28} {s['bedrooms']!s:6} "
                f"ask {s['asking_aed']:>11,} est {s['estimate_aed']:>11,.0f} gap {s['gap']:+.1%} "
                f"comps {len(s['comparables'])}"
            )
    finally:
        await close_clickhouse()


if __name__ == "__main__":
    asyncio.run(main())
