"""Database-grounded sales and rental metrics shared by the API and the chat tools.

The served canonical tables (ch_transactions / ch_rent_contracts over the market layer) are
the authority. A period is resolved to Dubai calendar dates first; the release's actual date
coverage then decides whether the answer is complete, partial or unavailable. Missing data
stays missing: an uncovered period returns no values rather than zeros.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.analytics import market_metric_queries as queries
from app.analytics.models import (
    MarketCoverage,
    MarketLocationMatch,
    MarketMetricDefinition,
    MarketMetricRow,
    MarketMetricsRequest,
    MarketMetricsResponse,
    MarketResolvedPeriod,
)
from app.core.observability import operation
from app.market.periods import (
    BUSINESS_TIMEZONE,
    ResolvedPeriod,
    business_today,
    previous_period,
    resolve_period,
)
from app.market.reference import community_location

SMALL_SAMPLE = 10

ELIGIBILITY = {
    "sales": (
        "Served canonical sales (one row per DLD transaction after corrections and "
        "de-duplication, plus DXBI sales DLD does not hold): transaction group 'Sales' with a "
        "price above zero. Mortgages, gifts, probable duplicates and superseded versions are "
        "excluded. Date: DLD registration date (instance_date), Dubai calendar."
    ),
    "rentals": (
        "Served canonical Ejari contracts (de-duplicated DLD rows plus DXBI contracts DLD does "
        "not hold) with an annual amount above zero and an end date after the start date. "
        "Date: contract registration date, Dubai calendar."
    ),
}

_VALUE = {"sales": "sale price", "rentals": "annual rent (DLD annualised amount)"}
_AREA = {"sales": "procedure area", "rentals": "contract area"}


def _definitions(dataset: str, names: list[str]) -> list[MarketMetricDefinition]:
    value, area = _VALUE[dataset], _AREA[dataset]
    rate = f"{value} ÷ {area}, records with {area} > 0 (see rated_count)"
    text = {
        "count": ("records", "Eligible records in the period."),
        "total_aed": ("AED", f"Sum of {value}."),
        "mean_aed": ("AED", f"Arithmetic mean {value}."),
        "median_aed": (
            "AED",
            f"Median {value}; an even count averages the two middle values.",
        ),
        "p25_aed": ("AED", f"25th percentile {value}, linear interpolation."),
        "p75_aed": ("AED", f"75th percentile {value}, linear interpolation."),
        "rated_count": ("records", f"Records with {area} > 0, the per-area denominator."),
        "mean_aed_per_sqm": ("AED/sqm", f"Mean of each record's {rate}."),
        "median_aed_per_sqm": ("AED/sqm", f"Median of each record's {rate}."),
        "weighted_aed_per_sqm": ("AED/sqm", f"Area-weighted: sum of {value} ÷ sum of {area}."),
        "mean_aed_per_sqft": ("AED/sqft", "mean_aed_per_sqm ÷ 10.7639 (1 sqm = 10.7639 sqft)."),
        "median_aed_per_sqft": ("AED/sqft", "median_aed_per_sqm ÷ 10.7639."),
        "weighted_aed_per_sqft": ("AED/sqft", "weighted_aed_per_sqm ÷ 10.7639."),
        "total_contract_aed": ("AED", "Sum of whole-term contract amounts (not annualised)."),
        "median_contract_aed": ("AED", "Median whole-term contract amount (not annualised)."),
    }
    return [
        MarketMetricDefinition(name=name, unit=text[name][0], definition=text[name][1])
        for name in names
    ]


def _resolve(request: MarketMetricsRequest) -> ResolvedPeriod:
    spec = request.period
    return resolve_period(
        spec.type,
        reference_date=request.reference_date or business_today(),
        months=spec.months,
        days=spec.days,
        month=spec.month,
        quarter=spec.quarter,
        start=spec.start,
        end=spec.end,
    )


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _coverage(period: ResolvedPeriod, release: dict[str, Any]) -> MarketCoverage:
    data_from, data_to = _as_date(release.get("data_from")), _as_date(release.get("data_to"))
    if data_to is None or data_to < period.start or (data_from and data_from > period.end):
        return MarketCoverage(
            status="unavailable",
            data_from=data_from,
            data_to=data_to,
            note=(
                f"The served data has no records for {period.label}"
                + (f"; it runs from {data_from} to {data_to}." if data_to else ".")
            ),
        )
    covered_from = max(period.start, data_from or period.start)
    covered_to = min(period.end, data_to)
    complete = covered_from == period.start and covered_to == period.end
    note = (
        f"Data covers all of {period.label}."
        if complete
        else f"Data covers {covered_from} to {covered_to} of {period.label} "
        f"({period.start} to {period.end}); later records are not loaded yet."
    )
    return MarketCoverage(
        status="complete" if complete else "partial",
        data_from=data_from,
        data_to=data_to,
        covered_from=covered_from,
        covered_to=covered_to,
        note=note,
    )


def _period_model(period: ResolvedPeriod) -> MarketResolvedPeriod:
    return MarketResolvedPeriod(
        start=period.start,
        end=period.end,
        label=period.label,
        type=period.type,
        reference_date=period.reference_date,
        timezone=str(BUSINESS_TIMEZONE),
    )


def _clean(value: Any, digits: int = 2) -> float | None:
    if value is None:
        return None
    number = float(value)
    return None if math.isnan(number) or math.isinf(number) else round(number, digits)


def _row(raw: dict[str, Any], names: list[str], group: str | None = None) -> MarketMetricRow:
    count = int(raw.get("count") or 0)
    values = {}
    for name in names:
        if name == "count":
            continue
        values[name] = _clean(raw.get(name)) if count else (0.0 if name == "total_aed" else None)
    return MarketMetricRow(group=group, count=count, values=values)


def _filters(request: MarketMetricsRequest, start: date, end: date) -> queries.MetricFilters:
    location = community_location(request.location) if request.location else None
    bedrooms = tuple(
        "Studio" if item == "studio" else f"{item} B/R" for item in (request.bedrooms or [])
    )
    return queries.MetricFilters(
        start=start,
        end=end,
        location_masters=location.master_projects if location else (),
        location_areas=location.areas if location else (),
        location_official_areas=location.official_areas if location else (),
        building=request.building,
        project=request.project,
        property_type=request.property_type,
        usage=request.usage,
        bedrooms=bedrooms,
        registration={"off_plan": "Off-Plan Properties", "ready": "Existing Properties"}.get(
            request.registration or ""
        ),
        contract_version={"new": "New", "renewed": "Renewed"}.get(request.contract_version or ""),
        min_term_days=request.min_term_days,
        max_term_days=request.max_term_days,
        value_min=request.min_value_aed,
        value_max=request.max_value_aed,
        min_value_inclusive=request.min_value_inclusive,
        max_value_inclusive=request.max_value_inclusive,
    )


def _band_label(index: int, bands: list[float], upper_inclusive: tuple[bool, ...] = ()) -> str:
    flags = upper_inclusive or (False,) * len(bands)
    # Decimal(str(...)) preserves the supplied threshold, including fractional AED.
    labels = [format(Decimal(str(value)).normalize(), ",f") for value in bands]
    if index == 0:
        return f"up to and including {labels[0]}" if flags[0] else f"under {labels[0]}"
    if index == len(bands):
        return f"over {labels[-1]}" if flags[-1] else f"{labels[-1]} and above"
    lower = f"over {labels[index - 1]}" if flags[index - 1] else labels[index - 1]
    upper = f"including {labels[index]}" if flags[index] else f"under {labels[index]}"
    return f"{lower} to {upper}"


def _month_starts(start: date, end: date) -> list[date]:
    months, current = [], start.replace(day=1)
    while current <= end:
        months.append(current)
        current = (current + timedelta(days=32)).replace(day=1)
    return months


async def _total(request, names, period, coverage) -> MarketMetricRow:
    if coverage.status == "unavailable":
        return MarketMetricRow(count=None, values={name: None for name in names if name != "count"})
    filters = _filters(request, coverage.covered_from, coverage.covered_to)
    rows = await queries.fetch_metric_rows(request.dataset, filters, tuple(names))
    return _row(rows[0] if rows else {}, names)


async def _groups(request, names, period, coverage, total) -> list[MarketMetricRow]:
    filters = _filters(request, coverage.covered_from, coverage.covered_to)
    bands = tuple(request.price_bands or ())
    upper_inclusive = tuple(request.price_band_upper_inclusive or ())
    raw = await queries.fetch_metric_rows(
        request.dataset,
        filters,
        tuple(names),
        group_by=request.group_by,
        price_bands=bands,
        price_band_upper_inclusive=upper_inclusive,
        min_group_count=request.min_group_count,
        order_by=request.sort_by,
        limit=request.limit if request.group_by not in {"month", "price_band"} else 500,
    )
    rows: list[MarketMetricRow] = []
    if request.group_by == "month":
        found = {_as_date(item["group_key"]): item for item in raw}
        for month in _month_starts(period.start, period.end):
            if month > coverage.covered_to:
                # Not loaded yet: unknown, not zero.
                rows.append(MarketMetricRow(group=month.isoformat()[:7], count=None))
            else:
                rows.append(_row(found.get(month, {}), names, month.isoformat()[:7]))
    elif request.group_by == "price_band":
        found = {int(item["group_key"]): item for item in raw}
        rows = [
            _row(found.get(index, {}), names, _band_label(index, list(bands), upper_inclusive))
            for index in range(len(bands) + 1)
        ]
    else:
        rows = [_row(item, names, str(item["group_label"])) for item in raw]
    for row in rows:
        if row.count is not None and total.count:
            row.share_of_count = round(row.count / total.count, 4)
    return rows


def _change(current: MarketMetricRow, previous: MarketMetricRow) -> dict[str, float | None]:
    pairs = {"count": (current.count, previous.count)} | {
        name: (value, previous.values.get(name)) for name, value in current.values.items()
    }
    return {
        name: round((now - before) / before * 100, 2) if now is not None and before else None
        for name, (now, before) in pairs.items()
    }


@operation
async def get_market_metrics(request: MarketMetricsRequest) -> MarketMetricsResponse:
    period = _resolve(request)
    names = list(dict.fromkeys(["count", *request.metrics]))
    if any("per_sq" in name for name in names):
        names.append("rated_count")
    release = await queries.fetch_release(request.dataset)
    coverage = _coverage(period, release)
    total = await _total(request, names, period, coverage)
    response = MarketMetricsResponse(
        dataset=request.dataset,
        period=_period_model(period),
        coverage=coverage,
        filters=request.model_dump(
            mode="json", exclude_none=True, exclude={"metrics", "period", "reference_date"}
        ),
        eligibility=ELIGIBILITY[request.dataset],
        definitions=_definitions(request.dataset, names),
        total=total,
        release_built_at=str(release.get("built_at")) if release.get("built_at") else None,
    )
    limitations = response.limitations
    if coverage.status != "complete":
        limitations.append(coverage.note)
    if coverage.status == "unavailable":
        return response

    filters = _filters(request, coverage.covered_from, coverage.covered_to)
    if request.group_by:
        response.rows = await _groups(request, names, period, coverage, total)
    if request.compare_with_previous_period:
        before = previous_period(period)
        before_coverage = _coverage(before, release)
        response.comparison_period = _period_model(before)
        response.comparison_coverage = before_coverage
        response.comparison = await _total(request, names, before, before_coverage)
        if before_coverage.status == "complete" and coverage.status == "complete":
            response.change_pct = _change(total, response.comparison)
        else:
            limitations.append(
                "Change is not computed because a compared period is not fully covered."
            )
    if request.location:
        location = community_location(request.location)
        matched = await queries.fetch_matched_locations(request.dataset, filters)
        response.matched_locations = [MarketLocationMatch(**item) for item in matched]
        official = set(location.official_areas)
        if location.note and any(m.area.lower() in official for m in response.matched_locations):
            limitations.append(location.note)
    sources = await queries.fetch_source_breakdown(request.dataset, filters)
    response.sources = {
        f"{item['source_system']}/{item['match_status']}": int(item["records"]) for item in sources
    }
    if request.bedrooms:
        known = await queries.fetch_bedroom_coverage(request.dataset, filters)
        if int(known["unknown_bedrooms"]):
            limitations.append(
                f"{int(known['unknown_bedrooms'])} of {int(known['rows'])} records matching the "
                "other filters have no bedroom count in the source and are excluded."
            )
    if total.count is not None and total.count < SMALL_SAMPLE:
        limitations.append(f"Small sample: {total.count} eligible records.")
    return response
