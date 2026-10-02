"""Public listing age, asking-price and registered-rent evidence operations."""

import math
from datetime import date, datetime

from app.analytics.evidence import get_market_evidence
from app.analytics.models import MarketMetricsRequest
from app.listings import capability_queries, service
from app.listings.capability_models import (
    ListingAgeRequest,
    ListingEvidenceRequest,
    ListingRentRequest,
)
from app.market.evidence import COVERAGE_NOTE, RELEASE_NOTE, MarketAccessContext, has_shared_release
from app.market.reference import community_location

AGE_DEFINITION = (
    "Age at capture is calendar days between source posted/listed date and captured_at. "
    "Missing, invalid, future posting or missing capture dates have unknown age. "
    "First observation is unavailable and never substituted for the posting date."
)


def _clean(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _area(request):
    return community_location(request.location).name if request.location else None


def _base(request, context):
    return {
        "reference_date": context.reference_date.isoformat(),
        "filters": request.model_dump(mode="json"),
        "source": "Property Finder current available listing snapshot (asking prices)",
        "coverage": {"status": "unverified", "note": COVERAGE_NOTE},
        "limitations": [
            "Only Property Finder is available. Bayut and Reelly evidence is unavailable.",
            "Asking prices are not achieved prices; listings may represent the same unit.",
            "Current inventory is not historical inventory for the requested market period.",
        ],
    }


async def get_listing_observation() -> dict:
    return await capability_queries.fetch_inventory_observation()


async def get_listing_inventory(
    request: ListingEvidenceRequest, *, context: MarketAccessContext
) -> dict:
    # Preserve the existing public analytics service's numbers and t-digest definitions.
    # Exact building evidence uses the contact-free capability operation below instead of
    # the legacy free-text search, which also searches agent and broker data.
    if request.building:
        return await get_listing_evidence(request, context=context)
    result = await service.listing_analytics_from_clickhouse(
        mode=request.mode,
        area=_area(request),
        bedrooms=request.bedrooms,
        property_type=request.property_type,
        price_max=request.price_max,
    )
    return _base(request, context) | {
        "inventory": result.model_dump(mode="json", exclude={"trend"}),
        "definitions": {
            "median_price_aed": "Approximate t-digest median asking price (AED); rental prices are annualized."
        },
    }


async def get_listing_evidence(
    request: ListingEvidenceRequest, *, context: MarketAccessContext
) -> dict:
    rows = await capability_queries.fetch_evidence_rows(request, _area(request))
    return _base(request, context) | {
        "listings": _clean(rows),
        "returned_count": len(rows),
        "sample_order": "Lowest asking price then listing ID; bounded evidence, not total inventory.",
        "definitions": {
            "asking_price_aed": "Asking sale price or annualized asking rent, AED.",
            "size_sqft": "Source units explicitly converted to sqft; unknown units remain null.",
        },
    }


async def compare_listing_age(request: ListingAgeRequest, *, context: MarketAccessContext) -> dict:
    groups, older, peers = await capability_queries.fetch_age_evidence(request, _area(request))
    comparable = {
        (row["building"], row["property_type"], row["bedrooms"], int(row["size_band"])): row
        for row in peers
    }
    listings = []
    for row in older:
        size = row.get("size_sqft")
        key = (
            row["building"],
            row["property_type"],
            row["bedrooms"],
            int(size // 100) if size else -1,
        )
        peer = comparable.get(key, {})
        median = peer.get("median_aed_per_sqft")
        count = int(peer.get("count", 0))
        price = row.get("asking_aed_per_sqft")
        supported = bool(count >= 3 and median and price)
        listings.append(
            row
            | {
                "first_observed_at": None,
                "newer_comparable_count": count,
                "newer_comparable_median_aed_per_sqft": median if supported else None,
                "asking_difference_pct": round((price / median - 1) * 100, 2)
                if supported
                else None,
                "comparison_status": "ok" if supported else "unavailable",
            }
        )
    return _base(request, context) | {
        "age_groups": _clean(groups),
        "older_listings": _clean(listings),
        "returned_count": len(listings),
        "definitions": {
            "age_days_at_capture": AGE_DEFINITION,
            "median_aed_per_sqft": "Exact inclusive median asking AED per sqft among valid-price/known-size records.",
            "newer_comparable": "Same exact building, property type, bedrooms and floor(size_sqft / 100) band, known age <= threshold, minimum 3 records; no fallback to another building.",
        },
        "limitations": _base(request, context)["limitations"]
        + [
            "Age-group aggregates alone are not matched comparisons. Per-listing differences require the specified peer selection.",
            "At most the requested number of oldest listings are returned; unknown-age rows are counted separately.",
        ],
    }


async def compare_listing_rents(
    request: ListingRentRequest, *, context: MarketAccessContext
) -> dict:
    result = await get_listing_evidence(request, context=context)
    buildings = list(
        dict.fromkeys(row["building"] for row in result["listings"] if row["building"])
    )
    rents = {}
    for building in buildings:
        rents[building] = await get_market_evidence(
            MarketMetricsRequest(
                dataset="rentals",
                period=request.period,
                location=request.location,
                building=building,
                bedrooms=[request.bedrooms],
                property_type="apartment"
                if request.property_type == "Apartment"
                else request.property_type.lower(),
                metrics=["count", "median_aed", "p25_aed", "p75_aed", "median_aed_per_sqft"],
                group_by="contract_version",
            ),
            context=context,
        )
    pinned = has_shared_release("listings", "rentals")
    for row in result["listings"]:
        rent = rents.get(row["building"])
        row["registered_rent_evidence_key"] = row["building"] if rent else None
        row.update(registered_rent_yield(row, rent, pinned=pinned))
    supported = any(row["yield_status"] == "ok" for row in result["listings"])
    return result | {
        "status": "ok" if supported else "unavailable",
        "registered_rents": rents,
        "definitions": result["definitions"]
        | {
            "gross_yield_pct": "100 × comparable median annual registered rent / sale asking price; excludes fees, vacancy, service charges and financing. Withheld without a shared immutable release and supported comparable sample.",
            "comparables": "Exact building, community, property type and known bedrooms, same explicit registration period. No silent geographic/building fallback; unknown bedrooms are excluded and disclosed by the rent service.",
        },
        "limitations": result["limitations"]
        + ([] if pinned else [RELEASE_NOTE])
        + [
            "A minimum of five same-building/layout contracts and authoritative period coverage are required. No adjustment is made for floor, view, condition or furnishing; the IQR is a comparable range, not a confidence interval."
        ],
    }


def registered_rent_yield(listing: dict, rents: dict | None, *, pinned: bool) -> dict:
    """Gross rental-income screening using the exact shared-service annual rent statistics."""
    unavailable = {
        "gross_yield_pct": None,
        "gross_yield_range_pct": None,
        "yield_status": "unavailable",
    }
    if not pinned or not rents or rents["coverage"]["status"] != "complete":
        return unavailable
    total = rents["total"]
    price = listing.get("asking_price_aed")
    values = total["values"]
    if (total.get("count") or 0) < 5 or not price or price <= 0:
        return unavailable
    numbers = [values.get(key) for key in ("median_aed", "p25_aed", "p75_aed")]
    if any(value is None or value <= 0 or not math.isfinite(value) for value in numbers):
        return unavailable
    median, low, high = numbers
    return {
        "gross_yield_pct": round(100 * median / price, 2),
        "gross_yield_range_pct": [round(100 * low / price, 2), round(100 * high / price, 2)],
        "yield_status": "ok",
    }
