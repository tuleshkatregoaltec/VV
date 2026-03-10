from typing import Optional

# Server-side market type filters — frontend passes market_type, never raw predicates.
# See analytics_architecture.md for taxonomy rationale.
MARKET_FILTERS: dict[str, dict] = {
    "residential_units": {
        "property_type_en": "Unit",
        "property_usage_en": "Residential",
        "trans_group_en": "Sales",
    },
    "villas": {
        "property_type_en": "Villa",
        "trans_group_en": "Sales",
    },
    "commercial_units": {
        "property_type_en": "Unit",
        "property_usage_en__in": ["Commercial", "Hospitality"],
        "trans_group_en": "Sales",
    },
    "bulk_building": {
        "property_type_en": "Building",
        "trans_group_en": "Sales",
    },
    "land": {
        "property_type_en": "Land",
        "trans_group_en": "Sales",
    },
    "mortgages": {"trans_group_en": "Mortgages"},
    "gifts": {"trans_group_en": "Gifts"},
}


# =============================================================================
# TRANSACTION AND RENTAL LISTING QUERIES
# =============================================================================


def list_sales_transactions(
    limit: int = 50,
    offset: int = 0,
    property_usage: Optional[str] = None,
    master_project: Optional[str] = None,
    project_name: Optional[str] = None,
    building_name: Optional[str] = None,
    property_type: Optional[str] = None,
    rooms: Optional[str] = None,
    reg_type: Optional[str] = None,
    area_min: Optional[float] = None,
    area_max: Optional[float] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    days_back: Optional[int] = None,
) -> str:
    """
    Get paginated list of sales transactions with filtering.

    Optimized using sort key (property_usage_en, instance_date) for fast queries.
    """
    where_clauses = []

    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")
    if master_project is not None:
        where_clauses.append("master_project_en = {master_project:String}")
    if project_name is not None:
        where_clauses.append("project_name_en = {project_name:String}")
    if building_name is not None:
        where_clauses.append("building_name_en = {building_name:String}")
    if property_type is not None:
        where_clauses.append("property_type_en = {property_type:String}")
    if rooms is not None:
        where_clauses.append("rooms_en = {rooms:String}")
    if reg_type is not None:
        where_clauses.append("reg_type_en = {reg_type:String}")
    if area_min is not None:
        where_clauses.append("procedure_area >= {area_min:Decimal64(2)}")
    if area_max is not None:
        where_clauses.append("procedure_area <= {area_max:Decimal64(2)}")
    if price_min is not None:
        where_clauses.append("actual_worth >= {price_min:Decimal64(2)}")
    if price_max is not None:
        where_clauses.append("actual_worth <= {price_max:Decimal64(2)}")
    if days_back is not None:
        where_clauses.append("instance_date >= today() - {days_back:Int32}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT
            transaction_id,
            project_name_en,
            building_name_en,
            property_type_en,
            property_sub_type_en,
            rooms_en,
            procedure_area,
            actual_worth,
            meter_sale_price,
            reg_type_en,
            instance_date,
            area_name_en,
            trans_group_en,
            property_usage_en,
            master_project_en
        FROM ch_transactions
        WHERE {where_clause}
        ORDER BY instance_date DESC
        LIMIT {{limit:Int32}}
        OFFSET {{offset:Int32}}
    """


def count_sales_transactions(
    property_usage: Optional[str] = None,
    master_project: Optional[str] = None,
    project_name: Optional[str] = None,
    building_name: Optional[str] = None,
    property_type: Optional[str] = None,
    rooms: Optional[str] = None,
    reg_type: Optional[str] = None,
    area_min: Optional[float] = None,
    area_max: Optional[float] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    days_back: Optional[int] = None,
) -> str:
    """
    Count sales transactions matching filters.
    """
    where_clauses = []

    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")
    if master_project is not None:
        where_clauses.append("master_project_en = {master_project:String}")
    if project_name is not None:
        where_clauses.append("project_name_en = {project_name:String}")
    if building_name is not None:
        where_clauses.append("building_name_en = {building_name:String}")
    if property_type is not None:
        where_clauses.append("property_type_en = {property_type:String}")
    if rooms is not None:
        where_clauses.append("rooms_en = {rooms:String}")
    if reg_type is not None:
        where_clauses.append("reg_type_en = {reg_type:String}")
    if area_min is not None:
        where_clauses.append("procedure_area >= {area_min:Decimal64(2)}")
    if area_max is not None:
        where_clauses.append("procedure_area <= {area_max:Decimal64(2)}")
    if price_min is not None:
        where_clauses.append("actual_worth >= {price_min:Decimal64(2)}")
    if price_max is not None:
        where_clauses.append("actual_worth <= {price_max:Decimal64(2)}")
    if days_back is not None:
        where_clauses.append("instance_date >= today() - {days_back:Int32}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT count() as total
        FROM ch_transactions
        WHERE {where_clause}
    """


def list_rental_contracts(
    limit: int = 50,
    offset: int = 0,
    property_usage: Optional[str] = None,
    master_project: Optional[str] = None,
    project_name: Optional[str] = None,
    property_type: Optional[str] = None,
    tenant_type: Optional[str] = None,
    contract_reg_type: Optional[str] = None,
    area_min: Optional[float] = None,
    area_max: Optional[float] = None,
    rent_min: Optional[float] = None,
    rent_max: Optional[float] = None,
    days_back: Optional[int] = None,
) -> str:
    """
    Get paginated list of rental contracts with filtering.

    Optimized using sort key (property_usage_en, contract_start_date).
    """
    where_clauses = []

    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")
    if master_project is not None:
        where_clauses.append("master_project_en = {master_project:String}")
    if project_name is not None:
        where_clauses.append("project_name_en = {project_name:String}")
    if property_type is not None:
        where_clauses.append("ejari_property_type_en = {property_type:String}")
    if tenant_type is not None:
        where_clauses.append("tenant_type_en = {tenant_type:String}")
    if contract_reg_type is not None:
        where_clauses.append("contract_reg_type_en = {contract_reg_type:String}")
    if area_min is not None:
        where_clauses.append("actual_area >= {area_min:Decimal64(2)}")
    if area_max is not None:
        where_clauses.append("actual_area <= {area_max:Decimal64(2)}")
    if rent_min is not None:
        where_clauses.append("annual_amount >= {rent_min:Decimal64(2)}")
    if rent_max is not None:
        where_clauses.append("annual_amount <= {rent_max:Decimal64(2)}")
    if days_back is not None:
        where_clauses.append("contract_start_date >= today() - {days_back:Int32}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT
            contract_id,
            project_name_en,
            ejari_property_type_en,
            ejari_property_sub_type_en,
            tenant_type_en,
            actual_area,
            annual_amount,
            contract_reg_type_en,
            contract_start_date,
            contract_end_date,
            area_name_en,
            property_usage_en,
            master_project_en
        FROM ch_rent_contracts
        WHERE {where_clause}
        ORDER BY contract_start_date DESC
        LIMIT {{limit:Int32}}
        OFFSET {{offset:Int32}}
    """


def count_rental_contracts(
    property_usage: Optional[str] = None,
    master_project: Optional[str] = None,
    project_name: Optional[str] = None,
    property_type: Optional[str] = None,
    tenant_type: Optional[str] = None,
    contract_reg_type: Optional[str] = None,
    area_min: Optional[float] = None,
    area_max: Optional[float] = None,
    rent_min: Optional[float] = None,
    rent_max: Optional[float] = None,
    days_back: Optional[int] = None,
) -> str:
    """
    Count rental contracts matching filters.
    """
    where_clauses = []

    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")
    if master_project is not None:
        where_clauses.append("master_project_en = {master_project:String}")
    if project_name is not None:
        where_clauses.append("project_name_en = {project_name:String}")
    if property_type is not None:
        where_clauses.append("ejari_property_type_en = {property_type:String}")
    if tenant_type is not None:
        where_clauses.append("tenant_type_en = {tenant_type:String}")
    if contract_reg_type is not None:
        where_clauses.append("contract_reg_type_en = {contract_reg_type:String}")
    if area_min is not None:
        where_clauses.append("actual_area >= {area_min:Decimal64(2)}")
    if area_max is not None:
        where_clauses.append("actual_area <= {area_max:Decimal64(2)}")
    if rent_min is not None:
        where_clauses.append("annual_amount >= {rent_min:Decimal64(2)}")
    if rent_max is not None:
        where_clauses.append("annual_amount <= {rent_max:Decimal64(2)}")
    if days_back is not None:
        where_clauses.append("contract_start_date >= today() - {days_back:Int32}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT count() as total
        FROM ch_rent_contracts
        WHERE {where_clause}
    """


# =============================================================================
# ANALYTICS QUERIES - SALES
# =============================================================================


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
    price_bucket: Optional[str] = None,
    area_bucket: Optional[str] = None,
    property_usage_in: Optional[list] = None,
) -> str:
    """
    Get sales analytics summary for a date range.

    Returns: transaction_count, median_price, avg_price, total_volume,
             median_price_per_sqm, median_area_sqm

    All filtering uses parameter binding - no SQL injection risk.
    property_usage_in values must come from MARKET_FILTERS (trusted, not user input).
    """
    # Build WHERE clause with parameter placeholders
    where_clauses = [
        "trans_group_en = 'Sales'",
        "instance_date BETWEEN {start_date:Date} AND {end_date:Date}",
    ]
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")
    elif property_usage_in is not None:
        vals = "', '".join(property_usage_in)
        where_clauses.append(f"property_usage_en IN ('{vals}')")

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
        FROM ch_transactions
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
    property_usage_in: Optional[list] = None,
) -> str:
    """
    Get price trends over time (grouped by day, week, or month).

    Args:
        interval: 'day', 'week', or 'month'

    Returns: period, transaction_count, avg_price, avg_price_sqm
    property_usage_in values must come from MARKET_FILTERS (trusted, not user input).
    """
    # SAFE: interval is controlled by application, not user input
    if interval not in ("day", "week", "month"):
        raise ValueError("interval must be 'day', 'week', or 'month'")

    if interval == "day":
        time_group = "instance_date"
    elif interval == "week":
        time_group = "toStartOfWeek(instance_date)"
    else:
        time_group = "toStartOfMonth(instance_date)"

    where_clauses = [
        "trans_group_en = 'Sales'",
        "instance_date BETWEEN {start_date:Date} AND {end_date:Date}",
    ]
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")
    elif property_usage_in is not None:
        vals = "', '".join(property_usage_in)
        where_clauses.append(f"property_usage_en IN ('{vals}')")

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
            round(avg(actual_worth), 2) as avg_price,
            round(avg(meter_sale_price), 2) as avg_price_sqm
        FROM ch_transactions
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
        "trans_group_en = 'Sales'",
        "property_usage_en = {property_usage:String}",
        "instance_date BETWEEN {start_date:Date} AND {end_date:Date}",
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
        FROM ch_transactions
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
        "trans_group_en = 'Sales'",
        "property_usage_en = {property_usage:String}",
        "instance_date BETWEEN {start_date:Date} AND {end_date:Date}",
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
        FROM ch_transactions
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
        "trans_group_en = 'Sales'",
        "property_type_en IN ('Unit', 'Villa')",
        "property_usage_en = {property_usage:String}",
        "instance_date BETWEEN {start_date:Date} AND {end_date:Date}",
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
        FROM ch_transactions
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
            round(median(annual_amount / nullIf(actual_area, 0)), 2) as median_rent_per_sqm,
            round(median(actual_area), 2) as median_area_sqm
        FROM ch_rent_contracts
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
    column = "ejari_property_type_en" if table == "ch_rent_contracts" else "property_type_en"

    where_clauses = []
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT DISTINCT {column}
        FROM {table}
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

    where_clauses = []
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT DISTINCT area_name_en
        FROM {table}
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

    where_clauses = []
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")
    if area_name is not None:
        where_clauses.append("area_name_en = {area_name:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT DISTINCT master_project_en
        FROM {table}
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

    where_clauses = []
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")
    if property_type is not None:
        column = "ejari_property_type_en" if table == "ch_rent_contracts" else "property_type_en"
        where_clauses.append(f"{column} = {{property_type:String}}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT DISTINCT rooms_en
        FROM {table}
        WHERE {where_clause} AND rooms_en IS NOT NULL
        ORDER BY rooms_en
    """


def distinct_property_sub_types(
    table: str = "ch_transactions",
    property_usage: Optional[str] = None,
    property_type: Optional[str] = None,
) -> str:
    """
    Get distinct property sub types for filter dropdowns.

    LowCardinality column = instant query.
    """
    if table not in ("ch_transactions", "ch_rent_contracts"):
        raise ValueError("table must be 'ch_transactions' or 'ch_rent_contracts'")

    # Use appropriate column name for each table
    sub_type_column = (
        "ejari_property_sub_type_en" if table == "ch_rent_contracts" else "property_sub_type_en"
    )
    type_column = "ejari_property_type_en" if table == "ch_rent_contracts" else "property_type_en"

    where_clauses = []
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")
    if property_type is not None:
        where_clauses.append(f"{type_column} = {{property_type:String}}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT DISTINCT {sub_type_column}
        FROM {table}
        WHERE {where_clause} AND {sub_type_column} IS NOT NULL
        ORDER BY {sub_type_column}
    """


def distinct_registration_types(
    property_usage: Optional[str] = None,
    property_type: Optional[str] = None,
) -> str:
    """
    Get distinct registration types for sales filter dropdowns.

    LowCardinality column = instant query.
    """
    where_clauses = []
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")
    if property_type is not None:
        where_clauses.append("property_type_en = {property_type:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT DISTINCT reg_type_en
        FROM ch_transactions
        WHERE {where_clause} AND reg_type_en IS NOT NULL
        ORDER BY reg_type_en
    """


def distinct_tenant_types(
    property_usage: Optional[str] = None,
    property_type: Optional[str] = None,
) -> str:
    """
    Get distinct tenant types for rental filter dropdowns.

    LowCardinality column = instant query.
    """
    where_clauses = []
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")
    if property_type is not None:
        where_clauses.append("ejari_property_type_en = {property_type:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT DISTINCT tenant_type_en
        FROM ch_rent_contracts
        WHERE {where_clause} AND tenant_type_en IS NOT NULL
        ORDER BY tenant_type_en
    """


def distinct_contract_reg_types(
    property_usage: Optional[str] = None,
    property_type: Optional[str] = None,
) -> str:
    """
    Get distinct contract registration types for rental filter dropdowns.

    LowCardinality column = instant query.
    """
    where_clauses = []
    if property_usage is not None:
        where_clauses.append("property_usage_en = {property_usage:String}")
    if property_type is not None:
        where_clauses.append("ejari_property_type_en = {property_type:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT DISTINCT contract_reg_type_en
        FROM ch_rent_contracts
        WHERE {where_clause} AND contract_reg_type_en IS NOT NULL
        ORDER BY contract_reg_type_en
    """


def get_upcoming_projects(
    limit: int = 100,
    offset: int = 0,
) -> str:
    """
    Get upcoming/active projects for supply catalog.

    Active = has start_date AND no completion_date AND no cancellation_date
    """
    return """
        SELECT
            p.project_id,
            p.project_name,
            p.developer_id,
            d.developer_name_en as developer_name,
            p.area_name_en,
            p.project_start_date,
            p.project_end_date,
            p.percent_completed,
            p.no_of_buildings,
            p.no_of_units
        FROM ch_projects p
        LEFT JOIN ch_developers d ON p.developer_id = d.developer_id
        WHERE
            p.project_start_date IS NOT NULL
            AND p.completion_date IS NULL
            AND p.cancellation_date IS NULL
        ORDER BY
            p.project_end_date ASC NULLS LAST,
            p.project_name ASC
        LIMIT {limit:Int32}
        OFFSET {offset:Int32}
    """


# =============================================================================
# PROJECTS QUERIES (DEPRECATED - Use direct queries in service layer instead)
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
    DEPRECATED: Use direct queries in app/project/service.py instead.

    List projects with optional filters.
    """
    where_clauses = ["1=1"]

    if area_id is not None:
        where_clauses.append("area_id = {area_id:Int32}")
    if developer_id is not None:
        where_clauses.append("developer_id = {developer_id:Int32}")
    if project_status is not None:
        where_clauses.append("project_status = {project_status:String}")

    where_clause = " AND ".join(where_clauses)

    return f"""
        SELECT
            project_id,
            project_number,
            project_name,
            master_project_en,
            developer_id,
            area_id,
            area_name_en,
            project_status,
            no_of_units,
            no_of_buildings,
            no_of_villas,
            completion_date
        FROM ch_projects
        WHERE {where_clause}
        ORDER BY project_name
        LIMIT {{limit:Int32}}
        OFFSET {{offset:Int32}}
    """


def get_project_details(project_id: int) -> str:
    """
    DEPRECATED: Use direct queries in app/project/service.py instead.

    Get full project details by ID.
    """
    return """
        SELECT
            project_id,
            project_number,
            project_name,
            master_project_en,
            developer_id,
            master_developer_id,
            area_id,
            area_name_en,
            project_status,
            project_start_date,
            completion_date,
            project_end_date,
            cancellation_date,
            percent_completed,
            no_of_units,
            no_of_buildings,
            no_of_villas,
            escrow_agent_name,
            zoning_authority_en
        FROM ch_projects
        WHERE project_id = {project_id:Int32}
    """


def list_developers(limit: int = 100, offset: int = 0) -> str:
    """
    DEPRECATED: Use direct queries in service layer instead.

    List all developers.
    """
    return """
        SELECT
            developer_id,
            developer_number,
            developer_name_en,
            developer_name_ar
        FROM ch_developers
        ORDER BY developer_name_en
        LIMIT {limit:Int32}
        OFFSET {offset:Int32}
    """


def list_buildings_for_project(project_number: str, limit: int = 100, offset: int = 0) -> str:
    """
    DEPRECATED: Use direct queries in service layer instead.

    List buildings for a specific project.
    """
    return """
        SELECT
            property_id,
            building_number,
            project_id,
            project_number,
            project_name_en,
            bld_levels,
            floors,
            flats,
            offices,
            car_parks,
            shops,
            elevators,
            swimming_pools,
            is_free_hold
        FROM ch_buildings
        WHERE project_number = {project_number:String}
        ORDER BY building_number
        LIMIT {limit:Int32}
        OFFSET {offset:Int32}
    """


def list_units_for_building(building_id: int, limit: int = 100, offset: int = 0) -> str:
    """
    DEPRECATED: Use direct queries in service layer instead.

    List units for a specific building.
    """
    return """
        SELECT
            property_id,
            unit_number,
            parent_property_id,
            project_id,
            project_number,
            project_name_en,
            property_type_en,
            rooms_en,
            actual_area,
            floor
        FROM ch_units
        WHERE parent_property_id = {building_id:Int32}
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
        FROM ch_units
        WHERE
            project_number = {project_number:String}
            AND property_usage_en = {property_usage:String}
            AND rooms_en = {rooms:String}
            AND actual_area BETWEEN {area_min:Decimal64(2)} AND {area_max:Decimal64(2)}

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
        FROM ch_transactions
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
        FROM ch_rent_contracts
        WHERE {where_clause}
        ORDER BY contract_start_date DESC
        LIMIT {{limit:Int32}}
    """


# =============================================================================
# PROJECT ANALYTICS QUERIES
# =============================================================================


def search_projects() -> str:
    """
    Search projects for the selector dropdown. Returns three types:
    - 'master': real master_project_en groupings
    - 'virtual_master': derived groupings from ' - ' prefix on orphaned projects with >1 sub-project
    - 'project': truly standalone projects not covered by any grouping
    """
    return """
        WITH virtual_masters AS (
            SELECT substring(project_name_en, 1, position(project_name_en, ' - ') - 1) AS prefix
            FROM ch_transactions
            WHERE (master_project_en = '' OR master_project_en IS NULL)
              AND position(project_name_en, ' - ') > 0
              AND project_name_en <> ''
            GROUP BY prefix
            HAVING count(DISTINCT project_name_en) > 1
               AND lower(prefix) NOT IN (
                   SELECT lower(master_project_en)
                   FROM ch_transactions
                   WHERE master_project_en <> ''
               )
        )
        SELECT name, filter_type FROM (
            SELECT DISTINCT master_project_en AS name, 'master' AS filter_type
            FROM ch_transactions
            WHERE master_project_en <> ''
              AND lower(master_project_en) LIKE {search_pattern:String}

            UNION ALL

            SELECT prefix AS name, 'virtual_master' AS filter_type
            FROM virtual_masters
            WHERE lower(prefix) LIKE {search_pattern:String}

            UNION ALL

            SELECT DISTINCT project_name_en AS name, 'project' AS filter_type
            FROM ch_transactions
            WHERE (master_project_en = '' OR master_project_en IS NULL)
              AND project_name_en <> ''
              AND lower(project_name_en) LIKE {search_pattern:String}
              AND project_name_en NOT IN (SELECT prefix FROM virtual_masters)
              AND (
                  position(project_name_en, ' - ') = 0
                  OR substring(project_name_en, 1, position(project_name_en, ' - ') - 1)
                     NOT IN (SELECT prefix FROM virtual_masters)
              )
              -- Exclude orphaned sub-projects whose prefix matches a real master (case-insensitive)
              AND NOT (
                  position(project_name_en, ' - ') > 0
                  AND lower(substring(project_name_en, 1, position(project_name_en, ' - ') - 1))
                      IN (SELECT lower(master_project_en) FROM ch_transactions WHERE master_project_en <> '')
              )
        )
        ORDER BY name
        LIMIT {limit:Int32}
    """


def search_sub_projects(filter_type: str = "master") -> str:
    """Return sub-projects (project_name_en) for a master or virtual_master, sorted by activity."""
    if filter_type == "virtual_master":
        where = "project_name_en LIKE {master_project:String}"
    else:
        # Include both properly-linked sub-projects and orphaned ones with the prefix naming pattern
        where = """(master_project_en = {master_project:String}
            OR (lower(project_name_en) LIKE concat(lower({master_project:String}), ' - %')
                AND (master_project_en = '' OR master_project_en IS NULL)))"""
    return f"""
        SELECT project_name_en, count() AS transaction_count
        FROM ch_transactions
        WHERE {where}
          AND project_name_en IS NOT NULL
          AND project_name_en <> ''
        GROUP BY project_name_en
        ORDER BY transaction_count DESC
    """


def _project_filter(filter_type: str) -> str:
    """WHERE clause condition for a given filter type.

    master: matches rows with master_project_en = X OR orphaned rows whose
    project_name_en starts with X + ' - ' (absorbs inconsistently-linked sub-projects).
    """
    if filter_type == "master":
        return """(master_project_en = {project_name:String}
            OR (lower(project_name_en) LIKE concat(lower({project_name:String}), ' - %')
                AND (master_project_en = '' OR master_project_en IS NULL)))"""
    if filter_type == "virtual_master":
        return "project_name_en LIKE {project_name:String}"
    return "project_name_en = {project_name:String}"


def project_sales_summary(filter_type: str = "project", reg_type: Optional[str] = None) -> str:
    """Overall sales KPIs for a project, master project, or virtual master.

    Filters to Sales transactions on Unit/Villa only to exclude mortgage/gift/building/land noise.
    Pass reg_type='Existing Properties' to get existing-only avg_price for yield denominator.
    """
    reg_filter = "AND reg_type_en = {reg_type_en:String}" if reg_type else ""
    return f"""
        SELECT
            count() as transaction_count,
            round(coalesce(sum(actual_worth), 0), 2) as total_volume,
            round(coalesce(avg(actual_worth), 0), 2) as avg_price,
            round(coalesce(avg(meter_sale_price), 0), 2) as avg_price_sqm,
            round(coalesce(median(actual_worth), 0), 2) as median_price
        FROM ch_transactions
        WHERE {_project_filter(filter_type)}
          AND trans_group_en = 'Sales'
          AND property_type_en IN ('Unit', 'Villa')
          AND property_usage_en = 'Residential'
          AND actual_worth > 0
          {reg_filter}
    """


def project_sales_by_rooms(filter_type: str = "project", reg_type: Optional[str] = None) -> str:
    """Sales breakdown by bedroom count for a project, master project, or virtual master.

    Pass reg_type='Existing Properties' to get existing-only avg_sale_price for yield denominator.
    """
    reg_filter = "AND reg_type_en = {reg_type_en:String}" if reg_type else ""
    return f"""
        SELECT
            rooms_en,
            count() as sale_count,
            round(avg(actual_worth), 2) as avg_sale_price,
            round(median(actual_worth), 2) as median_sale_price,
            round(avg(meter_sale_price), 2) as avg_sale_price_sqm
        FROM ch_transactions
        WHERE {_project_filter(filter_type)}
          AND trans_group_en = 'Sales'
          AND property_type_en IN ('Unit', 'Villa')
          AND property_usage_en = 'Residential'
          AND rooms_en IS NOT NULL
          AND actual_worth > 0
          {reg_filter}
        GROUP BY rooms_en
        ORDER BY sale_count DESC
    """


def project_sales_by_property_type(filter_type: str = "project") -> str:
    """Sales breakdown by property type for a project, master project, or virtual master.

    Shows all property types (Unit, Villa, Building, Land) so breakdown is informational.
    Excludes mortgages and gifts via trans_group_en filter.
    """
    return f"""
        SELECT
            property_type_en,
            count() as count,
            round(avg(actual_worth), 2) as avg_price
        FROM ch_transactions
        WHERE {_project_filter(filter_type)}
          AND trans_group_en = 'Sales'
          AND property_type_en IS NOT NULL
          AND actual_worth > 0
        GROUP BY property_type_en
        ORDER BY count DESC
    """


def project_sales_by_reg_type(filter_type: str = "project") -> str:
    """Sales breakdown by registration type (Off-Plan vs Existing) for a project."""
    return f"""
        SELECT
            reg_type_en,
            count() as count,
            round(avg(actual_worth), 2) as avg_price
        FROM ch_transactions
        WHERE {_project_filter(filter_type)}
          AND trans_group_en = 'Sales'
          AND property_type_en IN ('Unit', 'Villa')
          AND property_usage_en = 'Residential'
          AND reg_type_en IS NOT NULL
        GROUP BY reg_type_en
        ORDER BY count DESC
    """


def project_rentals_summary(filter_type: str = "project") -> str:
    """Overall rental KPIs for a project, master project, or virtual master.

    Uses median for rent figures — avg is severely skewed by outlier contracts
    (multi-year totals, bulk leases) that inflate the mean by 5-10x.
    """
    return f"""
        SELECT
            count() as contract_count,
            round(coalesce(sum(annual_amount), 0), 2) as total_annual_value,
            round(coalesce(median(annual_amount), 0), 2) as median_annual_rent,
            round(coalesce(median(annual_amount / nullIf(actual_area, 0)), 0), 2) as median_rent_sqm
        FROM ch_rent_contracts
        WHERE {_project_filter(filter_type)}
          AND property_usage_en = 'Residential'
          AND annual_amount > 0
    """


def project_rentals_by_rooms(filter_type: str = "project") -> str:
    """Per-room rental KPIs inferred from unit area distributions.

    ch_rent_contracts has no rooms_en, so room type is assigned probabilistically:
    - Compute IQR (p25/p75) area range per room type from ch_units (needs >= 3 units)
    - Only includes standard residential types (B/R, Studio, PENTHOUSE)
    - Join rent contracts to those ranges; keep only unambiguous matches
      (actual_area falls in exactly one room type's IQR)
    - Uses median for rent figures — avg is skewed by outlier contracts
    - Coverage: ~50-70% of contracts per project (the rest are ambiguous or out-of-range)

    All filter types use {project_name:String} for both the rent filter and units CTE.
    """
    # Unit area range filter — must scope to the same project
    if filter_type == "virtual_master":
        unit_filter = "project_name_en LIKE {project_name:String}"
    elif filter_type == "master":
        unit_filter = """(master_project_en = {project_name:String}
            OR (lower(project_name_en) LIKE concat(lower({project_name:String}), ' - %')
                AND (master_project_en = '' OR master_project_en IS NULL)))"""
    else:  # project — ch_units has project_name_en populated per sub-project
        unit_filter = "project_name_en = {project_name:String}"

    rent_filter = _project_filter(filter_type)

    return f"""
        SELECT
            rooms_en,
            count() AS rental_count,
            round(median(annual_amount), 2) AS median_annual_rent,
            round(median(annual_amount / nullIf(actual_area, 0)), 2) AS median_rent_sqm
        FROM (
            SELECT any(ar.rooms_en) AS rooms_en, annual_amount, actual_area
            FROM ch_rent_contracts
            INNER JOIN (
                SELECT
                    rooms_en,
                    quantile(0.25)(actual_area) AS lo,
                    quantile(0.75)(actual_area) AS hi,
                    count() AS n
                FROM ch_units
                WHERE {unit_filter}
                  AND (rooms_en LIKE '% B/R' OR rooms_en = 'Studio' OR rooms_en LIKE '%ENTHOUSE')
                  AND actual_area > 0
                GROUP BY rooms_en
                HAVING n >= 3
            ) AS ar ON actual_area BETWEEN ar.lo AND ar.hi
            WHERE {rent_filter}
              AND property_usage_en = 'Residential'
              AND annual_amount > 0
              AND actual_area > 0
            GROUP BY contract_id, line_number, annual_amount, actual_area
            HAVING count(DISTINCT ar.rooms_en) = 1
        )
        GROUP BY rooms_en
        ORDER BY rental_count DESC
    """


def project_units_composition(filter_type: str = "project") -> str:
    """Unit supply composition by bedroom count from ch_units.

    master → master_project_en = X OR orphaned rows with project_name_en LIKE 'X - %'
    virtual_master → project_name_en LIKE {project_name} (LIKE suffix already in param)
    project → master_project_en = X (receives master_project as project_name)
    """
    if filter_type == "virtual_master":
        where = "project_name_en LIKE {project_name:String}"
    elif filter_type == "master":
        where = """(master_project_en = {project_name:String}
            OR (lower(project_name_en) LIKE concat(lower({project_name:String}), ' - %')
                AND (master_project_en = '' OR master_project_en IS NULL)))"""
    else:
        where = "master_project_en = {project_name:String}"
    return f"""
        SELECT
            rooms_en,
            count() as unit_count
        FROM ch_units
        WHERE {where}
          AND rooms_en IS NOT NULL
        GROUP BY rooms_en
        ORDER BY unit_count DESC
    """


def project_meta_by_name() -> str:
    """Sub-project metadata joined with developer name."""
    return """
        SELECT
            p.project_name_en,
            p.area_name_en,
            d.developer_name_en,
            p.project_status,
            p.completion_date,
            p.percent_completed,
            p.no_of_units,
            p.no_of_buildings
        FROM ch_projects p
        LEFT JOIN ch_developers d ON p.developer_id = d.developer_id
        WHERE p.project_name_en = {project_name:String}
        LIMIT 1
    """


def project_meta_by_master() -> str:
    """Aggregated metadata for a master project, including orphaned sub-projects in ch_projects."""
    return """
        SELECT
            any(p.area_name_en) as area_name_en,
            any(d.developer_name_en) as developer_name_en,
            toNullable(toInt64(sum(p.no_of_units))) as no_of_units,
            toNullable(toInt64(sum(p.no_of_buildings))) as no_of_buildings
        FROM ch_projects p
        LEFT JOIN ch_developers d ON p.developer_id = d.developer_id
        WHERE (p.master_project_en = {project_name:String}
            OR lower(p.project_name_en) LIKE concat(lower({project_name:String}), ' - %'))
    """


def project_meta_by_virtual_master() -> str:
    """Aggregated metadata for a virtual master (matched by project_name_en LIKE prefix)."""
    return """
        SELECT
            any(p.area_name_en) as area_name_en,
            any(d.developer_name_en) as developer_name_en,
            toNullable(toInt64(sum(p.no_of_units))) as no_of_units,
            toNullable(toInt64(sum(p.no_of_buildings))) as no_of_buildings
        FROM ch_projects p
        LEFT JOIN ch_developers d ON p.developer_id = d.developer_id
        WHERE p.project_name_en LIKE {project_name:String}
    """


def project_price_trends(interval: str = "month", filter_type: str = "project") -> str:
    """Monthly/weekly/daily sales price trend for a project, master, or virtual master."""
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
            round(avg(meter_sale_price), 2) as avg_price_sqm
        FROM ch_transactions
        WHERE {_project_filter(filter_type)}
          AND trans_group_en = 'Sales'
          AND property_type_en IN ('Unit', 'Villa')
          AND property_usage_en = 'Residential'
          AND instance_date BETWEEN {{start_date:Date}} AND {{end_date:Date}}
          AND actual_worth > 0
        GROUP BY period
        ORDER BY period ASC
    """
