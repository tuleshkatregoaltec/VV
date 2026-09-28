from typing import Any

from app.clickhouse.client import query as ch_query
from app.listings.models import ListingMode
from app.market.reference import listing_area_terms


async def resolve_listing_area(mode: ListingMode, area: str | None) -> str | None:
    if not area:
        return None

    terms = listing_area_terms(area)
    params: dict[str, Any] = {
        "category_ids": [2, 4] if mode == "rent" else [1, 3],
        "area": area,
        "primary": terms[0],
    }
    match_clauses = []
    for index, term in enumerate(terms):
        term_key = f"area_term_{index}"
        params[term_key] = term
        match_clauses.append(
            f"""
            lower(area_name) = lower({{{term_key}:String}})
            OR positionCaseInsensitive(listing_location_names_json, {{{term_key}:String}}) > 0
            """
        )

    rows = await ch_query(
        f"""
        SELECT JSONExtract(listing_location_names_json, 'Array(String)')[2] AS area_name
        FROM pf_listings_bronze
        WHERE category_id IN {{category_ids:Array(UInt16)}}
          AND is_available = 1
          AND area_name != ''
          AND ({" OR ".join(f"({clause})" for clause in match_clauses)})
        GROUP BY area_name
        ORDER BY
            (lower(area_name) = lower({{area:String}})) DESC,
            (lower(area_name) = lower({{primary:String}})) DESC,
            count() DESC,
            area_name ASC
        LIMIT 1
        """,
        params,
    )
    return rows[0]["area_name"] if rows else area
