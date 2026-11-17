from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.listings import queries
from app.listings.mapping import (
    _as_dict,
    _as_list,
    _card_from_row,
    _float_or_none,
    _floorplans,
    _freshness_datetime,
    _images,
    _int_or_none,
    _location_names,
    _parse_datetime,
    _row_to_dict,
    _valuation_date,
)
from app.listings.models import (
    ListingAnalyticsResponse,
    ListingAssetClass,
    ListingComparableSale,
    ListingDetailResponse,
    ListingFiltersResponse,
    ListingFloorPlanResponse,
    ListingImageResponse,
    ListingListResponse,
    ListingMode,
    ListingTrendPoint,
)
from app.listings.policy import (
    MIN_BENCHMARK_COMPARABLES,
    _category_ids,
)
from app.listings.queries import (
    _achieved_trend,
)
from app.listings.redaction import redact_contacts
from app.listings.valuation import RESIDENTIAL_SALE_CATEGORY, listing_subject

_SALES_WINDOW_DAYS = 365


def _valuation_input(row: dict[str, Any]) -> dict[str, Any]:
    """The fields app.listings.valuation reads, taken from a listings row."""
    raw = _as_dict(row.get("raw_property_json"))
    return {
        "listing_id": row.get("listing_id"),
        "category_id": _int_or_none(row.get("category_id")),
        "location_names": _location_names(row),
        "property_type": raw.get("property_type"),
        "completion_status": raw.get("completion_status"),
        "bedrooms": row.get("bedrooms"),
        "price_aed": _int_or_none(_as_dict(row.get("price_json")).get("value")),
        "size_sqft": _float_or_none(_as_dict(row.get("size_json")).get("value")),
    }


_FLAGGED = frozenset({"below_market", "near_market", "above_market"})


def _apply_dld_valuation(row: dict[str, Any]) -> None:
    """Use the stored DLD-sales valuation (v_* columns) for a ready residential sale listing.

    Rent and commercial listings keep the asking-peer benchmark. Off-plan sale listings and ready
    ones without a usable valuation are never flagged from asking peers: that model is what Kian
    called grossly inaccurate (11 Nov 2026). A suppressed estimate exposes no gap anywhere.
    """
    listing = _valuation_input(row)
    unflagged = {
        "market_position_override": "insufficient_data",
        "market_delta_pct": None,
        "market_estimate_aed": None,
    }
    if listing["category_id"] == RESIDENTIAL_SALE_CATEGORY and str(
        listing["completion_status"] or ""
    ).startswith("off_plan"):
        row.update(unflagged)
        return
    estimate = _float_or_none(row.get("v_estimate_aed")) or 0
    subject = listing_subject(listing, date.today())
    if subject is None:
        return
    row["valuation_method"] = "dld_sales"
    row.update(unflagged)
    if estimate <= 0:
        return
    if (
        _float_or_none(row.get("v_size_sqft")) != subject.subject.size_sqft
        or row.get("v_bedrooms") != subject.subject.bedrooms
        or row.get("v_property_type") != subject.subject.property_type
        or list(row.get("v_location_names") or []) != subject.location_names
    ):
        return
    position = row.get("v_market_position") or "insufficient_data"
    stored_asking = _int_or_none(row.get("v_asking_aed"))
    price_changed = not stored_asking or stored_asking != listing["price_aed"]
    gap = _float_or_none(row.get("v_value_gap_pct"))
    row.update(
        estimated_value_aed=estimate,
        estimated_value_low_aed=_float_or_none(row.get("v_low_aed")),
        estimated_value_high_aed=_float_or_none(row.get("v_high_aed")),
        valuation_confidence=row.get("v_confidence") or None,
        valued_at=row.get("v_valued_at"),
        comparable_count=_int_or_none(row.get("v_comparable_count")) or 0,
    )
    if position in _FLAGGED and not price_changed:
        row.update(
            market_position_override=position,
            value_gap_pct=gap,
            market_delta_pct=gap,
            market_estimate_aed=estimate,
        )


async def _comparable_sales(row: dict[str, Any]) -> list[ListingComparableSale]:
    """The closest ready DLD sales behind a listing's estimate (same building, type and beds)."""
    building = str(row.get("v_building_key") or "")
    valued_at = _valuation_date(row.get("v_valued_at")) or date.today()
    subject = listing_subject(_valuation_input(row), valued_at)
    if not building or subject is None:
        return []
    from app.market.comparables import closest_sales

    sales = await queries.fetch_building_sales(
        {
            "building": building,
            "type": subject.subject.property_type,
            "beds": subject.subject.bedrooms,
            # The same 12 months the stored estimate used, so the evidence matches the flag.
            "since": valued_at - timedelta(days=_SALES_WINDOW_DAYS),
            "until": valued_at + timedelta(days=1),
        }
    )
    if row.get("v_basis") == "bedroom_price":
        # Villas are valued by bedroom price; DLD size is often the plot, so show the latest
        # same-bedroom sales rather than the closest in size.
        chosen = sorted(
            (s for s in sales if float(s.get("size_sqft") or 0) > 0),
            key=lambda s: s["transaction_date"],
            reverse=True,
        )[:5]
    else:
        found = closest_sales({"unit_key": "", "size_sqft": subject.subject.size_sqft}, sales)
        chosen = found["comparables"]
    return [
        ListingComparableSale(
            date=sale["transaction_date"],
            unit=sale.get("unit_number"),
            size_sqft=float(sale["size_sqft"]),
            price_aed=int(sale["sale_amount_aed"]),
            psf=round(float(sale["sale_amount_aed"]) / float(sale["size_sqft"]), 1),
        )
        for sale in chosen
    ]


async def _filters(
    mode: ListingMode, asset_class: ListingAssetClass | None = None
) -> ListingFiltersResponse:
    params = {"category_ids": list(_category_ids(mode, asset_class))}
    modes_future = queries.fetch_filter_modes({})
    areas_future = queries.fetch_filter_areas(params)
    property_types_future = queries.fetch_filter_property_types(params)
    bedrooms_future = queries.fetch_filter_bedrooms(params)
    prices_future = queries.fetch_filter_prices(params)
    (
        modes_result,
        areas_result,
        property_types_result,
        bedrooms_result,
        prices_result,
    ) = await asyncio.gather(
        modes_future,
        areas_future,
        property_types_future,
        bedrooms_future,
        prices_future,
    )
    prices = prices_result[0] if prices_result else {}
    return ListingFiltersResponse(
        modes=[row["listing_mode"] for row in modes_result],
        asset_classes=["residential", "commercial"],
        areas=[row["area_name"] for row in areas_result],
        property_types=[row["property_type"] for row in property_types_result],
        bedrooms=[row["bedrooms"] for row in bedrooms_result],
        price_min=_int_or_none(prices.get("price_min")),
        price_max=_int_or_none(prices.get("price_max")),
    )


async def listing_filters_from_clickhouse(
    mode: ListingMode, asset_class: ListingAssetClass | None = None
) -> ListingFiltersResponse:
    return await _filters(mode, asset_class)


async def list_listings_from_clickhouse(
    mode: ListingMode,
    asset_class: ListingAssetClass | None = None,
    limit: int = 48,
    offset: int = 0,
    search: str | None = None,
    area: str | None = None,
    property_type: str | None = None,
    bedrooms: str | None = None,
    bedrooms_in: list[str] | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    price_period: str | None = None,
    price_basis: str = "raw",
    include_filters: bool = True,
    market_position: str | None = None,
    sort: str = "default",
    building: str | None = None,
    min_age_days: int | None = None,
    max_age_days: int | None = None,
) -> ListingListResponse:
    use_dld = (
        mode == "sale" and asset_class != "commercial" and await queries.valuations_available()
    )
    if market_position and not use_dld:
        # A market-position view (e.g. possible bargains) needs DLD valuations; without them it
        # is empty rather than every listing.
        return ListingListResponse(listings=[], total=0, limit=limit, offset=offset)
    filters = dict(
        mode=mode,
        asset_class=asset_class,
        search=search,
        area=area,
        property_type=property_type,
        bedrooms=bedrooms,
        bedrooms_in=bedrooms_in,
        price_min=price_min,
        price_max=price_max,
        price_period=price_period,
        price_basis=price_basis,
        market_position=market_position if use_dld else None,
        building=building,
        min_age_days=min_age_days,
        max_age_days=max_age_days,
    )
    count_task = asyncio.create_task(queries.fetch_listing_count(filters))
    filters_task = asyncio.create_task(_filters(mode, asset_class)) if include_filters else None
    rows = await queries.fetch_listing_rows(
        filters,
        limit=limit,
        offset=offset,
        sort=sort if use_dld else "default",
        with_valuations=use_dld,
    )
    normalized_rows = [_row_to_dict(row) for row in rows]
    benchmark_property_types = sorted(
        {str(row.get("benchmark_property_type") or "") for row in normalized_rows}
    )
    benchmark_bedrooms = sorted({str(row.get("bedrooms") or "") for row in normalized_rows})
    benchmark_peer_locations = sorted(
        {str(row.get("benchmark_peer_location") or "") for row in normalized_rows}
    )
    benchmark_size_buckets = sorted(
        {_int_or_none(row.get("benchmark_size_bucket")) or 0 for row in normalized_rows}
    )
    benchmark_rows = []
    if normalized_rows:
        benchmark_rows = await queries.fetch_listing_benchmarks(
            {
                "category_ids": list(_category_ids(mode, asset_class)),
                "benchmark_peer_locations": benchmark_peer_locations,
                "benchmark_property_types": benchmark_property_types,
                "benchmark_bedrooms": benchmark_bedrooms,
                "benchmark_size_buckets": benchmark_size_buckets,
            },
            mode,
        )
    benchmarks = {
        (
            _int_or_none(row.get("category_id")),
            str(row.get("benchmark_peer_location") or ""),
            str(row.get("benchmark_property_type") or ""),
            str(row.get("bedrooms") or ""),
            _int_or_none(row.get("benchmark_size_bucket")) or 0,
        ): row
        for row in benchmark_rows
    }
    for row in normalized_rows:
        key = (
            _int_or_none(row.get("category_id")),
            str(row.get("benchmark_peer_location") or ""),
            str(row.get("benchmark_property_type") or ""),
            str(row.get("bedrooms") or ""),
            _int_or_none(row.get("benchmark_size_bucket")) or 0,
        )
        benchmark = benchmarks.get(key, {}) if row.get("has_valid_benchmark_size") else {}
        market_psf = _float_or_none(benchmark.get("market_median_price_per_sqft_aed"))
        comparable_count = _int_or_none(benchmark.get("comparable_count")) or 0
        market_price = _float_or_none(row.get("market_price_aed"))
        size_sqft = _float_or_none(row.get("size_sqft"))
        row["market_median_price_per_sqft_aed"] = market_psf
        row["comparable_count"] = comparable_count
        if (
            comparable_count >= MIN_BENCHMARK_COMPARABLES
            and market_psf
            and market_price
            and size_sqft
        ):
            row["market_estimate_aed"] = market_psf * size_sqft
            row["market_delta_pct"] = market_price / size_sqft / market_psf - 1
        if use_dld:
            _apply_dld_valuation(row)
    count_result = await count_task
    listing_filters = await filters_task if filters_task else ListingFiltersResponse()
    data_as_of, _ = await get_inventory_freshness()
    return ListingListResponse(
        listings=[_card_from_row(row) for row in normalized_rows],
        total=count_result[0]["total"] if count_result else 0,
        limit=limit,
        offset=offset,
        filters=listing_filters,
        data_as_of=data_as_of,
    )


async def listing_analytics_from_clickhouse(
    mode: ListingMode,
    asset_class: ListingAssetClass | None = None,
    search: str | None = None,
    area: str | None = None,
    property_type: str | None = None,
    bedrooms: str | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
) -> ListingAnalyticsResponse:
    """Return aggregate metrics for the same available-listing filter set as the grid."""
    filters = dict(
        mode=mode,
        asset_class=asset_class,
        search=search,
        area=area,
        property_type=property_type,
        bedrooms=bedrooms,
        bedrooms_in=None,
        price_min=price_min,
        price_max=price_max,
        price_basis="annual" if mode == "rent" else "raw",
    )
    result_future = queries.fetch_listing_analytics(filters)
    trend_future = queries.fetch_listing_trend(filters)
    result, trend_result = await asyncio.gather(result_future, trend_future)
    trend_periods = [
        str(point.get("period") or "") for point in trend_result if point.get("period")
    ]
    achieved_rows = await _achieved_trend(
        mode=mode,
        asset_class=asset_class or "residential",
        periods=trend_periods,
        area=area,
        property_type=property_type,
        bedrooms=bedrooms,
    )
    achieved_by_period = {
        str(point.get("period") or ""): point for point in achieved_rows if point.get("period")
    }
    row = result[0] if result else {}
    if mode == "sale" and asset_class == "residential" and await queries.valuations_available():
        # Below / near / above market from the DLD-sales valuations, not asking peers.
        counts = await queries.fetch_valuation_counts(filters)
        row = {**row, **(counts[0] if counts else {})}
    return ListingAnalyticsResponse(
        total=_int_or_none(row.get("total")) or 0,
        average_price_aed=_float_or_none(row.get("average_price_aed")),
        median_price_aed=_float_or_none(row.get("median_price_aed")),
        median_price_per_sqft_aed=_float_or_none(row.get("median_price_per_sqft_aed")),
        average_listing_age_days=_float_or_none(row.get("average_listing_age_days")),
        median_listing_age_days=_float_or_none(row.get("median_listing_age_days")),
        newly_listed_30d=_int_or_none(row.get("newly_listed_30d")) or 0,
        below_market_count=_int_or_none(row.get("below_market_count")) or 0,
        near_market_count=_int_or_none(row.get("near_market_count")) or 0,
        above_market_count=_int_or_none(row.get("above_market_count")) or 0,
        benchmarked_count=_int_or_none(row.get("benchmarked_count")) or 0,
        verified_count=_int_or_none(row.get("verified_count")) or 0,
        area_count=_int_or_none(row.get("area_count")) or 0,
        snapshot_at=_parse_datetime(row.get("snapshot_at")),
        data_as_of=_parse_datetime(row.get("snapshot_at")),
        trend=[
            ListingTrendPoint(
                period=str(point.get("period") or ""),
                average_asking_price_aed=_float_or_none(point.get("average_asking_price_aed")),
                median_asking_price_aed=_float_or_none(point.get("median_asking_price_aed")),
                median_price_per_sqft_aed=_float_or_none(point.get("median_price_per_sqft_aed")),
                listing_count=_int_or_none(point.get("listing_count")) or 0,
                median_achieved_price_per_sqft_aed=_float_or_none(
                    achieved_by_period.get(str(point.get("period") or ""), {}).get(
                        "median_achieved_price_per_sqft_aed"
                    )
                ),
                achieved_transaction_count=_int_or_none(
                    achieved_by_period.get(str(point.get("period") or ""), {}).get(
                        "achieved_transaction_count"
                    )
                )
                or 0,
            )
            for point in trend_result
            if point.get("period")
        ],
    )


async def get_listing_descriptions(listing_ids: list[str]) -> dict[str, str]:
    if not listing_ids:
        return {}
    rows = await queries.fetch_listing_descriptions({"ids": listing_ids})
    return {str(row["listing_id"]): str(row.get("description") or "") for row in rows}


async def get_listing_from_clickhouse(listing_id: str) -> ListingDetailResponse:
    rows = await queries.fetch_listing_detail({"listing_id": listing_id})
    if not rows:
        raise HTTPException(status_code=404, detail="Listing not found")

    data = _row_to_dict(rows[0])
    comparables: list[ListingComparableSale] = []
    if (
        listing_subject(_valuation_input(data), date.today()) is not None
        and await queries.valuations_available()
    ):
        valuation = await queries.fetch_listing_valuation({"listing_id": listing_id})
        data = {**data, **(valuation[0] if valuation else {})}
        _apply_dld_valuation(data)
        if data.get("estimated_value_aed") is not None:
            comparables = await _comparable_sales(data)
    raw_property = _as_dict(data.get("raw_property_json"))
    card = _card_from_row(data)
    amenities = raw_property.get("amenity_names") or raw_property.get("amenities")
    return ListingDetailResponse(
        **card.model_dump(),
        description=redact_contacts(raw_property.get("description")),
        amenities=[str(item) for item in _as_list(amenities) if item],
        images=[
            ListingImageResponse.model_validate(item) for item in _images(data.get("images_json"))
        ],
        floorplans=[
            ListingFloorPlanResponse.model_validate(item) for item in _floorplans(raw_property)
        ],
        furnished=raw_property.get("furnished"),
        completion_status=raw_property.get("completion_status"),
        rera=raw_property.get("rera"),
        number_of_cheques=_int_or_none(raw_property.get("number_of_cheques")),
        payment_method=[str(item) for item in _as_list(raw_property.get("payment_method"))],
        video_url=raw_property.get("video_url"),
        view_360_url=raw_property.get("view_360"),
        valuation_comparables=comparables,
    )


async def resolve_listing_area(db: AsyncSession, mode: ListingMode, area: str | None) -> str | None:
    from app.listings.queries import resolve_listing_area as query_area

    del db
    return await query_area(mode, area)


_LISTING_MAX_AGE_HOURS = 48


async def get_inventory_freshness() -> tuple[datetime | None, bool]:
    try:
        rows = await queries.fetch_inventory_freshness({})
        refreshed = _freshness_datetime(rows[0].get("refreshed") if rows else None)
        fresh = bool(
            refreshed
            and (datetime.now(timezone.utc) - refreshed).total_seconds()
            <= _LISTING_MAX_AGE_HOURS * 3600
        )
        return refreshed, fresh
    except Exception:
        return None, False
