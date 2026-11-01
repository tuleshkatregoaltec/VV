"""Deterministic comparable screening on the same canonical market filters as analytics."""

import math

from app.analytics import market_metric_queries as queries
from app.analytics import market_metrics
from app.analytics.assistant_models import ComparableRequest
from app.analytics.models import MarketMetricsRequest


def _number(value):
    return float(value) if value is not None and math.isfinite(float(value)) else None


async def get_comparable_evidence(request: ComparableRequest) -> dict:
    base = MarketMetricsRequest(
        dataset=request.dataset,
        period=request.period,
        location=request.location,
        building=request.building,
        property_type=request.property_type,
        bedrooms=[request.bedrooms],
        contract_version=request.contract_version,
        reference_date=request.reference_date,
    )
    period = market_metrics._resolve(base)
    if (period.end - period.start).days > 730:
        raise ValueError("Comparable periods cannot exceed two years")
    filters = market_metrics._filters(base, period.start, period.end)
    size_min = (
        request.target_size_sqft * (1 - request.size_tolerance)
        if request.target_size_sqft
        else None
    )
    size_max = (
        request.target_size_sqft * (1 + request.size_tolerance)
        if request.target_size_sqft
        else None
    )
    for _ in range(2):
        release = await queries.fetch_release(request.dataset)
        coverage = market_metrics._coverage(period, release)
        summary, rows = await queries.fetch_comparable_evidence(
            request.dataset, filters, size_min=size_min, size_max=size_max, limit=request.limit
        )
        if await queries.fetch_release_id(request.dataset) == (release.get("release_id") or ""):
            break
    else:
        return {"available": False, "reason": "Stored evidence changed during retrieval; retry"}
    count = int(summary.get("count") or 0)
    median = _number(summary.get("median_aed")) if count else None
    rated = int(summary.get("rated_count") or 0)
    estimate = None
    if count >= 5:
        if request.target_size_sqft and rated >= 5:
            rate = _number(summary.get("median_aed_per_sqft"))
            estimate = round(rate * request.target_size_sqft, 2) if rate else None
        elif request.building:
            estimate = median
    limits = [
        "Recent sample rows are not the whole population; sample_count differs from matching_count.",
        "Exact location, bedroom and property-type filters are used; sizes are bounded only when supplied.",
        "Indicative screening is not a formal valuation. Condition, floor, view and service charges are not matched.",
        "Gross yield excludes fees, service charges, vacancy and financing; rental samples are not the subject property's lease.",
    ]
    if count < 5:
        limits.append("Fewer than five matching records: no supported appraisal or yield estimate.")
    if coverage.status != "complete":
        limits.append(coverage.note)
    return {
        "available": count > 0,
        "dataset": request.dataset,
        "source": "Reconciled DLD and DXBI registered records",
        "period": market_metrics._period_model(period).model_dump(mode="json"),
        "coverage": coverage.model_dump(mode="json"),
        "applied_filters": request.model_dump(mode="json"),
        "matching_count": None if not count and coverage.status == "unavailable" else count,
        "sample_count": len(rows),
        "sample_order": "Most recent first",
        "records": rows,
        "median_aed": median,
        "middle_50_percent_range_aed": [
            _number(summary.get("p25_aed")),
            _number(summary.get("p75_aed")),
        ]
        if count
        else None,
        "indicative_value_aed": estimate,
        "indicative_value_definition": "Median achieved amount per sq ft multiplied by subject size"
        if request.target_size_sqft
        else "Median matching amount within the named building",
        "gross_yield_pct": round(estimate / request.asking_price_aed * 100, 2)
        if request.dataset == "rentals" and estimate and request.asking_price_aed
        else None,
        "asking_vs_median_pct": round((request.asking_price_aed / median - 1) * 100, 2)
        if request.dataset == "sales" and request.asking_price_aed and median
        else None,
        "confidence": "limited"
        if count < 10 or coverage.status != "complete" or not request.building
        else "moderate",
        "limitations": limits,
    }
