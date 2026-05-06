"""Demo-only PropertyFinder listings service.

The data behind this module is loaded by backend/scripts/listings/import_pf_listings_demo.py
into local Postgres tables. It is intentionally shaped for the May 2026 demo, not as a
production ingestion path.
"""

from datetime import timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.listings.models import (
    ListingCardResponse,
    ListingDetailResponse,
    ListingFiltersResponse,
    ListingFloorPlanResponse,
    ListingImageResponse,
    ListingListResponse,
    ListingMode,
    ListingPartyResponse,
)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _aware(value: Any) -> Any:
    if value is not None and getattr(value, "tzinfo", None) is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _demo_table_missing(exc: Exception) -> bool:
    message = str(exc).lower()
    return "demo_pf_listings" in message and (
        "does not exist" in message or "undefinedtable" in message
    )


def _primary_image(images: list[Any]) -> str | None:
    for image in images:
        for key in ("small_url", "medium_url", "original_url", "url"):
            value = _as_dict(image).get(key)
            if value:
                return str(value)
    return None


def _available_image_count(images: list[Any]) -> int:
    return sum(
        1
        for image in images
        if any(
            _as_dict(image).get(key) for key in ("small_url", "medium_url", "original_url", "url")
        )
    )


def _card_from_row(row: Any) -> ListingCardResponse:
    data = dict(row._mapping)
    images = _as_list(data.get("images"))
    agent = _as_dict(data.get("agent"))
    broker = _as_dict(data.get("broker"))

    return ListingCardResponse(
        listing_id=data["listing_id"],
        listing_mode=data["listing_mode"],
        title=data["title"],
        reference=data.get("reference"),
        property_type=data.get("property_type"),
        price_value=data.get("price_value"),
        price_currency=data.get("price_currency"),
        price_period=data.get("price_period"),
        size_value=data.get("size_value"),
        size_unit=data.get("size_unit"),
        bedrooms=data.get("bedrooms"),
        bathrooms=data.get("bathrooms"),
        city_name=data.get("city_name"),
        area_name=data.get("area_name"),
        subcommunity_name=data.get("subcommunity_name"),
        tower_name=data.get("tower_name"),
        location_name=data.get("location_name"),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        primary_image_url=_primary_image(images),
        image_count=_available_image_count(images),
        floorplan_count=data.get("floorplan_count") or len(_as_list(data.get("floorplans"))),
        agent_name=agent.get("name"),
        agent_image_url=agent.get("image_url"),
        broker_name=broker.get("name"),
        broker_logo_url=broker.get("logo_url"),
        listed_date=_aware(data.get("listed_date")),
        is_available=data.get("is_available"),
        is_verified=data.get("is_verified"),
        is_featured=data.get("is_featured"),
        is_premium=data.get("is_premium"),
        share_url=data.get("share_url"),
    )


def _party(value: Any) -> ListingPartyResponse | None:
    data = _as_dict(value)
    if not data:
        return None
    return ListingPartyResponse.model_validate(data)


def _sql_filters(
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
    clauses = ["listing_mode = :mode"]
    params: dict[str, Any] = {"mode": mode}
    if search:
        clauses.append(
            """
            (
                title ILIKE :search
                OR reference ILIKE :search
                OR location_name ILIKE :search
                OR area_name ILIKE :search
                OR subcommunity_name ILIKE :search
                OR tower_name ILIKE :search
                OR agent->>'name' ILIKE :search
                OR broker->>'name' ILIKE :search
            )
            """
        )
        params["search"] = f"%{search}%"
    if area:
        clauses.append("area_name = :area")
        params["area"] = area
    if property_type:
        clauses.append("property_type = :property_type")
        params["property_type"] = property_type
    if bedrooms:
        clauses.append("bedrooms = :bedrooms")
        params["bedrooms"] = bedrooms
    elif bedrooms_in:
        bedroom_placeholders = []
        for index, bedroom in enumerate(bedrooms_in):
            key = f"bedroom_{index}"
            bedroom_placeholders.append(f":{key}")
            params[key] = bedroom
        clauses.append(f"bedrooms IN ({', '.join(bedroom_placeholders)})")
    if price_period:
        clauses.append("price_period = :price_period")
        params["price_period"] = price_period
    price_expr = (
        """
        CASE
            WHEN listing_mode = 'rent' AND lower(COALESCE(price_period, '')) LIKE 'year%'
                THEN price_value / 12.0
            ELSE price_value
        END
        """
        if price_basis == "monthly"
        else "price_value"
    )
    if price_min is not None:
        clauses.append(f"{price_expr} >= :price_min")
        params["price_min"] = price_min
    if price_max is not None:
        clauses.append(f"{price_expr} <= :price_max")
        params["price_max"] = price_max
    return "WHERE " + " AND ".join(clauses), params


async def _filters(db: AsyncSession, mode: ListingMode) -> ListingFiltersResponse:
    modes_result = await db.execute(
        text(
            """
            SELECT listing_mode
            FROM demo_pf_listings
            GROUP BY listing_mode
            ORDER BY listing_mode ASC
            """
        )
    )
    areas_result = await db.execute(
        text(
            """
            SELECT area_name
            FROM demo_pf_listings
            WHERE listing_mode = :mode AND area_name IS NOT NULL AND area_name <> ''
            GROUP BY area_name
            ORDER BY COUNT(*) DESC, area_name ASC
            LIMIT 60
            """
        ),
        {"mode": mode},
    )
    property_types_result = await db.execute(
        text(
            """
            SELECT property_type
            FROM demo_pf_listings
            WHERE listing_mode = :mode AND property_type IS NOT NULL AND property_type <> ''
            GROUP BY property_type
            ORDER BY COUNT(*) DESC, property_type ASC
            LIMIT 40
            """
        ),
        {"mode": mode},
    )
    bedrooms_result = await db.execute(
        text(
            """
            SELECT bedrooms
            FROM demo_pf_listings
            WHERE listing_mode = :mode AND bedrooms IS NOT NULL AND bedrooms <> ''
            GROUP BY bedrooms
            ORDER BY
                CASE WHEN bedrooms = 'studio' THEN -1 ELSE NULLIF(regexp_replace(bedrooms, '\\D', '', 'g'), '')::int END ASC NULLS LAST,
                bedrooms ASC
            """
        ),
        {"mode": mode},
    )
    prices_result = await db.execute(
        text(
            """
            SELECT MIN(price_value), MAX(price_value)
            FROM demo_pf_listings
            WHERE listing_mode = :mode AND price_value IS NOT NULL AND price_value > 0
            """
        ),
        {"mode": mode},
    )
    price_min, price_max = prices_result.one()
    return ListingFiltersResponse(
        modes=[row[0] for row in modes_result.fetchall()],
        areas=[row[0] for row in areas_result.fetchall()],
        property_types=[row[0] for row in property_types_result.fetchall()],
        bedrooms=[row[0] for row in bedrooms_result.fetchall()],
        price_min=price_min,
        price_max=price_max,
    )


async def list_demo_listings(
    db: AsyncSession,
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
    where, params = _sql_filters(
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
    query_params = {**params, "limit": limit, "offset": offset}

    try:
        rows_result = await db.execute(
            text(
                f"""
                SELECT *
                FROM demo_pf_listings
                {where}
                ORDER BY
                    COALESCE(is_featured, false) DESC,
                    COALESCE(is_premium, false) DESC,
                    listed_date DESC NULLS LAST,
                    scraped_at DESC NULLS LAST,
                    price_value ASC NULLS LAST
                LIMIT :limit OFFSET :offset
                """
            ),
            query_params,
        )
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM demo_pf_listings {where}"),
            params,
        )
        filters = await _filters(db, mode)
    except ProgrammingError as exc:
        if _demo_table_missing(exc):
            await db.rollback()
            return ListingListResponse(
                listings=[],
                total=0,
                limit=limit,
                offset=offset,
                filters=ListingFiltersResponse(),
            )
        raise

    return ListingListResponse(
        listings=[_card_from_row(row) for row in rows_result.fetchall()],
        total=count_result.scalar_one(),
        limit=limit,
        offset=offset,
        filters=filters,
    )


async def get_demo_listing(db: AsyncSession, listing_id: str) -> ListingDetailResponse:
    try:
        result = await db.execute(
            text("SELECT * FROM demo_pf_listings WHERE listing_id = :listing_id"),
            {"listing_id": listing_id},
        )
    except ProgrammingError as exc:
        if _demo_table_missing(exc):
            await db.rollback()
            raise HTTPException(
                status_code=404, detail="Listings demo table is not loaded"
            ) from exc
        raise

    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Listing not found")

    data = dict(row._mapping)
    card = _card_from_row(row)
    return ListingDetailResponse(
        **card.model_dump(),
        description=data.get("description"),
        amenities=[str(item) for item in _as_list(data.get("amenities")) if item],
        images=[
            ListingImageResponse.model_validate(item)
            for item in _as_list(data.get("images"))
            if isinstance(item, dict)
        ],
        floorplans=[
            ListingFloorPlanResponse.model_validate(item)
            for item in _as_list(data.get("floorplans"))
            if isinstance(item, dict)
        ],
        agent=_party(data.get("agent")),
        broker=_party(data.get("broker")),
        client=_party(data.get("client")),
        furnished=data.get("furnished"),
        completion_status=data.get("completion_status"),
        rera=data.get("rera"),
        number_of_cheques=data.get("number_of_cheques"),
        payment_method=[str(item) for item in _as_list(data.get("payment_method")) if item],
        video_url=data.get("video_url"),
        view_360_url=data.get("view_360_url"),
        source_run_id=data.get("source_run_id"),
        source_manifest_key=data.get("source_manifest_key"),
        scraped_at=_aware(data.get("scraped_at")),
        demo_metadata={
            "source": "PropertyFinder listings R2 demo import",
            "imported_at": data.get("imported_at").isoformat()
            if data.get("imported_at") is not None
            else None,
        },
    )
