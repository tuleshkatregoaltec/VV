"""Property Finder inventory selected for the organization's Company listings and matches."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import datetime, timezone

from clickhouse_connect.driver.exceptions import ClickHouseError
from fastapi import HTTPException
from sqlalchemy import update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.clickhouse.client import query
from app.crm.inbound_models import CrmInboundEnquiry, CrmInboundMatch
from app.crm.models import (
    CrmCompanyListing,
    CrmCompanyListingAgentInventory,
    CrmCompanyListingCompany,
    CrmCompanyListingDetail,
    CrmCompanyListingResponse,
    CrmCompanyListingSource,
    CrmCompanyListingsResponse,
)

logger = logging.getLogger(__name__)

_CURRENT_LISTINGS = """
WITH latest_keys AS (
    SELECT property_key, listing_id, run_id, scraped_at
    FROM pf_listings_bronze
    WHERE property_key != ''
    ORDER BY property_key, scraped_at DESC, run_id DESC
    LIMIT 1 BY property_key
), latest AS (
    SELECT
        p.property_key,
        p.listing_id,
        p.run_id,
        p.scraped_at,
        p.title,
        p.category_id,
        p.raw_property_json,
        p.price_json,
        p.size_json,
        p.bedrooms,
        p.listing_location_names_json,
        p.broker_json,
        p.agent_json,
        p.images_json,
        p.is_available
    FROM pf_listings_bronze AS p
    INNER JOIN latest_keys AS k
        ON p.property_key = k.property_key
        AND p.listing_id = k.listing_id
        AND p.run_id = k.run_id
        AND p.scraped_at = k.scraped_at
), current_listings AS (
    SELECT
        property_key,
        toString(listing_id) AS listing_id,
        title,
        category_id,
        JSONExtractString(raw_property_json, 'property_type') AS property_type,
        if(category_id IN (2, 4), 'rent', 'sale') AS mode,
        toInt64(JSONExtractInt(price_json, 'value') * multiIf(
            lowerUTF8(JSONExtractString(price_json, 'period')) IN ('month', 'monthly'), 12,
            lowerUTF8(JSONExtractString(price_json, 'period')) IN ('week', 'weekly'), 52,
            lowerUTF8(JSONExtractString(price_json, 'period')) IN ('day', 'daily'), 365,
            1
        )) AS price_aed,
        nullIf(toInt64(JSONExtractFloat(size_json, 'value')), 0) AS size_sqft,
        bedrooms,
        arrayElement(JSONExtract(listing_location_names_json, 'Array(String)'), 2) AS area_name,
        if(
            length(JSONExtract(listing_location_names_json, 'Array(String)')) > 2,
            arrayElement(JSONExtract(listing_location_names_json, 'Array(String)'), -1),
            ''
        ) AS building_name,
        JSONExtractString(broker_json, 'id') AS broker_id,
        JSONExtractString(broker_json, 'name') AS broker_name,
        JSONExtractString(agent_json, 'id') AS agent_id,
        JSONExtractString(agent_json, 'name') AS agent_name,
        -- Property Finder publishes the agent's own number in the listing's contact options
        -- (agent_json has no phone); the email is on agent_json.
        JSONExtractString(
            arrayFirst(
                option -> JSONExtractString(option, 'type') = 'phone',
                JSONExtractArrayRaw(raw_property_json, 'contact_options')
            ),
            'value'
        ) AS agent_phone,
        JSONExtractString(agent_json, 'email') AS agent_email,
        parseDateTimeBestEffortOrNull(scraped_at) AS scraped_at_dt,
        images_json,
        JSONExtractString(raw_property_json, 'description') AS description,
        coalesce(
            parseDateTimeBestEffortOrNull(JSON_VALUE(raw_property_json, '$.listed_date')),
            parseDateTimeBestEffortOrNull(scraped_at)
        ) AS listed_at,
        is_available
    FROM latest
    WHERE category_id IN (1, 2, 3, 4)
)
"""

_COMPANY_LISTING_FIELDS = """
    broker_id != '' AND broker_name != '' AND property_type != ''
    AND price_aed > 0 AND area_name != ''
"""


def _company(row) -> CrmCompanyListingCompany:
    return CrmCompanyListingCompany(
        broker_id=str(row["broker_id"]),
        broker_name=str(row["company_name"]),
        listings=int(row["listings"]),
        agents=int(row["agents"]),
        last_scraped_at=row["last_scraped_at"],
    )


async def list_property_finder_companies() -> list[CrmCompanyListingCompany]:
    rows = await query(
        f"""{_CURRENT_LISTINGS}
        SELECT
            broker_id,
            argMax(broker_name, scraped_at_dt) AS company_name,
            count() AS listings,
            uniqExactIf(
                if(agent_id = '', concat('name:', agent_name), concat('id:', agent_id)),
                agent_id != '' OR agent_name != ''
            ) AS agents,
            max(scraped_at_dt) AS last_scraped_at
        FROM current_listings
        WHERE is_available = 1 AND {_COMPANY_LISTING_FIELDS}
        GROUP BY broker_id
        ORDER BY listings DESC, company_name ASC
        """
    )
    return [_company(row) for row in rows]


async def _selected_source(
    db: AsyncSession, organization_id: str
) -> CrmCompanyListingSource | None:
    return await db.get(CrmCompanyListingSource, organization_id)


def _bedrooms(value: str | None) -> int | None:
    normalized = str(value or "").strip().casefold()
    if normalized == "studio":
        return 0
    digits = normalized.rstrip("+")
    return int(digits) if digits.isdigit() else None


def _aware(value: datetime | None) -> datetime | None:
    # ClickHouse returns naive datetimes; they are UTC.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _listing(row, organization_id: str, now: datetime) -> CrmCompanyListing:
    reference = str(row["listing_id"] or row["property_key"])
    agent = str(row["agent_name"] or "Agent not listed")
    company = str(row["broker_name"] or "Property Finder company")
    phone = str(row["agent_phone"] or "").strip() or None
    return CrmCompanyListing(
        organization_id=organization_id,
        reference=f"PF-{reference}",
        agent_name=f"{company} · {agent}",
        agent_phone=phone,
        mode=str(row["mode"]),
        title=str(row["title"] or row["building_name"] or "Property Finder listing"),
        property_type=str(row["property_type"]),
        bedrooms=_bedrooms(row["bedrooms"]),
        size_sqft=row["size_sqft"],
        price_aed=int(row["price_aed"]),
        area_name=str(row["area_name"]),
        building_name=str(row["building_name"] or "").strip() or None,
        status="active",
        is_synthetic=False,
        listed_at=_aware(row["listed_at"]) or now,
        created_at=now,
        updated_at=now,
    )


async def _company_rows(
    broker_id: str | None,
    *,
    limit: int,
    offset: int,
    agent_id: str | None = None,
    agent_name: str | None = None,
    search: str | None = None,
) -> list[dict]:
    agent_filter = ""
    search_filter = ""
    parameters: dict[str, object] = {"limit": limit, "offset": offset}
    broker_filter = ""
    if broker_id:
        broker_filter = "AND broker_id = {broker_id:String}"
        parameters["broker_id"] = broker_id
    if agent_id:
        agent_filter = "AND agent_id = {agent_id:String}"
        parameters["agent_id"] = agent_id
    elif agent_name:
        agent_filter = "AND agent_id = '' AND if(agent_name = '', 'Agent not listed', agent_name) = {agent_name:String}"
        parameters["agent_name"] = agent_name
    if search and search.strip():
        # Property name: the listing title, its building or its area.
        search_filter = (
            "AND positionCaseInsensitiveUTF8("
            "concat(title, ' ', building_name, ' ', area_name), {search:String}) > 0"
        )
        parameters["search"] = search.strip()
    return await query(
        f"""{_CURRENT_LISTINGS}
        SELECT * EXCEPT (images_json, description), count() OVER () AS matched_total
        FROM current_listings
        WHERE is_available = 1 AND {_COMPANY_LISTING_FIELDS}
          {broker_filter}
          {agent_filter}
          {search_filter}
        ORDER BY listed_at DESC NULLS LAST, listing_id ASC
        LIMIT {{limit:Int32}}
        OFFSET {{offset:Int32}}
        """,
        parameters,
    )


async def _agent_inventory(broker_id: str) -> list[CrmCompanyListingAgentInventory]:
    rows = await query(
        f"""{_CURRENT_LISTINGS}
        SELECT
            nullIf(agent_id, '') AS agent_id,
            if(agent_name = '', 'Agent not listed', agent_name) AS display_name,
            count() AS listings,
            anyIf(agent_phone, agent_phone != '') AS agent_phone,
            anyIf(agent_email, agent_email != '') AS agent_email
        FROM current_listings
        WHERE is_available = 1 AND {_COMPANY_LISTING_FIELDS}
          AND broker_id = {{broker_id:String}}
        GROUP BY agent_id, display_name
        ORDER BY listings DESC, display_name ASC
        """,
        {"broker_id": broker_id},
    )
    return [
        CrmCompanyListingAgentInventory(
            agent_id=row["agent_id"],
            agent_name=row["display_name"],
            listings=int(row["listings"]),
            phone=str(row.get("agent_phone") or "").strip() or None,
            email=str(row.get("agent_email") or "").strip() or None,
        )
        for row in rows
    ]


async def list_company_listings(
    db: AsyncSession,
    organization_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
    broker_id: str | None = None,
    all_companies: bool = False,
    agent_id: str | None = None,
    agent_name: str | None = None,
    search: str | None = None,
) -> CrmCompanyListingsResponse:
    companies = await list_property_finder_companies()
    source = await _selected_source(db, organization_id)
    matching_company = next(
        (item for item in companies if source and item.broker_id == source.broker_id),
        CrmCompanyListingCompany(
            broker_id=source.broker_id,
            broker_name=source.broker_name,
            listings=0,
            agents=0,
            last_scraped_at=None,
        )
        if source
        else None,
    )
    company = next((item for item in companies if item.broker_id == broker_id), None)
    if broker_id and company is None:
        company = CrmCompanyListingCompany(
            broker_id=broker_id,
            broker_name=broker_id,
            listings=0,
            agents=0,
            last_scraped_at=None,
        )
    if not all_companies and not broker_id:
        company = matching_company
        if company is None:
            return CrmCompanyListingsResponse(
                company=None,
                matching_company=None,
                companies=companies,
                limit=limit,
                offset=offset,
            )

    agent_inventory = await _agent_inventory(broker_id) if broker_id else []
    selected_agent = next(
        (
            agent
            for agent in agent_inventory
            if (agent_id and agent.agent_id == agent_id)
            or (agent_name and agent.agent_id is None and agent.agent_name == agent_name)
        ),
        None,
    )
    rows = await _company_rows(
        broker_id if all_companies else (company.broker_id if company else None),
        limit=limit,
        offset=offset,
        agent_id=agent_id,
        agent_name=agent_name,
        search=search,
    )
    now = datetime.now(timezone.utc)
    photos = await _page_photos([str(row["listing_id"]) for row in rows if row.get("listing_id")])
    items = [
        CrmCompanyListingResponse.model_validate(
            _listing(row, organization_id, now), from_attributes=True
        ).model_copy(update={"photos": photos.get(str(row.get("listing_id")), [])})
        for row in rows
    ]
    return CrmCompanyListingsResponse(
        company=company,
        matching_company=matching_company,
        companies=companies,
        agents=agent_inventory,
        items=items,
        # A search counts its matches; otherwise the agent's or company's listing total.
        total=int(rows[0]["matched_total"])
        if rows
        else 0
        if search and search.strip()
        else selected_agent.listings
        if selected_agent
        else (
            0
            if agent_id or agent_name
            else company.listings
            if company
            else sum(item.listings for item in companies)
        ),
        limit=limit,
        offset=offset,
    )


async def get_company_listing(
    db: AsyncSession, organization_id: str, listing_key: str
) -> CrmCompanyListingDetail | None:
    """A currently published Property Finder listing by its listing id, or None."""
    rows = await query(
        f"""{_CURRENT_LISTINGS}
        SELECT * EXCEPT (images_json, description)
        FROM current_listings
        WHERE is_available = 1 AND listing_id = {{listing_key:String}} AND {_COMPANY_LISTING_FIELDS}
        LIMIT 1
        """,
        {"listing_key": listing_key},
    )
    if not rows:
        return None
    row = rows[0]
    source = await _selected_source(db, organization_id)
    listing = CrmCompanyListingResponse.model_validate(
        _listing(row, organization_id, datetime.now(timezone.utc)), from_attributes=True
    )
    broker_id = str(row["broker_id"])
    return CrmCompanyListingDetail(
        **listing.model_dump(),
        listing_key=listing_key,
        broker_id=broker_id,
        broker_name=str(row["broker_name"]),
        managed=source is not None and source.broker_id == broker_id,
    )


# The warehouse stores {"medium", "small", "classification_label"}; the *_url names are fallbacks.
_PHOTO_URL_KEYS = ("medium", "medium_url", "original", "original_url", "url", "small", "small_url")


def _photos(images_json: object) -> list[str]:
    """Image URLs from Property Finder's `images_json` (a list of objects with sized URLs)."""
    try:
        images = json.loads(str(images_json or "[]"))
    except ValueError:
        return []
    photos: list[str] = []
    for image in images if isinstance(images, list) else []:
        if not isinstance(image, dict):
            continue
        url = next((image[key] for key in _PHOTO_URL_KEYS if image.get(key)), None)
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            photos.append(url)
    return photos


CARD_PHOTOS = 5


async def _page_photos(keys: Sequence[str]) -> dict[str, list[str]]:
    """Up to CARD_PHOTOS photo URLs per listing, for one page of cards, in one small query.

    Kept out of the paged query so ranking 228k listings never reads the heavy images column.
    Photos are decoration: if the warehouse fails here, the cards still load without them.
    """
    unique = list(dict.fromkeys(keys))
    if not unique:
        return {}
    try:
        rows = await query(
            f"""{_CURRENT_LISTINGS}
            SELECT listing_id, images_json
            FROM current_listings
            WHERE listing_id IN {{keys:Array(String)}}
            """,
            {"keys": unique},
        )
    except (ClickHouseError, OSError):
        logger.warning("crm.company_listings.photos_unavailable")
        return {}
    return {str(row["listing_id"]): _photos(row.get("images_json"))[:CARD_PHOTOS] for row in rows}


async def listings_by_keys(
    db: AsyncSession, organization_id: str, keys: Sequence[str]
) -> dict[str, CrmCompanyListingDetail]:
    """Currently published listings by listing id, in one query; absent keys are not returned.

    Verified on the shared ClickHouse: `raw_property_json` has a `description` key, and
    `images_json` is a list of objects `{"medium": url, "small": url, "classification_label": ""}`.
    Photos use `medium`, falling back to the other size keys.
    `managed` is set per row, so callers decide whether an unmanaged listing may be shown.
    ClickHouse errors propagate.
    """
    unique = list(dict.fromkeys(keys))
    if not unique:
        return {}
    rows = await query(
        f"""{_CURRENT_LISTINGS}
        SELECT *
        FROM current_listings
        WHERE is_available = 1 AND listing_id IN {{keys:Array(String)}} AND {_COMPANY_LISTING_FIELDS}
        """,
        {"keys": unique},
    )
    source = await _selected_source(db, organization_id)
    now = datetime.now(timezone.utc)
    found: dict[str, CrmCompanyListingDetail] = {}
    for row in rows:
        listing = CrmCompanyListingResponse.model_validate(
            _listing(row, organization_id, now), from_attributes=True
        )
        broker_id = str(row["broker_id"])
        key = str(row["listing_id"])
        found[key] = CrmCompanyListingDetail(
            **listing.model_dump(exclude={"photos"}),
            listing_key=key,
            broker_id=broker_id,
            broker_name=str(row["broker_name"]),
            managed=source is not None and source.broker_id == broker_id,
            photos=_photos(row.get("images_json")),
            description=str(row.get("description") or "").strip() or None,
            updated_at=_aware(row.get("scraped_at_dt")),
        )
    return found


async def select_company_source(
    db: AsyncSession, *, organization_id: str, user_id: str, broker_id: str
) -> CrmCompanyListingSource:
    companies = await list_property_finder_companies()
    selected = next((item for item in companies if item.broker_id == broker_id), None)
    if selected is None:
        raise HTTPException(status_code=404, detail="Property Finder company not found")

    now = datetime.now(timezone.utc)
    record = await _selected_source(db, organization_id)
    changed = record is None or record.broker_id != selected.broker_id
    if record is None:
        record = CrmCompanyListingSource(
            organization_id=organization_id,
            broker_id=selected.broker_id,
            broker_name=selected.broker_name,
            selected_by_user_id=user_id,
            created_at=now,
            updated_at=now,
        )
    else:
        record.broker_id = selected.broker_id
        record.broker_name = selected.broker_name
        record.selected_by_user_id = user_id
        record.updated_at = now
    db.add(record)
    if changed:
        await _rerun_buyer_matches(db, organization_id, now)
    await db.commit()
    await db.refresh(record)
    return record


async def clear_company_source(db: AsyncSession, *, organization_id: str) -> None:
    """Stop matching buyers and tenants against any company's listings."""
    record = await _selected_source(db, organization_id)
    if record is None:
        return
    await db.delete(record)
    await _rerun_buyer_matches(db, organization_id, datetime.now(timezone.utc))
    await db.commit()


async def _rerun_buyer_matches(db: AsyncSession, organization_id: str, now: datetime) -> None:
    """Buyers' and tenants' stored matches re-run on next load (the company lane changed)."""
    buyer_enquiries = select(CrmInboundEnquiry.id).where(
        CrmInboundEnquiry.organization_id == organization_id,
        CrmInboundEnquiry.intent.in_(["buy", "rent"]),  # type: ignore[attr-defined]
    )
    await db.exec(
        update(CrmInboundMatch)
        .where(
            CrmInboundMatch.organization_id == organization_id,
            CrmInboundMatch.enquiry_id.in_(buyer_enquiries),  # type: ignore[attr-defined]
        )
        .values(algorithm_version="source_changed", updated_at=now)
    )


async def find_matching_company_listings(
    db: AsyncSession,
    organization_id: str,
    *,
    mode: str,
    locations: list[str],
    band: tuple[int, int] | None,
    property_type: str | None,
    bedrooms: list[str] | None,
) -> list[CrmCompanyListing]:
    source = await _selected_source(db, organization_id)
    if source is None:
        return []

    clauses = ["is_available = 1", _COMPANY_LISTING_FIELDS, "broker_id = {broker_id:String}"]
    parameters: dict[str, object] = {
        "broker_id": source.broker_id,
        "category_ids": [2, 4] if mode == "rent" else [1, 3],
        "limit": 200,
    }
    clauses.append("category_id IN {category_ids:Array(UInt16)}")
    if locations:
        location_clauses = []
        for index, location in enumerate(locations):
            key = f"location_{index}"
            parameters[key] = location
            location_clauses.append(
                f"positionCaseInsensitive(area_name, {{{key}:String}}) > 0 "
                f"OR positionCaseInsensitive(building_name, {{{key}:String}}) > 0"
            )
        clauses.append(f"({' OR '.join(f'({item})' for item in location_clauses)})")
    if band:
        clauses.append("price_aed BETWEEN {price_min:Int64} AND {price_max:Int64}")
        parameters.update(price_min=band[0], price_max=band[1])
    if property_type:
        clauses.append("lowerUTF8(property_type) = lowerUTF8({property_type:String})")
        parameters["property_type"] = property_type
    if bedrooms:
        clauses.append(
            "multiIf(lowerUTF8(bedrooms) = 'studio', 'studio', replaceAll(bedrooms, '+', '')) "
            "IN {bedrooms:Array(String)}"
        )
        parameters["bedrooms"] = bedrooms

    rows = await query(
        f"""{_CURRENT_LISTINGS}
        SELECT * EXCEPT (images_json, description) FROM current_listings
        WHERE {" AND ".join(f"({item})" for item in clauses)}
        ORDER BY listed_at DESC NULLS LAST, listing_id ASC
        LIMIT {{limit:Int32}}
        """,
        parameters,
    )
    now = datetime.now(timezone.utc)
    return [_listing(row, organization_id, now) for row in rows]
