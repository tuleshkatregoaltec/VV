import logging
from app.clickhouse.client import query
from app.feasibility.models import LandPlot, ComparableData, UnitTypeData

logger = logging.getLogger(__name__)


async def get_areas() -> list[str]:
    """Get all distinct area names from land registry."""
    sql = """
    SELECT DISTINCT area_name_en
    FROM ch_land_registry
    WHERE area_name_en != ''
    ORDER BY area_name_en
    """
    rows = await query(sql, {})
    return [r["area_name_en"] for r in rows]


async def get_land_plots(area: str, size_sqm: float, tolerance: float = 0.25) -> list[LandPlot]:
    """Find land plots near a given size in the specified area."""
    sql = """
    SELECT
        property_id,
        land_number,
        area_name_en,
        actual_area,
        property_type_en,
        is_free_hold,
        project_name_en
    FROM ch_land_registry
    WHERE area_name_en = {area:String}
      AND actual_area BETWEEN {min_area:Float64} AND {max_area:Float64}
    ORDER BY abs(actual_area - {size_sqm:Float64})
    LIMIT 50
    """
    rows = await query(sql, {
        "area": area,
        "min_area": size_sqm * (1 - tolerance),
        "max_area": size_sqm * (1 + tolerance),
        "size_sqm": size_sqm,
    })
    return [
        LandPlot(
            property_id=r["property_id"],
            land_number=r.get("land_number") or None,
            area_name_en=r["area_name_en"],
            actual_area=float(r["actual_area"]),
            property_type_en=r.get("property_type_en") or None,
            is_free_hold=r.get("is_free_hold"),
            project_name_en=r.get("project_name_en") or None,
        )
        for r in rows
    ]


async def get_comparable_data(project_ids: list[int]) -> ComparableData | None:
    """Aggregate building and unit data across a set of comparable projects."""
    if not project_ids:
        return None

    # Get building stats
    buildings_sql = """
    SELECT
        count() AS no_of_buildings,
        avg(floors) AS avg_floors
    FROM ch_buildings
    WHERE project_id IN ({project_ids:Array(Int32)})
      AND floors > 0
    """
    buildings_rows = await query(buildings_sql, {"project_ids": project_ids})
    b = buildings_rows[0] if buildings_rows else {}
    no_of_buildings = int(b.get("no_of_buildings") or 0)
    avg_floors = float(b["avg_floors"]) if b.get("avg_floors") else None

    # Get project names
    project_sql = """
    SELECT project_id, project_name_en, area_name_en
    FROM ch_projects
    WHERE project_id IN ({project_ids:Array(Int32)})
    """
    project_rows = await query(project_sql, {"project_ids": project_ids})
    project_names = [r["project_name_en"] for r in project_rows if r.get("project_name_en")]
    area_names = [r["area_name_en"] for r in project_rows if r.get("area_name_en")]

    # Get unit composition across all projects
    units_sql = """
    SELECT
        rooms_en AS unit_type,
        count() AS cnt,
        round(avg(actual_area), 2) AS avg_size_sqm
    FROM ch_units
    WHERE project_id IN ({project_ids:Array(Int32)})
      AND rooms_en != ''
      AND actual_area > 0
    GROUP BY rooms_en
    ORDER BY cnt DESC
    """
    units_rows = await query(units_sql, {"project_ids": project_ids})
    total_units = sum(r["cnt"] for r in units_rows)

    # Get median price/sqm by unit type from transactions (join via project name)
    price_sql = """
    SELECT
        rooms_en AS unit_type,
        round(median(meter_sale_price), 0) AS median_price_sqm
    FROM ch_transactions
    WHERE project_name_en IN ({project_names:Array(String)})
      AND rooms_en != ''
      AND meter_sale_price > 0
      AND instance_date >= today() - 730
    GROUP BY rooms_en
    """
    price_rows = await query(price_sql, {"project_names": project_names}) if project_names else []
    price_by_type = {r["unit_type"]: float(r["median_price_sqm"]) for r in price_rows}

    unit_mix = [
        UnitTypeData(
            type=r["unit_type"],
            count=int(r["cnt"]),
            percentage=round((r["cnt"] / total_units) * 100, 1) if total_units else 0,
            avg_size_sqm=float(r["avg_size_sqm"]),
            avg_price_sqm=price_by_type.get(r["unit_type"]),
        )
        for r in units_rows
    ]

    return ComparableData(
        project_id=project_ids[0],
        project_name=", ".join(project_names[:3]) or f"Project {project_ids[0]}",
        area_name=area_names[0] if area_names else "Unknown",
        no_of_buildings=no_of_buildings,
        avg_floors=avg_floors,
        unit_mix=unit_mix,
        price_per_sqm_by_type=price_by_type,
    )
