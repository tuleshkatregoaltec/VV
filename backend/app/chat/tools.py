from typing import Any

from pydantic_ai import RunContext

from app.analytics import service as analytics_service
from app.project import service as project_service


async def get_market_pulse(
    ctx: RunContext[None], area: str, period_days: int = 90
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


async def rank_areas(
    ctx: RunContext[None],
    metric: str = "volume",
    limit: int = 5,
    period_days: int = 90,
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


async def get_similar_projects(
    ctx: RunContext[None], project_name: str, limit: int = 5
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
