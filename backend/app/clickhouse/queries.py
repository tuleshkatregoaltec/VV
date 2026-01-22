"""ClickHouse SQL query templates.

CRITICAL SECURITY: Never use f-strings to interpolate user input into SQL.
Always use {param:Type} syntax for parameter binding.

IMPORTANT: All queries on ReplacingMergeTree tables MUST use FINAL
to get deduplicated view. Without FINAL, you'll get multiple versions
of the same row with different etl_inserted_at values.

Schema Reference (from chETL/schemas.sql):
- ch_transactions: ReplacingMergeTree, partitioned by month, ORDER BY (property_usage_en, instance_date, transaction_id)
- ch_rent_contracts: ReplacingMergeTree, partitioned by month, ORDER BY (property_usage_en, contract_start_date, contract_id, line_number)
- ch_developers: ReplacingMergeTree, ORDER BY developer_id
- ch_projects: ReplacingMergeTree, ORDER BY (project_number, project_id)
- ch_buildings: ReplacingMergeTree, ORDER BY building_id
- ch_units: ReplacingMergeTree, ORDER BY unit_id
- ch_land_registry: ReplacingMergeTree, ORDER BY land_registry_id
- ch_areas: ReplacingMergeTree, ORDER BY area_id

LowCardinality Columns (instant DISTINCT queries, <10ms):
- property_type_en, property_sub_type_en, property_usage_en
- rooms_en, reg_type_en, master_project_en, area_name_en
- ejari_property_type_en, ejari_property_sub_type_en, contract_reg_type_en

Projections (fast filtering on non-key columns):
- ch_projects: generic_attribute_search (developer_id, area_id, is_free_hold, project_id)
- ch_buildings: generic_attribute_search (project_number, property_usage_en, building_id)
- ch_units: generic_attribute_search (project_number, building_id, rooms_en, unit_id)
"""

from typing import List, Optional


# =============================================================================
# ANALYTICS QUERIES - SALES
# =============================================================================


def sales_summary(
    property_usage: str,
    start_date: str,
    end_date: str,
    master_project: Optional[str] = None,
    property_type: Optional[str] = None,
    property_sub_type: Optional[str] = None,
    rooms: Optional[str] = None,
    area_name: Optional[str] = None,
    reg_type: Optional[str] = None,
    price_bucket: Optional[str] = None,
    area_bucket: Optional[str] = None,
) -> str:
    """
    Get sales analytics summary for a date range.

    Returns: transaction_count, median_price, avg_price, total_volume,
             median_price_per_sqm, median_area_sqm

    All filtering uses parameter binding - no SQL injection risk.
    """
    # Build WHERE clause with parameter placeholders
    where_clauses = [
        "property_usage_en = {property_usage:String}",
        "instance_date BETWEEN {start_date:Date} AND {end_date:Date}",
        "is_deleted = 0",
    ]

    if master_project is not None:
        where_clauses.append("master_project_en = {master_project:String}")
    if property_type is not None:
        where_clauses.append("property_type_en = {property_type:String}")
    if property_sub_type is not None:
        where_clauses.append("property_sub_type_en = {property_sub_type:String}")
    if rooms is not None:
        where_clauses.append("rooms_en = {rooms:String}")
    if area_name is not None:
        where_clauses.append("area_name_en = {area_name:String}")
    if reg_type is not None:
        where_clauses.append("reg_type_en = {reg_type:String}")
    if price_bucket is not None:
        where_clauses.append("price_bucket = {price_bucket:String}")
    if area_bucket is not None:
        where_clauses.append("area_bucket = {area_bucket:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT
            count() as transaction_count,
            round(median(actual_worth), 2) as median_price,
            round(avg(actual_worth), 2) as avg_price,
            round(sum(actual_worth), 2) as total_volume,
            round(median(meter_sale_price), 2) as median_price_per_sqm,
            round(median(procedure_area), 2) as median_area_sqm
        FROM ch_transactions FINAL
        WHERE {where_clause}
    """


def price_trends(
    property_usage: str,
    start_date: str,
    end_date: str,
    interval: str = "month",
    master_project: Optional[str] = None,
    property_type: Optional[str] = None,
    area_name: Optional[str] = None,
) -> str:
    """
    Get price trends over time (grouped by week or month).

    Args:
        interval: 'week' or 'month'

    Returns: period, transaction_count, median_price, avg_price
    """
    # SAFE: interval is controlled by application, not user input
    # But we still validate it
    if interval not in ("week", "month"):
        raise ValueError("interval must be 'week' or 'month'")

    if interval == "week":
        time_group = "toStartOfWeek(instance_date)"
    else:
        time_group = "toStartOfMonth(instance_date)"

    where_clauses = [
        "property_usage_en = {property_usage:String}",
        "instance_date BETWEEN {start_date:Date} AND {end_date:Date}",
        "is_deleted = 0",
    ]

    if master_project is not None:
        where_clauses.append("master_project_en = {master_project:String}")
    if property_type is not None:
        where_clauses.append("property_type_en = {property_type:String}")
    if area_name is not None:
        where_clauses.append("area_name_en = {area_name:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT
            {time_group} as period,
            count() as transaction_count,
            round(median(actual_worth), 2) as median_price,
            round(avg(actual_worth), 2) as avg_price
        FROM ch_transactions FINAL
        WHERE {where_clause}
        GROUP BY period
        ORDER BY period ASC
    """


def sales_by_area(
    property_usage: str,
    start_date: str,
    end_date: str,
    property_type: Optional[str] = None,
    limit: int = 20,
) -> str:
    """
    Get top areas by transaction volume.

    Returns: area_name_en, transaction_count, median_price, total_volume
    """
    where_clauses = [
        "property_usage_en = {property_usage:String}",
        "instance_date BETWEEN {start_date:Date} AND {end_date:Date}",
        "is_deleted = 0",
    ]

    if property_type is not None:
        where_clauses.append("property_type_en = {property_type:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT
            area_name_en,
            count() as transaction_count,
            round(median(actual_worth), 2) as median_price,
            round(sum(actual_worth), 2) as total_volume
        FROM ch_transactions FINAL
        WHERE {where_clause}
        GROUP BY area_name_en
        ORDER BY transaction_count DESC
        LIMIT {{limit:Int32}}
    """


def sales_by_property_type(
    property_usage: str,
    start_date: str,
    end_date: str,
    master_project: Optional[str] = None,
    area_name: Optional[str] = None,
) -> str:
    """
    Get breakdown by property type.

    Returns: property_type_en, transaction_count, median_price, total_volume
    """
    where_clauses = [
        "property_usage_en = {property_usage:String}",
        "instance_date BETWEEN {start_date:Date} AND {end_date:Date}",
        "is_deleted = 0",
    ]

    if master_project is not None:
        where_clauses.append("master_project_en = {master_project:String}")
    if area_name is not None:
        where_clauses.append("area_name_en = {area_name:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT
            property_type_en,
            count() as transaction_count,
            round(median(actual_worth), 2) as median_price,
            round(sum(actual_worth), 2) as total_volume
        FROM ch_transactions FINAL
        WHERE {where_clause}
        GROUP BY property_type_en
        ORDER BY transaction_count DESC
    """


def sales_by_rooms(
    property_usage: str,
    start_date: str,
    end_date: str,
    property_type: Optional[str] = None,
    area_name: Optional[str] = None,
) -> str:
    """
    Get breakdown by room count.

    Returns: rooms_en, transaction_count, median_price, avg_price
    """
    where_clauses = [
        "property_usage_en = {property_usage:String}",
        "instance_date BETWEEN {start_date:Date} AND {end_date:Date}",
        "is_deleted = 0",
    ]

    if property_type is not None:
        where_clauses.append("property_type_en = {property_type:String}")
    if area_name is not None:
        where_clauses.append("area_name_en = {area_name:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT
            rooms_en,
            count() as transaction_count,
            round(median(actual_worth), 2) as median_price,
            round(avg(actual_worth), 2) as avg_price
        FROM ch_transactions FINAL
        WHERE {where_clause}
        GROUP BY rooms_en
        ORDER BY transaction_count DESC
    """


# =============================================================================
# ANALYTICS QUERIES - RENTALS
# =============================================================================


def rentals_summary(
    property_usage: str,
    start_date: str,
    end_date: str,
    master_project: Optional[str] = None,
    property_type: Optional[str] = None,
    area_name: Optional[str] = None,
) -> str:
    """
    Get rental analytics summary for a date range.

    Returns: contract_count, median_rent, avg_rent, total_annual_value,
             median_rent_per_sqm, median_area_sqm
    """
    where_clauses = [
        "property_usage_en = {property_usage:String}",
        "contract_start_date BETWEEN {start_date:Date} AND {end_date:Date}",
        "is_deleted = 0",
    ]

    if master_project is not None:
        where_clauses.append("master_project_en = {master_project:String}")
    if property_type is not None:
        where_clauses.append("ejari_property_type_en = {property_type:String}")
    if area_name is not None:
        where_clauses.append("area_name_en = {area_name:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT
            count() as contract_count,
            round(median(annual_amount), 2) as median_rent,
            round(avg(annual_amount), 2) as avg_rent,
            round(sum(annual_amount), 2) as total_annual_value,
            round(median(rent_per_sqm), 2) as median_rent_per_sqm,
            round(median(actual_area), 2) as median_area_sqm
        FROM ch_rent_contracts FINAL
        WHERE {where_clause}
    """


# =============================================================================
# FILTER QUERIES (LowCardinality = instant)
# =============================================================================


def distinct_property_types(
    table: str = "ch_transactions",
    property_usage: Optional[str] = None,
) -> str:
    """
    Get distinct property types for filter dropdowns.

    Uses LowCardinality columns for instant queries (<10ms).

    Args:
        table: 'ch_transactions' or 'ch_rent_contracts'
        property_usage: Optional filter by usage type

    Returns: List of distinct property_type_en values
    """
    # SAFE: table is controlled by application, not user input
    if table not in ("ch_transactions", "ch_rent_contracts"):
        raise ValueError("table must be 'ch_transactions' or 'ch_rent_contracts'")

    # Use ejari_property_type_en for rent contracts
    column = (
        "ejari_property_type_en" if table == "ch_rent_contracts" else "property_type_en"
    )

    where_clauses = ["is_deleted = 0"]
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT DISTINCT {column}
        FROM {table} FINAL
        WHERE {where_clause} AND {column} IS NOT NULL
        ORDER BY {column}
    """


def distinct_areas(
    table: str = "ch_transactions",
    property_usage: Optional[str] = None,
) -> str:
    """
    Get distinct areas for filter dropdowns.

    LowCardinality column = instant query.
    """
    if table not in ("ch_transactions", "ch_rent_contracts"):
        raise ValueError("table must be 'ch_transactions' or 'ch_rent_contracts'")

    where_clauses = ["is_deleted = 0"]
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT DISTINCT area_name_en
        FROM {table} FINAL
        WHERE {where_clause} AND area_name_en IS NOT NULL
        ORDER BY area_name_en
    """


def distinct_master_projects(
    table: str = "ch_transactions",
    property_usage: Optional[str] = None,
    area_name: Optional[str] = None,
) -> str:
    """
    Get distinct master projects for filter dropdowns.

    LowCardinality column = instant query.
    """
    if table not in ("ch_transactions", "ch_rent_contracts"):
        raise ValueError("table must be 'ch_transactions' or 'ch_rent_contracts'")

    where_clauses = ["is_deleted = 0"]
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")
    if area_name is not None:
        where_clauses.append("area_name_en = {area_name:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT DISTINCT master_project_en
        FROM {table} FINAL
        WHERE {where_clause} AND master_project_en IS NOT NULL
        ORDER BY master_project_en
    """


def distinct_rooms(
    table: str = "ch_transactions",
    property_usage: Optional[str] = None,
    property_type: Optional[str] = None,
) -> str:
    """
    Get distinct room counts for filter dropdowns.

    LowCardinality column = instant query.
    """
    if table not in ("ch_transactions", "ch_rent_contracts"):
        raise ValueError("table must be 'ch_transactions' or 'ch_rent_contracts'")

    where_clauses = ["is_deleted = 0"]
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")
    if property_type is not None:
        column = (
            "ejari_property_type_en"
            if table == "ch_rent_contracts"
            else "property_type_en"
        )
        where_clauses.append(f"{column} = {{property_type:String}}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT DISTINCT rooms_en
        FROM {table} FINAL
        WHERE {where_clause} AND rooms_en IS NOT NULL
        ORDER BY rooms_en
    """


# =============================================================================
# PROJECTS QUERIES
# =============================================================================


def list_projects(
    area_id: Optional[int] = None,
    developer_id: Optional[int] = None,
    is_free_hold: Optional[bool] = None,
    property_usage: Optional[str] = None,
    project_status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """
    List projects with optional filters.

    Uses generic_attribute_search projection for fast filtering
    on developer_id, area_id, is_free_hold.
    """
    where_clauses = ["is_deleted = 0"]

    if area_id is not None:
        where_clauses.append("area_id = {area_id:Int32}")
    if developer_id is not None:
        where_clauses.append("developer_id = {developer_id:Int32}")
    if is_free_hold is not None:
        where_clauses.append("is_free_hold = {is_free_hold:UInt8}")
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")
    if project_status is not None:
        where_clauses.append("project_status = {project_status:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT
            project_id,
            project_number,
            project_name_en,
            project_name_ar,
            master_project_en,
            master_project_id,
            developer_id,
            area_id,
            area_name_en,
            property_usage_en,
            is_free_hold,
            project_status,
            total_units,
            total_buildings,
            total_villas,
            completion_date
        FROM ch_projects FINAL
        WHERE {where_clause}
        ORDER BY project_name_en
        LIMIT {{limit:Int32}}
        OFFSET {{offset:Int32}}
    """


def get_project_details(project_id: int) -> str:
    """
    Get full project details by ID.

    Returns all columns from ch_projects.
    """
    return """
        SELECT
            project_id,
            project_number,
            project_name_en,
            project_name_ar,
            master_project_en,
            master_project_id,
            developer_id,
            master_developer_id,
            area_id,
            area_name_en,
            property_usage_en,
            is_free_hold,
            project_status,
            project_start_date,
            completion_date,
            project_end_date,
            cancellation_date,
            percent_completed,
            total_units,
            total_buildings,
            total_villas,
            escrow_agent_name,
            zoning_authority_en
        FROM ch_projects FINAL
        WHERE project_id = {project_id:Int32}
        AND is_deleted = 0
    """


def list_developers(limit: int = 100, offset: int = 0) -> str:
    """
    List all developers.

    Returns: developer_id, developer_number, name_en, name_ar
    """
    return """
        SELECT
            developer_id,
            developer_number,
            name_en,
            name_ar
        FROM ch_developers FINAL
        WHERE is_deleted = 0
        ORDER BY name_en
        LIMIT {limit:Int32}
        OFFSET {offset:Int32}
    """


def list_buildings_for_project(
    project_number: str, limit: int = 100, offset: int = 0
) -> str:
    """
    List buildings for a specific project.

    Uses generic_attribute_search projection for fast project_number filtering.
    """
    return """
        SELECT
            building_id,
            building_number,
            building_name_en,
            building_name_ar,
            project_id,
            project_number,
            project_name_en,
            property_usage_en,
            bld_levels,
            floors,
            units,
            flats,
            offices,
            car_parks,
            shops,
            elevators,
            swimming_pools,
            is_free_hold
        FROM ch_buildings FINAL
        WHERE project_number = {project_number:String}
        AND is_deleted = 0
        ORDER BY building_name_en
        LIMIT {limit:Int32}
        OFFSET {offset:Int32}
    """


def list_units_for_building(
    building_id: int, limit: int = 100, offset: int = 0
) -> str:
    """
    List units for a specific building.

    Uses generic_attribute_search projection for fast building_id filtering.
    """
    return """
        SELECT
            unit_id,
            unit_number,
            unit_name_en,
            building_id,
            building_name_en,
            project_id,
            project_number,
            project_name_en,
            property_type_en,
            property_usage_en,
            rooms_en,
            actual_area,
            floor
        FROM ch_units FINAL
        WHERE building_id = {building_id:Int32}
        AND is_deleted = 0
        ORDER BY unit_number
        LIMIT {limit:Int32}
        OFFSET {offset:Int32}
    """


# =============================================================================
# COMPARABLE PROPERTIES (uses projections for fast filtering)
# =============================================================================


def find_comparable_units(
    project_number: str,
    property_usage: str,
    rooms: str,
    area_min: float,
    area_max: float,
    limit: int = 20,
) -> str:
    """
    Find comparable units for valuation.

    Uses generic_attribute_search projection for fast filtering
    on project_number, building_id, rooms_en.
    """
    return """
        SELECT
            unit_id,
            project_number,
            project_name_en,
            building_id,
            building_name_en,
            property_type_en,
            property_sub_type_en,
            rooms_en,
            actual_area,
            floor
        FROM ch_units FINAL
        WHERE
            project_number = {project_number:String}
            AND property_usage_en = {property_usage:String}
            AND rooms_en = {rooms:String}
            AND actual_area BETWEEN {area_min:Decimal64(2)} AND {area_max:Decimal64(2)}
            AND is_deleted = 0
        ORDER BY actual_area
        LIMIT {limit:Int32}
    """


def recent_transactions_for_area(
    area_name: str,
    property_usage: str,
    property_type: str,
    rooms: Optional[str] = None,
    days: int = 180,
    limit: int = 50,
) -> str:
    """
    Get recent comparable transactions for an area.

    Optimized by ORDER BY (property_usage_en, instance_date) sort key.
    """
    where_clauses = [
        "area_name_en = {area_name:String}",
        "property_usage_en = {property_usage:String}",
        "property_type_en = {property_type:String}",
        "instance_date >= today() - {days:Int32}",
        "is_deleted = 0",
    ]

    if rooms is not None:
        where_clauses.append("rooms_en = {rooms:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT
            transaction_id,
            instance_date,
            property_type_en,
            property_sub_type_en,
            rooms_en,
            actual_worth,
            procedure_area,
            meter_sale_price,
            master_project_en,
            area_name_en,
            nearest_metro_en,
            nearest_landmark_en
        FROM ch_transactions FINAL
        WHERE {where_clause}
        ORDER BY instance_date DESC
        LIMIT {{limit:Int32}}
    """


def recent_rentals_for_area(
    area_name: str,
    property_usage: str,
    property_type: str,
    rooms: Optional[str] = None,
    days: int = 180,
    limit: int = 50,
) -> str:
    """
    Get recent comparable rental contracts for an area.

    Optimized by ORDER BY (property_usage_en, contract_start_date) sort key.
    """
    where_clauses = [
        "area_name_en = {area_name:String}",
        "property_usage_en = {property_usage:String}",
        "ejari_property_type_en = {property_type:String}",
        "contract_start_date >= today() - {days:Int32}",
        "is_deleted = 0",
    ]

    if rooms is not None:
        where_clauses.append("rooms_en = {rooms:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT
            contract_id,
            line_number,
            contract_start_date,
            ejari_property_type_en as property_type_en,
            ejari_property_sub_type_en as property_sub_type_en,
            rooms_en,
            annual_amount,
            actual_area,
            rent_per_sqm,
            master_project_en,
            area_name_en
        FROM ch_rent_contracts FINAL
        WHERE {where_clause}
        ORDER BY contract_start_date DESC
        LIMIT {{limit:Int32}}
    """
