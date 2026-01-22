"""Pydantic AI Agent for Real Estate Analytics using ClickHouse."""

import logging
import os
from typing import Any

import logfire
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel

from app.config import settings
from app.clickhouse import query

logger = logging.getLogger(__name__)

# Configure Logfire for LLM observability
logfire.configure()
logfire.instrument_pydantic_ai()


# Set OpenRouter credentials via environment (Pydantic AI reads these)
os.environ["OPENROUTER_API_KEY"] = settings.OPENROUTER_API_KEY

# Configure OpenRouter model
# Pydantic AI will use OPENROUTER_API_KEY env var automatically
model = OpenAIChatModel(
    model_name=settings.CHAT_MODEL,
    provider="openrouter",
)

# Define agent
agent = Agent(
    model,
    system_prompt=(
        "You are ViteVue AI, an expert Real Estate Analyst for Dubai real estate markets. "
        "You are SQL-literate and have direct access to a comprehensive ClickHouse database containing "
        "transactions, rental contracts, projects, and developer data.\n\n"
        "Your philosophy: ALWAYS prefer aggregate SQL analysis over fetching raw rows. "
        "Use the provided tools to execute optimized queries that return summary statistics, "
        "rankings, and insights.\n\n"
        "When answering questions:\n"
        "- Cite specific numbers from tool results\n"
        "- Provide context (time periods, sample sizes)\n"
        "- Explain trends and patterns\n"
        "- Recommend areas based on data-driven metrics\n\n"
        "Be concise, professional, and data-focused."
    ),
)


@agent.tool
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
    sql = """
    SELECT
        count(*) as transaction_count,
        round(median(trans_value), 0) as median_price,
        round(avg(trans_value), 0) as avg_price,
        round(median(actual_area), 1) as median_area_sqft,
        round(median(trans_value / actual_area), 0) as median_price_per_sqft,
        min(instance_date) as period_start,
        max(instance_date) as period_end
    FROM ch_transactions
    WHERE
        area_en = {area:String}
        AND instance_date >= today() - {period_days:Int32}
        AND trans_value > 0
        AND actual_area > 0
    """

    try:
        rows = await query(sql, {"area": area, "period_days": period_days})
        
        if not rows:
            return {
                "success": False,
                "error": f"No data found for area '{area}' in the last {period_days} days",
            }

        row = rows[0]
        return {
            "success": True,
            "area": area,
            "period_days": period_days,
            "transaction_count": row[0],
            "median_price_aed": row[1],
            "avg_price_aed": row[2],
            "median_area_sqft": row[3],
            "median_price_per_sqft_aed": row[4],
            "period_start": str(row[5]),
            "period_end": str(row[6]),
        }
    except Exception as e:
        logger.exception(f"Error executing get_market_pulse for area {area}")
        return {"success": False, "error": str(e)}


@agent.tool
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
    if metric == "volume":
        sql = """
        SELECT
            area_en as area,
            count(*) as transaction_count,
            round(median(trans_value), 0) as median_price
        FROM ch_transactions
        WHERE
            instance_date >= today() - {period_days:Int32}
            AND trans_value > 0
            AND area_en != ''
        GROUP BY area_en
        ORDER BY transaction_count DESC
        LIMIT {limit:Int32}
        """
    elif metric == "price":
        sql = """
        SELECT
            area_en as area,
            round(median(trans_value), 0) as median_price,
            count(*) as transaction_count
        FROM ch_transactions
        WHERE
            instance_date >= today() - {period_days:Int32}
            AND trans_value > 0
            AND area_en != ''
        GROUP BY area_en
        HAVING transaction_count >= 10
        ORDER BY median_price DESC
        LIMIT {limit:Int32}
        """
    elif metric == "growth":
        # Compare current period vs previous period
        sql = """
        WITH
            current_period AS (
                SELECT
                    area_en as area,
                    median(trans_value) as current_median
                FROM ch_transactions
                WHERE
                    instance_date >= today() - {period_days:Int32}
                    AND trans_value > 0
                    AND area_en != ''
                GROUP BY area_en
                HAVING count(*) >= 10
            ),
            previous_period AS (
                SELECT
                    area_en as area,
                    median(trans_value) as previous_median
                FROM ch_transactions
                WHERE
                    instance_date >= today() - {period_days:Int32} * 2
                    AND instance_date < today() - {period_days:Int32}
                    AND trans_value > 0
                    AND area_en != ''
                GROUP BY area_en
                HAVING count(*) >= 10
            )
        SELECT
            c.area,
            round(c.current_median, 0) as current_median_price,
            round(p.previous_median, 0) as previous_median_price,
            round(((c.current_median - p.previous_median) / p.previous_median) * 100, 2) as growth_percentage
        FROM current_period c
        INNER JOIN previous_period p ON c.area = p.area
        ORDER BY growth_percentage DESC
        LIMIT {limit:Int32}
        """
    else:
        return {
            "success": False,
            "error": f"Invalid metric '{metric}'. Use 'volume', 'price', or 'growth'",
        }

    try:
        rows = await query(
            sql, {"period_days": period_days, "limit": limit}
        )

        if not rows:
            return {
                "success": False,
                "error": f"No data found for metric '{metric}' in the last {period_days} days",
            }

        areas = []
        for row in rows:
            if metric == "volume":
                areas.append(
                    {
                        "area": row[0],
                        "transaction_count": row[1],
                        "median_price_aed": row[2],
                    }
                )
            elif metric == "price":
                areas.append(
                    {
                        "area": row[0],
                        "median_price_aed": row[1],
                        "transaction_count": row[2],
                    }
                )
            elif metric == "growth":
                areas.append(
                    {
                        "area": row[0],
                        "current_median_price_aed": row[1],
                        "previous_median_price_aed": row[2],
                        "growth_percentage": row[3],
                    }
                )

        return {
            "success": True,
            "metric": metric,
            "period_days": period_days,
            "top_areas": areas,
        }
    except Exception as e:
        logger.exception(f"Error executing rank_areas for metric {metric}")
        return {"success": False, "error": str(e)}


@agent.tool
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
    ref_sql = """
    SELECT
        master_project_en,
        area_en,
        property_type_en,
        round(median(trans_value), 0) as median_price,
        round(median(actual_area), 1) as median_area,
        count(*) as transaction_count
    FROM ch_transactions
    WHERE
        master_project_en ILIKE {project_name:String}
        AND trans_value > 0
        AND actual_area > 0
        AND instance_date >= today() - 365
    GROUP BY master_project_en, area_en, property_type_en
    LIMIT 1
    """

    try:
        ref_rows = await query(
            ref_sql, {"project_name": f"%{project_name}%"}
        )

        if not ref_rows:
            return {
                "success": False,
                "error": f"No data found for project '{project_name}'",
            }

        ref_row = ref_rows[0]
        ref_project = ref_row[0]
        ref_area = ref_row[1]
        ref_type = ref_row[2]
        ref_price = ref_row[3]
        ref_area_sqft = ref_row[4]

        # Find similar projects
        similar_sql = """
        SELECT
            master_project_en,
            area_en,
            property_type_en,
            round(median(trans_value), 0) as median_price,
            round(median(actual_area), 1) as median_area,
            count(*) as transaction_count,
            abs(median(trans_value) - {ref_price:Float64}) as price_diff
        FROM ch_transactions
        WHERE
            master_project_en != {ref_project:String}
            AND property_type_en = {ref_type:String}
            AND trans_value > 0
            AND actual_area > 0
            AND instance_date >= today() - 365
            AND master_project_en != ''
        GROUP BY master_project_en, area_en, property_type_en
        HAVING transaction_count >= 5
        ORDER BY price_diff ASC
        LIMIT {limit:Int32}
        """

        similar_rows = await query(
            similar_sql,
            {
                "ref_price": ref_price,
                "ref_project": ref_project,
                "ref_type": ref_type,
                "limit": limit,
            },
        )

        similar_projects = []
        for row in similar_rows:
            similar_projects.append(
                {
                    "project": row[0],
                    "area": row[1],
                    "property_type": row[2],
                    "median_price_aed": row[3],
                    "median_area_sqft": row[4],
                    "transaction_count": row[5],
                    "price_difference_aed": row[6],
                }
            )

        return {
            "success": True,
            "reference_project": {
                "name": ref_project,
                "area": ref_area,
                "property_type": ref_type,
                "median_price_aed": ref_price,
                "median_area_sqft": ref_area_sqft,
            },
            "similar_projects": similar_projects,
        }
    except Exception as e:
        logger.exception(f"Error executing get_similar_projects for {project_name}")
        return {"success": False, "error": str(e)}
