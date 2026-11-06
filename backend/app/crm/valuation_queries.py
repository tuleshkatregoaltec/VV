"""Comparable-sales statistics for owner valuation, read from the DLD sales registry."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.clickhouse.client import query

# Same price-per-sqft bounds as the listings market benchmark (listings/queries.py).
_SALE_FILTER = "price_per_sqft_aed BETWEEN 200 AND 12000 AND size_sqft > 0"
# Units sold on the same day at the same price per sqft (within about 1%) are one deal, e.g. a
# developer or investor block. Each deal counts once, so one bulk sale cannot pass for many
# independent comparables (Miracle Residence, Arjan: 15 studios in one Jan 2026 block deal).
_DEAL = "transaction_date, round(log(price_per_sqft_aed) * 100)"


def _level(name: str, keys: str, scope: str) -> str:
    building = "building_key" if "building_key" in keys else "''"
    area = "area_key" if "area_key" in keys else "''"
    bedrooms = "bedrooms" if "bedrooms" in keys else "''"
    return f"""
        SELECT '{name}' AS level, building_key, area_key, property_type, bedrooms,
               count() AS count, sum(sales) AS sales,
               quantilesTDigest(0.25, 0.5, 0.75)(deal_psf) AS psf
        FROM (
            SELECT {building} AS building_key, {area} AS area_key, property_type,
                   {bedrooms} AS bedrooms, count() AS sales,
                   avg(price_per_sqft_aed) AS deal_psf
            FROM dxbi_sales_unit_events FINAL
            WHERE transaction_date >= {{since:Date}} AND transaction_date < {{until:Date}}
              AND {_SALE_FILTER} AND {scope}
            GROUP BY {keys}, {_DEAL}
        )
        GROUP BY building_key, area_key, property_type, bedrooms
    """


async def fetch_comparable_stats(
    building_keys: list[str], area_keys: list[str], since: date, until: date
) -> list[dict[str, Any]]:
    """Sales statistics at the four comparable levels used by valuation.LADDER."""
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


async def fetch_area_psf_by_quarter(
    area_keys: list[str], property_types: list[str]
) -> list[dict[str, Any]]:
    """Median price per sqft by area, type and calendar quarter, for the purchase-price index."""
    return await query(
        f"""
        SELECT area_key, property_type, toStartOfQuarter(transaction_date) AS quarter,
               count() AS count, quantileTDigest(0.5)(price_per_sqft_aed) AS p50
        FROM dxbi_sales_unit_events FINAL
        WHERE area_key IN {{area_keys:Array(String)}}
          AND property_type IN {{property_types:Array(String)}}
          AND {_SALE_FILTER}
        GROUP BY area_key, property_type, quarter
        """,
        {"area_keys": area_keys, "property_types": property_types},
    )
