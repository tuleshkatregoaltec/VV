from datetime import date
from typing import Annotated, Any, Literal, Optional

from pydantic import Field
from pydantic_ai import RunContext

from app.analytics import assistant as analytics_assistant
from app.analytics import market_metrics
from app.analytics import service as analytics_service
from app.analytics.assistant_models import ComparableRequest
from app.analytics.models import MarketMetricsRequest
from app.listings import assistant as listing_assistant
from app.listings import service as listings_service
from app.listings.assistant import ListingResearchRequest
from app.market.reference import community_location
from app.market.scope import ProjectFilterType
from app.market_ai.sources import safe_tool
from app.project import assistant as project_assistant
from app.project import delivery
from app.project import service as project_service
from app.project.models import DeliveryStatus


@safe_tool
async def get_database_coverage(
    ctx: RunContext[None], dataset: Literal["sales", "rentals"]
) -> dict[str, Any]:
    """Discover stored sales or rental data: eligible count, dates and load evidence.

    Use when asked what data is available, how up to date it is, or which dates can be
    analysed. Date bounds alone do not prove all intervening days were loaded. Follow up
    with query_market_metrics for verified coverage and numbers for a specific period.
    """
    return await market_metrics.get_market_data_coverage(dataset)


@safe_tool
async def search_database_locations(
    ctx: RunContext[None],
    search: Annotated[str, Field(min_length=1, max_length=120)],
    limit: Annotated[int, Field(ge=1, le=20)] = 10,
) -> dict[str, Any]:
    """Find stored project, master/community and building names, including aliases like JVC.

    Use before a project/building-specific question when its exact name or scope is unclear.
    Results include filter_type and building_id for get_project_profile. Ask the user to
    choose when multiple places match; an empty result means no stored match, not no property.
    """
    result = await analytics_service.get_project_search(search, limit=limit)
    return result.model_dump(mode="json")


@safe_tool
async def get_project_profile(
    ctx: RunContext[None],
    name: Annotated[str, Field(min_length=1, max_length=160)],
    filter_type: ProjectFilterType = "project",
    usage: Literal["auto", "Residential", "Commercial"] = "auto",
) -> dict[str, Any]:
    """Read a stored DXBI project/community/building profile and registered stock metadata.

    Use a name and filter_type from search_database_locations. For a building use its
    building_id as name. Returns metadata, all-stored-date sales/rental summaries and
    bedroom breakdowns. This is the Analytics page's DXBI dataset, distinct from the
    DLD/reconciled market metrics dataset. For dated metrics use query_market_metrics.
    Zero sale/rental counts mean their price statistics are unavailable, not zero prices.
    """
    result = await analytics_service.get_project_summary(name, filter_type, usage=usage)
    payload = result.model_dump(
        mode="json",
        include={"project", "usage", "usage_counts", "sales", "rentals", "by_rooms"},
    )
    # The Analytics UI uses zero placeholders; the model must receive absence explicitly.
    for key, count_key in (("sales", "transaction_count"), ("rentals", "contract_count")):
        if payload[key][count_key] == 0:
            payload[key] = {count_key: 0}
    payload["by_rooms"] = [
        {
            key: value
            for key, value in row.items()
            if (row["sale_count"] or key not in {"avg_sale_price", "avg_sale_price_sqft"})
            and (row["rental_count"] or key not in {"median_annual_rent", "median_rent_sqft"})
        }
        for row in payload["by_rooms"]
    ]
    return payload | {
        "source": "DXBI stored sales and leases; stock metadata includes field_sources",
        "scope": {"name": name, "filter_type": filter_type},
        "period": "All stored dates; completeness is unverified",
        "limitations": [
            "Missing metadata is unknown, not zero.",
            "Sale prices are achieved prices; rents are annual AED; sizes are sq ft.",
            "Gross yield compares stored sale and rental samples, not the same property's return.",
        ],
    }


@safe_tool
async def get_market_pulse(
    ctx: RunContext[None],
    area: Annotated[str, Field(min_length=1, max_length=160)],
    period_days: Annotated[int, Field(ge=1, le=730)] = 90,
) -> dict[str, Any]:
    """Get vital market statistics for a specific area.

    Returns aggregate metrics including median price, average yield, transaction volume,
    and price trends for the specified area and time period.

    Args:
        ctx: Runtime context (unused)
        area: Area name (e.g., "Dubai Marina", "Downtown Dubai")
        period_days: Analysis period in days (default: 90)

    Returns:
        Dictionary with price, yield, volume, and trend data
    """
    return await analytics_service.get_market_pulse(area, period_days)


@safe_tool
async def rank_areas(
    ctx: RunContext[None],
    metric: Literal["volume", "price", "growth"] = "volume",
    limit: Annotated[int, Field(ge=1, le=20)] = 5,
    period_days: Annotated[int, Field(ge=1, le=730)] = 90,
) -> dict[str, Any]:
    """Rank top areas by a specific metric.

    Args:
        ctx: Runtime context (unused)
        metric: Ranking metric - "volume" (transaction count), "price" (median price),
                or "growth" (price change percentage)
        limit: Number of top areas to return (default: 5)
        period_days: Analysis period in days (default: 90)

    Returns:
        List of top areas with their respective metrics
    """
    return await analytics_service.rank_areas(metric, limit, period_days)


@safe_tool
async def get_similar_projects(
    ctx: RunContext[None],
    project_name: Annotated[str, Field(min_length=1, max_length=160)],
    limit: Annotated[int, Field(ge=1, le=20)] = 5,
) -> dict[str, Any]:
    """Find similar projects based on attributes.

    Uses ClickHouse projections to efficiently search for comparable projects
    based on property characteristics, location, and developer.

    Args:
        ctx: Runtime context (unused)
        project_name: Name of the reference project
        limit: Number of similar projects to return (default: 5)

    Returns:
        List of similar projects with comparison metrics
    """
    # First, get the reference project details
    return await project_service.get_similar_projects(project_name, limit)


@safe_tool
async def query_market_metrics(
    ctx: RunContext[None], request: MarketMetricsRequest
) -> dict[str, Any]:
    """Compute sales or rental metrics from the stored DLD/DXBI records.

    Use this for counts, totals, averages (mean_aed), medians, quartiles, prices per sq ft,
    price brackets, rankings by building/project/community/area (area = official DLD
    district), monthly series and new-versus-renewed rents. Periods are calendar periods in
    Dubai time: "last month" is {"type": "previous_month"}, "last quarter"
    {"type": "previous_quarter"}, "last 90 days" {"type": "rolling_days", "days": 90}, "last
    six complete months" {"type": "previous_months", "months": 6}. "Average" means mean_aed
    unless the user asks for the median.

    The result states the resolved dates, coverage (complete, partial, unverified or
    unavailable; only complete means every day is verified as loaded), eligible record
    count, metric definitions, sources and limitations. Report those with the
    numbers. A community answer leaves out records DLD locates only by a wider district; the
    limitations say how many. If coverage is unavailable or a value is null, say the stored
    data does not contain it; never fill the gap from other sources.
    """
    result = await market_metrics.get_market_metrics(request)
    return result.model_dump(mode="json")


@safe_tool
async def get_listing_inventory(
    ctx: RunContext[None],
    mode: Literal["sale", "rent"],
    location: Optional[str] = None,
    bedrooms: Optional[str] = None,
    property_type: Optional[str] = None,
    price_max: Optional[int] = None,
) -> dict[str, Any]:
    """Current Property Finder listing inventory: count and asking prices.

    These are asking prices from the latest captured listing snapshot, not achieved prices.
    Medians here are approximate (t-digest). snapshot_at is when the inventory was captured.

    Args:
        ctx: Runtime context (unused)
        mode: "sale" or "rent" (rent prices are annual)
        location: Community, e.g. "Dubai Hills Estate" or "JVC"
        bedrooms: Bedroom value as listed, e.g. "studio", "1", "2"
        property_type: Listing property type, e.g. "Apartment"
        price_max: Maximum asking price in AED
    """
    area = community_location(location).name if location else None
    result = await listings_service.listing_analytics_from_clickhouse(
        mode=mode,
        area=area,
        bedrooms=bedrooms,
        property_type=property_type,
        price_max=price_max,
    )
    payload = result.model_dump(mode="json", exclude={"trend"})
    return payload | {
        "source": "Property Finder listings (asking prices)",
        "filters": {"mode": mode, "community": area, "bedrooms": bedrooms},
    }


@safe_tool
async def get_project_delivery_summary(
    ctx: RunContext[None],
    location: Optional[str] = None,
    group_by: Literal["developer", "delivery_status", "delivery_year", "project"] = "developer",
    delivery_statuses: Optional[list[DeliveryStatus]] = None,
    horizon_months: int = 24,
    project_statuses: Optional[list[str]] = None,
    reference_date: Optional[date] = None,
) -> dict[str, Any]:
    """DLD-registered projects and units by delivery status, developer, year or project.

    Delivery status on the reference date (Dubai): missing_date, overdue,
    scheduled_in_horizon (planned end within horizon_months), scheduled_later, completed,
    cancelled. project_statuses are DLD register statuses (default ["ACTIVE"]).
    Example: developers' share of units due in the next two years ->
    group_by="developer", delivery_statuses=["scheduled_in_horizon"], horizon_months=24.
    """
    result = await delivery.get_delivery_summary(
        location=location,
        project_statuses=tuple(project_statuses or ["ACTIVE"]),
        delivery_statuses=tuple(delivery_statuses or delivery.ALL_DELIVERY_STATUSES),
        group_by=group_by,
        horizon_months=horizon_months,
        reference_date=reference_date,
    )
    return result.model_dump(mode="json")


@safe_tool
async def research_listing_shortlist(
    ctx: RunContext[None], request: "ListingResearchRequest"
) -> dict[str, Any]:
    """Read a bounded contact-free listing shortlist with exact total and age at capture.

    Use min_age_days=91 for more than ninety days old, max_age_days=90 for newer listings.
    Filters apply before paging. Rental budgets are annual AED. Call comparable_evidence
    for registered rents/sales supporting a listing yield or indicative appraisal.
    """
    return await listing_assistant.research_listings(request)


@safe_tool
async def comparable_evidence(
    ctx: RunContext[None], request: "ComparableRequest"
) -> dict[str, Any]:
    """Read registered sale/rental comparables and deterministic indicative appraisal/yield.

    Require community, bedrooms, property type and a period no longer than two years.
    Match a named building and subject size when available. Rentals use annual amounts;
    request new and renewed contracts separately for comparison. Provide asking_price_aed
    with rentals to compute gross yield, or with sales to compute asking-versus-median.
    Results include exact matching population, recent bounded sample, IQR, coverage,
    applied filters and confidence. No supported appraisal for fewer than five matches.
    """
    return await analytics_assistant.get_comparable_evidence(request)


@safe_tool
async def compare_stored_projects(
    ctx: RunContext[None],
    names: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=160)]], Field(min_length=1, max_length=3)
    ],
) -> dict[str, Any]:
    """Compare up to three exact catalogue projects: prices, sizes, payment plans, progress and delivery.

    Ambiguous names return candidates for clarification. Missing fields remain unknown.
    Never download the catalogue's documents; no files or assets are returned.
    """
    return await project_assistant.compare_stored_projects(names)
