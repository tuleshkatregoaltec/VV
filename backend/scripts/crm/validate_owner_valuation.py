#!/usr/bin/env python3
"""Validate stored owner valuations on a sample (read-only; nothing is written to any database).

sample     pick a stratified sample of valued owners and list the closest exact DLD sales
summarise  combine comparables.json with a hand-collected listings.csv into the verdicts
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.clickhouse.client import close_clickhouse, query
from app.crm import owner_repository
from app.crm.owner_repository import CURRENT_OWNER_STATUSES
from app.crm.valuation_service import _registry_rows
from app.crm.valuation_validation import (
    closest_sales,
    gap_pct,
    listing_stats,
    pick_sample,
    summarise,
)
from app.postgres import close_postgres, get_postgres_engine

# Areas Kian has seen in the before/after document; a fifth is the next largest owner area.
FOCUS_AREAS = ("town square", "palm jumeirah", "arjan", "damac hills 2")


def _area(name: str | None) -> str:
    return " ".join(str(name or "").lower().split())


def _focus(name: str | None) -> str | None:
    area = _area(name)
    return next((f for f in FOCUS_AREAS if f in area), None)


async def _building_sales(row: dict, since: date) -> list[dict]:
    return await query(
        """
        SELECT replaceRegexpAll(lowerUTF8(unit_number), '\\s+', '') AS unit_key, unit_number,
               transaction_date, sale_amount_aed, size_sqft
        FROM dxbi_sales_unit_events FINAL
        WHERE building_key = {building:String} AND property_type = {type:String}
          AND bedrooms = {beds:String} AND sale_amount_aed > 0
          AND transaction_date >= {since:Date}
        """,
        {
            "building": row["building_key"],
            "type": row["property_type"],
            "beds": row["bedrooms"],
            "since": since,
        },
    )


async def sample(args: argparse.Namespace) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    factory = async_sessionmaker(get_postgres_engine(), class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        claims = [
            c
            for c in await owner_repository.list_claims_for_valuation(db, args.organization_id)
            if c.ownership_status in CURRENT_OWNER_STATUSES and c.estimated_value_aed
        ]
        db.expunge_all()  # read-only: never commit; keep the loaded rows usable
    others = Counter(_area(c.area_name) for c in claims if not _focus(c.area_name) and c.area_name)
    fifth = others.most_common(1)[0][0] if others else None
    pool = [
        {
            "id": c.id,
            "area": _focus(c.area_name) or fifth,
            "confidence": c.valuation.get("confidence"),
        }
        for c in claims
        if _focus(c.area_name) or (fifth and _area(c.area_name) == fifth)
    ]
    by_id = {c.id: c for c in claims}
    picked = [by_id[p["id"]] for p in pick_sample(pool, args.size, args.seed)]
    registry = await _registry_rows(picked)
    valued_at = date.fromisoformat(picked[0].valuation["valued_at"]) if picked else date.today()
    records = []
    for n, claim in enumerate(picked, start=1):
        row = registry.get(claim.id or 0)
        if not isinstance(row, dict):
            continue
        subject = {
            "unit_key": row["unit_key"],
            "building_key": row["building_key"],
            "property_type": row["property_type"],
            "bedrooms": row["bedrooms"],
            "size_sqft": float(row.get("size_sqft") or 0),
        }
        sales = await _building_sales(row, valued_at - timedelta(days=365))
        found = closest_sales(subject, sales)
        median = found["median_adjusted_aed"]
        records.append(
            {
                "sample_id": n,
                "building": row.get("building_name") or row.get("project_name"),
                "project": row.get("project_name"),
                "area": row.get("area_name"),
                "property_type": row["property_type"],
                "bedrooms": row["bedrooms"],
                "size_sqft": subject["size_sqft"],
                "purchase_date": str(claim.latest_sale_date),
                "purchase_aed": claim.latest_sale_price_aed,
                "estimate_aed": claim.estimated_value_aed,
                "low_aed": claim.estimated_value_low_aed,
                "high_aed": claim.estimated_value_high_aed,
                "confidence": claim.valuation.get("confidence"),
                "method": claim.valuation.get("method"),
                "level": claim.valuation.get("level"),
                "comparables": [
                    {
                        "date": str(c["transaction_date"]),
                        "unit": c.get("unit_number"),
                        "price_aed": int(c["sale_amount_aed"]),
                        "size_sqft": float(c["size_sqft"]),
                        "psf": c["psf"],
                    }
                    for c in found["comparables"]
                ],
                "same_unit_resale": {
                    "date": str(found["same_unit_resale"]["transaction_date"]),
                    "price_aed": int(found["same_unit_resale"]["sale_amount_aed"]),
                }
                if found["same_unit_resale"]
                else None,
                "median_adjusted_aed": median,
                "gap_pct": gap_pct(claim.estimated_value_aed, median) if median else None,
            }
        )
    (out / "comparables.json").write_text(json.dumps(records, indent=2, default=str))
    with (out / "sample.csv").open("w", newline="") as handle:
        keys = [
            "sample_id",
            "building",
            "project",
            "area",
            "property_type",
            "bedrooms",
            "size_sqft",
            "estimate_aed",
            "confidence",
        ]
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows({k: r[k] for k in keys} for r in records)
    with_median = sum(r["median_adjusted_aed"] is not None for r in records)
    mix = Counter((r["area"], r["confidence"]) for r in records)
    print(f"{len(records)} sampled, {with_median} with exact comparables")
    print("types:", dict(Counter(r["property_type"] for r in records)))
    print("area x confidence:", dict(mix))


def summarise_files(args: argparse.Namespace) -> None:
    folder = Path(args.dir)
    records = json.loads((folder / "comparables.json").read_text())
    grouped: dict[str, list[dict]] = defaultdict(list)
    with (folder / "listings.csv").open() as handle:
        for row in csv.DictReader(handle):
            grouped[row["sample_id"]].append(row)
    estimates = {str(r["sample_id"]): r["estimate_aed"] for r in records}
    listings = {}
    table = []
    for record in records:
        sid = str(record["sample_id"])
        stats = listing_stats(grouped.get(sid, []))
        if stats["count"] >= 2:
            listings[sid] = {"estimate": estimates[sid], "median": stats["median"]}
        table.append(
            {
                "sample_id": sid,
                "property": f"{record['building']}, {record['bedrooms']} {record['property_type']}",
                "estimate_aed": record["estimate_aed"],
                "confidence": record["confidence"],
                "comparables_median_aed": record["median_adjusted_aed"],
                "comparables_gap_pct": record["gap_pct"],
                "listings": stats["count"],
                "asking_low_aed": stats["low"],
                "asking_median_aed": stats["median"],
                "asking_high_aed": stats["high"],
                "estimate_to_asking": round(record["estimate_aed"] / stats["median"], 3)
                if stats["count"] >= 2
                else None,
            }
        )
    result = summarise(records, listings)
    (folder / "summary.json").write_text(json.dumps(result, indent=2))
    with (folder / "table.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    print(json.dumps(result, indent=2))


async def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("sample")
    one.add_argument("--organization-id", required=True)
    one.add_argument("--size", type=int, default=25)
    one.add_argument("--seed", type=int, default=7)
    one.add_argument("--out", required=True)
    two = sub.add_parser("summarise")
    two.add_argument("--dir", required=True)
    args = parser.parse_args()
    if args.command == "summarise":
        summarise_files(args)
        return
    try:
        await sample(args)
    finally:
        await close_clickhouse()
        await close_postgres()


if __name__ == "__main__":
    asyncio.run(main())
