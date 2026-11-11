"""DLD-sales comparables for listing valuation (listing underpricing, 11 Nov 2026).

Owned by listings: the CRM owner valuation model (app.crm.valuation) is deliberately not used or
changed. A ready sale listing is valued from ready DLD sales over the last 12 months, from the most
specific group with enough sales: same building and bedrooms, same building, same area and
bedrooms, same area.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from app.clickhouse.client import query

Confidence = Literal["high", "medium", "low"]
# Comparable groups from the most to the least specific: (name, minimum deals, confidence).
LADDER: tuple[tuple[str, int, Confidence], ...] = (
    ("building_type_beds", 5, "high"),
    ("building_type", 5, "medium"),
    ("area_type_beds", 10, "medium"),
    ("area_type", 10, "low"),
)
# A range is never narrower than this on either side of the estimate.
MIN_RANGE = 0.05
# Villas and townhouses at a bedroom level are valued from the median sale price: DLD often
# records a villa's plot as its size, which breaks price per sqft x size.
PRICED_BY_BEDROOM = frozenset({"Villa", "Townhouse"})

_SALE_FILTER = "price_per_sqft_aed BETWEEN 200 AND 12000 AND size_sqft > 0"
# Off-plan launches sell at a premium to ready homes, so ready listings use ready sales only.
_READY = "market_status = 'Ready'"
# Units sold on one day at one price per sqft (within ~1%) are one deal, e.g. an investor block.
_DEAL = "transaction_date, round(log(price_per_sqft_aed) * 100)"


@dataclass(frozen=True)
class SalesStats:
    """Price-per-sqft quartiles of a group of deals, plus sale-price quartiles and typical size."""

    count: int
    p25: float
    p50: float
    p75: float
    price_p25: float | None = None
    price_p50: float | None = None
    price_p75: float | None = None
    size_p50: float | None = None


@dataclass(frozen=True)
class ListingHome:
    property_type: str  # Apartment, Villa or Townhouse
    bedrooms: str  # DLD form: "Studio", "2 Bed"; "" when unknown
    size_sqft: float


@dataclass(frozen=True)
class ListingValuation:
    estimated_value_aed: int
    low_aed: int
    high_aed: int
    confidence: Confidence
    detail: dict[str, Any]


def _aed(value: float) -> int:
    return int(round(value / 1000)) * 1000


def _level(name: str, keys: str, scope: str) -> str:
    building = "building_key" if "building_key" in keys else "''"
    area = "area_key" if "area_key" in keys else "''"
    bedrooms = "bedrooms" if "bedrooms" in keys else "''"
    return f"""
        SELECT '{name}' AS level, building_key, area_key, property_type, bedrooms,
               count() AS count, sum(sales) AS sales,
               quantilesTDigest(0.25, 0.5, 0.75)(deal_psf) AS psf,
               quantilesTDigest(0.25, 0.5, 0.75)(deal_price) AS price,
               quantileTDigest(0.5)(deal_size) AS size_p50
        FROM (
            SELECT {building} AS building_key, {area} AS area_key, property_type,
                   {bedrooms} AS bedrooms, count() AS sales,
                   avg(price_per_sqft_aed) AS deal_psf, avg(sale_amount_aed) AS deal_price,
                   avg(size_sqft) AS deal_size
            FROM dxbi_sales_unit_events FINAL
            WHERE transaction_date >= {{since:Date}} AND transaction_date < {{until:Date}}
              AND {_SALE_FILTER} AND {_READY} AND {scope}
            GROUP BY {keys}, {_DEAL}
        )
        GROUP BY building_key, area_key, property_type, bedrooms
    """


async def fetch_sales_stats(
    building_keys: list[str], area_keys: list[str], since: date, until: date
) -> list[dict[str, Any]]:
    """Ready-sales statistics at the four LADDER levels."""
    in_buildings = "building_key IN {building_keys:Array(String)}"
    in_areas = "area_key IN {area_keys:Array(String)}"
    parts = [
        _level("building_type_beds", "building_key, property_type, bedrooms", in_buildings),
        _level("building_type", "building_key, property_type", in_buildings),
        _level("area_type_beds", "area_key, property_type, bedrooms", in_areas),
        _level("area_type", "area_key, property_type", in_areas),
    ]
    return await query(
        " UNION ALL ".join(parts),
        {
            "building_keys": building_keys,
            "area_keys": area_keys,
            "since": since.isoformat(),
            "until": until.isoformat(),
        },
    )


def stats_from_row(row: dict[str, Any]) -> SalesStats:
    p25, p50, p75 = (float(v) for v in row["psf"])
    prices = [float(v) for v in row.get("price") or []]
    size = float(row["size_p50"]) if row.get("size_p50") else None
    if len(prices) == 3:
        return SalesStats(int(row["count"]), p25, p50, p75, *prices, size_p50=size)
    return SalesStats(int(row["count"]), p25, p50, p75, size_p50=size)


def estimate_value(
    home: ListingHome, comps: dict[str, SalesStats | None]
) -> ListingValuation | None:
    """The estimate from the most specific group with enough sales, or None."""
    if home.size_sqft <= 0:
        return None
    for level, minimum, confidence in LADDER:
        stats = comps.get(level)
        if stats is None or stats.count < minimum:
            continue
        by_price = (
            home.property_type in PRICED_BY_BEDROOM
            and level.endswith("_beds")
            and stats.price_p50 is not None
        )
        if by_price:
            value = float(stats.price_p50 or 0)
            low, high = float(stats.price_p25 or value), float(stats.price_p75 or value)
        else:
            size = home.size_sqft
            value, low, high = stats.p50 * size, stats.p25 * size, stats.p75 * size
        return ListingValuation(
            estimated_value_aed=_aed(value),
            low_aed=_aed(min(low, value * (1 - MIN_RANGE))),
            high_aed=_aed(max(high, value * (1 + MIN_RANGE))),
            confidence=confidence,
            detail={
                "level": level,
                "comparable_count": stats.count,
                "basis": "bedroom_price" if by_price else "psf_size",
                "size_sqft": round(home.size_sqft, 1),
                "comparable_size_sqft": round(stats.size_p50) if stats.size_p50 else None,
            },
        )
    return None
