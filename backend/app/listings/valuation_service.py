"""Batch-value ready residential sale listings from DLD sales (listing underpricing, 11 Nov 2026).

Results go to the ClickHouse table `listing_valuations` (one row per listing, keyed by
listing_id), which the listings API joins to sort and filter by the gap to estimated value.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from app.listings import comparables
from app.listings import queries as listing_queries
from app.listings.comparables import (
    LADDER,
    MIN_RANGE,
    ListingValuation,
    SalesStats,
    estimate_value,
    stats_from_row,
)
from app.listings.valuation import (
    EXACT_MIN,
    LISTING_VALUATION_VERSION,
    ListingSubject,
    listing_subject,
    market_position,
)
from app.market.comparables import closest_sales

_CHUNK = 2000
_WINDOW_DAYS = 365
_BUILDING_LEVELS = ("building_type_beds", "building_type")

TABLE = "listing_valuations"
COLUMNS = (
    "listing_id",
    "estimate_aed",
    "low_aed",
    "high_aed",
    "confidence",
    "level",
    "basis",
    "comparable_count",
    "building_key",
    "market_position",
    "value_gap_pct",
    "asking_aed",
    "bedrooms",
    "size_sqft",
    "property_type",
    "location_names",
    "version",
    "valued_at",
)
CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    listing_id String,
    estimate_aed UInt64,
    low_aed UInt64,
    high_aed UInt64,
    confidence LowCardinality(String),
    level LowCardinality(String),
    basis LowCardinality(String),
    comparable_count UInt32,
    building_key String,
    market_position LowCardinality(String),
    value_gap_pct Float64,
    asking_aed UInt64,
    bedrooms LowCardinality(String),
    size_sqft Float64,
    property_type LowCardinality(String),
    location_names Array(String),
    version LowCardinality(String),
    valued_at Date
)
ENGINE = ReplacingMergeTree(valued_at)
ORDER BY listing_id
"""

StatsKey = tuple[str, str, str, str, str]


def dedupe_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """The same unit listed by several agents: same building, bedrooms, size (~1%) and price."""
    size = float(row.get("size_sqft") or 0)
    size_bucket = round(math.log(size) * 100) if size > 0 else 0
    return (row.get("building_key"), row.get("bedrooms"), size_bucket, row.get("asking_aed"))


_MINIMUM = {level: minimum for level, minimum, _ in LADDER}


def _building(subject: ListingSubject, stats: dict[StatsKey, SalesStats]) -> str:
    """The first candidate (building, then project) with enough sales to value from."""
    t, beds = subject.subject.property_type, subject.subject.bedrooms
    for candidate in subject.building_candidates:
        for level, b in (("building_type_beds", beds), ("building_type", "")):
            found = stats.get((level, candidate, "", t, b))
            if found and found.count >= _MINIMUM[level]:
                return candidate
    return ""


SalesKey = tuple[str, str, str]


def _exact(
    result: ListingValuation, subject: ListingSubject, sales: list[dict[str, Any]]
) -> ListingValuation:
    """Re-centre an apartment's estimate on its closest-size sales in the same building."""
    size = float(subject.subject.size_sqft or 0)
    found = closest_sales({"unit_key": "", "size_sqft": size}, sales)
    count, median = len(found["comparables"]), found["median_adjusted_aed"]
    detail = {**result.detail, "exact_count": count}
    if count < EXACT_MIN or not median:
        return replace(result, detail=detail)
    return replace(
        result,
        estimated_value_aed=median,
        low_aed=_round(median * (1 - MIN_RANGE)),
        high_aed=_round(median * (1 + MIN_RANGE)),
        detail={**detail, "comparable_count": count, "basis": "exact_comparables"},
    )


def _round(value: float) -> int:
    return int(round(value / 1000)) * 1000


def _unvalued(subject: ListingSubject, building: str, valued_at: date) -> dict[str, Any]:
    return {
        "listing_id": subject.listing_id,
        "estimate_aed": 0,
        "low_aed": 0,
        "high_aed": 0,
        "confidence": "",
        "level": "",
        "basis": "",
        "comparable_count": 0,
        "building_key": building,
        "market_position": "insufficient_data",
        "value_gap_pct": 0.0,
        "asking_aed": subject.asking_aed,
        "bedrooms": subject.subject.bedrooms,
        "size_sqft": float(subject.subject.size_sqft or 0),
        "property_type": subject.subject.property_type,
        "location_names": subject.location_names,
        "version": LISTING_VALUATION_VERSION,
        "valued_at": valued_at,
        "exact_count": 0,
    }


def _value_one(
    subject: ListingSubject,
    stats: dict[StatsKey, SalesStats],
    sales: dict[SalesKey, list[dict[str, Any]]],
    valued_at: date,
) -> dict[str, Any]:
    b = _building(subject, stats)
    a, t, beds = subject.area_key, subject.subject.property_type, subject.subject.bedrooms
    comps = {
        "building_type_beds": stats.get(("building_type_beds", b, "", t, beds))
        if b and beds
        else None,
        "building_type": stats.get(("building_type", b, "", t, "")) if b else None,
        "area_type_beds": stats.get(("area_type_beds", "", a, t, beds)) if a and beds else None,
        "area_type": stats.get(("area_type", "", a, t, "")) if a else None,
    }
    result = estimate_value(subject.subject, comps)
    if result is None:
        # Stored as "not flagged" so a rewrite retires any earlier flag for this listing.
        return _unvalued(subject, b, valued_at)
    if (
        result.detail.get("level") == "building_type_beds"
        and result.detail.get("basis") == "psf_size"
    ):
        result = _exact(result, subject, sales.get((b, t, beds), []))
    position, gap = market_position(subject.asking_aed, result)
    return {
        "listing_id": subject.listing_id,
        "estimate_aed": result.estimated_value_aed,
        "low_aed": result.low_aed,
        "high_aed": result.high_aed,
        "confidence": result.confidence,
        "level": str(result.detail.get("level") or ""),
        "basis": str(result.detail.get("basis") or ""),
        "comparable_count": int(result.detail.get("comparable_count") or 0),
        "building_key": b,
        "market_position": position,
        "value_gap_pct": gap if gap is not None else 0.0,
        "asking_aed": subject.asking_aed,
        "bedrooms": beds,
        "size_sqft": float(subject.subject.size_sqft or 0),
        "property_type": subject.subject.property_type,
        "location_names": subject.location_names,
        "version": LISTING_VALUATION_VERSION,
        "valued_at": valued_at,
        "exact_count": int(result.detail.get("exact_count") or 0),
    }


async def value_listing_rows(rows: list[dict[str, Any]], valued_at: date) -> list[dict[str, Any]]:
    """One row per in-scope listing; those without evidence are stored as not flagged."""
    subjects = [s for s in (listing_subject(r, valued_at) for r in rows) if s is not None]
    results: list[dict[str, Any]] = []
    for start in range(0, len(subjects), _CHUNK):
        chunk = subjects[start : start + _CHUNK]
        stat_rows = await comparables.fetch_sales_stats(
            sorted({c for s in chunk for c in s.building_candidates}),
            sorted({s.area_key for s in chunk if s.area_key}),
            valued_at - timedelta(days=_WINDOW_DAYS),
            valued_at + timedelta(days=1),
        )
        stats: dict[StatsKey, SalesStats] = {
            (
                r["level"],
                r["building_key"],
                r["area_key"],
                r["property_type"],
                r["bedrooms"],
            ): stats_from_row(r)
            for r in stat_rows
        }
        sale_rows = await listing_queries.fetch_ready_sales_for_buildings(
            sorted({b for b in (_building(s, stats) for s in chunk) if b}),
            valued_at - timedelta(days=_WINDOW_DAYS),
        )
        sales: dict[SalesKey, list[dict[str, Any]]] = {}
        for sale in sale_rows:
            key = (sale["building_key"], sale["property_type"], sale["bedrooms"])
            sales.setdefault(key, []).append(sale)
        for subject in chunk:
            results.append(_value_one(subject, stats, sales, valued_at))
    return results
