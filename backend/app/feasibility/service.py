import json
import logging
from typing import Any

from app.clickhouse.client import query
from app.feasibility.models import (
    ComparableData,
    ComparableProject,
    GISLandUse,
    GISPlotDossier,
    GISPlotSummary,
    HBUProductOption,
    HBUStudy,
    HBUUnitRecommendation,
    LandSaleEvidence,
    MarketPricingRow,
    UnitTypeData,
)
from app.feasibility.normalization import (
    Stage,
    Usage,
    canonical_unit_type_case_sql,
    infer_usage_from_plot,
    normalize_project_stage,
    transaction_stage_clause,
    transaction_usage_clause,
)

logger = logging.getLogger(__name__)

RESIDENTIAL_TYPES = ["studio", "1br", "2br", "3br", "4br", "4br+", "villa", "townhouse"]
COMMERCIAL_TYPES = ["office", "retail", "industrial", "hospitality"]


def _parse_land_use(raw: str) -> list[GISLandUse]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return [
            GISLandUse(
                type=str(item.get("type", "")).strip(),
                use=str(item.get("use", "")).strip(),
            )
            for item in parsed
            if item.get("type") or item.get("use")
        ]
    except Exception:
        return []


def _parse_notes(raw: str) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(" | ") if part.strip()]


def _parse_coordinates(raw: str) -> list[list[float]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        coords: list[list[float]] = []
        for pair in parsed:
            if isinstance(pair, list) and len(pair) == 2:
                coords.append([float(pair[0]), float(pair[1])])
        return coords
    except Exception:
        return []


def _build_setbacks(row: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for side in range(1, 5):
        building = str(row.get(f"side{side}_building") or "").strip()
        podium = str(row.get(f"side{side}_podium") or "").strip()
        if building:
            result[f"side{side}_building"] = building
        if podium:
            result[f"side{side}_podium"] = podium
    return result


def _build_plot_warnings(row: dict[str, Any], far: float | None, notes: list[str]) -> list[str]:
    warnings: list[str] = []
    if not row.get("is_verified"):
        warnings.append("GIS plot is not marked as verified.")
    if not row.get("max_gfa_sqm"):
        warnings.append("Maximum GFA is missing, so HBU fit is lower confidence.")
    if row.get("site_plan_expiry_date"):
        warnings.append(f"Site plan expiry date: {row['site_plan_expiry_date']}.")
    if row.get("max_height", "").upper() == "SEE NOTES":
        warnings.append("Maximum height is defined in notes instead of a structured field.")
    if row.get("max_coverage", "").upper() == "SEE NOTES":
        warnings.append("Maximum coverage is defined in notes instead of a structured field.")
    if far and far > 12:
        warnings.append("Derived FAR is unusually high; confirm the GIS record manually.")
    if any("NOC" in note.upper() for note in notes):
        warnings.append("General notes include authority or third-party NOC requirements.")
    return warnings


def _dominant_type(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    return str(rows[0].get("unit_type") or rows[0].get("dominant_unit_type") or "").strip() or None


async def get_areas() -> list[str]:
    """Get distinct transaction areas with sales activity."""
    sql = """
    SELECT area_name_en
    FROM ch_transactions
    WHERE trans_group_en = 'Sales'
      AND area_name_en != ''
    GROUP BY area_name_en
    ORDER BY count() DESC, area_name_en
    """
    rows = await query(sql, {})
    return [r["area_name_en"] for r in rows]


async def resolve_market_area(name: str) -> str:
    if not name:
        return name
    sql = """
    SELECT area_name_en
    FROM ch_transactions
    WHERE trans_group_en = 'Sales'
      AND area_name_en ILIKE {pattern:String}
    GROUP BY area_name_en
    ORDER BY (lower(area_name_en) = lower({name:String})) DESC, count() DESC
    LIMIT 1
    """
    rows = await query(sql, {"name": name, "pattern": f"%{name}%"})
    return rows[0]["area_name_en"] if rows else name


async def search_gis_plots(
    q: str = "",
    community: str = "",
    min_plot_area_sqm: float | None = None,
    max_plot_area_sqm: float | None = None,
    offset: int = 0,
    limit: int = 30,
) -> list[GISPlotSummary]:
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
    FROM ch_gis_land_plots FINAL
    WHERE {" AND ".join(where)}
    ORDER BY is_verified DESC, plot_area_sqm DESC
    LIMIT {{limit:UInt32}}
    OFFSET {{offset:UInt32}}
    """
    rows = await query(sql, params)
    plots: list[GISPlotSummary] = []
    for row in rows:
        land_use = _parse_land_use(row.get("land_use", ""))
        plots.append(
            GISPlotSummary(
                plot_number=row["plot_number"],
                community_name=row.get("community_name") or "",
                project_name=row.get("project_name") or "",
                plot_area_sqm=float(row.get("plot_area_sqm") or 0),
                max_gfa_sqm=float(row.get("max_gfa_sqm") or 0),
                max_height=row.get("max_height") or "",
                max_coverage=row.get("max_coverage") or "",
                gfa_type=row.get("gfa_type") or "",
                is_verified=bool(row.get("is_verified")),
                land_use_summary=[f"{item.type}: {item.use}" for item in land_use[:3]],
            )
        )
    return plots


async def list_plot_communities(limit: int = 5000) -> list[str]:
    sql = """
    SELECT community_name
    FROM ch_gis_land_plots FINAL
    WHERE community_name != ''
    GROUP BY community_name
    ORDER BY count() DESC, community_name
    LIMIT {limit:UInt32}
    """
    rows = await query(sql, {"limit": limit})
    return [r["community_name"] for r in rows]


async def get_gis_plot_dossier(plot_number: str) -> GISPlotDossier | None:
    sql = """
    SELECT *
    FROM ch_gis_land_plots FINAL
    WHERE plot_number = {plot_number:String}
    LIMIT 1
    """
    rows = await query(sql, {"plot_number": plot_number})
    if not rows:
        return None

    row = rows[0]
    plot_area_sqm = float(row.get("plot_area_sqm") or 0)
    max_gfa_sqm = float(row.get("max_gfa_sqm") or 0)
    far = round(max_gfa_sqm / plot_area_sqm, 2) if plot_area_sqm > 0 and max_gfa_sqm > 0 else None
    land_use = _parse_land_use(row.get("land_use", ""))
    notes = _parse_notes(row.get("general_notes", ""))
    inferred_usage = infer_usage_from_plot(
        [f"{item.type} {item.use}" for item in land_use],
        str(row.get("gfa_type") or ""),
        notes,
    )
    return GISPlotDossier(
        plot_number=row["plot_number"],
        community_name=row.get("community_name") or "",
        project_name=row.get("project_name") or "",
        master_developer=(row.get("master_developer") or None),
        plot_area_sqm=plot_area_sqm,
        max_gfa_sqm=max_gfa_sqm,
        max_gfa_sqft=float(row.get("max_gfa_sqft") or 0),
        max_height=row.get("max_height") or "",
        max_coverage=row.get("max_coverage") or "",
        gfa_type=row.get("gfa_type") or "",
        far=far,
        inferred_usage=inferred_usage,
        site_plan_issue_date=str(row.get("site_plan_issue_date"))
        if row.get("site_plan_issue_date")
        else None,
        site_plan_expiry_date=str(row.get("site_plan_expiry_date"))
        if row.get("site_plan_expiry_date")
        else None,
        is_verified=bool(row.get("is_verified")),
        verify_comments=(row.get("verify_comments") or None),
        land_use=land_use,
        general_notes=notes,
        setbacks=_build_setbacks(row),
        coordinates=_parse_coordinates(row.get("coordinates", "")),
        warnings=_build_plot_warnings(row, far, notes),
    )


async def get_market_pricing(
    area_name: str,
    usage: Usage,
    stage: Stage = "existing",
    days: int = 365,
) -> list[MarketPricingRow]:
    canonical_unit_sql = canonical_unit_type_case_sql("rooms_en")
    where = [
        "trans_group_en = 'Sales'",
        "meter_sale_price > 0",
        "area_name_en = {area_name:String}",
        transaction_usage_clause(usage),
        transaction_stage_clause(stage),
        "instance_date >= today() - {days:Int32}",
    ]
    sql = f"""
    SELECT
        {canonical_unit_sql} AS unit_type,
        count() AS transaction_count,
        round(median(meter_sale_price), 0) AS median_price_sqm,
        round(avg(procedure_area), 0) AS avg_area_sqm
    FROM ch_transactions
    WHERE {" AND ".join(where)}
    GROUP BY unit_type
    HAVING unit_type != 'other'
    ORDER BY transaction_count DESC
    """
    rows = await query(sql, {"area_name": area_name, "days": days})
    return [
        MarketPricingRow(
            unit_type=row["unit_type"],
            transaction_count=int(row["transaction_count"]),
            median_price_sqm=float(row["median_price_sqm"]),
            avg_area_sqm=float(row["avg_area_sqm"]) if row.get("avg_area_sqm") else None,
        )
        for row in rows
    ]


async def get_land_sale_evidence(
    area_name: str,
    plot_area_sqm: float | None = None,
    days: int = 1825,
    limit: int = 12,
) -> list[LandSaleEvidence]:
    where = [
        "trans_group_en = 'Sales'",
        "property_type_en = 'Land'",
        "actual_worth > 0",
        "procedure_area > 0",
        "area_name_en = {area_name:String}",
        "instance_date >= today() - {days:Int32}",
    ]
    if plot_area_sqm and plot_area_sqm > 0:
        where.append("procedure_area BETWEEN {min_area:Float64} AND {max_area:Float64}")
        min_area = plot_area_sqm * 0.5
        max_area = plot_area_sqm * 1.75
    else:
        min_area = None
        max_area = None

    sql = f"""
    SELECT
        transaction_id,
        instance_date,
        area_name_en,
        project_name_en,
        procedure_name_en,
        property_usage_en,
        toFloat64(procedure_area) AS plot_area_sqm,
        toFloat64(actual_worth) AS price_aed,
        round(toFloat64(actual_worth) / greatest(toFloat64(procedure_area), 1), 0) AS price_sqm,
        nullIf(nearest_landmark_en, '') AS nearest_landmark
    FROM ch_transactions
    WHERE {" AND ".join(where)}
    ORDER BY
        abs(toFloat64(procedure_area) - {{target_area:Float64}}) ASC,
        instance_date DESC
    LIMIT {{limit:Int32}}
    """
    params: dict[str, Any] = {
        "area_name": area_name,
        "days": days,
        "limit": limit,
        "target_area": plot_area_sqm or 0,
    }
    if min_area is not None and max_area is not None:
        params["min_area"] = min_area
        params["max_area"] = max_area

    rows = await query(sql, params)
    return [
        LandSaleEvidence(
            transaction_id=row["transaction_id"],
            instance_date=str(row["instance_date"]),
            area_name=row["area_name_en"],
            project_name=row.get("project_name_en") or "",
            procedure_name=row.get("procedure_name_en") or "",
            property_usage=row.get("property_usage_en") or "",
            plot_area_sqm=float(row.get("plot_area_sqm") or 0),
            price_aed=float(row.get("price_aed") or 0),
            price_sqm=float(row.get("price_sqm") or 0),
            nearest_landmark=row.get("nearest_landmark"),
        )
        for row in rows
    ]


async def _project_unit_mix(project_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not project_ids:
        return {}
    canonical_unit_sql = canonical_unit_type_case_sql("rooms_en")
    sql = f"""
    SELECT
        project_id,
        {canonical_unit_sql} AS unit_type,
        count() AS cnt,
        round(avg(actual_area), 1) AS avg_area_sqm
    FROM ch_units
    WHERE project_id IN ({{project_ids:Array(Int32)}})
      AND actual_area > 0
    GROUP BY project_id, unit_type
    HAVING unit_type != 'other'
    ORDER BY project_id, cnt DESC
    """
    rows = await query(sql, {"project_ids": project_ids})
    result: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        result.setdefault(int(row["project_id"]), []).append(row)
    return result


async def rank_plot_comparables(
    dossier: GISPlotDossier,
    usage: Usage,
    comparison_type: str,
    limit: int = 5,
) -> list[ComparableProject]:
    market_area = await resolve_market_area(dossier.community_name)
    params = {"market_area": market_area}
    sql = """
    WITH land AS (
        SELECT
            project_id,
            sum(toFloat64(actual_area)) AS total_land_area_sqm
        FROM ch_land_registry
        WHERE project_id > 0
        GROUP BY project_id
    )
    SELECT
        p.project_id,
        any(p.project_name_en) AS project_name,
        any(p.area_name_en) AS area_name,
        any(p.project_status) AS project_status,
        any(p.no_of_buildings) AS no_of_buildings,
        any(p.no_of_units) AS no_of_units,
        any(land.total_land_area_sqm) AS total_land_area_sqm
    FROM ch_projects p
    LEFT JOIN land ON p.project_id = land.project_id
    WHERE p.area_name_en = {market_area:String}
      AND p.project_name_en != ''
    GROUP BY p.project_id
    LIMIT 250
    """
    project_rows = await query(sql, params)
    project_ids = [int(row["project_id"]) for row in project_rows]
    unit_mix_by_project = await _project_unit_mix(project_ids)

    price_by_project: dict[int, float] = {}
    dominant_type_by_project: dict[int, str] = {}
    if comparison_type == "pricing":
        canonical_unit_sql = canonical_unit_type_case_sql("rooms_en")
        pricing_sql = f"""
        SELECT
            p.project_id AS project_id,
            round(median(t.meter_sale_price), 0) AS median_price_sqm,
            argMax(unit_type, cnt) AS dominant_unit_type
        FROM (
            SELECT
                project_name_en,
                {canonical_unit_sql} AS unit_type,
                count() AS cnt,
                meter_sale_price
            FROM ch_transactions
            WHERE trans_group_en = 'Sales'
              AND area_name_en = {{market_area:String}}
              AND {transaction_usage_clause(usage)}
              AND {transaction_stage_clause("existing")}
              AND meter_sale_price > 0
            GROUP BY project_name_en, unit_type, meter_sale_price
        ) t
        INNER JOIN ch_projects p ON p.project_name_en = t.project_name_en
        GROUP BY p.project_id
        """
        for row in await query(pricing_sql, {"market_area": market_area}):
            price_by_project[int(row["project_id"])] = float(row["median_price_sqm"])
            dominant_type_by_project[int(row["project_id"])] = row.get("dominant_unit_type") or ""

    scored: list[ComparableProject] = []
    target_area = dossier.plot_area_sqm
    for row in project_rows:
        project_id = int(row["project_id"])
        total_land_area = (
            float(row["total_land_area_sqm"]) if row.get("total_land_area_sqm") else None
        )
        if comparison_type == "pricing" and project_id not in price_by_project:
            continue

        stage = normalize_project_stage(str(row.get("project_status") or ""))
        if comparison_type == "pipeline" and stage not in {"off_plan", "upcoming"}:
            continue

        unit_rows = unit_mix_by_project.get(project_id, [])
        dominant_type = dominant_type_by_project.get(project_id) or _dominant_type(unit_rows)
        if usage == "residential" and dominant_type and dominant_type not in RESIDENTIAL_TYPES:
            continue
        if usage == "commercial" and dominant_type and dominant_type not in COMMERCIAL_TYPES:
            continue

        score = 100.0
        rationale = [f"Same market area: {market_area}."]
        delta_pct = None
        if total_land_area and target_area > 0:
            delta_pct = abs(total_land_area - target_area) / target_area
            score -= min(delta_pct * 40, 45)
            rationale.append(f"Land area delta {round(delta_pct * 100, 1)}%.")
        else:
            score -= 25
            rationale.append("Missing derived land area.")

        if comparison_type == "pricing":
            rationale.append("Has existing transaction evidence.")
        else:
            rationale.append(f"Pipeline status: {row.get('project_status') or 'Unknown'}.")
            if stage == "upcoming":
                score += 5

        if dominant_type:
            rationale.append(f"Dominant unit type: {dominant_type}.")

        scored.append(
            ComparableProject(
                project_id=project_id,
                project_name=row.get("project_name") or f"Project {project_id}",
                area_name=row.get("area_name") or market_area,
                project_status=row.get("project_status") or None,
                comparison_type="pricing" if comparison_type == "pricing" else "pipeline",
                score=round(score, 1),
                total_land_area_sqm=round(total_land_area, 0) if total_land_area else None,
                land_area_delta_pct=round(delta_pct * 100, 1) if delta_pct is not None else None,
                no_of_buildings=int(row["no_of_buildings"])
                if row.get("no_of_buildings") is not None
                else None,
                no_of_units=int(row["no_of_units"]) if row.get("no_of_units") is not None else None,
                median_price_sqm=price_by_project.get(project_id),
                dominant_unit_type=dominant_type,
                rationale=rationale,
            )
        )

    scored.sort(key=lambda item: (-item.score, item.land_area_delta_pct or 9999))
    return scored[:limit]


def _pick_price(pricing: list[MarketPricingRow], unit_type: str, fallback: float) -> float:
    for row in pricing:
        if row.unit_type == unit_type:
            return row.median_price_sqm
    return fallback


def _weighted_average(values: list[tuple[float, float]]) -> float | None:
    total_weight = sum(weight for _, weight in values if weight > 0)
    if total_weight <= 0:
        return None
    return sum(value * weight for value, weight in values if weight > 0) / total_weight


def _evidence_defaults_for_usage(usage: Usage) -> list[tuple[str, float, float]]:
    if usage == "commercial":
        return [("office", 0.65, 120), ("retail", 0.25, 95), ("hospitality", 0.10, 80)]
    return [
        ("studio", 0.18, 44),
        ("1br", 0.34, 76),
        ("2br", 0.30, 122),
        ("3br", 0.18, 178),
    ]


def _build_product_options(
    dossier: GISPlotDossier,
    usage: Usage,
    weighted_prices: dict[str, float],
    adjusted_shares: dict[str, float],
    pipeline_pressure: dict[str, float],
) -> list[HBUProductOption]:
    dominant_type = max(adjusted_shares, key=adjusted_shares.get) if adjusted_shares else None
    blended_price = (
        _weighted_average(
            [
                (price, adjusted_shares.get(unit_type, 0))
                for unit_type, price in weighted_prices.items()
            ]
        )
        or 0
    )
    high_pipeline_types = [
        unit_type for unit_type, pressure in pipeline_pressure.items() if pressure > 0.35
    ]

    if usage == "commercial":
        primary = "Office-led commercial"
        positioning = "Office floors with selective retail support"
        rationale = [
            "Weighted comparable evidence points to a commercial-led product stack.",
            f"Blended commercial pricing is about {round(blended_price):,} AED/sqm."
            if blended_price > 0
            else "Commercial pricing evidence is limited.",
        ]
        if high_pipeline_types:
            rationale.append(
                f"Pipeline pressure is highest in {', '.join(high_pipeline_types[:2])}, so keep the scheme selective."
            )
        secondary = HBUProductOption(
            name="Mixed commercial stack",
            positioning="Balanced office and retail mix with tighter floorplate control",
            fit_score=76,
            rationale=[
                "Useful if frontage, parking, and access conditions support a broader commercial program."
            ],
        )
        return [
            HBUProductOption(
                name=primary, positioning=positioning, fit_score=89, rationale=rationale
            ),
            secondary,
        ]

    if blended_price >= 22000:
        name = "Luxury residential"
        positioning = "Larger 1BR/2BR/3BR product with limited studio exposure"
    elif blended_price >= 17000:
        name = "Upper-mid residential"
        positioning = "Balanced end-user residential with family-weighted mix"
    else:
        name = "Mid-market residential"
        positioning = "Broad apartment mix optimized for liquidity"

    rationale = [
        f"Weighted pricing evidence centers around {round(blended_price):,} AED/sqm."
        if blended_price > 0
        else "Pricing evidence is thin, so confidence is lower.",
        f"Dominant evidence-backed unit type is {dominant_type}."
        if dominant_type
        else "Comparable evidence did not produce a dominant unit type.",
    ]
    if high_pipeline_types:
        rationale.append(
            f"Pipeline pressure is elevated in {', '.join(high_pipeline_types[:2])}, so those types were de-emphasized."
        )
    if dossier.far and dossier.far <= 1.5:
        rationale.append(
            "Lower plotted density supports a lower-density or family-led residential outcome."
        )

    return [
        HBUProductOption(
            name=name,
            positioning=positioning,
            fit_score=91 if blended_price >= 22000 else 86,
            rationale=rationale,
        ),
        HBUProductOption(
            name="Defensive alternative",
            positioning="Slightly more family-weighted mix with less exposure to saturated unit types",
            fit_score=78,
            rationale=[
                "Provides a safer fallback if current pipeline launches crowd the primary mix."
            ],
        ),
    ]


def _build_constraints_and_summary(
    dossier: GISPlotDossier,
    usage: Usage,
    pricing_evidence: list[ComparableProject],
    competition_evidence: list[ComparableProject],
    weighted_prices: dict[str, float],
) -> tuple[list[str], list[str]]:
    constraints = [
        f"Plot area {round(dossier.plot_area_sqm):,} sqm.",
        f"Maximum GFA {round(dossier.max_gfa_sqm):,} sqm."
        if dossier.max_gfa_sqm > 0
        else "Maximum GFA missing from GIS.",
        f"Maximum height: {dossier.max_height or 'Unknown'}.",
    ]
    if dossier.max_coverage:
        constraints.append(f"Maximum coverage: {dossier.max_coverage}.")
    if dossier.site_plan_expiry_date:
        constraints.append(f"Site plan expiry date: {dossier.site_plan_expiry_date}.")

    summary = [
        f"HBU uses {len(pricing_evidence)} pricing comparables and {len(competition_evidence)} pipeline comparables.",
        f"Segmented pricing is treated as {usage} only; commercial and residential evidence are not blended.",
    ]
    if weighted_prices:
        strongest = max(weighted_prices, key=weighted_prices.get)
        summary.append(f"Highest evidence-backed rate is currently in {strongest}.")
    if dossier.warnings:
        summary.append(
            "GIS notes and warnings still need manual review before treating this as investment-grade underwriting."
        )
    return constraints, summary


def _derive_assumptions_patch(
    dossier: GISPlotDossier, usage: Usage
) -> dict[str, float | bool | str]:
    loss_factor = 18.0 if usage == "commercial" else 15.0
    build_efficiency = 78.0 if usage == "commercial" else 82.0
    return {
        "siteAreaSqm": round(dossier.plot_area_sqm, 2),
        "plotRatioFAR": round(dossier.far or 0, 2),
        "lossFactorGFAtoNSA": loss_factor,
        "buaEfficiencyPct": build_efficiency,
        "hasAncillaryRetail": usage in {"commercial", "mixed_use"},
    }


def _build_evidence_weighted_mix(
    dossier: GISPlotDossier,
    usage: Usage,
    market_pricing: list[MarketPricingRow],
    pricing_evidence: list[ComparableProject],
    competition_evidence: list[ComparableProject],
    pricing_unit_mix_by_project: dict[int, list[dict[str, Any]]],
    pipeline_unit_mix_by_project: dict[int, list[dict[str, Any]]],
) -> tuple[
    list[HBUProductOption],
    list[HBUUnitRecommendation],
    dict[str, float],
    dict[str, float | bool | str],
    list[str],
    list[str],
]:
    base_mix: dict[str, float] = {}
    size_evidence: dict[str, list[tuple[float, float]]] = {}
    pipeline_mix: dict[str, float] = {}

    total_pricing_weight = 0.0
    for comp in pricing_evidence:
        weight = max(comp.score, 1) / 100
        rows = pricing_unit_mix_by_project.get(comp.project_id, [])
        row_total = sum(float(row["cnt"]) for row in rows)
        if row_total <= 0:
            continue
        total_pricing_weight += weight
        for row in rows:
            unit_type = str(row["unit_type"])
            share = float(row["cnt"]) / row_total
            base_mix[unit_type] = base_mix.get(unit_type, 0) + share * weight
            size_evidence.setdefault(unit_type, []).append(
                (float(row["avg_area_sqm"]), share * weight)
            )

    total_pipeline_weight = 0.0
    for comp in competition_evidence:
        weight = max(comp.score, 1) / 100
        rows = pipeline_unit_mix_by_project.get(comp.project_id, [])
        row_total = sum(float(row["cnt"]) for row in rows)
        if row_total <= 0:
            continue
        total_pipeline_weight += weight
        for row in rows:
            unit_type = str(row["unit_type"])
            share = float(row["cnt"]) / row_total
            pipeline_mix[unit_type] = pipeline_mix.get(unit_type, 0) + share * weight

    if total_pricing_weight > 0:
        base_mix = {
            unit_type: value / total_pricing_weight for unit_type, value in base_mix.items()
        }
    if total_pipeline_weight > 0:
        pipeline_mix = {
            unit_type: value / total_pipeline_weight for unit_type, value in pipeline_mix.items()
        }

    if not base_mix:
        base_mix = {unit_type: share for unit_type, share, _ in _evidence_defaults_for_usage(usage)}
        for unit_type, _, avg_size in _evidence_defaults_for_usage(usage):
            size_evidence.setdefault(unit_type, []).append((avg_size, 1))

    adjusted_mix: dict[str, float] = {}
    for unit_type, share in base_mix.items():
        pressure = pipeline_mix.get(unit_type, 0)
        adjusted_mix[unit_type] = share * max(0.6, 1 - pressure * 0.45)

    if usage == "residential" and dossier.far and dossier.far <= 1.5:
        adjusted_mix["3br"] = adjusted_mix.get("3br", 0) * 1.15
        adjusted_mix["4br+"] = adjusted_mix.get("4br+", 0.04) * 1.35
        adjusted_mix["studio"] = adjusted_mix.get("studio", 0) * 0.6
    if usage == "commercial":
        adjusted_mix["office"] = adjusted_mix.get("office", 0.4) * 1.1
        adjusted_mix["retail"] = adjusted_mix.get("retail", 0.2) * 0.95

    mix_total = sum(adjusted_mix.values()) or 1.0
    adjusted_shares = {
        unit_type: value / mix_total for unit_type, value in adjusted_mix.items() if value > 0
    }

    weighted_prices: dict[str, float] = {}
    weighted_sizes: dict[str, float] = {}
    blended_price = _weighted_average(
        [(row.median_price_sqm, row.transaction_count) for row in market_pricing]
    ) or (11000 if usage == "commercial" else 15000)
    for unit_type, share in sorted(adjusted_shares.items(), key=lambda item: item[1], reverse=True):
        price = _pick_price(market_pricing, unit_type, blended_price)
        size = _weighted_average(size_evidence.get(unit_type, []))
        if size is None:
            default_size = next(
                (
                    avg_size
                    for t, _, avg_size in _evidence_defaults_for_usage(usage)
                    if t == unit_type
                ),
                80,
            )
            size = default_size
        weighted_prices[unit_type] = round(price, 0)
        weighted_sizes[unit_type] = round(size, 1)

    sellable_area = (
        dossier.max_gfa_sqm
        * (1 - (_derive_assumptions_patch(dossier, usage)["lossFactorGFAtoNSA"] / 100))
        if dossier.max_gfa_sqm > 0
        else dossier.plot_area_sqm * 1.2
    )
    recommended_mix: list[HBUUnitRecommendation] = []
    for unit_type, share in sorted(adjusted_shares.items(), key=lambda item: item[1], reverse=True):
        avg_size_sqm = weighted_sizes[unit_type]
        target_nsa = sellable_area * share
        suggested_units = max(1, round(target_nsa / max(avg_size_sqm, 1)))
        recommended_mix.append(
            HBUUnitRecommendation(
                unit_type=unit_type,
                share_pct=round(share * 100, 1),
                avg_size_sqm=avg_size_sqm,
                price_sqm=weighted_prices[unit_type],
                suggested_units=suggested_units,
            )
        )

    product_options = _build_product_options(
        dossier, usage, weighted_prices, adjusted_shares, pipeline_mix
    )
    assumptions_patch = _derive_assumptions_patch(dossier, usage)
    constraints, summary = _build_constraints_and_summary(
        dossier, usage, pricing_evidence, competition_evidence, weighted_prices
    )
    return (
        product_options,
        recommended_mix,
        weighted_prices,
        assumptions_patch,
        constraints,
        summary,
    )


async def generate_hbu_study(
    plot_number: str, usage_override: Usage | None = None
) -> HBUStudy | None:
    dossier = await get_gis_plot_dossier(plot_number)
    if dossier is None:
        return None

    usage = usage_override or dossier.inferred_usage
    market_area = await resolve_market_area(dossier.community_name)
    market_pricing = await get_market_pricing(market_area, usage, stage="existing")
    pricing_evidence = await rank_plot_comparables(dossier, usage, "pricing")
    competition_evidence = await rank_plot_comparables(dossier, usage, "pipeline")
    pricing_unit_mix_by_project = await _project_unit_mix(
        [comp.project_id for comp in pricing_evidence]
    )
    pipeline_unit_mix_by_project = await _project_unit_mix(
        [comp.project_id for comp in competition_evidence]
    )

    (
        product_options,
        recommended_mix,
        price_per_sqm_by_type,
        assumptions_patch,
        constraints,
        summary,
    ) = _build_evidence_weighted_mix(
        dossier,
        usage,
        market_pricing,
        pricing_evidence,
        competition_evidence,
        pricing_unit_mix_by_project,
        pipeline_unit_mix_by_project,
    )

    headline = (
        f"Initial HBU: {product_options[0].positioning} on plot {dossier.plot_number}"
        if product_options
        else f"Initial HBU study for plot {dossier.plot_number}"
    )
    warnings = list(dossier.warnings)
    if not market_pricing:
        warnings.append("No segmented transaction pricing was found for the resolved market area.")

    return HBUStudy(
        plot_number=dossier.plot_number,
        usage=usage,
        market_area=market_area,
        headline=headline,
        summary=summary,
        constraints=constraints,
        pricing_evidence=pricing_evidence,
        competition_evidence=competition_evidence,
        market_pricing=market_pricing,
        product_options=product_options,
        recommended_mix=recommended_mix,
        price_per_sqm_by_type=price_per_sqm_by_type,
        assumptions_patch=assumptions_patch,
        warnings=warnings,
    )


async def get_land_plots(
    area: str, size_sqm: float, tolerance: float = 0.25
) -> list[GISPlotSummary]:
    min_plot_area_sqm = size_sqm * (1 - tolerance)
    max_plot_area_sqm = size_sqm * (1 + tolerance)
    return await search_gis_plots(
        community=area,
        min_plot_area_sqm=min_plot_area_sqm,
        max_plot_area_sqm=max_plot_area_sqm,
        limit=50,
    )


async def search_land_plots(area: str, q: str, limit: int = 30) -> list[GISPlotSummary]:
    return await search_gis_plots(q=q, community=area, limit=limit)


async def get_comparable_data(project_ids: list[int]) -> ComparableData | None:
    if not project_ids:
        return None

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

    project_sql = """
    SELECT project_id, project_name_en, area_name_en
    FROM ch_projects
    WHERE project_id IN ({project_ids:Array(Int32)})
    """
    project_rows = await query(project_sql, {"project_ids": project_ids})
    project_names = [r["project_name_en"] for r in project_rows if r.get("project_name_en")]
    area_names = [r["area_name_en"] for r in project_rows if r.get("area_name_en")]

    canonical_unit_sql = canonical_unit_type_case_sql("rooms_en")
    units_sql = f"""
    SELECT
        {canonical_unit_sql} AS unit_type,
        count() AS cnt,
        round(avg(actual_area), 2) AS avg_size_sqm
    FROM ch_units
    WHERE project_id IN ({{project_ids:Array(Int32)}})
      AND actual_area > 0
    GROUP BY unit_type
    HAVING unit_type != 'other'
    ORDER BY cnt DESC
    """
    units_rows = await query(units_sql, {"project_ids": project_ids})
    total_units = sum(r["cnt"] for r in units_rows)

    price_sql = f"""
    SELECT
        {canonical_unit_sql} AS unit_type,
        round(median(meter_sale_price), 0) AS median_price_sqm
    FROM ch_transactions
    WHERE project_name_en IN ({{project_names:Array(String)}})
      AND meter_sale_price > 0
      AND instance_date >= today() - 730
    GROUP BY unit_type
    HAVING unit_type != 'other'
    """
    price_rows = await query(price_sql, {"project_names": project_names}) if project_names else []
    price_by_type = {r["unit_type"]: float(r["median_price_sqm"]) for r in price_rows}

    unit_mix = [
        UnitTypeData(
            type=str(r["unit_type"]),
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
