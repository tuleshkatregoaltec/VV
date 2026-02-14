"""Business logic for project analytics — merges parallel ClickHouse results."""

import asyncio
from datetime import date, timedelta
from typing import Optional

from app.clickhouse.client import query
from app.clickhouse.queries import (
    search_projects,
    search_sub_projects,
    project_sales_summary,
    project_sales_by_rooms,
    project_sales_by_property_type,
    project_sales_by_reg_type,
    project_rentals_summary,
    project_rentals_by_rooms,
    project_units_composition,
    project_meta_by_name,
    project_meta_by_master,
    project_meta_by_virtual_master,
    project_price_trends,
)
from app.analytics.models import (
    ProjectMeta,
    ProjectSalesSummary,
    ProjectRentalSummary,
    RoomAnalytics,
    PropertyTypeBreakdown,
    RegTypeBreakdown,
    UnitComposition,
    ProjectAnalyticsResponse,
    ProjectTrendPoint,
    ProjectTrendsResponse,
    ProjectSearchItem,
    ProjectSearchResponse,
    SubProjectItem,
    SubProjectsResponse,
)

# Room sort order: Studio first, then numeric bedrooms, then anything else
_ROOM_ORDER = {"Studio": 0}


def _room_sort_key(rooms: str) -> tuple:
    if rooms in _ROOM_ORDER:
        return (0, 0)
    # Extract leading number e.g. "1 B/R" → 1
    parts = rooms.split()
    try:
        return (1, int(parts[0]))
    except (ValueError, IndexError):
        return (2, rooms)


async def get_project_search(search: str, limit: int = 50) -> ProjectSearchResponse:
    """Return matching projects for the dropdown selector."""
    pattern = f"%{search.lower()}%" if search.strip() else "%"
    rows = await query(
        search_projects(),
        {"search_pattern": pattern, "limit": limit},
    )
    return ProjectSearchResponse(
        projects=[
            ProjectSearchItem(name=r["name"], filter_type=r["filter_type"])
            for r in rows
        ]
    )


async def get_sub_project_list(master_project: str, filter_type: str = "master") -> SubProjectsResponse:
    """Return sub-projects for a given master/virtual_master, sorted by transaction volume."""
    param = master_project + " - %" if filter_type == "virtual_master" else master_project
    rows = await query(
        search_sub_projects(filter_type),
        {"master_project": param},
    )
    return SubProjectsResponse(
        sub_projects=[
            SubProjectItem(name=r["project_name_en"], transaction_count=int(r["transaction_count"]))
            for r in rows
        ]
    )


async def get_project_summary(
    project_name: str,
    filter_type: str = "project",
    master_project: Optional[str] = None,
) -> ProjectAnalyticsResponse:
    """
    Run 10 ClickHouse queries in parallel and merge into a single response.
    filter_type controls the WHERE clause: 'master', 'virtual_master', or 'project'.
    For virtual_master, project_name is used as a LIKE prefix (suffix ' - %' appended here).
    """
    # For LIKE queries the param needs the wildcard appended
    like_name = project_name + " - %" if filter_type == "virtual_master" else project_name
    params = {"project_name": like_name}

    # Unit composition: master/project use master_project_en equality;
    # virtual_master uses project_name_en LIKE (ch_units also lacks master_project_en for orphans)
    if filter_type == "virtual_master":
        units_params = {"project_name": like_name}
    elif filter_type == "master":
        units_params = {"project_name": project_name}
    else:
        units_params = {"project_name": master_project or project_name}

    meta_fn = {
        "master": project_meta_by_master,
        "virtual_master": project_meta_by_virtual_master,
        "project": project_meta_by_name,
    }[filter_type]
    # meta for master/virtual_master uses the like_name for virtual (LIKE) or plain name
    meta_params = {"project_name": like_name} if filter_type == "virtual_master" else {"project_name": project_name}

    existing_params = {**params, "reg_type_en": "Existing Properties"}

    # project_rentals_by_rooms uses {project_name} for both rent and units filters
    rent_rooms_params = params

    (
        sales_sum_rows,
        sales_sum_existing_rows,
        sales_rooms_rows,
        sales_rooms_existing_rows,
        sales_type_rows,
        sales_reg_rows,
        rent_sum_rows,
        rent_rooms_rows,
        units_rows,
        meta_rows,
    ) = await asyncio.gather(
        query(project_sales_summary(filter_type), params),
        query(project_sales_summary(filter_type, reg_type="Existing Properties"), existing_params),
        query(project_sales_by_rooms(filter_type), params),
        query(project_sales_by_rooms(filter_type, reg_type="Existing Properties"), existing_params),
        query(project_sales_by_property_type(filter_type), params),
        query(project_sales_by_reg_type(filter_type), params),
        query(project_rentals_summary(filter_type), params),
        query(project_rentals_by_rooms(filter_type), rent_rooms_params),
        query(project_units_composition(filter_type), units_params),
        query(meta_fn(), meta_params),
    )

    # --- Project metadata ---
    project: Optional[ProjectMeta] = None
    if meta_rows:
        m = meta_rows[0]
        if filter_type in ("master", "virtual_master"):
            project = ProjectMeta(
                project_name=project_name,
                area_name=m.get("area_name_en") or None,
                developer_name=m.get("developer_name_en") or None,
                project_status=None,
                completion_date=None,
                percent_completed=None,
                no_of_units=int(m["no_of_units"]) if m.get("no_of_units") is not None else None,
                no_of_buildings=int(m["no_of_buildings"]) if m.get("no_of_buildings") is not None else None,
            )
        else:
            project = ProjectMeta(
                project_name=m.get("project_name_en", project_name),
                area_name=m.get("area_name_en") or None,
                developer_name=m.get("developer_name_en") or None,
                project_status=m.get("project_status") or None,
                completion_date=m.get("completion_date") or None,
                percent_completed=float(m["percent_completed"]) if m.get("percent_completed") is not None else None,
                no_of_units=int(m["no_of_units"]) if m.get("no_of_units") is not None else None,
                no_of_buildings=int(m["no_of_buildings"]) if m.get("no_of_buildings") is not None else None,
            )

    # --- Sales summary ---
    s = sales_sum_rows[0] if sales_sum_rows else {}
    sales = ProjectSalesSummary(
        transaction_count=int(s.get("transaction_count", 0)),
        total_volume=float(s.get("total_volume", 0) or 0),
        avg_price=float(s.get("avg_price", 0) or 0),
        avg_price_sqm=float(s.get("avg_price_sqm", 0) or 0),
        median_price=float(s.get("median_price", 0) or 0),
    )

    # --- Rental summary ---
    r = rent_sum_rows[0] if rent_sum_rows else {}
    rentals = ProjectRentalSummary(
        contract_count=int(r.get("contract_count", 0)),
        total_annual_value=float(r.get("total_annual_value", 0) or 0),
        median_annual_rent=float(r.get("median_annual_rent", 0) or 0),
        median_rent_sqm=float(r.get("median_rent_sqm", 0) or 0),
    )

    # --- Overall gross yield ---
    # Use existing-only median_price as denominator — off-plan launch prices are discounted
    # and would produce artificially inflated yields (e.g. JVC showing ~25%).
    # Median/median: both sides use the same central tendency measure for a consistent yield.
    existing_median_price = float(
        (sales_sum_existing_rows[0].get("median_price") or 0) if sales_sum_existing_rows else 0
    )
    overall_yield: Optional[float] = None
    if existing_median_price > 0 and rentals.median_annual_rent > 0:
        overall_yield = round(rentals.median_annual_rent / existing_median_price * 100, 2)

    # --- By rooms (merge sales + rentals) ---
    sales_by_room = {row["rooms_en"]: row for row in sales_rooms_rows}
    # Existing-only prices used as yield denominator — same rationale as overall_gross_yield_pct
    sales_existing_by_room = {row["rooms_en"]: row for row in sales_rooms_existing_rows}
    rent_by_room = {row["rooms_en"]: row for row in rent_rooms_rows}
    all_rooms = set(sales_by_room) | set(rent_by_room)

    by_rooms: list[RoomAnalytics] = []
    for rooms in all_rooms:
        s_row = sales_by_room.get(rooms, {})
        s_ex_row = sales_existing_by_room.get(rooms, {})
        r_row = rent_by_room.get(rooms, {})
        avg_sale = float(s_row.get("avg_sale_price", 0) or 0)
        existing_median_sale = float(s_ex_row.get("median_sale_price", 0) or 0)
        median_rent = float(r_row.get("median_annual_rent", 0) or 0)
        yield_pct: Optional[float] = None
        if existing_median_sale > 0 and median_rent > 0:
            yield_pct = round(median_rent / existing_median_sale * 100, 2)
        by_rooms.append(RoomAnalytics(
            rooms=rooms,
            sale_count=int(s_row.get("sale_count", 0)),
            avg_sale_price=avg_sale,
            avg_sale_price_sqm=float(s_row.get("avg_sale_price_sqm", 0) or 0),
            rental_count=int(r_row.get("rental_count", 0)),
            median_annual_rent=median_rent,
            median_rent_sqm=float(r_row.get("median_rent_sqm", 0) or 0),
            gross_yield_pct=yield_pct,
        ))
    by_rooms.sort(key=lambda x: _room_sort_key(x.rooms))

    # --- By property type ---
    total_sales = sum(int(row["count"]) for row in sales_type_rows) or 1
    by_property_type = [
        PropertyTypeBreakdown(
            property_type=row["property_type_en"],
            count=int(row["count"]),
            avg_price=float(row["avg_price"] or 0),
            pct_of_total=round(int(row["count"]) / total_sales * 100, 1),
        )
        for row in sales_type_rows
    ]

    # --- By registration type ---
    total_reg = sum(int(row["count"]) for row in sales_reg_rows) or 1
    by_reg_type = [
        RegTypeBreakdown(
            reg_type=row["reg_type_en"],
            count=int(row["count"]),
            avg_price=float(row["avg_price"] or 0),
            pct_of_total=round(int(row["count"]) / total_reg * 100, 1),
        )
        for row in sales_reg_rows
    ]

    # --- Unit composition ---
    total_units = sum(int(row["unit_count"]) for row in units_rows) or 1
    unit_composition = [
        UnitComposition(
            rooms=row["rooms_en"],
            count=int(row["unit_count"]),
            pct_of_total=round(int(row["unit_count"]) / total_units * 100, 1),
        )
        for row in units_rows
    ]
    unit_composition.sort(key=lambda x: _room_sort_key(x.rooms))

    return ProjectAnalyticsResponse(
        project=project,
        sales=sales,
        rentals=rentals,
        overall_gross_yield_pct=overall_yield,
        by_rooms=by_rooms,
        by_property_type=by_property_type,
        by_reg_type=by_reg_type,
        unit_composition=unit_composition,
    )


async def get_project_trends(project_name: str, days: int, filter_type: str = "project") -> ProjectTrendsResponse:
    """Price trend time series for a project over the given number of days."""
    end_dt = date.today()
    start_dt = end_dt - timedelta(days=days)

    if days <= 30:
        interval = "day"
    elif days <= 180:
        interval = "week"
    else:
        interval = "month"

    like_name = project_name + " - %" if filter_type == "virtual_master" else project_name
    rows = await query(
        project_price_trends(interval, filter_type),
        {
            "project_name": like_name,
            "start_date": start_dt.isoformat(),
            "end_date": end_dt.isoformat(),
        },
    )

    data = [
        ProjectTrendPoint(
            date=row["period"],
            transaction_count=int(row["transaction_count"]),
            avg_price=float(row["avg_price"] or 0),
            avg_price_sqm=float(row["avg_price_sqm"] or 0),
        )
        for row in rows
    ]
    return ProjectTrendsResponse(data=data)
