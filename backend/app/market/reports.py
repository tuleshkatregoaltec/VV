"""Bounded composition of public market capabilities for the four report intents.

Report components are useful evidence independently. Cross-source valuations and report
conclusions fail closed while the canonical layer has no immutable shared release handle.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.analytics.evidence import get_market_evidence
from app.analytics.models import MarketBedrooms, MarketMetricsRequest, MarketPeriodRequest
from app.listings.capabilities import get_listing_evidence, get_listing_inventory
from app.listings.capability_models import ListingEvidenceRequest
from app.market.evidence import RELEASE_NOTE, MarketAccessContext, has_shared_release
from app.project.delivery import get_delivery_summary
from app.project.evidence import get_project_evidence


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["rental_appraisal", "seller_competition", "monthly_area", "off_plan_comparison"]
    location: str | None = Field(default=None, max_length=120)
    building: str | None = Field(default=None, max_length=160)
    bedrooms: MarketBedrooms | None = None
    projects: list[str] = Field(default_factory=list, max_length=3)
    asking_price_aed: float | None = Field(default=None, gt=0, le=1_000_000_000)
    period: MarketPeriodRequest = Field(
        default_factory=lambda: MarketPeriodRequest(type="previous_month")
    )


def required_bindings(request: ReportRequest) -> list[str]:
    required = []
    if request.kind in {"rental_appraisal", "seller_competition"}:
        required = [
            key for key in ("building", "location", "bedrooms") if not getattr(request, key)
        ]
    elif request.kind == "monthly_area" and not request.location:
        required = ["location"]
    elif request.kind == "off_plan_comparison" and len(request.projects) < 2:
        required = ["projects (two or three explicit names)"]
    return required


async def compose_market_report(request: ReportRequest, *, context: MarketAccessContext) -> dict:
    missing = required_bindings(request)
    if missing:
        return {"status": "clarification_required", "required_bindings": missing}
    components = {}
    if request.kind == "off_plan_comparison":
        projects = await get_project_evidence(request.projects, context=context)
        found = {}
        for row in projects["projects"]:
            found.setdefault(row["project_name_en"].casefold(), []).append(row)
        ambiguous = [name for name in request.projects if len(found.get(name.casefold(), [])) != 1]
        if ambiguous:
            return {
                "status": "clarification_required",
                "required_bindings": ambiguous,
                "reason": "A project name did not identify exactly one DLD project. Supply its exact registered name.",
                "components": {"project_register": projects},
            }
        components["project_register"] = projects
        for index, name in enumerate(request.projects):
            row = found[name.casefold()][0]
            if row["area_name_en"]:
                components[f"project_{index + 1}_area_sales"] = await get_market_evidence(
                    MarketMetricsRequest(
                        dataset="sales",
                        location=row["area_name_en"],
                        period=request.period,
                        metrics=["count", "median_aed", "median_aed_per_sqft"],
                    ),
                    context=context,
                )
    else:
        datasets = (
            ["rentals"]
            if request.kind == "rental_appraisal"
            else ["sales"]
            if request.kind == "seller_competition"
            else ["sales", "rentals"]
        )
        for dataset in datasets:
            components[dataset] = await get_market_evidence(
                MarketMetricsRequest(
                    dataset=dataset,
                    period=request.period,
                    location=request.location,
                    building=request.building,
                    bedrooms=[request.bedrooms] if request.bedrooms else None,
                    property_type="apartment",
                    metrics=[
                        "count",
                        "total_aed",
                        "mean_aed",
                        "median_aed",
                        "p25_aed",
                        "p75_aed",
                        "median_aed_per_sqft",
                    ],
                    group_by="contract_version" if request.kind == "rental_appraisal" else None,
                    compare_with_previous_period=request.kind == "monthly_area",
                ),
                context=context,
            )
        modes = (
            ["rent"]
            if request.kind == "rental_appraisal"
            else ["sale"]
            if request.kind == "seller_competition"
            else ["sale", "rent"]
        )
        for mode in modes:
            listing_request = ListingEvidenceRequest(
                mode=mode,
                location=request.location,
                building=request.building,
                bedrooms=request.bedrooms,
                limit=10,
            )
            operation = (
                get_listing_inventory if request.kind == "monthly_area" else get_listing_evidence
            )
            components[f"{mode}_listings"] = await operation(listing_request, context=context)
        if request.kind == "monthly_area":
            components["scheduled_delivery"] = (
                await get_delivery_summary(
                    location=request.location,
                    reference_date=context.reference_date,
                    delivery_statuses=("scheduled_in_horizon",),
                    horizon_months=24,
                )
            ).model_dump(mode="json")
    sources = {
        "off_plan_comparison": ("projects", "sales"),
        "monthly_area": ("sales", "rentals", "listings", "projects"),
        "rental_appraisal": ("rentals", "listings"),
        "seller_competition": ("sales", "listings"),
    }[request.kind]
    pinned = has_shared_release(*sources)
    conclusions = report_conclusions(request, components, pinned=pinned)
    return {
        "status": "ok" if pinned else "unavailable",
        "kind": request.kind,
        "filters": request.model_dump(mode="json"),
        "components": components,
        **conclusions,
        "limitations": ([] if pinned else [RELEASE_NOTE])
        + [
            "Components retain their own periods, samples and limitations; they are not a verified cross-source appraisal.",
            "Period-over-period changes require authoritative coverage and remain withheld.",
            "Nearby achieved prices are area-level context, not a property valuation or distance-based comparable set.",
        ],
    }


def report_conclusions(request: ReportRequest, components: dict, *, pinned: bool) -> dict:
    result = {"supported_annual_asking_rent_range_aed": None, "owner_asking_position": None}
    if not pinned:
        return result
    dataset = "rentals" if request.kind == "rental_appraisal" else "sales"
    metrics = components.get(dataset, {})
    if metrics.get("coverage", {}).get("status") != "complete":
        return result
    if (metrics.get("total", {}).get("count") or 0) < 5:
        return result
    values = metrics["total"]["values"]
    if request.kind == "rental_appraisal":
        new = next((row for row in metrics.get("rows", []) if row.get("group") == "New"), None)
        competition = components.get("rent_listings", {}).get("listings", [])
        supported_listings = [row for row in competition if (row.get("asking_price_aed") or 0) > 0]
        if new and new["count"] >= 5 and len(supported_listings) >= 3:
            low, high = (new["values"].get(key) for key in ("p25_aed", "p75_aed"))
            if low and high:
                result["supported_annual_asking_rent_range_aed"] = [low, high]
                result["asking_range_basis"] = (
                    "Middle 50% of same-building/layout new registered annual rents; competing listings shown separately. Not an adjusted appraisal or a guaranteed achievable rent."
                )
    if (
        request.kind == "seller_competition"
        and request.asking_price_aed
        and values.get("median_aed")
    ):
        low, high = (values.get(key) for key in ("p25_aed", "p75_aed"))
        result["owner_asking_position"] = {
            "asking_price_aed": request.asking_price_aed,
            "achieved_comparable_count": metrics["total"]["count"],
            "difference_from_achieved_median_pct": round(
                (request.asking_price_aed / values["median_aed"] - 1) * 100, 2
            ),
            "relative_to_achieved_iqr": "below"
            if low and request.asking_price_aed < low
            else "above"
            if high and request.asking_price_aed > high
            else "within"
            if low and high
            else "unknown",
            "definition": "Asking price compared with achieved sales for the same building/layout/period, not a valuation adjusted for size, floor, view or condition.",
        }
    return result
