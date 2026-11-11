"""Value a Property Finder sale listing from DLD sales (listing underpricing, 11 Nov 2026).

The old "below market" flag compared a listing's asking price with other asking prices, about
60% of them off-plan. A ready residential sale listing is now valued with the owner valuation
DLD sales (app.listings.comparables) and flagged only when its asking price falls outside the estimated
range at high or medium confidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.listings.comparables import ListingHome, ListingValuation
from app.listings.mapping import _location_hierarchy
from app.listings.models import ListingMarketPosition

LISTING_VALUATION_VERSION = "listing-value-v1"
RESIDENTIAL_SALE_CATEGORY = 1
READY_STATUSES = frozenset({"completed", "completed_primary"})
PROPERTY_TYPES = {
    "apartment": "Apartment",
    "penthouse": "Apartment",
    "villa": "Villa",
    "townhouse": "Townhouse",
}
FLAG_CONFIDENCE = frozenset({"high", "medium"})
# Only an estimate from sales of the same bedroom count in the same building is specific enough
# to call a listing under- or overpriced. Area-wide sales mix very different homes (Dubai Hills
# 5BR: townhouses with mansions); all-bedroom building prices mix studios with 2BR (11 Nov 2026).
FLAG_LEVELS = frozenset({"building_type_beds"})
# A listing much larger or smaller than the homes that sold is not comparable: price per sqft x a
# size that includes a terrace (or is simply wrong) makes a fake bargain. Park Horizon Tower 2
# 3BR: sales at ~1,356 sqft, a listing at 2,291 sqft looked 39% cheap at a normal price.
SIZE_TOLERANCE = 0.25
# An apartment is flagged from its exact comparables (same building and bedrooms, closest size),
# so the flag always agrees with the sales shown as evidence. Fewer than this: no flag.
EXACT_MIN = 3
# More than this far under same-building sales is almost always a data error (wrong size,
# bedrooms or price), not a bargain.
MAX_CREDIBLE_DISCOUNT = -0.40

# Mirror of holocron/sources/dxbi/sales_units.py: location_key, which builds DLD building_key.
_KEY_REPLACEMENTS = {"jumeriah": "jumeirah", "residences": "residence", "apartments": "apartment"}


def location_key(name: str | None) -> str:
    normalized = str(name or "").lower()
    for source, target in _KEY_REPLACEMENTS.items():
        normalized = normalized.replace(source, target)
    return re.sub(r"[^a-z0-9]+", "", normalized)


@dataclass(frozen=True)
class ListingSubject:
    listing_id: str
    asking_aed: int
    subject: ListingHome
    building_candidates: list[str]
    area_key: str


def _bedrooms(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw == "studio":
        return "Studio"
    digits = raw.rstrip("+")
    return f"{int(digits)} Bed" if digits.isdigit() else ""


def listing_subject(row: dict[str, Any], valued_at: date) -> ListingSubject | None:
    """The valuation subject for a ready residential sale listing, or None when it is out of scope.

    `row` keys: listing_id, category_id, location_names (list, city first), property_type,
    completion_status, bedrooms, price_aed, size_sqft.
    """
    if row.get("category_id") != RESIDENTIAL_SALE_CATEGORY:
        return None
    if str(row.get("completion_status") or "").lower() not in READY_STATUSES:
        return None
    raw_type = str(row.get("property_type") or "").strip().lower()
    property_type = PROPERTY_TYPES.get(raw_type)
    price, size = row.get("price_aed"), float(row.get("size_sqft") or 0)
    if property_type is None or not price or int(price) <= 0 or size <= 0:
        return None
    names = [str(n) for n in row.get("location_names") or []]
    area, project, building = _location_hierarchy(names, raw_type)
    candidates: list[str] = []
    for name in (building, project):
        key = location_key(name)
        if key and key not in candidates:
            candidates.append(key)
    area_key = location_key(area)
    return ListingSubject(
        listing_id=str(row.get("listing_id") or ""),
        asking_aed=int(price),
        subject=ListingHome(
            property_type=property_type,
            bedrooms=_bedrooms(row.get("bedrooms")),
            size_sqft=size,
        ),
        building_candidates=candidates,
        area_key=area_key,
    )


def _comparable_size(valuation: ListingValuation) -> bool:
    if valuation.detail.get("basis") == "bedroom_price":
        return True  # villas: valued by bedroom price, and DLD size is often the plot
    size, typical = valuation.detail.get("size_sqft"), valuation.detail.get("comparable_size_sqft")
    if not size or not typical:
        return False
    return abs(float(size) / float(typical) - 1) <= SIZE_TOLERANCE


def market_position(
    asking_aed: int, valuation: ListingValuation | None
) -> tuple[ListingMarketPosition, float | None]:
    """Below, near or above the estimated range.

    Flagged only at high or medium confidence, from same-building sales, and within a credible gap.
    """
    if valuation is None or not valuation.estimated_value_aed:
        return "insufficient_data", None
    gap = round(asking_aed / valuation.estimated_value_aed - 1, 4)
    if (
        valuation.confidence not in FLAG_CONFIDENCE
        or valuation.detail.get("level") not in FLAG_LEVELS
        or gap < MAX_CREDIBLE_DISCOUNT
        or not _comparable_size(valuation)
        or (
            valuation.detail.get("basis") != "bedroom_price"
            and int(valuation.detail.get("exact_count") or 0) < EXACT_MIN
        )
    ):
        return "insufficient_data", gap
    if asking_aed < valuation.low_aed:
        return "below_market", gap
    if asking_aed > valuation.high_aed:
        return "above_market", gap
    return "near_market", gap
