"""Warehouse SQL for database-grounded sales and rental metrics.

Every user value is a bound parameter. Metric, grouping and dataset names reach SQL only
through the fixed fragments below, selected by validated Literal names.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.analytics.dxbi import RENTALS_SOURCE, SALES_SOURCE
from app.clickhouse import query
from app.market.reference import SQM_TO_SQFT


@dataclass(frozen=True, slots=True)
class Dataset:
    table: str
    listed_table: str
    # The load evidence (source_load_windows) of the DXBI feed behind the listed table.
    evidence_table: str
    evidence_date: str
    event_date: str
    value: str
    area_sqm: str
    eligible: str
    bedrooms: str
    building: str
    property_types: dict[str, str]


# Capability property types on the uniform property_type column (one list for both datasets).
UNIFORM_PROPERTY_TYPES = {
    "apartment": "property_type = 'Apartment'",
    "hotel_apartment": "property_type = 'Hotel Apartment'",
    "villa": "property_type IN ('Villa', 'Townhouse')",
    "townhouse": "property_type = 'Townhouse'",
    "office": "property_type = 'Office'",
    "shop": "property_type = 'Shop'",
    "land": "property_type = 'Plot'",
}

# The Analytics records (decision 2026-11-15): DXBI's listed sales and leases, as /analytics/sales,
# /rentals, market-trend and the project pages read them, price floors included
# (app.analytics.dxbi). They used to be the combined DXBI + DLD market layer, so the same filter
# answered different counts here and on the pages.
SALES = Dataset(
    table=SALES_SOURCE,
    listed_table="dxbi_sales_listed",
    evidence_table="dxbi_sales_unit_events",
    evidence_date="transaction_date",
    # DXBI's transaction date (Dubai calendar).
    event_date="toDate(instance_date)",
    value="toFloat64(actual_worth)",
    area_sqm="size_sqm",
    eligible="trans_group_en = 'Sales' AND actual_worth > 0",
    bedrooms="rooms_en",
    building="building_label",
    property_types=UNIFORM_PROPERTY_TYPES,
)

RENTALS = Dataset(
    table=RENTALS_SOURCE,
    listed_table="dxbi_leases_listed",
    evidence_table="dxbi_rental_events",
    evidence_date="lease_start",
    # A lease counts in the month it starts (decision 2026-10-07), on every page.
    event_date="toDate(contract_start_date)",
    # The annualised rent; contract_amount is the whole-term value.
    value="toFloat64(annual_amount)",
    area_sqm="size_sqm",
    eligible="annual_amount > 0",
    bedrooms="rooms_en",
    building="building_label",
    property_types=UNIFORM_PROPERTY_TYPES,
)

DATASETS = {"sales": SALES, "rentals": RENTALS}

# A name as a location key (app.market.reference.location_key): lower case, single-spaced.
_LOCATION_KEY = "replaceRegexpAll(lowerUTF8(trimBoth({e})), '[[:space:]]+', ' ')"
# A community is DXBI's community or the master project; a district is DLD's area.
LOCATION_PREDICATE = (
    f"({_LOCATION_KEY.format(e='location_name')} IN {{loc_communities:Array(String)}}"
    f" OR {_LOCATION_KEY.format(e='master_project_en')} IN {{loc_communities:Array(String)}}"
    " OR lowerUTF8(area_name_en) IN {loc_districts:Array(String)})"
)


def _from(dataset: str) -> str:
    return DATASETS[dataset].table


def _rate(ds: Dataset) -> str:
    """AED per square foot of one record (sizes are stored in m²)."""
    return f"{ds.value} / ({ds.area_sqm} * {SQM_TO_SQFT})"


def metric_expressions(ds: Dataset) -> dict[str, str]:
    rated = f"{ds.area_sqm} > 0"
    expressions = {
        "count": "toFloat64(count())",
        "total_aed": f"sum({ds.value})",
        "mean_aed": f"avg({ds.value})",
        # Linear interpolation between order statistics (PERCENTILE.INC): the median of an
        # even count is the mean of the two middle values.
        "median_aed": f"quantileExactInclusive(0.5)({ds.value})",
        "p25_aed": f"quantileExactInclusive(0.25)({ds.value})",
        "p75_aed": f"quantileExactInclusive(0.75)({ds.value})",
        "rated_count": f"toFloat64(countIf({rated}))",
        "mean_aed_per_sqft": f"avgIf({_rate(ds)}, {rated})",
        "median_aed_per_sqft": f"quantileExactInclusiveIf(0.5)({_rate(ds)}, {rated})",
        "weighted_aed_per_sqft": (
            f"sumIf({ds.value}, {rated}) / sumIf({ds.area_sqm} * {SQM_TO_SQFT}, {rated})"
        ),
    }
    if ds is RENTALS:
        expressions["total_contract_aed"] = "sum(toFloat64(contract_amount))"
        expressions["median_contract_aed"] = (
            "quantileExactInclusive(0.5)(toFloat64(contract_amount))"
        )
    return expressions


def group_expressions(ds: Dataset) -> dict[str, tuple[str, str]]:
    """Group name -> (key expression, display label expression)."""
    return {
        # DLD's area (the record's profile), else DXBI's community.
        "area": ("lowerUTF8(area_name_en)", "any(area_name_en)"),
        "community": (
            _LOCATION_KEY.format(e="location_name"),
            "if(any(location_name) = '', '(no community)', any(location_name))",
        ),
        "master_project": ("master_key_en", "any(master_project_en)"),
        "project": ("scope_key", "any(project_name_en)"),
        "building": (f"lowerUTF8({ds.building})", f"any({ds.building})"),
        "month": (f"toStartOfMonth({ds.event_date})", f"toString(toStartOfMonth({ds.event_date}))"),
        "bedrooms": (ds.bedrooms, f"any({ds.bedrooms})"),
        "property_type": ("property_type", "any(property_type)"),
    } | (
        {"registration": ("reg_type_en", "any(reg_type_en)")}
        if ds is SALES
        else {"contract_version": ("version_en", "any(version_en)")}
    )


@dataclass(frozen=True, slots=True)
class MetricFilters:
    start: date
    end: date
    location_communities: tuple[str, ...] = ()
    location_districts: tuple[str, ...] = ()
    building: str | None = None
    project: str | None = None
    property_type: str | None = None
    usage: str | None = None
    bedrooms: tuple[str, ...] = ()
    registration: str | None = None
    contract_version: str | None = None
    min_term_days: int | None = None
    max_term_days: int | None = None
    value_min: float | None = None
    value_max: float | None = None


def where_clause(
    ds: Dataset, filters: MetricFilters, *, include_bedrooms: bool = True
) -> tuple[str, dict[str, Any]]:
    clauses = [ds.eligible, f"{ds.event_date} BETWEEN {{start:Date}} AND {{end:Date}}"]
    params: dict[str, Any] = {"start": filters.start, "end": filters.end}
    if filters.location_communities or filters.location_districts:
        clauses.append(LOCATION_PREDICATE)
        params |= {
            "loc_communities": list(filters.location_communities),
            "loc_districts": list(filters.location_districts),
        }
    if filters.building:
        clauses.append(f"lowerUTF8({ds.building}) = lowerUTF8({{building:String}})")
        params["building"] = filters.building.strip()
    if filters.project:
        clauses.append("lowerUTF8(project_name_en) = lowerUTF8({project:String})")
        params["project"] = filters.project.strip()
    if filters.property_type:
        clauses.append(ds.property_types[filters.property_type])
    if filters.usage:
        # The pages' usage, as they bind it ('Residential', 'Commercial').
        clauses.append("property_usage_en = {usage:String}")
        params["usage"] = filters.usage.capitalize()
    if include_bedrooms and filters.bedrooms:
        clauses.append(f"{ds.bedrooms} IN {{bedrooms:Array(String)}}")
        params["bedrooms"] = list(filters.bedrooms)
    if filters.registration:
        clauses.append("reg_type_en = {registration:String}")
        params["registration"] = filters.registration
    if filters.contract_version:
        clauses.append("version_en = {contract_version:String}")
        params["contract_version"] = filters.contract_version
    term = "dateDiff('day', toDate(contract_start_date), toDate(contract_end_date)) + 1"
    if filters.min_term_days is not None:
        clauses.append(f"{term} >= {{min_term:Int32}}")
        params["min_term"] = filters.min_term_days
    if filters.max_term_days is not None:
        clauses.append(f"{term} <= {{max_term:Int32}}")
        params["max_term"] = filters.max_term_days
    if filters.value_min is not None:
        clauses.append(f"{ds.value} >= {{value_min:Float64}}")
        params["value_min"] = filters.value_min
    if filters.value_max is not None:
        clauses.append(f"{ds.value} < {{value_max:Float64}}")
        params["value_max"] = filters.value_max
    return " AND ".join(clauses), params


def _band_expression(ds: Dataset, bands: tuple[float, ...]) -> tuple[str, str]:
    # Bands are [b0, b1), [b1, b2) ... ; boundaries are bound as parameters.
    conditions = ", ".join(
        f"{ds.value} < {{band_{index}:Float64}}, {index}" for index in range(len(bands))
    )
    key = f"multiIf({conditions}, {len(bands)})"
    return key, key


async def fetch_metric_rows(
    dataset: str,
    filters: MetricFilters,
    metrics: tuple[str, ...],
    *,
    group_by: str | None = None,
    price_bands: tuple[float, ...] = (),
    min_group_count: int = 1,
    order_by: str = "count",
    limit: int = 50,
) -> list[dict[str, Any]]:
    ds = DATASETS[dataset]
    expressions = metric_expressions(ds)
    where, params = where_clause(ds, filters)
    names = dict.fromkeys(("count", *metrics))
    selected = ", ".join(f"{expressions[name]} AS {name}" for name in names)
    if group_by is None:
        return await query(f"SELECT {selected} FROM {_from(dataset)} WHERE {where}", params)
    if group_by == "price_band":
        key, label = _band_expression(ds, price_bands)
        params |= {f"band_{index}": value for index, value in enumerate(price_bands)}
    else:
        key, label = group_expressions(ds)[group_by]
    params |= {"min_group_count": min_group_count, "limit": limit}
    return await query(
        f"""
        SELECT {key} AS group_key, {label} AS group_label, {selected}
        FROM {_from(dataset)}
        WHERE {where}
        GROUP BY group_key
        HAVING count() >= {{min_group_count:UInt32}}
        ORDER BY {order_by} DESC, group_key
        LIMIT {{limit:UInt32}}
        """,
        params,
    )


async def fetch_bedroom_coverage(dataset: str, filters: MetricFilters) -> dict[str, Any]:
    """Rows matching every filter except bedrooms, and how many have no bedroom count."""
    ds = DATASETS[dataset]
    where, params = where_clause(ds, filters, include_bedrooms=False)
    rows = await query(
        f"SELECT count() AS rows, countIf({ds.bedrooms} = '') AS unknown_bedrooms "
        f"FROM {_from(dataset)} WHERE {where}",
        params,
    )
    return rows[0] if rows else {"rows": 0, "unknown_bedrooms": 0}


async def fetch_matched_locations(dataset: str, filters: MetricFilters) -> list[dict[str, Any]]:
    """Source names behind the matched rows: DXBI's community, the master and DLD's area."""
    ds = DATASETS[dataset]
    where, params = where_clause(ds, filters)
    return await query(
        f"""
        SELECT location_name AS area, master_project_en AS master_project,
               area_name_en AS district, location_name AS community,
               'dxbi_community' AS method, count() AS records
        FROM {_from(dataset)}
        WHERE {where}
        GROUP BY area, master_project, district, community, method
        ORDER BY records DESC
        LIMIT 10
        """,
        params,
    )


async def fetch_source_breakdown(dataset: str, filters: MetricFilters) -> list[dict[str, Any]]:
    """Every record is a DXBI listed one (``dxbi/listed``); kept so answers name their source."""
    ds = DATASETS[dataset]
    where, params = where_clause(ds, filters)
    return await query(
        f"""
        SELECT 'dxbi' AS source_system, 'listed' AS match_status, count() AS records
        FROM {_from(dataset)}
        WHERE {where}
        """,
        params,
    )


def _release_id(ds: Dataset) -> str:
    """The listed table's build: it is rebuilt whole, so its build time identifies its rows."""
    return (
        f"(SELECT concat('dxbi-', formatDateTime(max(built_at), '%Y%m%d%H%i%S')) "
        f"FROM {ds.listed_table})"
    )


async def fetch_release_id(dataset: str) -> str:
    """The build the listed table holds right now."""
    rows = await query(f"SELECT {_release_id(DATASETS[dataset])} AS release_id", {})
    return str(rows[0]["release_id"]) if rows else ""


def coverage_ranges(windows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Day ranges by status from load windows in load order: a day takes its latest load's.

    A window loaded whole (from its first row) and complete is verified; anything else is
    partial (holocron.platform.load_windows.window_statuses, for the windows the DXBI sync
    records).
    """
    status: dict[date, str] = {}
    for window in windows:
        verified = window["status"] == "complete" and int(window["first_row"]) == 0
        day, last = _as_day(window["window_start"]), _as_day(window["window_end"])
        while day <= last:
            status[day] = "verified" if verified else "partial"
            day += timedelta(days=1)
    ranges: list[dict[str, str]] = []
    for day in sorted(status):
        last_range = ranges[-1] if ranges else None
        if (
            last_range
            and last_range["status"] == status[day]
            and date.fromisoformat(last_range["to"]) == day - timedelta(days=1)
        ):
            last_range["to"] = day.isoformat()
        else:
            ranges.append({"from": day.isoformat(), "to": day.isoformat(), "status": status[day]})
    return ranges


def _as_day(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


async def fetch_release(dataset: str) -> dict[str, Any]:
    """Identity, record dates and load-evidence coverage of the records served now.

    Coverage is the DXBI feed's own load evidence: the days each daily run (``_SUCCESS``: every
    shard finished) replaced, recorded by the warehouse sync in ``source_load_windows``.
    """
    ds = DATASETS[dataset]
    rows = await query(
        f"""
        SELECT {_release_id(ds)} AS release_id,
               count() AS eligible_count,
               min({ds.event_date}) AS data_from,
               max({ds.event_date}) AS data_to,
               (SELECT toString(max(built_at)) FROM {ds.listed_table}) AS built_at
        FROM {_from(dataset)}
        WHERE {ds.eligible} AND {ds.event_date} <= today()
        """,
        {},
    )
    release = dict(rows[0]) if rows else {}
    windows = await query(
        "SELECT window_start, window_end, status, first_row, toString(loaded_at) AS loaded_at "
        "FROM source_load_windows "
        "WHERE bronze_table = {bronze_table:String} AND date_field = {date_field:String} "
        "ORDER BY loaded_at, window_start",
        {"bronze_table": ds.evidence_table, "date_field": ds.evidence_date},
    )
    release["coverage"] = {
        "basis": ds.evidence_date,
        "ranges": coverage_ranges(windows),
        "last_loaded_at": windows[-1]["loaded_at"] if windows else None,
    }
    return release


async def fetch_comparable_evidence(
    dataset: str,
    filters: MetricFilters,
    *,
    size_min: float | None,
    size_max: float | None,
    limit: int,
) -> tuple[dict, list[dict]]:
    """Exact aggregate plus a bounded recent comparable sample; no contact or unit IDs."""
    ds = DATASETS[dataset]
    where, params = where_clause(ds, filters)
    if size_min is not None:
        where += f" AND {ds.area_sqm} * {SQM_TO_SQFT} BETWEEN {{size_min:Float64}} AND {{size_max:Float64}}"
        params |= {"size_min": size_min, "size_max": size_max}
    expressions = metric_expressions(ds)
    aggregate = await query(
        f"SELECT {', '.join(expressions[name] + ' AS ' + name for name in ('count', 'median_aed', 'p25_aed', 'p75_aed', 'rated_count', 'median_aed_per_sqft'))} FROM {_from(dataset)} WHERE {where}",
        params,
    )
    rental = (
        ", version_en AS contract_version, toDate(contract_end_date) AS contract_end, "
        "toFloat64(contract_amount) AS contract_amount_aed"
        if dataset == "rentals"
        else ", reg_type_en AS registration"
    )
    rows = await query(
        f"""SELECT {ds.event_date} AS event_date, {ds.value} AS amount_aed,
            if({ds.area_sqm} > 0, {ds.area_sqm} * {SQM_TO_SQFT}, NULL) AS size_sqft,
            if({ds.area_sqm} > 0, {_rate(ds)}, NULL) AS amount_per_sqft_aed,
            {ds.building} AS building, {ds.bedrooms} AS bedrooms, 'dxbi' AS source
            {rental}
            FROM {_from(dataset)} WHERE {where}
            ORDER BY {ds.event_date} DESC, {ds.value}, {ds.building}
            LIMIT {{limit:UInt32}}""",
        params | {"limit": limit},
    )
    return aggregate[0] if aggregate else {}, rows
