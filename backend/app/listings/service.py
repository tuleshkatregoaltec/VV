"""Property Finder listings backed by ph_box ClickHouse bronze data."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.clickhouse.client import query
from app.listings.models import (
    ListingAnalyticsResponse,
    ListingCardResponse,
    ListingDetailResponse,
    ListingFiltersResponse,
    ListingFloorPlanResponse,
    ListingImageResponse,
    ListingListResponse,
    ListingMode,
    ListingPartyResponse,
)

SALE_CATEGORY_IDS = (1, 3)
RENT_CATEGORY_IDS = (2, 4)
LISTINGS_TABLE = "pf_listings_bronze"
LISTINGS_SOURCE_LABEL = f"ph_box ClickHouse {LISTINGS_TABLE}"
PRICE_VALUE_EXPR = "JSONExtractInt(price_json, 'value')"
PRICE_PERIOD_EXPR = "lower(JSON_VALUE(price_json, '$.period'))"
MONTHLY_PRICE_EXPR = f"""
multiIf(
    {PRICE_PERIOD_EXPR} IN ('year', 'yearly', 'annual', 'annually'), {PRICE_VALUE_EXPR} / 12,
    {PRICE_PERIOD_EXPR} IN ('week', 'weekly'), {PRICE_VALUE_EXPR} * 52 / 12,
    {PRICE_PERIOD_EXPR} IN ('day', 'daily'), {PRICE_VALUE_EXPR} * 365 / 12,
    {PRICE_VALUE_EXPR}
)
"""


def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


def _json(value: Any) -> Any:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _as_list(value: Any) -> list[Any]:
    parsed = _json(value)
    return parsed if isinstance(parsed, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    parsed = _json(value)
    return parsed if isinstance(parsed, dict) else {}


def _listing_mode(category_id: int | None) -> ListingMode:
    return "rent" if category_id in RENT_CATEGORY_IDS else "sale"


def _category_ids(mode: ListingMode) -> tuple[int, ...]:
    return RENT_CATEGORY_IDS if mode == "rent" else SALE_CATEGORY_IDS


def _price_expr(price_basis: str) -> str:
    return MONTHLY_PRICE_EXPR if price_basis == "monthly" else PRICE_VALUE_EXPR


def _price_basis(value: str | None) -> str:
    return "monthly" if str(value or "").strip().lower() == "monthly" else "raw"


def _price_period(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def _listing_sql(sql: str) -> str:
    return sql.replace("{LISTINGS_TABLE}", LISTINGS_TABLE).replace(
        "{PRICE_VALUE_EXPR}", PRICE_VALUE_EXPR
    )


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _image_url(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _images(value: Any) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    for image in _as_list(value):
        if not isinstance(image, dict):
            continue
        normalized = {
            "small_url": _image_url(image.get("small_url") or image.get("small")),
            "medium_url": _image_url(image.get("medium_url") or image.get("medium")),
            "original_url": _image_url(
                image.get("original_url") or image.get("original") or image.get("large")
            ),
            "url": _image_url(image.get("url")),
            "label": image.get("classification_label") or image.get("label"),
        }
        if not any(
            normalized.get(key) for key in ("small_url", "medium_url", "original_url", "url")
        ):
            continue
        images.append(normalized)
    return images


def _primary_image(images: list[dict[str, Any]]) -> str | None:
    for image in images:
        for key in ("small_url", "medium_url", "original_url", "url"):
            if image.get(key):
                return str(image[key])
    return None


def _party(value: Any) -> ListingPartyResponse | None:
    data = _as_dict(value)
    if not data:
        return None
    normalized = {
        "id": None if data.get("id") is None else str(data.get("id")),
        "name": data.get("name"),
        "email": data.get("email"),
        "phone": data.get("phone"),
        "whatsapp": data.get("whatsapp"),
        "image_url": data.get("image_url") or data.get("image"),
        "logo_url": data.get("logo_url") or data.get("logo"),
        "address": data.get("address"),
        "slug": data.get("slug"),
        "is_super_agent": data.get("is_super_agent"),
        "languages": _as_list(data.get("languages")),
    }
    return ListingPartyResponse.model_validate(normalized)


def _floorplans(raw_property: dict[str, Any]) -> list[dict[str, Any]]:
    floorplans: list[dict[str, Any]] = []
    for item in _as_list(raw_property.get("floor_plans")):
        if not isinstance(item, dict):
            continue
        floorplans.append(
            {
                "title": item.get("title") or item.get("name"),
                "image_url": item.get("image_url") or item.get("url"),
                "area_sqft": _float_or_none(item.get("area")),
                "floor_number": _int_or_none(item.get("floor_number")),
                "unit_number": item.get("unit_number"),
                "dimension": item.get("dimension"),
            }
        )
    return floorplans


def _location_names(row: dict[str, Any]) -> list[str]:
    return [str(item) for item in _as_list(row.get("listing_location_names_json")) if item]


def _card_from_row(row: Any) -> ListingCardResponse:
    row = _row_to_dict(row)
    category_id = _int_or_none(row.get("category_id"))
    raw_property = _as_dict(row.get("raw_property_json"))
    price = _as_dict(row.get("price_json"))
    size = _as_dict(row.get("size_json"))
    names = _location_names(row)
    images = _images(row.get("images_json", row.get("images")))
    agent = _party(row.get("agent_json", row.get("agent")))
    broker = _party(row.get("broker_json", row.get("broker")))

    return ListingCardResponse(
        listing_id=str(row["listing_id"]),
        listing_mode=_listing_mode(category_id),
        title=str(row.get("title") or raw_property.get("title") or "Untitled listing"),
        reference=row.get("reference") or raw_property.get("reference"),
        property_type=raw_property.get("property_type")
        or row.get("property_type_name")
        or (str(row.get("property_type_id")) if row.get("property_type_id") is not None else None),
        price_value=_int_or_none(price.get("value")),
        price_currency=price.get("currency"),
        price_period=price.get("period"),
        size_value=_float_or_none(size.get("value")),
        size_unit=size.get("unit"),
        bedrooms=str(row.get("bedrooms")) if row.get("bedrooms") not in (None, "") else None,
        bathrooms=str(row.get("bathrooms")) if row.get("bathrooms") not in (None, "") else None,
        city_name=names[0] if len(names) > 0 else None,
        area_name=names[1] if len(names) > 1 else None,
        subcommunity_name=names[2] if len(names) > 2 else None,
        tower_name=names[3] if len(names) > 3 else None,
        location_name=", ".join(names) if names else None,
        latitude=_float_or_none(row.get("lat")),
        longitude=_float_or_none(row.get("lng")),
        primary_image_url=_primary_image(images),
        image_count=len(images),
        floorplan_count=len(_floorplans(raw_property)),
        agent_name=agent.name if agent else None,
        agent_image_url=agent.image_url if agent else None,
        broker_name=broker.name if broker else None,
        broker_logo_url=broker.logo_url if broker else None,
        listed_date=_parse_datetime(raw_property.get("listed_date")),
        is_available=_bool_or_none(row.get("is_available")),
        is_verified=_bool_or_none(row.get("is_verified")),
        is_featured=_bool_or_none(row.get("is_featured")),
        is_premium=_bool_or_none(row.get("is_premium")),
        share_url=row.get("share_url"),
    )


def _where_sql(
    mode: ListingMode,
    search: str | None,
    area: str | None,
    property_type: str | None,
    bedrooms: str | None,
    bedrooms_in: list[str] | None,
    price_min: int | None,
    price_max: int | None,
    price_period: str | None = None,
    price_basis: str = "raw",
) -> tuple[str, dict[str, Any]]:
    clauses = ["category_id IN {category_ids:Array(UInt16)}", "is_available = 1"]
    params: dict[str, Any] = {"category_ids": list(_category_ids(mode))}
    price_filter_expr = _price_expr(_price_basis(price_basis))
    if search:
        clauses.append(
            """
            (
                positionCaseInsensitive(title, {search:String}) > 0
                OR positionCaseInsensitive(reference, {search:String}) > 0
                OR positionCaseInsensitive(listing_location_names_json, {search:String}) > 0
                OR positionCaseInsensitive(agent_json, {search:String}) > 0
                OR positionCaseInsensitive(broker_json, {search:String}) > 0
            )
            """
        )
        params["search"] = search.strip()
    if area:
        clauses.append(
            "JSONExtract(listing_location_names_json, 'Array(String)')[2] = {area:String}"
        )
        params["area"] = area
    if property_type:
        clauses.append("JSON_VALUE(raw_property_json, '$.property_type') = {property_type:String}")
        params["property_type"] = property_type
    if bedrooms_in:
        clauses.append("bedrooms IN {bedrooms:Array(String)}")
        params["bedrooms"] = bedrooms_in
    elif bedrooms:
        clauses.append("bedrooms = {bedrooms:String}")
        params["bedrooms"] = bedrooms
    if normalized_period := _price_period(price_period):
        clauses.append(f"{PRICE_PERIOD_EXPR} = {{price_period:String}}")
        params["price_period"] = normalized_period
    if price_min is not None:
        clauses.append(f"{price_filter_expr} >= {{price_min:Int64}}")
        params["price_min"] = price_min
    if price_max is not None:
        clauses.append(f"{price_filter_expr} <= {{price_max:Int64}}")
        params["price_max"] = price_max
    return " AND ".join(clauses), params


async def _filters(mode: ListingMode) -> ListingFiltersResponse:
    params = {"category_ids": list(_category_ids(mode))}
    modes_result = await query(
        _listing_sql(
            """
        SELECT DISTINCT if(category_id IN (2, 4), 'rent', 'sale') AS listing_mode
        FROM {LISTINGS_TABLE}
        WHERE is_available = 1
        ORDER BY listing_mode
        """
        ),
        {},
    )
    areas_result = await query(
        _listing_sql(
            """
        SELECT JSONExtract(listing_location_names_json, 'Array(String)')[2] AS area_name, count() AS n
        FROM {LISTINGS_TABLE}
        WHERE category_id IN {category_ids:Array(UInt16)}
          AND is_available = 1
          AND area_name != ''
        GROUP BY area_name
        ORDER BY n DESC, area_name ASC
        LIMIT 60
        """
        ),
        params,
    )
    property_types_result = await query(
        _listing_sql(
            """
        SELECT JSON_VALUE(raw_property_json, '$.property_type') AS property_type, count() AS n
        FROM {LISTINGS_TABLE}
        WHERE category_id IN {category_ids:Array(UInt16)}
          AND is_available = 1
          AND property_type != ''
        GROUP BY property_type
        ORDER BY n DESC, property_type ASC
        LIMIT 40
        """
        ),
        params,
    )
    bedrooms_result = await query(
        _listing_sql(
            """
        SELECT bedrooms
        FROM {LISTINGS_TABLE}
        WHERE category_id IN {category_ids:Array(UInt16)}
          AND is_available = 1
          AND bedrooms != ''
        GROUP BY bedrooms
        ORDER BY toInt32OrNull(bedrooms) ASC NULLS FIRST, bedrooms ASC
        """
        ),
        params,
    )
    prices_result = await query(
        _listing_sql(
            """
        SELECT
            minIf({PRICE_VALUE_EXPR}, {PRICE_VALUE_EXPR} > 0)
                AS price_min,
            max({PRICE_VALUE_EXPR}) AS price_max
        FROM {LISTINGS_TABLE}
        WHERE category_id IN {category_ids:Array(UInt16)}
          AND is_available = 1
        """
        ),
        params,
    )
    prices = prices_result[0] if prices_result else {}
    return ListingFiltersResponse(
        modes=[row["listing_mode"] for row in modes_result],
        areas=[row["area_name"] for row in areas_result],
        property_types=[row["property_type"] for row in property_types_result],
        bedrooms=[row["bedrooms"] for row in bedrooms_result],
        price_min=_int_or_none(prices.get("price_min")),
        price_max=_int_or_none(prices.get("price_max")),
    )


async def list_listings_from_clickhouse(
    mode: ListingMode,
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
) -> ListingListResponse:
    price_sort_expr = _price_expr(_price_basis(price_basis))
    where, params = _where_sql(
        mode=mode,
        search=search,
        area=area,
        property_type=property_type,
        bedrooms=bedrooms,
        bedrooms_in=bedrooms_in,
        price_min=price_min,
        price_max=price_max,
        price_period=price_period,
        price_basis=price_basis,
    )
    rows = await query(
        f"""
        SELECT
            listing_id,
            category_id,
            title,
            reference,
            property_type_id,
            price_json,
            size_json,
            bedrooms,
            bathrooms,
            listing_location_names_json,
            lat,
            lng,
            is_available,
            is_verified,
            is_featured,
            is_premium,
            share_url,
            agent_json,
            broker_json,
            client_json,
            images_json,
            raw_property_json,
            run_id,
            scraped_at
        FROM {LISTINGS_TABLE}
        WHERE {where}
        ORDER BY
            is_featured DESC,
            is_premium DESC,
            parseDateTimeBestEffortOrNull(scraped_at) DESC NULLS LAST,
            {price_sort_expr} ASC NULLS LAST
        LIMIT {{limit:Int32}} OFFSET {{offset:Int32}}
        """,
        {**params, "limit": limit, "offset": offset},
    )
    count_result = await query(
        f"""
        SELECT count() AS total
        FROM {LISTINGS_TABLE}
        WHERE {where}
        """,
        params,
    )
    return ListingListResponse(
        listings=[_card_from_row(row) for row in rows],
        total=count_result[0]["total"] if count_result else 0,
        limit=limit,
        offset=offset,
        filters=await _filters(mode),
    )


async def listing_analytics_from_clickhouse(
    mode: ListingMode,
    search: str | None = None,
    area: str | None = None,
    property_type: str | None = None,
    bedrooms: str | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
) -> ListingAnalyticsResponse:
    """Return aggregate metrics for the same available-listing filter set as the grid."""
    where, params = _where_sql(
        mode=mode,
        search=search,
        area=area,
        property_type=property_type,
        bedrooms=bedrooms,
        bedrooms_in=None,
        price_min=price_min,
        price_max=price_max,
    )
    size_expr = "JSONExtractFloat(size_json, 'value')"
    result = await query(
        f"""
        SELECT
            count() AS total,
            quantileTDigestIf(0.5)({PRICE_VALUE_EXPR}, {PRICE_VALUE_EXPR} > 0) AS median_price_aed,
            quantileTDigestIf(
                0.5
            )({PRICE_VALUE_EXPR} / {size_expr}, {PRICE_VALUE_EXPR} > 0 AND {size_expr} > 0)
                AS median_price_per_sqft_aed,
            countIf(is_verified = 1) AS verified_count,
            uniqExact(JSONExtract(listing_location_names_json, 'Array(String)')[2]) AS area_count
        FROM {LISTINGS_TABLE}
        WHERE {where}
        """,
        params,
    )
    row = result[0] if result else {}
    return ListingAnalyticsResponse(
        total=_int_or_none(row.get("total")) or 0,
        median_price_aed=_float_or_none(row.get("median_price_aed")),
        median_price_per_sqft_aed=_float_or_none(row.get("median_price_per_sqft_aed")),
        verified_count=_int_or_none(row.get("verified_count")) or 0,
        area_count=_int_or_none(row.get("area_count")) or 0,
    )


async def get_listing_from_clickhouse(listing_id: str) -> ListingDetailResponse:
    rows = await query(
        _listing_sql(
            """
        SELECT
            listing_id,
            category_id,
            title,
            reference,
            property_type_id,
            price_json,
            size_json,
            bedrooms,
            bathrooms,
            listing_location_names_json,
            lat,
            lng,
            is_available,
            is_verified,
            is_featured,
            is_premium,
            share_url,
            agent_json,
            broker_json,
            client_json,
            images_json,
            raw_property_json,
            raw_wrapper_json,
            run_id,
            scraped_at
        FROM {LISTINGS_TABLE}
        WHERE listing_id = {listing_id:String}
        LIMIT 1
        """
        ),
        {"listing_id": listing_id},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Listing not found")

    data = rows[0]
    raw_property = _as_dict(data.get("raw_property_json"))
    card = _card_from_row(data)
    amenities = raw_property.get("amenity_names") or raw_property.get("amenities")
    return ListingDetailResponse(
        **card.model_dump(),
        description=raw_property.get("description"),
        amenities=[str(item) for item in _as_list(amenities) if item],
        images=[
            ListingImageResponse.model_validate(item) for item in _images(data.get("images_json"))
        ],
        floorplans=[
            ListingFloorPlanResponse.model_validate(item) for item in _floorplans(raw_property)
        ],
        agent=_party(data.get("agent_json")),
        broker=_party(data.get("broker_json")),
        client=_party(data.get("client_json")),
        furnished=raw_property.get("furnished"),
        completion_status=raw_property.get("completion_status"),
        rera=raw_property.get("rera"),
        number_of_cheques=_int_or_none(raw_property.get("number_of_cheques")),
        payment_method=[str(item) for item in _as_list(raw_property.get("payment_method"))],
        video_url=raw_property.get("video_url"),
        view_360_url=raw_property.get("view_360"),
        source_run_id=data.get("run_id"),
        source_manifest_key=None,
        scraped_at=_parse_datetime(data.get("scraped_at")),
        source_metadata={
            "source": LISTINGS_SOURCE_LABEL,
            "run_id": data.get("run_id"),
        },
    )
