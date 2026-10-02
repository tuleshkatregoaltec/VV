"""Public, conservative evidence over the shared metric operation; no new calculations."""

from app.analytics import market_metric_queries, market_metrics
from app.analytics.models import MarketMetricsRequest
from app.market.evidence import COVERAGE_NOTE, MarketAccessContext, current_market_release


async def get_market_observation(dataset: str) -> dict:
    release = await market_metric_queries.fetch_release(dataset)
    return {key: str(value) if value is not None else None for key, value in release.items()}


async def get_market_evidence(
    request: MarketMetricsRequest, *, context: MarketAccessContext
) -> dict:
    # Relative periods are anchored by the server. Explicit month/range periods remain intact.
    request = request.model_copy(update={"reference_date": context.reference_date})
    result = await market_metrics.get_market_metrics(request)
    data = result.model_dump(mode="json")
    release = current_market_release()
    verified = {}
    authoritative = {}
    for key in ("coverage", "comparison_coverage"):
        if data.get(key):
            period = result.period if key == "coverage" else result.comparison_period
            manifest_complete = bool(
                release and period and release.covers(request.dataset, period.start, period.end)
            )
            authoritative[key] = manifest_complete
            metric_row = data.get("total" if key == "coverage" else "comparison")
            has_result = metric_row is not None and metric_row.get("count") is not None
            verified[key] = manifest_complete and has_result
            if manifest_complete and not has_result:
                data[key] = {
                    **data[key],
                    "status": "unavailable",
                    "note": "The pinned manifest declares coverage, but the shared metric service returned unknown values. Unknown is not zero; no complete numerical result is available.",
                }
                data["limitations"].append(data[key]["note"])
                continue
            if verified[key]:
                data[key] = {
                    **data[key],
                    "status": "complete",
                    "note": "Complete period coverage verified by the pinned release manifest.",
                }
                continue
            data[key] = {
                **data[key],
                "status": "unavailable" if data[key]["status"] == "unavailable" else "unverified",
                "note": COVERAGE_NOTE,
            }
    if not (verified.get("coverage") and verified.get("comparison_coverage")):
        data["change_pct"] = {}
    data["limitations"] = [
        note for note in data["limitations"] if not note.startswith("Data covers ")
    ] + ([] if authoritative.get("coverage") else [COVERAGE_NOTE])
    if request.compare_with_previous_period and not data["change_pct"]:
        data["limitations"].append(
            "Period changes require authoritative complete coverage and supported metric rows for both periods."
        )
    return data
