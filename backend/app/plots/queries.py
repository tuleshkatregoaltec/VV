from typing import Any

from app.analytics.dxbi import SALES_SOURCE
from app.clickhouse.client import query
from app.plots.models import (
    Usage,
)


def land_sale_usage_clause(usage: Usage, column: str = "property_usage_en") -> str:
    if usage == "residential":
        return f"{column} = 'Residential'"
    if usage == "commercial":
        return f"({column} IN ('Commercial', 'Industrial', 'Storage', 'Industrial / Commercial'))"
    if usage == "mixed_use":
        return (
            f"({column} IN ('Residential / Commercial', 'Multi-Use', "
            "'Industrial / Commercial', 'Industrial / Commercial / Residential'))"
        )
    return "1 = 1"


async def fetch_plots(*, community, limit, max_plot_area_sqm, min_plot_area_sqm, offset, q):
    where = ["plot_number != ''"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if q:
        where.append(
            "(plot_number ILIKE {q:String} OR project_name ILIKE {q:String} OR community_name ILIKE {q:String})"
        )
        params["q"] = f"%{q}%"
    if community:
        where.append(
            "lowerUTF8(trimBoth(community_name)) = lowerUTF8(trimBoth({community:String}))"
        )
        params["community"] = community
    if min_plot_area_sqm is not None:
        where.append("plot_area_sqm >= {min_plot_area_sqm:Float64}")
        params["min_plot_area_sqm"] = min_plot_area_sqm
    if max_plot_area_sqm is not None:
        where.append("plot_area_sqm <= {max_plot_area_sqm:Float64}")
        params["max_plot_area_sqm"] = max_plot_area_sqm

    sql = f"""
    SELECT
        plot_number,
        community_name,
        project_name,
        plot_area_sqm,
        max_gfa_sqm,
        max_height,
        max_coverage,
        gfa_type,
        is_verified,
        land_use
    FROM ch_gis_land_plots
    WHERE {" AND ".join(where)}
    ORDER BY is_verified DESC, plot_area_sqm DESC
    LIMIT {{limit:UInt32}}
    OFFSET {{offset:UInt32}}
    """
    rows = await query(sql, params)
    return rows


async def fetch_plot_geometries(parameters):
    return await query(
        """
    WITH parcel_assets AS (
        SELECT
            parcel_id,
            count() AS linked_asset_count,
            countIf(floors > 0 OR units > 0 OR built_up_area > 0 OR actual_area > 0)
                AS linked_physical_asset_count
        FROM ch_buildings
        WHERE parcel_id != ''
        GROUP BY parcel_id
    )
    SELECT
        p.plot_number,
        p.project_name,
        p.community_name,
        p.plot_area_sqm,
        p.max_gfa_sqm,
        p.max_height,
        p.max_coverage,
        p.site_plan_issue_date,
        p.site_plan_expiry_date,
        p.land_use,
        p.gfa_type,
        p.is_verified,
        p.coordinates,
        ifNull(a.linked_asset_count, 0) AS linked_asset_count,
        ifNull(a.linked_physical_asset_count, 0) AS linked_physical_asset_count
    FROM ch_gis_land_plots AS p FINAL
    LEFT JOIN parcel_assets AS a ON a.parcel_id = p.plot_number
    WHERE p.coordinates != ''
    LIMIT 100000
    """,
        parameters,
    )


async def fetch_communities(parameters):
    return await query(
        """
    SELECT community_name
    FROM ch_gis_land_plots
    WHERE community_name != ''
    GROUP BY community_name
    ORDER BY count() DESC, community_name
    LIMIT {limit:UInt32}
    """,
        parameters,
    )


async def fetch_plot_details(parameters):
    return await query(
        """
    SELECT *
    FROM ch_gis_land_plots
    WHERE plot_number = {plot_number:String}
    LIMIT 1
    """,
        parameters,
    )


# Plot sales: DXBI's listed sales (the Analytics records, price floor included). DLD's register
# (ch_transactions) holds no DLD plot sale after 2026-10-14, and DXBI's plot sales there carry no
# DLD procedure. A DXBI sale is a market sale, so no procedure filter applies; DXBI names no land
# use, so a usage request finds no rows and the evidence falls back to every plot sale, as it did
# for a usage DLD did not record. A plot's area is its sale's size (m²).
_PLOT_SALES = f"""(
    SELECT transaction_id, instance_date, area_name_en, location_name, project_name_en,
           '' AS procedure_name_en, property_usage_en, size_sqm AS procedure_area,
           actual_worth, CAST(NULL AS Nullable(String)) AS nearest_landmark
    FROM {SALES_SOURCE}
    WHERE property_type = 'Plot'
)"""


async def fetch_land_sale_evidence(*, area_name, days, limit, plot_area_sqm, usage):
    base_where = [
        "actual_worth > 0",
        "procedure_area > 0",
        "(lower(area_name_en) = lower({area_name:String})"
        " OR lower(location_name) = lower({area_name:String}))",
        "instance_date >= today() - {days:Int32}",
    ]
    if plot_area_sqm and plot_area_sqm > 0:
        base_where.append("procedure_area BETWEEN {min_area:Float64} AND {max_area:Float64}")
        # procedure_area is in m², like the plot (the DDA valuation below reads it the same way).
        min_area = plot_area_sqm * 0.5
        max_area = plot_area_sqm * 1.75
    else:
        min_area = None
        max_area = None

    params: dict[str, Any] = {
        "area_name": area_name,
        "days": days,
        "limit": limit,
        "target_area": plot_area_sqm or 0,
    }
    if min_area is not None and max_area is not None:
        params["min_area"] = min_area
        params["max_area"] = max_area

    async def fetch_rows(where: list[str]) -> list[dict[str, Any]]:
        sql = f"""
        SELECT
            transaction_id,
            instance_date,
            area_name_en,
            project_name_en,
            procedure_name_en,
            property_usage_en,
            round(toFloat64(procedure_area), 1) AS plot_area_sqm,
            toFloat64(actual_worth) AS price_aed,
            round(toFloat64(actual_worth) / greatest(toFloat64(procedure_area), 1), 0) AS price_sqm,
            nearest_landmark
        FROM {_PLOT_SALES}
        WHERE {" AND ".join(where)}
        ORDER BY
            instance_date DESC,
            abs(toFloat64(procedure_area) - {{target_area:Float64}}) ASC
        LIMIT {{limit:Int32}}
        """
        return await query(sql, params)

    rows: list[dict[str, Any]] = []
    if usage and usage != "unknown":
        rows = await fetch_rows([*base_where, land_sale_usage_clause(usage)])
    if not rows:
        rows = await fetch_rows(base_where)
    return rows


DDA_VALUATION_LOOKBACK_DAYS = 365 * 5

DDA_VALUATION_MIN_TRANSACTION_AED = 1_000_000


async def _dda_land_transaction_rows(communities: set[str]) -> list[dict[str, Any]]:
    if not communities:
        return []
    return await query(
        f"""
        SELECT
            transaction_id,
            instance_date,
            area_name_en,
            project_name_en,
            property_usage_en,
            procedure_name_en,
            toFloat64(procedure_area) AS plot_area_sqm,
            toFloat64(actual_worth) AS price_aed
        FROM {_PLOT_SALES}
        WHERE actual_worth > {{min_transaction_aed:Float64}}
          AND procedure_area > 0
          AND instance_date >= today() - {{lookback_days:Int32}}
          AND (has({{communities:Array(String)}}, lowerUTF8(area_name_en))
               OR has({{communities:Array(String)}}, lowerUTF8(location_name)))
        ORDER BY instance_date DESC
        LIMIT 100000
        """,
        {
            "communities": sorted(communities),
            "lookback_days": DDA_VALUATION_LOOKBACK_DAYS,
            "min_transaction_aed": DDA_VALUATION_MIN_TRANSACTION_AED,
        },
    )
