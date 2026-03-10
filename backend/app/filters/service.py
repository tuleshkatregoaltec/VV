"""Filter options service - redesigned for ClickHouse from first principles."""

import re
from typing import Optional

from app.clickhouse.client import query
from app.clickhouse.queries import _project_filter
from app.filters.models import FilterOptionsResponse


def _rooms_sort_key(room: str) -> tuple:
    """Studio first, then numeric bedroom counts in order, then anything else."""
    if room.lower() == "studio":
        return (0, 0)
    m = re.match(r"^(\d+)", room)
    if m:
        return (1, int(m.group(1)))
    return (2, 0)


async def get_sales_filter_options(
    property_usage: Optional[str] = None,
    project: Optional[str] = None,
    filter_type: str = "project",
    property_type: Optional[str] = None,
    area: Optional[str] = None,
) -> FilterOptionsResponse:
    """
    Get filter options for sales transactions.

    Uses ClickHouse LowCardinality columns for instant (<10ms) DISTINCT queries.
    Supports dynamic narrowing: selecting a project narrows buildings to that project.
    """

    # Build WHERE clause for filtering
    where_clauses = []
    params = {}

    if property_usage:
        where_clauses.append("property_usage_en = {property_usage:String}")
        params["property_usage"] = property_usage

    if project:
        where_clauses.append(_project_filter(filter_type))
        params["project_name"] = project + " - %" if filter_type == "virtual_master" else project

    if property_type:
        where_clauses.append("property_type_en = {property_type:String}")
        params["property_type"] = property_type

    if area:
        where_clauses.append("area_name_en = {area:String}")
        params["area"] = area

    where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"

    # Get property types (LowCardinality = instant)
    property_types_sql = f"""
        SELECT DISTINCT property_type_en
        FROM ch_transactions
        WHERE {where_clause} AND property_type_en != ''
        ORDER BY property_type_en
    """
    property_types_result = await query(property_types_sql, params)
    property_types = [row["property_type_en"] for row in property_types_result]

    # Get property sub types (LowCardinality = instant)
    property_sub_types_sql = f"""
        SELECT DISTINCT property_sub_type_en
        FROM ch_transactions
        WHERE {where_clause} AND property_sub_type_en != ''
        ORDER BY property_sub_type_en
    """
    property_sub_types_result = await query(property_sub_types_sql, params)
    property_sub_types = [row["property_sub_type_en"] for row in property_sub_types_result]

    # Get rooms (LowCardinality = instant) - sorted numerically, not alphabetically
    rooms_sql = f"""
        SELECT DISTINCT rooms_en
        FROM ch_transactions
        WHERE {where_clause} AND rooms_en != ''
    """
    rooms_result = await query(rooms_sql, params)
    rooms = sorted([row["rooms_en"] for row in rooms_result], key=_rooms_sort_key)

    # Get registration types (LowCardinality = instant)
    reg_types_sql = f"""
        SELECT DISTINCT reg_type_en
        FROM ch_transactions
        WHERE {where_clause} AND reg_type_en != ''
        ORDER BY reg_type_en
    """
    reg_types_result = await query(reg_types_sql, params)
    registration_types = [row["reg_type_en"] for row in reg_types_result]

    # Get areas (LowCardinality = instant)
    areas_sql = f"""
        SELECT DISTINCT area_name_en
        FROM ch_transactions
        WHERE {where_clause} AND area_name_en != ''
        ORDER BY area_name_en
    """
    areas_result = await query(areas_sql, params)
    areas = [row["area_name_en"] for row in areas_result]

    # Get projects (not LowCardinality, but still fast with WHERE clause)
    projects_sql = f"""
        SELECT DISTINCT project_name_en
        FROM ch_transactions
        WHERE {where_clause} AND project_name_en != ''
        ORDER BY project_name_en
    """
    projects_result = await query(projects_sql, params)
    projects = [row["project_name_en"] for row in projects_result]

    # Get buildings (dynamic - filtered by project if selected)
    buildings_sql = f"""
        SELECT DISTINCT building_name_en
        FROM ch_transactions
        WHERE {where_clause} AND building_name_en != ''
        ORDER BY building_name_en
        LIMIT 1000
    """
    buildings_result = await query(buildings_sql, params)
    buildings = [row["building_name_en"] for row in buildings_result]

    return FilterOptionsResponse(
        property_types=property_types,
        property_sub_types=property_sub_types,
        rooms=rooms,
        registration_types=registration_types,
        areas=areas,
        projects=projects,
        buildings=buildings,
    )


async def get_rental_filter_options(
    property_usage: Optional[str] = None,
    project: Optional[str] = None,
    filter_type: str = "project",
    property_type: Optional[str] = None,
    area: Optional[str] = None,
) -> FilterOptionsResponse:
    """
    Get filter options for rental contracts.

    Uses ClickHouse LowCardinality columns for instant (<10ms) DISTINCT queries.
    """

    # Build WHERE clause for filtering
    where_clauses = []
    params = {}

    if property_usage:
        where_clauses.append("property_usage_en = {property_usage:String}")
        params["property_usage"] = property_usage

    if project:
        where_clauses.append(_project_filter(filter_type))
        params["project_name"] = project + " - %" if filter_type == "virtual_master" else project

    if property_type:
        where_clauses.append("ejari_property_type_en = {property_type:String}")
        params["property_type"] = property_type

    if area:
        where_clauses.append("area_name_en = {area:String}")
        params["area"] = area

    where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"

    # Get property types (ejari for rentals, LowCardinality = instant)
    property_types_sql = f"""
        SELECT DISTINCT ejari_property_type_en
        FROM ch_rent_contracts
        WHERE {where_clause} AND ejari_property_type_en != ''
        ORDER BY ejari_property_type_en
    """
    property_types_result = await query(property_types_sql, params)
    property_types = [row["ejari_property_type_en"] for row in property_types_result]

    # Get property sub types (ejari for rentals, LowCardinality = instant)
    property_sub_types_sql = f"""
        SELECT DISTINCT ejari_property_sub_type_en
        FROM ch_rent_contracts
        WHERE {where_clause} AND ejari_property_sub_type_en != ''
        ORDER BY ejari_property_sub_type_en
    """
    property_sub_types_result = await query(property_sub_types_sql, params)
    property_sub_types = [row["ejari_property_sub_type_en"] for row in property_sub_types_result]

    # Get tenant types (LowCardinality = instant)
    tenant_types_sql = f"""
        SELECT DISTINCT tenant_type_en
        FROM ch_rent_contracts
        WHERE {where_clause} AND tenant_type_en != ''
        ORDER BY tenant_type_en
    """
    tenant_types_result = await query(tenant_types_sql, params)
    tenant_types = [row["tenant_type_en"] for row in tenant_types_result]

    # Get contract registration types (LowCardinality = instant)
    contract_reg_types_sql = f"""
        SELECT DISTINCT contract_reg_type_en
        FROM ch_rent_contracts
        WHERE {where_clause} AND contract_reg_type_en != ''
        ORDER BY contract_reg_type_en
    """
    contract_reg_types_result = await query(contract_reg_types_sql, params)
    contract_reg_types = [row["contract_reg_type_en"] for row in contract_reg_types_result]

    # Get areas (LowCardinality = instant)
    areas_sql = f"""
        SELECT DISTINCT area_name_en
        FROM ch_rent_contracts
        WHERE {where_clause} AND area_name_en != ''
        ORDER BY area_name_en
    """
    areas_result = await query(areas_sql, params)
    areas = [row["area_name_en"] for row in areas_result]

    # Get projects (not LowCardinality, but still fast)
    projects_sql = f"""
        SELECT DISTINCT project_name_en
        FROM ch_rent_contracts
        WHERE {where_clause} AND project_name_en != ''
        ORDER BY project_name_en
    """
    projects_result = await query(projects_sql, params)
    projects = [row["project_name_en"] for row in projects_result]

    return FilterOptionsResponse(
        property_types=property_types,
        property_sub_types=property_sub_types,
        tenant_types=tenant_types,
        contract_reg_types=contract_reg_types,
        areas=areas,
        projects=projects,
        buildings=[],  # Rentals don't have building names in schema
    )
