from app.clickhouse.client import query
from app.supply.scope import reelly_dubai_project_scope


async def fetch_matching_inventory(parameters):
    return await query(
        f"""
        SELECT
            p.project_id,
            p.project_name,
            p.developer_name,
            p.area_name,
            p.sale_status,
            p.units_in_sale,
            p.min_price_aed,
            p.max_price_aed,
            p.completion_date,
            p.readiness_progress,
            p.website_url,
            p.scraped_at,
            u.unit_type_key,
            u.unit_bedrooms,
            u.unit_type,
            u.price_from_aed AS unit_price_from,
            u.price_to_aed AS unit_price_to,
            u.area_from_sqft,
            u.area_to_sqft,
            u.units_amount
        FROM (
            SELECT
                project_id,
                project_name,
                developer_name,
                area_name,
                sale_status,
                units_in_sale,
                min_price_aed,
                max_price_aed,
                completion_date,
                readiness_progress,
                website_url,
                scraped_at
            FROM reelly_projects_bronze
            WHERE {reelly_dubai_project_scope()}
            ORDER BY parseDateTimeBestEffortOrNull(scraped_at) DESC
            LIMIT 1 BY project_id
        ) AS p
        LEFT JOIN (
            SELECT
                project_id,
                unit_type_key,
                unit_bedrooms,
                unit_type,
                price_from_aed,
                price_to_aed,
                area_from_sqft,
                area_to_sqft,
                units_amount
            FROM reelly_project_unit_types_bronze
            ORDER BY parseDateTimeBestEffortOrNull(scraped_at) DESC
            LIMIT 1 BY unit_type_key
        ) AS u USING (project_id)
        WHERE
            lowerUTF8(p.sale_status) = 'on sale'
            AND (
                {{area:String}} = ''
                OR positionCaseInsensitiveUTF8(p.area_name, {{area:String}}) > 0
                OR positionCaseInsensitiveUTF8(p.project_name, {{area:String}}) > 0
            )
        ORDER BY coalesce(u.price_from_aed, p.min_price_aed) ASC
        LIMIT 120
        """,
        parameters,
    )


async def fetch_catalog_freshness(parameters):
    return await query(
        "SELECT max(parseDateTimeBestEffortOrNull(scraped_at)) AS refreshed "
        "FROM reelly_projects_bronze "
        f"WHERE {reelly_dubai_project_scope()}",
        parameters,
    )
