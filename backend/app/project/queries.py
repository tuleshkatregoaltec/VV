from app.clickhouse.client import query

GET_SIMILAR_PROJECTS_REF_SQL = """
    SELECT
        master_project_en,
        area_name_en,
        property_type_en,
        round(median(actual_worth), 0) as median_price,
        round(median(actual_area), 1) as median_area,
        count(*) as transaction_count
    FROM ch_transactions
    WHERE
        master_project_en ILIKE {project_name:String}
        AND actual_worth > 0
        AND actual_area > 0
        AND instance_date >= today() - 365
    GROUP BY master_project_en, area_name_en, property_type_en
    LIMIT 1
    """


GET_SIMILAR_PROJECTS_SIMILAR_SQL = """
        SELECT
            master_project_en,
            area_name_en,
            property_type_en,
            round(median(actual_worth), 0) as median_price,
            round(median(actual_area), 1) as median_area,
            count(*) as transaction_count,
            abs(median(actual_worth) - {ref_price:Float64}) as price_diff
        FROM ch_transactions
        WHERE
            master_project_en != {ref_project:String}
            AND property_type_en = {ref_type:String}
            AND actual_worth > 0
            AND actual_area > 0
            AND instance_date >= today() - 365
            AND master_project_en != ''
        GROUP BY master_project_en, area_name_en, property_type_en
        HAVING transaction_count >= 5
        ORDER BY price_diff ASC
        LIMIT {limit:Int32}
        """


async def fetch_similar_projects(parameters: dict):
    return await query(GET_SIMILAR_PROJECTS_SIMILAR_SQL, parameters)


async def fetch_similar_project_reference(parameters: dict):
    return await query(GET_SIMILAR_PROJECTS_REF_SQL, parameters)
