#!/usr/bin/env python3
"""Check owner valuation accuracy against real recent sales (read-only).

Samples residential sales from recent months whose unit sold before. Each sale is valued as
an owner would be, from comparables before that sale's month and with the earlier sale as the
purchase, then compared with the price actually achieved.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections import defaultdict
from datetime import date, timedelta

from app.clickhouse.client import close_clickhouse, query
from app.crm.valuation import CompStats, ValuationSubject, estimate
from app.crm.valuation_queries import fetch_area_psf_by_quarter, fetch_comparable_stats


def _quarter(day: date) -> date:
    return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)


async def _sample(months: int, size: int) -> list[dict]:
    return await query(
        """
        WITH unit_sales AS (
            SELECT building_key, area_key, replaceRegexpAll(lowerUTF8(unit_number), '\\s+', '') AS unit_key,
                   transaction_date, sale_amount_aed, property_type, bedrooms, size_sqft
            FROM dxbi_sales_unit_events FINAL
            WHERE property_type IN ('Apartment', 'Villa', 'Townhouse') AND unit_number != ''
              AND building_key != '' AND sale_amount_aed > 0
        )
        SELECT s.*, p.purchase_date, p.purchase_price
        FROM unit_sales AS s
        INNER JOIN (
            SELECT building_key, unit_key,
                   max(transaction_date) AS purchase_date,
                   argMax(sale_amount_aed, transaction_date) AS purchase_price
            FROM unit_sales
            WHERE transaction_date < toStartOfMonth(today()) - toIntervalMonth({months:UInt8})
            GROUP BY building_key, unit_key
        ) AS p USING (building_key, unit_key)
        WHERE s.transaction_date >= toStartOfMonth(today()) - toIntervalMonth({months:UInt8})
          AND s.transaction_date < toStartOfMonth(today())
        ORDER BY cityHash64(s.building_key, s.unit_key, s.transaction_date)
        LIMIT {size:UInt32}
        """,
        {"months": months, "size": size},
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=2000)
    parser.add_argument("--months", type=int, default=6)
    args = parser.parse_args()
    try:
        sales = await _sample(args.months, args.sample)
        by_month: dict[date, list[dict]] = defaultdict(list)
        for sale in sales:
            by_month[sale["transaction_date"].replace(day=1)].append(sale)
        quarters = await fetch_area_psf_by_quarter(
            sorted({s["area_key"] for s in sales}), ["Apartment", "Villa", "Townhouse"]
        )
        then = {
            (r["area_key"], r["property_type"], r["quarter"]): CompStats(
                int(r["count"]), float(r["p50"]), float(r["p50"]), float(r["p50"])
            )
            for r in quarters
        }
        errors: dict[str, list[float]] = defaultdict(list)
        for month, rows in sorted(by_month.items()):
            # Comparables strictly before the month of the sale: the sale cannot value itself.
            stat_rows = await fetch_comparable_stats(
                sorted({r["building_key"] for r in rows}),
                sorted({r["area_key"] for r in rows}),
                month - timedelta(days=365),
                month,
            )
            stats = {
                (
                    r["level"],
                    r["building_key"],
                    r["area_key"],
                    r["property_type"],
                    r["bedrooms"],
                ): CompStats(int(r["count"]), *(float(v) for v in r["psf"]))
                for r in stat_rows
            }
            for r in rows:
                b, a, t, beds = r["building_key"], r["area_key"], r["property_type"], r["bedrooms"]
                comps = {
                    "building_type_beds": stats.get(("building_type_beds", b, "", t, beds))
                    if beds
                    else None,
                    "building_type": stats.get(("building_type", b, "", t, "")),
                    "area_type_beds": stats.get(("area_type_beds", "", a, t, beds))
                    if beds
                    else None,
                    "area_type": stats.get(("area_type", "", a, t, "")),
                }
                subject = ValuationSubject(
                    claim_id=0,
                    purchase_price_aed=int(r["purchase_price"]),
                    purchase_date=r["purchase_date"],
                    property_type=t,
                    bedrooms=beds,
                    size_sqft=float(r["size_sqft"]) or None,
                    building_key=b,
                    area_key=a,
                )
                result = estimate(
                    subject,
                    comps,
                    comps["area_type"],
                    then.get((a, t, _quarter(r["purchase_date"]))),
                    month,
                )
                if result is None:
                    errors["not_valued"].append(0)
                    continue
                error = abs(result.estimated_value_aed / int(r["sale_amount_aed"]) - 1)
                errors[result.detail["level"]].append(error)
                errors[f"confidence_{result.confidence}"].append(error)
                errors["all"].append(error)

        def report(values: list[float]) -> dict:
            return {
                "sales": len(values),
                "median_error_pct": round(statistics.median(values) * 100, 1),
                "within_10_pct": round(sum(v <= 0.10 for v in values) / len(values) * 100, 1),
                "within_20_pct": round(sum(v <= 0.20 for v in values) / len(values) * 100, 1),
            }

        print(
            json.dumps(
                {
                    "sampled_sales": len(sales),
                    "not_valued": len(errors.pop("not_valued", [])),
                    **{k: report(v) for k, v in sorted(errors.items()) if v},
                },
                indent=2,
            )
        )
    finally:
        await close_clickhouse()


if __name__ == "__main__":
    asyncio.run(main())
