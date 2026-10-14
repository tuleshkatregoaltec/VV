from typing import Optional

from app.analytics.dxbi import RENTALS_SOURCE, SALES_SOURCE
from app.analytics.models import TrendInterval
from app.clickhouse.client import query
from app.market.location_search import location_keyword_clause
from app.market.scope import MARKET_FILTERS as MARKET_FILTERS
from app.market.scope import ProjectFilterType, ProjectScopeType, project_filter_clause


def _project_filter(filter_type: ProjectScopeType) -> str:
    # DXBI names retain provider casing; typed/cached links must select the same scope.
    return (
        project_filter_clause(filter_type)
        .replace(
            "project_name_en = {project_name:String}",
            "lowerUTF8(project_name_en) = lowerUTF8({project_name:String})",
        )
        .replace(
            "master_project_en = {project_name:String}",
            "lowerUTF8(master_project_en) = lowerUTF8({project_name:String})",
        )
        .replace(
            "project_name_en LIKE {project_name:String}",
            "lowerUTF8(project_name_en) LIKE lowerUTF8({project_name:String})",
        )
    )


# Half-open bounds of a range filter: (low or None, high or None).
Bounds = tuple[Optional[float], Optional[float]]


def search_projects(keyword_clause: str | None = None) -> str:
    """Projects and master projects whose names (with their area) match, then buildings.

    A building opens the project its records are in, so it is listed with that project's name
    (``building`` set). Each kind returns up to the limit; the service keeps room for buildings.
    """
    search_clause = keyword_clause or "lowerUTF8(name) LIKE {search_pattern:String}"
    records = f"""(
                    SELECT project_name_en, master_project_en, area_name_en, scope_kind,
                           building_name
                    FROM {SALES_SOURCE}
                    UNION ALL
                    SELECT project_name_en, master_project_en, area_name_en, scope_kind,
                           building_name
                    FROM {RENTALS_SOURCE}
                )"""
    order = """lowerUTF8(name) = replaceAll({search_pattern:String}, '%', '') DESC,
                 startsWith(lowerUTF8(name), replaceAll({search_pattern:String}, '%', '')) DESC"""
    return f"""
        SELECT * FROM (
            SELECT name, filter_type,
                   if(uniqExact(kind) = 1, any(kind), 'Location') AS scope_kind, '' AS building
            FROM (
                SELECT scope.1 AS name, scope.2 AS filter_type, scope.3 AS kind,
                       scope.4 AS search_location
                FROM (
                    SELECT arrayJoin([
                        (project_name_en, 'project', scope_kind,
                         concat(project_name_en, ' ', area_name_en)),
                        (master_project_en, 'master', 'Master', master_project_en)
                    ]) AS scope
                    FROM {records}
                )
            )
            WHERE name != '' AND {search_clause}
            GROUP BY name, filter_type
            ORDER BY {order}, name, filter_type
            LIMIT {{limit:Int32}}
        )
        UNION ALL
        SELECT * FROM (
            SELECT name, 'project' AS filter_type, 'Building' AS scope_kind, building
            FROM (
                -- The project most of the building's records are in (over all of them: a
                -- stray pairing must not outvote the building's own project).
                SELECT building_name AS building, argMax(project_name_en, n) AS name,
                       any(search_location) AS search_location, max(n) AS in_project,
                       sum(n) AS records
                FROM (
                    SELECT building_name, project_name_en, count() AS n,
                           any(concat(building_name, ' ', area_name_en)) AS search_location
                    FROM {records}
                    WHERE building_name != '' AND project_name_en != ''
                    GROUP BY building_name, project_name_en
                )
                GROUP BY building
            )
            -- A building that is its project's namesake is listed as the project already; one
            -- or two records (a stray pairing) are no evidence of the building's project.
            WHERE lowerUTF8(building) != lowerUTF8(name)
              AND in_project >= 3 AND in_project * 2 >= records
              AND {search_clause.replace("lowerUTF8(name)", "lowerUTF8(building)")}
            ORDER BY {order.replace("lowerUTF8(name)", "lowerUTF8(building)")}, building
            LIMIT {{limit:Int32}}
        )
    """


def search_sub_projects(filter_type: ProjectFilterType = "master") -> str:
    if filter_type == "virtual_master":
        where = "project_name_en LIKE {master_project:String}"
    else:
        where = """(master_project_en = {master_project:String}
            OR (lower(project_name_en) LIKE concat(lower({master_project:String}), ' - %')
                AND (master_project_en = '' OR master_project_en IS NULL)))"""
    return f"""
        SELECT project_name_en, countIf(is_sale) AS transaction_count
        FROM (
            SELECT project_name_en, master_project_en, 1 AS is_sale FROM {SALES_SOURCE}
            UNION ALL
            SELECT project_name_en, master_project_en, 0 AS is_sale FROM {RENTALS_SOURCE}
        )
        WHERE {where}
          AND project_name_en IS NOT NULL
          AND project_name_en <> ''
        GROUP BY project_name_en
        ORDER BY transaction_count DESC
    """


def project_sales_summary(
    filter_type: ProjectScopeType = "project", reg_type: Optional[str] = None
) -> str:
    reg_filter = "AND reg_type_en = {reg_type_en:String}" if reg_type else ""
    return f"""
        SELECT
            count() as transaction_count,
            round(coalesce(sum(actual_worth), 0), 2) as total_volume,
            round(coalesce(avg(actual_worth), 0), 2) as avg_price,
            round(coalesce(avg(meter_sale_price), 0) / 10.7639, 2) as avg_price_sqft,
            round(coalesce(medianExact(actual_worth), 0), 2) as median_price
        FROM {SALES_SOURCE}
        WHERE {_project_filter(filter_type)}
          AND trans_group_en = 'Sales'
          AND property_type NOT IN ('Plot', 'Building', '')
          AND property_usage_en = 'Residential'
          AND actual_worth > 0
          {reg_filter}
    """


def project_sales_by_rooms(
    filter_type: ProjectScopeType = "project", reg_type: Optional[str] = None
) -> str:
    reg_filter = "AND reg_type_en = {reg_type_en:String}" if reg_type else ""
    return f"""
        SELECT
            rooms_en,
            count() as sale_count,
            round(avg(actual_worth), 2) as avg_sale_price,
            round(medianExact(actual_worth), 2) as median_sale_price,
            round(avg(meter_sale_price) / 10.7639, 2) as avg_sale_price_sqft
        FROM {SALES_SOURCE}
        WHERE {_project_filter(filter_type)}
          AND trans_group_en = 'Sales'
          AND property_type NOT IN ('Plot', 'Building', '')
          AND property_usage_en = 'Residential'
          AND rooms_en != ''
          AND actual_worth > 0
          {reg_filter}
        GROUP BY rooms_en
        ORDER BY sale_count DESC
    """


def project_configuration_sales(
    filter_type: ProjectScopeType = "project", reg_type: Optional[str] = None
) -> str:
    reg_filter = "AND reg_type_en = {reg_type_en:String}" if reg_type else ""
    return f"""
        WITH scoped_sales AS (
            SELECT
                rooms_en,
                instance_date,
                actual_worth,
                meter_sale_price,
                size_sqm
            FROM {SALES_SOURCE}
            WHERE {_project_filter(filter_type)}
              AND trans_group_en = 'Sales'
              AND property_type NOT IN ('Plot', 'Building', '')
              AND property_usage_en = 'Residential'
              AND rooms_en != ''
              AND actual_worth > 0
              {reg_filter}
        ),
        anchor AS (
            SELECT addDays(toDate(now('Asia/Dubai')), 1) AS latest_sale_date
        )
        SELECT
            rooms_en,
            count() AS sale_count,
            medianExactIf(size_sqm * 10.7639, size_sqm > 0) AS median_sale_size_sqft,
            countIf(instance_date >= addYears(latest_sale_date, -1) AND instance_date < latest_sale_date) AS sales_last_12m,
            countIf(
                instance_date >= addYears(latest_sale_date, -2)
                AND instance_date < addYears(latest_sale_date, -1)
            ) AS sales_prev_12m,
            countIf(instance_date >= addDays(latest_sale_date, -90) AND instance_date < latest_sale_date) AS sales_last_90d,
            countIf(
                instance_date >= addDays(latest_sale_date, -180)
                AND instance_date < addDays(latest_sale_date, -90)
            ) AS sales_prev_90d,
            round(avg(actual_worth), 2) AS avg_sale_price,
            round(medianExact(actual_worth), 2) AS median_sale_price,
            round(avg(meter_sale_price) / 10.7639, 2) AS avg_sale_price_sqft,
            round(quantileExact(0.25)(actual_worth), 2) AS price_p25,
            round(medianExact(actual_worth), 2) AS price_p50,
            round(quantileExact(0.75)(actual_worth), 2) AS price_p75,
            round(avgIf(meter_sale_price / 10.7639, instance_date >= addYears(latest_sale_date, -1) AND instance_date < latest_sale_date), 2) AS avg_price_sqft_last_12m,
            round(
                avgIf(
                    meter_sale_price / 10.7639,
                    instance_date >= addYears(latest_sale_date, -2)
                    AND instance_date < addYears(latest_sale_date, -1)
                ),
                2
            ) AS avg_price_sqft_prev_12m
        FROM scoped_sales
        CROSS JOIN anchor
        GROUP BY rooms_en, latest_sale_date
        ORDER BY sale_count DESC
    """


def project_sales_by_property_type(filter_type: ProjectScopeType = "project") -> str:
    return f"""
        SELECT
            property_type AS property_type_en,
            count() as count,
            round(avg(actual_worth), 2) as avg_price
        FROM {SALES_SOURCE}
        WHERE {_project_filter(filter_type)}
          AND trans_group_en = 'Sales'
          AND property_type != ''
          AND actual_worth > 0
        GROUP BY property_type_en
        ORDER BY count DESC
    """


def project_sales_by_reg_type(filter_type: ProjectScopeType = "project") -> str:
    return f"""
        SELECT
            reg_type_en,
            count() as count,
            round(avg(actual_worth), 2) as avg_price
        FROM {SALES_SOURCE}
        WHERE {_project_filter(filter_type)}
          AND trans_group_en = 'Sales'
          AND property_type NOT IN ('Plot', 'Building', '')
          AND property_usage_en = 'Residential'
          AND reg_type_en IS NOT NULL
        GROUP BY reg_type_en
        ORDER BY count DESC
    """


def project_rentals_summary(filter_type: ProjectScopeType = "project") -> str:
    return f"""
        SELECT
            count() as contract_count,
            round(coalesce(sum(annual_amount), 0), 2) as total_annual_value,
            round(coalesce(medianExact(annual_amount), 0), 2) as median_annual_rent,
            round(coalesce(medianExact(annual_amount / nullIf(actual_area * 10.7639, 0)), 0), 2) as median_rent_sqft
        FROM {RENTALS_SOURCE}
        WHERE {_project_filter(filter_type)}
          AND property_usage_en = 'Residential'
          AND annual_amount > 0
    """


def project_rentals_by_rooms(filter_type: ProjectScopeType = "project") -> str:
    rent_filter = _project_filter(filter_type)

    # A lease counts under the bedrooms it records (DXBI gives them on most leases since 2025)
    # and nowhere else. Placing a lease without them by its size put the largest bedroom type's
    # range around every oversized lease: 7-9-bed rents at AED 5 per sq ft and a 0.6% yield
    # (2026-10-08), because DLD's villa leases record the plot, not the home, and 633,000
    # labour-camp rooms fell in the studio range. No minimum sample or per-type range fixed it
    # (2026-10-09: 6-bed villas still at AED 22 per sq ft), so sizes do not place leases.
    return f"""
        SELECT
            rooms_en,
            count() AS rental_count,
            round(medianExact(annual_amount), 2) AS median_annual_rent,
            round(medianExact(annual_amount / nullIf(actual_area * 10.7639, 0)), 2) AS median_rent_sqft
        FROM {RENTALS_SOURCE}
        WHERE {rent_filter}
          AND property_usage_en = 'Residential'
          AND annual_amount > 0
          AND rooms_en != ''
        GROUP BY rooms_en
        ORDER BY rental_count DESC
    """


def project_units_composition(filter_type: ProjectScopeType = "project") -> str:
    # DXBI transaction observations cannot establish registered unit stock.
    return "SELECT '' AS rooms_en, 0 AS unit_count, 0.0 AS median_unit_size_sqft WHERE 0"


def pipeline_project_meta_by_name() -> str:
    return """
        SELECT
            p.project_name_en,
            p.area_name_en,
            coalesce(
                nullIf(d.developer_name_en, ''),
                nullIf(dn.developer_name_en, ''),
                nullIf(md.developer_name_en, ''),
                nullIf(mdn.developer_name_en, ''),
                nullIf(p.developer_name, ''),
                nullIf(p.master_developer_name, '')
            ) as developer_name_en,
            p.project_status,
            coalesce(p.completion_date, p.project_end_date) as completion_date,
            p.percent_completed,
            p.no_of_units,
            p.no_of_buildings
        FROM ch_projects p
        ANY LEFT JOIN ch_developers d ON p.developer_id = d.developer_id
        ANY LEFT JOIN ch_developers dn
            ON notEmpty(trim(BOTH ' ' FROM ifNull(p.developer_name, '')))
            AND notEmpty(trim(BOTH ' ' FROM ifNull(dn.developer_name_ar, '')))
            AND replaceRegexpAll(trim(BOTH ' ' FROM ifNull(p.developer_name, '')), '\\s+', ' ')
                = replaceRegexpAll(trim(BOTH ' ' FROM ifNull(dn.developer_name_ar, '')), '\\s+', ' ')
        ANY LEFT JOIN ch_developers md ON p.master_developer_id = md.developer_id
        ANY LEFT JOIN ch_developers mdn
            ON notEmpty(trim(BOTH ' ' FROM ifNull(p.master_developer_name, '')))
            AND notEmpty(trim(BOTH ' ' FROM ifNull(mdn.developer_name_ar, '')))
            AND replaceRegexpAll(
                trim(BOTH ' ' FROM ifNull(p.master_developer_name, '')), '\\s+', ' '
            ) = replaceRegexpAll(
                trim(BOTH ' ' FROM ifNull(mdn.developer_name_ar, '')), '\\s+', ' '
            )
        WHERE lowerUTF8(p.project_name_en) = lowerUTF8({project_name:String})
        LIMIT 1
    """


def pipeline_project_meta_by_master() -> str:
    return """
        SELECT
            any(p.area_name_en) as area_name_en,
            argMax(
                coalesce(
                    nullIf(d.developer_name_en, ''),
                    nullIf(dn.developer_name_en, ''),
                    nullIf(md.developer_name_en, ''),
                    nullIf(mdn.developer_name_en, ''),
                    nullIf(p.developer_name, ''),
                    nullIf(p.master_developer_name, '')
                ),
                coalesce(p.no_of_units, 0)
            ) as developer_name_en,
            nullIf(argMax(p.project_status, coalesce(p.percent_completed, 0)), '') as project_status,
            toNullable(
                if(
                    countIf(
                        coalesce(p.completion_date, p.project_end_date) IS NOT NULL
                        AND coalesce(p.completion_date, p.project_end_date) <= today()
                    ) > 0,
                    minIf(
                        coalesce(p.completion_date, p.project_end_date),
                        coalesce(p.completion_date, p.project_end_date) IS NOT NULL
                        AND coalesce(p.completion_date, p.project_end_date) <= today()
                    ),
                    minIf(
                        coalesce(p.completion_date, p.project_end_date),
                        coalesce(p.completion_date, p.project_end_date) IS NOT NULL
                        AND coalesce(p.completion_date, p.project_end_date) > today()
                    )
                )
            ) as completion_date,
            toNullable(round(sumWithOverflow(p.percent_completed * coalesce(p.no_of_units, 0)) / nullIf(sumWithOverflow(coalesce(p.no_of_units, 0)), 0), 1)) as percent_completed,
            toNullable(toInt64(sum(p.no_of_units))) as no_of_units,
            toNullable(toInt64(sum(p.no_of_buildings))) as no_of_buildings,
            arrayMap(
                x -> tupleElement(x, 2),
                arrayReverseSort(
                    x -> tupleElement(x, 1),
                    arrayFilter(
                        x -> notEmpty(tupleElement(x, 2)),
                        groupArray((
                            coalesce(p.no_of_units, 0),
                            coalesce(
                                nullIf(d.developer_name_en, ''),
                                nullIf(dn.developer_name_en, ''),
                                nullIf(md.developer_name_en, ''),
                                nullIf(mdn.developer_name_en, ''),
                                nullIf(p.developer_name, ''),
                                nullIf(p.master_developer_name, '')
                            )
                        ))
                    )
                )
            ) as developer_names
        FROM ch_projects p
        ANY LEFT JOIN ch_developers d ON p.developer_id = d.developer_id
        ANY LEFT JOIN ch_developers dn
            ON notEmpty(trim(BOTH ' ' FROM ifNull(p.developer_name, '')))
            AND notEmpty(trim(BOTH ' ' FROM ifNull(dn.developer_name_ar, '')))
            AND replaceRegexpAll(trim(BOTH ' ' FROM ifNull(p.developer_name, '')), '\\s+', ' ')
                = replaceRegexpAll(trim(BOTH ' ' FROM ifNull(dn.developer_name_ar, '')), '\\s+', ' ')
        ANY LEFT JOIN ch_developers md ON p.master_developer_id = md.developer_id
        ANY LEFT JOIN ch_developers mdn
            ON notEmpty(trim(BOTH ' ' FROM ifNull(p.master_developer_name, '')))
            AND notEmpty(trim(BOTH ' ' FROM ifNull(mdn.developer_name_ar, '')))
            AND replaceRegexpAll(
                trim(BOTH ' ' FROM ifNull(p.master_developer_name, '')), '\\s+', ' '
            ) = replaceRegexpAll(
                trim(BOTH ' ' FROM ifNull(mdn.developer_name_ar, '')), '\\s+', ' '
            )
        WHERE (p.master_project_en = {project_name:String}
            OR lower(p.project_name_en) LIKE concat(lower({project_name:String}), ' - %'))
    """


def pipeline_project_meta_by_virtual_master() -> str:
    return """
        SELECT
            any(p.area_name_en) as area_name_en,
            argMax(
                coalesce(
                    nullIf(d.developer_name_en, ''),
                    nullIf(dn.developer_name_en, ''),
                    nullIf(md.developer_name_en, ''),
                    nullIf(mdn.developer_name_en, ''),
                    nullIf(p.developer_name, ''),
                    nullIf(p.master_developer_name, '')
                ),
                coalesce(p.no_of_units, 0)
            ) as developer_name_en,
            nullIf(argMax(p.project_status, coalesce(p.percent_completed, 0)), '') as project_status,
            toNullable(
                if(
                    countIf(
                        coalesce(p.completion_date, p.project_end_date) IS NOT NULL
                        AND coalesce(p.completion_date, p.project_end_date) <= today()
                    ) > 0,
                    minIf(
                        coalesce(p.completion_date, p.project_end_date),
                        coalesce(p.completion_date, p.project_end_date) IS NOT NULL
                        AND coalesce(p.completion_date, p.project_end_date) <= today()
                    ),
                    minIf(
                        coalesce(p.completion_date, p.project_end_date),
                        coalesce(p.completion_date, p.project_end_date) IS NOT NULL
                        AND coalesce(p.completion_date, p.project_end_date) > today()
                    )
                )
            ) as completion_date,
            toNullable(round(sumWithOverflow(p.percent_completed * coalesce(p.no_of_units, 0)) / nullIf(sumWithOverflow(coalesce(p.no_of_units, 0)), 0), 1)) as percent_completed,
            toNullable(toInt64(sum(p.no_of_units))) as no_of_units,
            toNullable(toInt64(sum(p.no_of_buildings))) as no_of_buildings,
            arrayMap(
                x -> tupleElement(x, 2),
                arrayReverseSort(
                    x -> tupleElement(x, 1),
                    arrayFilter(
                        x -> notEmpty(tupleElement(x, 2)),
                        groupArray((
                            coalesce(p.no_of_units, 0),
                            coalesce(
                                nullIf(d.developer_name_en, ''),
                                nullIf(dn.developer_name_en, ''),
                                nullIf(md.developer_name_en, ''),
                                nullIf(mdn.developer_name_en, ''),
                                nullIf(p.developer_name, ''),
                                nullIf(p.master_developer_name, '')
                            )
                        ))
                    )
                )
            ) as developer_names
        FROM ch_projects p
        LEFT JOIN ch_developers d ON p.developer_id = d.developer_id
        LEFT JOIN ch_developers dn
            ON replaceRegexpAll(trim(BOTH ' ' FROM ifNull(p.developer_name, '')), '\\s+', ' ')
            = replaceRegexpAll(trim(BOTH ' ' FROM ifNull(dn.developer_name_ar, '')), '\\s+', ' ')
        LEFT JOIN ch_developers md ON p.master_developer_id = md.developer_id
        LEFT JOIN ch_developers mdn
            ON replaceRegexpAll(trim(BOTH ' ' FROM ifNull(p.master_developer_name, '')), '\\s+', ' ')
            = replaceRegexpAll(trim(BOTH ' ' FROM ifNull(mdn.developer_name_ar, '')), '\\s+', ' ')
        WHERE p.project_name_en LIKE {project_name:String}
    """


def project_meta(filter_type: ProjectScopeType = "project") -> str:
    return f"""
        SELECT {{project_name:String}} AS project_name_en,
               if(uniqExactIf(area_name_en, area_name_en != '') = 1,
                  anyIf(area_name_en, area_name_en != ''), '') AS area_name_en
        FROM (
            SELECT project_name_en, master_project_en, area_name_en FROM {SALES_SOURCE}
            UNION ALL
            SELECT project_name_en, master_project_en, area_name_en FROM {RENTALS_SOURCE}
        ) WHERE {_project_filter(filter_type)}
    """


def project_price_distribution(
    filter_type: ProjectScopeType = "project", reg_type: Optional[str] = None
) -> str:
    reg_filter = "AND reg_type_en = {reg_type_en:String}" if reg_type else ""
    project_filter = _project_filter(filter_type)
    return f"""
        SELECT
            rooms_en,
            count() as sale_count,
            round(avg(actual_worth), 2) as mean_price,
            round(stddevPop(actual_worth), 2) as std_price,
            round(avg(log(actual_worth)), 6) as log_mean_price,
            round(stddevPop(log(actual_worth)), 6) as log_std_price,
            round(quantileExact(0.05)(actual_worth), 2) as p05_price,
            round(quantileExact(0.16)(actual_worth), 2) as p16_price,
            round(quantileExact(0.25)(actual_worth), 2) as p25_price,
            round(quantileExact(0.50)(actual_worth), 2) as p50_price,
            round(quantileExact(0.75)(actual_worth), 2) as p75_price,
            round(quantileExact(0.84)(actual_worth), 2) as p84_price,
            round(quantileExact(0.95)(actual_worth), 2) as p95_price,
            round(avg(meter_sale_price) / 10.7639, 2) as mean_price_sqft,
            round(stddevPop(meter_sale_price) / 10.7639, 2) as std_price_sqft
        FROM {SALES_SOURCE}
        WHERE {project_filter}
          AND trans_group_en = 'Sales'
          AND property_type NOT IN ('Plot', 'Building', '')
          AND property_usage_en = 'Residential'
          AND rooms_en != ''
          AND actual_worth > 0
          {reg_filter}
        GROUP BY rooms_en
        UNION ALL
        SELECT
            '__all__' as rooms_en,
            count() as sale_count,
            round(avg(actual_worth), 2) as mean_price,
            round(stddevPop(actual_worth), 2) as std_price,
            round(avg(log(actual_worth)), 6) as log_mean_price,
            round(stddevPop(log(actual_worth)), 6) as log_std_price,
            round(quantileExact(0.05)(actual_worth), 2) as p05_price,
            round(quantileExact(0.16)(actual_worth), 2) as p16_price,
            round(quantileExact(0.25)(actual_worth), 2) as p25_price,
            round(quantileExact(0.50)(actual_worth), 2) as p50_price,
            round(quantileExact(0.75)(actual_worth), 2) as p75_price,
            round(quantileExact(0.84)(actual_worth), 2) as p84_price,
            round(quantileExact(0.95)(actual_worth), 2) as p95_price,
            round(avg(meter_sale_price) / 10.7639, 2) as mean_price_sqft,
            round(stddevPop(meter_sale_price) / 10.7639, 2) as std_price_sqft
        FROM {SALES_SOURCE}
        WHERE {project_filter}
          AND trans_group_en = 'Sales'
          AND property_type NOT IN ('Plot', 'Building', '')
          AND property_usage_en = 'Residential'
          AND actual_worth > 0
          {reg_filter}
    """


def project_price_trends(
    interval: TrendInterval = "month", filter_type: ProjectScopeType = "project"
) -> str:
    if interval not in ("day", "week", "month"):
        raise ValueError("interval must be 'day', 'week', or 'month'")

    if interval == "day":
        time_group = "instance_date"
    elif interval == "week":
        time_group = "toStartOfWeek(instance_date)"
    else:
        time_group = "toStartOfMonth(instance_date)"

    return f"""
        SELECT
            {time_group} as period,
            count() as transaction_count,
            round(avg(actual_worth), 2) as avg_price,
            round(avg(meter_sale_price) / 10.7639, 2) as avg_price_sqft
        FROM {SALES_SOURCE}
        WHERE {_project_filter(filter_type)}
          AND trans_group_en = 'Sales'
          AND property_type NOT IN ('Plot', 'Building', '')
          AND property_usage_en = 'Residential'
          AND toDate(instance_date) BETWEEN {{start_date:Date}} AND {{end_date:Date}}
          AND actual_worth > 0
        GROUP BY period
        ORDER BY period ASC
    """


def area_supply_projects(filter_by_area: bool = True) -> str:
    area_filter = (
        "(lowerUTF8(p.area_name_en) = lowerUTF8({area_name:String}) "
        "OR lowerUTF8(p.master_project_en) = lowerUTF8({area_name:String})) AND"
        if filter_by_area
        else ""
    )
    return f"""
        SELECT
            p.project_name_en,
            coalesce(
                nullIf(d.developer_name_en, ''),
                nullIf(dn.developer_name_en, ''),
                nullIf(md.developer_name_en, ''),
                nullIf(mdn.developer_name_en, ''),
                nullIf(p.developer_name, ''),
                nullIf(p.master_developer_name, '')
            ) as developer_name_en,
            p.area_name_en,
            p.project_status,
            p.project_start_date,
            toDate(p.project_end_date) AS project_end_date,
            toDate(p.completion_date) AS completion_date,
            p.percent_completed,
            p.no_of_units
        FROM ch_projects p
        ANY LEFT JOIN ch_developers d ON p.developer_id = d.developer_id
        ANY LEFT JOIN ch_developers dn
            ON notEmpty(trim(BOTH ' ' FROM ifNull(p.developer_name, '')))
            AND notEmpty(trim(BOTH ' ' FROM ifNull(dn.developer_name_ar, '')))
            AND replaceRegexpAll(trim(BOTH ' ' FROM ifNull(p.developer_name, '')), '\\s+', ' ')
                = replaceRegexpAll(trim(BOTH ' ' FROM ifNull(dn.developer_name_ar, '')), '\\s+', ' ')
        ANY LEFT JOIN ch_developers md ON p.master_developer_id = md.developer_id
        ANY LEFT JOIN ch_developers mdn
            ON notEmpty(trim(BOTH ' ' FROM ifNull(p.master_developer_name, '')))
            AND notEmpty(trim(BOTH ' ' FROM ifNull(mdn.developer_name_ar, '')))
            AND replaceRegexpAll(
                trim(BOTH ' ' FROM ifNull(p.master_developer_name, '')), '\\s+', ' '
            ) = replaceRegexpAll(
                trim(BOTH ' ' FROM ifNull(mdn.developer_name_ar, '')), '\\s+', ' '
            )
        WHERE {area_filter}
          coalesce(p.no_of_units, 0) > 0
          AND p.cancellation_date IS NULL
    """


async def fetch_latest_sales_anchor_date_rows(parameters: dict):
    return await query(
        f"""
        SELECT max(instance_date) AS latest_sales_date
        FROM {SALES_SOURCE}
        WHERE trans_group_en = 'Sales'
          AND actual_worth > 0
          AND instance_date <= today()
        """,
        parameters,
    )


async def fetch_search_projects(parameters: dict):
    params = dict(parameters)
    search = params.pop("search", "")
    clause = location_keyword_clause("search_location", search, params)
    return await query(search_projects(clause), params)


async def fetch_search_sub_projects(parameters: dict, filter_type: ProjectFilterType = "master"):
    return await query(search_sub_projects(filter_type), parameters)


async def fetch_project_meta(parameters: dict, filter_type):
    return await query(project_meta(filter_type), parameters)


# DXBI's building list (the heatmap's building cards: developer, completion, unit count) for a
# project DLD's projects register does not hold (older ones such as LAKE SHORE TOWER). A project
# is the buildings DXBI lists under its name, the one building of that name, or the DXBI buildings
# whose paired sales sit in it (>= 90% of >= 3: DLD's "SKY COURTS" is DXBI's Sky Courts Tower A-F).
# A project card (display_as 'P') carries the project's totals and lists its building cards
# (building_csv): it counts only when none of its buildings' cards is counted already.
_NAME_KEY = "lowerUTF8(replaceRegexpAll({value}, '[^A-Za-z0-9]', ''))"
_PAIRED_BUILDINGS = f"""(
        SELECT building_key FROM (
            SELECT {_NAME_KEY.format(value="building_name")} AS building_key,
                   countIf(project_name = {{project_name:String}}) AS inside, count() AS sales
            FROM dxbi_sale_profile
            WHERE project_source = 'dld_pair' AND building_name != ''
              AND {_NAME_KEY.format(value="building_name")} IN (
                  SELECT {_NAME_KEY.format(value="building_name")} FROM dxbi_sale_profile
                  WHERE project_name = {{project_name:String}} AND project_source = 'dld_pair')
            GROUP BY building_key
        )
        WHERE inside >= 0.9 * sales AND sales >= 3
    )"""
PROJECT_META_FROM_DXBI = f"""
    SELECT
        topK(1)(area)[1] AS area_name_en,
        topKIf(1)(dev, dev != '')[1] AS developer_name_en,
        maxOrNull(completion) AS completion_date,
        minOrNull(percent) AS percent_completed,
        groupArrayIf(card_id, card != 'P') AS building_ids,
        arrayFilter((u, kids) -> NOT hasAny(kids, building_ids),
                    groupArrayIf(units, card = 'P'), groupArrayIf(kids, card = 'P')) AS project_units,
        sumIf(units, card != 'P') + arraySum(project_units) AS no_of_units,
        nullIf(length(building_ids) + arraySum(arrayMap(
            (u, kids) -> if(hasAny(kids, building_ids), 0, length(kids)),
            groupArrayIf(units, card = 'P'), groupArrayIf(kids, card = 'P'))), 0)
            AS no_of_buildings
    FROM (
        SELECT JSONExtractString(payload_json, 'Building', 'project') AS project,
               JSONExtractString(payload_json, 'Building', 'location') AS location,
               JSONExtractString(payload_json, 'Building', 'area_name') AS area,
               trimBoth(JSONExtractString(payload_json, 'Building', 'dev')) AS dev,
               toDate(parseDateTimeBestEffortOrNull(
                   JSONExtractString(payload_json, 'Building', 'completion_date'))) AS completion,
               JSONExtract(payload_json, 'Building', 'completion_percent', 'Nullable(Float64)')
                   AS percent,
               JSONExtractUInt(payload_json, 'Building', 'unit_count') AS units,
               JSONExtractString(payload_json, 'Building', 'display_as') AS card,
               toUInt64OrZero(location_id) AS card_id,
               JSONExtract(payload_json, 'Building', 'building_csv', 'Array(UInt64)') AS kids
        FROM dxbi_heatmap_buildings_bronze
        WHERE status = 200
        LIMIT 1 BY location_id
    )
    WHERE {_NAME_KEY.format(value="project")} = {_NAME_KEY.format(value="{project_name:String}")}
       OR {_NAME_KEY.format(value="location")} = {_NAME_KEY.format(value="{project_name:String}")}
       OR {_NAME_KEY.format(value="location")} IN {_PAIRED_BUILDINGS}
    HAVING count() > 0
"""


async def fetch_project_meta_from_dxbi(parameters: dict):
    return await query(PROJECT_META_FROM_DXBI, parameters)


async def fetch_pipeline_meta(parameters: dict, filter_type):
    meta_fn = {
        "master": pipeline_project_meta_by_master,
        "virtual_master": pipeline_project_meta_by_virtual_master,
        "project": pipeline_project_meta_by_name,
    }[filter_type]
    return await query(meta_fn(), parameters)


async def fetch_project_developers_by_scope(parameters: dict, filter_type="master"):
    # The loaded DXBI transaction catalogue has no verified developer field.
    return []


async def fetch_project_sales_bundle(parameters: dict, filter_type: ProjectScopeType):
    """Summary, bedrooms and configuration segments from one normalized-source scan."""
    rows = await query(
        f"""
        SELECT segment, rooms_en, grouping(rooms_en) AS is_total,
               count() AS sale_count, round(sum(actual_worth), 2) AS total_volume,
               round(avg(actual_worth), 2) AS avg_sale_price,
               round(medianExact(actual_worth), 2) AS median_sale_price,
               round(avg(meter_sale_price) / 10.7639, 2) AS avg_sale_price_sqft,
               round(medianExactIf(size_sqm * 10.7639, size_sqm > 0), 2) AS median_sale_size_sqft,
               countIf(instance_date >= addYears(latest_sale_date, -1) AND instance_date < latest_sale_date) AS sales_last_12m,
               countIf(instance_date >= addYears(latest_sale_date, -2)
                    AND instance_date < addYears(latest_sale_date, -1)) AS sales_prev_12m,
               countIf(instance_date >= addDays(latest_sale_date, -90) AND instance_date < latest_sale_date) AS sales_last_90d,
               countIf(instance_date >= addDays(latest_sale_date, -180)
                    AND instance_date < addDays(latest_sale_date, -90)) AS sales_prev_90d,
               round(quantileExact(0.25)(actual_worth), 2) AS price_p25,
               round(medianExact(actual_worth), 2) AS price_p50,
               round(quantileExact(0.75)(actual_worth), 2) AS price_p75,
               round(avgIf(meter_sale_price / 10.7639,
                    instance_date >= addYears(latest_sale_date, -1) AND instance_date < latest_sale_date), 2) AS avg_price_sqft_last_12m,
               round(avgIf(meter_sale_price / 10.7639,
                    instance_date >= addYears(latest_sale_date, -2)
                    AND instance_date < addYears(latest_sale_date, -1)), 2) AS avg_price_sqft_prev_12m
        FROM (
            SELECT *, addDays(toDate(now('Asia/Dubai')), 1) AS latest_sale_date
            FROM (
                SELECT *, arrayJoin(['all', multiIf(reg_type_en = 'Existing Properties',
                        'secondary', reg_type_en = 'Off-Plan Properties', 'off_plan', 'unknown')])
                        AS segment
                FROM {SALES_SOURCE}
                WHERE {_project_filter(filter_type)} AND trans_group_en = 'Sales'
                    AND property_type NOT IN ('Plot', 'Building', '')
                    AND property_usage_en = 'Residential' AND actual_worth > 0
            )
        )
        GROUP BY GROUPING SETS ((segment), (segment, rooms_en))
        """,
        parameters,
    )

    def summary(segment):
        return [
            dict(
                row,
                transaction_count=row["sale_count"],
                avg_price=row["avg_sale_price"],
                median_price=row["median_sale_price"],
                avg_price_sqft=row["avg_sale_price_sqft"],
            )
            for row in rows
            if row["is_total"] and row["segment"] == segment
        ]

    def rooms(segment):
        return [
            row
            for row in rows
            if not row["is_total"] and row["rooms_en"] and row["segment"] == segment
        ]

    return (
        summary("all"),
        summary("secondary"),
        rooms("all"),
        rooms("secondary"),
        rooms("all"),
        rooms("off_plan"),
        rooms("secondary"),
    )


async def fetch_project_sales_summary(
    parameters: dict, filter_type: ProjectScopeType = "project", reg_type: Optional[str] = None
):
    return await query(project_sales_summary(filter_type, reg_type), parameters)


async def fetch_project_sales_by_rooms(
    parameters: dict, filter_type: ProjectScopeType = "project", reg_type: Optional[str] = None
):
    return await query(project_sales_by_rooms(filter_type, reg_type), parameters)


async def fetch_project_configuration_sales(
    parameters: dict, filter_type: ProjectScopeType = "project", reg_type: Optional[str] = None
):
    return await query(project_configuration_sales(filter_type, reg_type), parameters)


async def fetch_project_sales_by_property_type(
    parameters: dict, filter_type: ProjectScopeType = "project"
):
    return await query(project_sales_by_property_type(filter_type), parameters)


async def fetch_project_sales_by_reg_type(
    parameters: dict, filter_type: ProjectScopeType = "project"
):
    return await query(project_sales_by_reg_type(filter_type), parameters)


async def fetch_project_rentals_summary(
    parameters: dict, filter_type: ProjectScopeType = "project"
):
    return await query(project_rentals_summary(filter_type), parameters)


async def fetch_project_rentals_by_rooms(
    parameters: dict, filter_type: ProjectScopeType = "project"
):
    return await query(project_rentals_by_rooms(filter_type), parameters)


async def fetch_project_units_composition(
    parameters: dict, filter_type: ProjectScopeType = "project"
):
    return await query(project_units_composition(filter_type), parameters)


async def fetch_project_price_trends(
    parameters: dict, interval: TrendInterval = "month", filter_type: ProjectScopeType = "project"
):
    return await query(project_price_trends(interval, filter_type), parameters)


async def fetch_area_supply_projects(parameters: dict, filter_by_area: bool = True):
    return await query(area_supply_projects(filter_by_area), parameters)


async def fetch_project_price_distribution(
    parameters: dict, filter_type: ProjectScopeType = "project", reg_type: Optional[str] = None
):
    return await query(project_price_distribution(filter_type, reg_type), parameters)


async def fetch_sales_summary(
    parameters: dict,
    property_usage: Optional[str],
    start_date: str,
    end_date: str,
    master_project: Optional[str] = None,
    property_type: Optional[str] = None,
    property_sub_type: Optional[str] = None,
    rooms: Optional[str] = None,
    area_name: Optional[str] = None,
    reg_type: Optional[str] = None,
    price_range: Optional[Bounds] = None,
    area_range: Optional[Bounds] = None,
    market: Optional[dict[str, str]] = None,
):
    return await query(
        sales_summary(
            property_usage,
            start_date,
            end_date,
            master_project,
            property_type,
            property_sub_type,
            rooms,
            area_name,
            reg_type,
            price_range,
            area_range,
            market,
        ),
        parameters,
    )


async def fetch_rentals_summary(
    parameters: dict,
    property_usage: str,
    start_date: str,
    end_date: str,
    master_project: Optional[str] = None,
    property_type: Optional[str] = None,
    area_name: Optional[str] = None,
    rent_range: Optional[Bounds] = None,
    area_range: Optional[Bounds] = None,
):
    return await query(
        rentals_summary(
            property_usage,
            start_date,
            end_date,
            master_project,
            property_type,
            area_name,
            rent_range,
            area_range,
        ),
        parameters,
    )


async def fetch_price_trends(
    parameters: dict,
    property_usage: Optional[str],
    start_date: str,
    end_date: str,
    interval: str = "month",
    master_project: Optional[str] = None,
    property_type: Optional[str] = None,
    area_name: Optional[str] = None,
    market: Optional[dict[str, str]] = None,
):
    return await query(
        price_trends(
            property_usage,
            start_date,
            end_date,
            interval,
            master_project,
            property_type,
            area_name,
            market,
        ),
        parameters,
    )


def _range_clauses(expression: str, name: str, bounds: Optional[Bounds]) -> list[str]:
    """``expression`` in the half-open [low, high); bounds bind as ``{name}_min``/``_max``."""
    if bounds is None:
        return []
    low, high = bounds
    clauses = []
    if low is not None:
        clauses.append(f"{expression} >= {{{name}_min:Float64}}")
    if high is not None:
        clauses.append(f"{expression} < {{{name}_max:Float64}}")
    return clauses


def _market_clauses(market: Optional[dict[str, str]]) -> list[str]:
    """Sales by default; a market type's own group and predicate otherwise (trusted)."""
    if market is None:
        return ["trans_group_en = 'Sales'"]
    return [f"trans_group_en = '{market['trans_group_en']}'", f"({market['where']})"]


def sales_summary(
    property_usage: Optional[str],
    start_date: str,
    end_date: str,
    master_project: Optional[str] = None,
    property_type: Optional[str] = None,
    property_sub_type: Optional[str] = None,
    rooms: Optional[str] = None,
    area_name: Optional[str] = None,
    reg_type: Optional[str] = None,
    price_range: Optional[Bounds] = None,
    area_range: Optional[Bounds] = None,
    market: Optional[dict[str, str]] = None,
) -> str:
    """
    Get sales analytics summary for a date range.

    Returns: transaction_count, median_price, avg_price, total_volume,
             median_price_per_sqft, median_area_sqft

    All filtering uses parameter binding - no SQL injection risk. ``market`` is a
    MARKET_FILTERS entry (trusted, not user input): its group and predicate.
    """
    where_clauses = _market_clauses(market) + [
        "toDate(instance_date) BETWEEN {start_date:Date} AND {end_date:Date}",
    ]
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")

    if master_project is not None:
        where_clauses.append("master_project_en = {master_project:String}")
    if property_type is not None:
        where_clauses.append("property_type = {property_type:String}")
    if property_sub_type is not None:
        where_clauses.append("property_sub_type_en = {property_sub_type:String}")
    if rooms is not None:
        where_clauses.append("rooms_en = {rooms:String}")
    if area_name is not None:
        where_clauses.append("location_name = {area_name:String}")
    if reg_type is not None:
        where_clauses.append("reg_type_en = {reg_type:String}")
    where_clauses += _range_clauses("actual_worth", "price", price_range)
    where_clauses += _range_clauses("size_sqm * 10.7639", "area_sqft", area_range)

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT
            count() as transaction_count,
            round(medianExact(actual_worth), 2) as median_price,
            round(avg(actual_worth), 2) as avg_price,
            round(sum(actual_worth), 2) as total_volume,
            round(medianExact(meter_sale_price) / 10.7639, 2) as median_price_per_sqft,
            round(medianExactIf(size_sqm, size_sqm > 0) * 10.7639, 2) as median_area_sqft,
            round(min(actual_worth), 2) as min_price,
            round(max(actual_worth), 2) as max_price,
            round(avgIf(actual_worth / size_sqm, size_sqm > 0) / 10.7639, 2)
                as avg_price_sqft
        FROM {SALES_SOURCE}
        WHERE {where_clause}
    """


def price_trends(
    property_usage: Optional[str],
    start_date: str,
    end_date: str,
    interval: str = "month",
    master_project: Optional[str] = None,
    property_type: Optional[str] = None,
    area_name: Optional[str] = None,
    market: Optional[dict[str, str]] = None,
    source: Optional[str] = None,
) -> str:
    """
    Get price trends over time (grouped by day, week, or month).

    ``source`` is the Analytics DXBI records by default; chat charts pass the combined market
    layer (``ch_transactions``) their other queries read.

    Args:
        interval: 'day', 'week', or 'month'

    Returns: period, transaction_count, avg_price, avg_price_sqft
    ``market`` is a MARKET_FILTERS entry (trusted, not user input).
    """
    source = source or SALES_SOURCE
    # SAFE: interval is controlled by application, not user input
    if interval not in ("day", "week", "month"):
        raise ValueError("interval must be 'day', 'week', or 'month'")

    if interval == "day":
        time_group = "toDate(instance_date)"
    elif interval == "week":
        time_group = "toStartOfWeek(instance_date)"
    else:
        time_group = "toStartOfMonth(instance_date)"

    where_clauses = _market_clauses(market) + [
        "toDate(instance_date) BETWEEN {start_date:Date} AND {end_date:Date}",
    ]
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")

    if master_project is not None:
        where_clauses.append("master_project_en = {master_project:String}")
    if property_type is not None:
        where_clauses.append("property_type = {property_type:String}")
    if area_name is not None:
        where_clauses.append("location_name = {area_name:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT
            {time_group} as period,
            count() as transaction_count,
            round(avg(actual_worth), 2) as avg_price,
            round(avg(meter_sale_price) / 10.7639, 2) as avg_price_sqft
        FROM {source}
        WHERE {where_clause}
        GROUP BY period
        ORDER BY period ASC
    """


def rentals_summary(
    property_usage: str,
    start_date: str,
    end_date: str,
    master_project: Optional[str] = None,
    property_type: Optional[str] = None,
    area_name: Optional[str] = None,
    rent_range: Optional[Bounds] = None,
    area_range: Optional[Bounds] = None,
) -> str:
    """
    Get rental analytics summary for a date range.

    Returns: contract_count, median_rent, avg_rent, total_annual_value,
             median_rent_per_sqft, median_area_sqft
    """
    where_clauses = [
        "property_usage_en = {property_usage:String}",
        "toDate(contract_start_date) BETWEEN {start_date:Date} AND {end_date:Date}",
    ]

    if master_project is not None:
        where_clauses.append("master_project_en = {master_project:String}")
    if property_type is not None:
        where_clauses.append("property_type = {property_type:String}")
    if area_name is not None:
        where_clauses.append("location_name = {area_name:String}")
    where_clauses += _range_clauses("annual_amount", "rent", rent_range)
    where_clauses += _range_clauses("size_sqm * 10.7639", "area_sqft", area_range)

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT
            count() as contract_count,
            round(medianExact(annual_amount), 2) as median_rent,
            round(avg(annual_amount), 2) as avg_rent,
            round(sum(annual_amount), 2) as total_annual_value,
            round(medianExact(annual_amount / nullIf(size_sqm * 10.7639, 0)), 2) as median_rent_per_sqft,
            round(medianExactIf(size_sqm, size_sqm > 0) * 10.7639, 2) as median_area_sqft,
            round(min(annual_amount), 2) as min_rent,
            round(max(annual_amount), 2) as max_rent,
            round(avgIf(annual_amount / size_sqm, size_sqm > 0) / 10.7639, 2)
                as avg_rent_sqft
        FROM {RENTALS_SOURCE}
        WHERE {where_clause}
    """


GET_MARKET_PULSE_SQL = """
    SELECT
        count(*) as transaction_count,
        round(medianExact(actual_worth), 0) as median_price,
        round(avg(actual_worth), 0) as avg_price,
        round(medianExact(size_sqm) * 10.7639, 1) as median_area_sqft,
        round(medianExact(actual_worth / size_sqm) / 10.7639, 0) as median_price_per_sqft,
        min(instance_date) as period_start,
        max(instance_date) as period_end
    FROM ch_transactions
    WHERE
        location_name = {area:String}
        AND trans_group_en = 'Sales'
        AND instance_date >= today() - {period_days:Int32}
        AND actual_worth > 0
        AND size_sqm > 0
    """


async def fetch_market_pulse(parameters: dict):
    return await query(GET_MARKET_PULSE_SQL, parameters)


# Chat's market tools (market pulse, area rankings) read the combined market layer, as the rest
# of chat does; the Analytics page reads the DXBI records. Ranked by location in the uniform
# vocabulary (DXBI community names; the names market pulse and the Transactions page filter on).
RANK_AREAS_VOLUME_SQL = """
        SELECT
            location_name as area,
            count(*) as transaction_count,
            round(medianExact(actual_worth), 0) as median_price
        FROM ch_transactions
        WHERE
            instance_date >= today() - {period_days:Int32}
            AND trans_group_en = 'Sales'
            AND actual_worth > 0
            AND location_name != ''
        GROUP BY location_name
        ORDER BY transaction_count DESC
        LIMIT {limit:Int32}
        """


RANK_AREAS_PRICE_SQL = """
        SELECT
            location_name as area,
            round(medianExact(actual_worth), 0) as median_price,
            count(*) as transaction_count
        FROM ch_transactions
        WHERE
            instance_date >= today() - {period_days:Int32}
            AND trans_group_en = 'Sales'
            AND actual_worth > 0
            AND location_name != ''
        GROUP BY location_name
        HAVING transaction_count >= 10
        ORDER BY median_price DESC
        LIMIT {limit:Int32}
        """


RANK_AREAS_GROWTH_SQL = """
        WITH
            current_period AS (
                SELECT
                    location_name as area,
                    medianExact(actual_worth) as current_median
                FROM ch_transactions
                WHERE
                    instance_date >= today() - {period_days:Int32}
                    AND trans_group_en = 'Sales'
                    AND actual_worth > 0
                    AND location_name != ''
                GROUP BY location_name
                HAVING count(*) >= 10
            ),
            previous_period AS (
                SELECT
                    location_name as area,
                    medianExact(actual_worth) as previous_median
                FROM ch_transactions
                WHERE
                    instance_date >= today() - {period_days:Int32} * 2
                    AND instance_date < today() - {period_days:Int32}
                    AND trans_group_en = 'Sales'
                    AND actual_worth > 0
                    AND location_name != ''
                GROUP BY location_name
                HAVING count(*) >= 10
            )
        SELECT
            c.area,
            round(c.current_median, 0) as current_median_price,
            round(p.previous_median, 0) as previous_median_price,
            round(((c.current_median - p.previous_median) / p.previous_median) * 100, 2) as growth_percentage
        FROM current_period c
        INNER JOIN previous_period p ON c.area = p.area
        ORDER BY growth_percentage DESC
        LIMIT {limit:Int32}
        """


async def fetch_rank_areas(metric: str, parameters: dict):
    statement = {
        "volume": RANK_AREAS_VOLUME_SQL,
        "price": RANK_AREAS_PRICE_SQL,
        "growth": RANK_AREAS_GROWTH_SQL,
    }[metric]
    return await query(statement, parameters)
