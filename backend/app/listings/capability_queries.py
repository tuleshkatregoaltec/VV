"""Parameter-bound, contact-free listing evidence queries over the current PF snapshot."""

from app.clickhouse import query
from app.listings import queries
from app.listings.capability_models import ListingEvidenceRequest

# Units are checked explicitly; an unknown unit cannot silently become square feet.
SIZE_SQFT = """multiIf(
    lowerUTF8(JSON_VALUE(size_json, '$.unit')) IN ('sqft', 'sq ft', 'sq. ft.', 'ft2'),
        JSONExtractFloat(size_json, 'value'),
    lowerUTF8(JSON_VALUE(size_json, '$.unit')) IN ('sqm', 'sq m', 'm2'),
        JSONExtractFloat(size_json, 'value') * 10.7639,
    NULL)"""
ASKING_PRICE = """if(lowerUTF8(JSON_VALUE(price_json, '$.currency')) = 'aed',
    toFloat64(JSONExtractInt(price_json, 'value')), NULL)"""
ANNUAL_RENT = f"""multiIf(
    lowerUTF8(JSON_VALUE(price_json, '$.period')) IN ('year', 'yearly', 'annual', 'annually'),
        {ASKING_PRICE},
    lowerUTF8(JSON_VALUE(price_json, '$.period')) IN ('month', 'monthly'), {ASKING_PRICE} * 12,
    lowerUTF8(JSON_VALUE(price_json, '$.period')) IN ('week', 'weekly'), {ASKING_PRICE} * 52,
    lowerUTF8(JSON_VALUE(price_json, '$.period')) IN ('day', 'daily'), {ASKING_PRICE} * 365,
    NULL)"""


def _inventory(request: ListingEvidenceRequest, area: str | None):
    where, params = queries._where_sql(
        mode=request.mode,
        search=None,
        area=area,
        property_type=request.property_type,
        bedrooms=request.bedrooms,
        bedrooms_in=None,
        price_min=None,
        price_max=request.price_max,
        asset_class=None,
    )
    if request.building:
        where += " AND lowerUTF8(" + queries.PEER_LOCATION_EXPR + ") = lowerUTF8({building:String})"
        params["building"] = request.building
    # Do not expose JSON payloads, free-text descriptions, brokers or contact information.
    sql = f"""SELECT listing_id, bedrooms,
        {queries.PROPERTY_TYPE_EXPR} AS property_type,
        {queries.AREA_NAME_EXPR} AS community,
        {queries.PEER_LOCATION_EXPR} AS building,
        {ASKING_PRICE if request.mode == "sale" else ANNUAL_RENT} AS asking_price_aed,
        {SIZE_SQFT} AS size_sqft,
        {queries.LISTED_AT_EXPR} AS posted_at,
        {queries.SCRAPED_AT_EXPR} AS captured_at,
        if(posted_at >= toDateTime('2010-01-01') AND posted_at <= captured_at,
           dateDiff('day', posted_at, captured_at), NULL) AS age_days_at_capture,
        if(asking_price_aed > 0 AND size_sqft > 0, asking_price_aed / size_sqft, NULL)
           AS asking_aed_per_sqft
        FROM {queries.LISTINGS_TABLE} WHERE {where}"""
    return sql, params


async def fetch_inventory_observation() -> dict:
    rows = await query(f"""SELECT max({queries.SCRAPED_AT_EXPR}) AS captured_at,
        count() AS rows, uniqExact(run_id) AS source_runs FROM {queries.LISTINGS_TABLE}""")
    return {
        key: str(value) if value is not None else None
        for key, value in (rows[0] if rows else {}).items()
    }


async def fetch_evidence_rows(request: ListingEvidenceRequest, area: str | None):
    sql, params = _inventory(request, area)
    params["limit"] = request.limit
    return await query(
        f"SELECT * FROM ({sql}) ORDER BY asking_price_aed ASC, listing_id ASC LIMIT {{limit:UInt32}}",
        params,
    )


async def fetch_age_evidence(request, area):
    sql, params = _inventory(request, area)
    params |= {"older_than": request.older_than_days, "limit": request.limit}
    # A 100-sqft band, the exact building, property type and bedrooms define the comparison.
    grouped = await query(
        f"""SELECT
        multiIf(age_days_at_capture IS NULL, 'unknown',
            age_days_at_capture > {{older_than:UInt32}}, 'older', 'newer') AS age_group,
        count() AS count, countIf(asking_aed_per_sqft > 0) AS rated_count,
        quantileExactInclusiveIf(0.5)(asking_aed_per_sqft, asking_aed_per_sqft > 0) AS median_aed_per_sqft
        FROM ({sql}) GROUP BY age_group ORDER BY age_group""",
        params,
    )
    older = await query(
        f"""SELECT * FROM ({sql})
        WHERE age_days_at_capture > {{older_than:UInt32}}
        ORDER BY age_days_at_capture DESC, listing_id ASC LIMIT {{limit:UInt32}}""",
        params,
    )
    if not older:
        return grouped, [], []
    params["buildings"] = sorted({row["building"] for row in older if row["building"]})
    newer = await query(
        f"""SELECT building, property_type, bedrooms,
        toInt64(floor(size_sqft / 100)) AS size_band, count() AS count,
        quantileExactInclusive(0.5)(asking_aed_per_sqft) AS median_aed_per_sqft
        FROM ({sql}) WHERE age_days_at_capture BETWEEN 0 AND {{older_than:UInt32}}
        AND building IN {{buildings:Array(String)}} AND size_sqft > 0 AND asking_aed_per_sqft > 0
        GROUP BY building, property_type, bedrooms, size_band
        ORDER BY building, property_type, bedrooms, size_band LIMIT 500""",
        params,
    )
    return grouped, older, newer
