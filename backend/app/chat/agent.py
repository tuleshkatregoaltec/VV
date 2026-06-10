import logging
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints
from pydantic_ai import Agent, RunContext

from app.clickhouse import query
from app.core.normalization import area_search_text
from app.core.openrouter import create_openrouter_model

logger = logging.getLogger(__name__)

model = create_openrouter_model()
AreaInput = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
AreaComparisonInput = Annotated[list[AreaInput], Field(min_length=2, max_length=5)]


def _float_or_none(value: Any) -> float | None:
    return float(value) if value is not None else None


def _int_value(value: Any) -> int:
    return int(value or 0)


def _string_list(value: Any, *, limit: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item][:limit]


def _computed_area_yield_pct(row: dict[str, Any]) -> float | None:
    median_price = _float_or_none(row.get("median_sale_price"))
    median_rent = _float_or_none(row.get("median_annual_rent"))
    if not median_price or not median_rent:
        return None
    return round(median_rent / median_price * 100, 2)


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value or minimum)))


async def _resolve_area_name(area: str) -> str:
    search_text = area_search_text(area)
    if not search_text:
        return area

    rows = await query(
        """
        SELECT area_name_en
        FROM ch_area_fact
        WHERE area_name_en != ''
          AND (
            lower(area_name_en) = lower({area:String})
            OR lower(area_name_en) = lower({search_text:String})
            OR positionCaseInsensitive(area_name_en, {search_text:String}) > 0
            OR arrayExists(
                project -> positionCaseInsensitive(project, {search_text:String}) > 0,
                top_master_projects
            )
          )
        ORDER BY
            (lower(area_name_en) = lower({area:String})) DESC,
            (lower(area_name_en) = lower({search_text:String})) DESC,
            sales_transaction_count_12m DESC,
            pipeline_units DESC,
            area_name_en ASC
        LIMIT 1
        """,
        {"area": area, "search_text": search_text},
    )
    return str(rows[0]["area_name_en"]) if rows else search_text


def _project_type_for_rent(property_type: str) -> str | None:
    normalized = property_type.lower().strip()
    if not normalized:
        return "Flat"
    if normalized in {"unit", "apartment", "apartments", "flat", "flats"}:
        return "Flat"
    if normalized in {"villa", "villas"}:
        return "Villa"
    if normalized in {"office", "shop", "warehouse", "hotel"}:
        return normalized.title()
    if normalized in {"all", "any"}:
        return None
    return property_type.strip()


async def _developer_match_names(developer: str) -> list[str]:
    search_text = developer.strip()
    if not search_text:
        return []

    rows = await query(
        """
        SELECT developer_name_ar, developer_name_en
        FROM ch_developers
        WHERE positionCaseInsensitive(developer_name_en, {developer:String}) > 0
           OR positionCaseInsensitive(developer_name_ar, {developer:String}) > 0
        ORDER BY
            (lower(developer_name_en) = lower({developer:String})) DESC,
            developer_name_en ASC
        LIMIT 12
        """,
        {"developer": search_text},
    )
    names = [search_text]
    for row in rows:
        for key in ("developer_name_ar", "developer_name_en"):
            value = str(row.get(key) or "").strip()
            if value and value not in names:
                names.append(value)
    return names


async def _developer_where_clause(
    developer: str, params: dict[str, Any], prefix: str = "developer_match"
) -> str:
    names = await _developer_match_names(developer)
    clauses = []
    for index, name in enumerate(names):
        key = f"{prefix}_{index}"
        params[key] = name
        clauses.append(f"positionCaseInsensitive(developer_name, {{{key}:String}}) > 0")
    return "(" + " OR ".join(clauses or ["1 = 0"]) + ")"


# Define agent
agent = Agent(
    model,
    system_prompt=(
        "You are Vitevue AI, an expert Real Estate Analyst specializing in Dubai real estate markets. "
        "You have access to predefined database queries that can retrieve comprehensive real estate data.\n\n"
        "## Available Data and Tools\n\n"
        "You have access to predefined, parameterized database queries that can retrieve information from these data categories:\n"
        "- Transaction records (sales data, prices, locations, dates)\n"
        "- Rental contracts (rental prices, terms, locations)\n"
        "- Development projects (new construction, developers, timelines)\n"
        "- Developer information (company profiles, track records)\n\n"
        "Important: You work with a set of predefined queries with specific parameters. You select the appropriate queries "
        "and provide the necessary parameters (such as date ranges, location filters, price ranges, etc.) based on the user's question. "
        "You cannot construct arbitrary SQL queries, but you have access to a comprehensive set of query templates designed to answer real estate questions.\n\n"
        "## Core Principles\n\n"
        "**Scope Restriction**: You are specifically designed to answer questions about the Dubai real estate market. "
        "If a user asks about topics outside of this market (questions about other markets, general non-real-estate topics, or unrelated subjects), "
        "politely decline and redirect them to ask about real estate in Dubai.\n\n"
        "**No Investment Advisory**: Do not provide personalised investment, financial, or legal advice. "
        "Do not tell a user to buy, sell, invest in, or avoid a specific property, developer, or area. "
        "You may compare historical data, explain observed patterns, and outline data-backed considerations. "
        "Label trend analysis as historical unless the user explicitly asks for a scenario or assumption-based projection.\n\n"
        "**Data Analysis Philosophy**: Always prefer aggregate analysis over fetching raw data records. When you use your database tools, "
        "select queries that return summary statistics, rankings, trends, and calculated metrics rather than individual records. "
        "Exception: when the user explicitly asks to show matching inventory, listings, or comparable records, use a display tool so the app can render the results as an inline rich message.\n\n"
        "**Query Strategy for Complex Questions**: When questions require multiple data points, you may need to chain together multiple query calls. "
        "Use the results from one query to inform the parameters of the next. For example, you might first query to identify the top performing neighborhoods, "
        "then query again for detailed metrics on those specific neighborhoods.\n\n"
        "**Tool Usage in Responses**: Focus on what insights the data reveals, not on the mechanics of how you retrieved it. "
        "In your final response to the user, avoid explicitly naming tool functions, describing technical query details, or explaining which queries you selected. "
        "Simply present the insights as if you have natural expertise in this market.\n\n"
        "**Rich Chat UI**: When a user asks to show, list, open, chart, graph, or compare data, call a display tool in addition to answering briefly. "
        'Use `show_listings` for live rental/sales inventory. For generic listing/inventory/property requests, use rental listings (`mode="rent"`) unless the user explicitly says sale, buy, purchase, for-sale, resale, or off-plan. '
        "Use `show_market_trend` for simple price trend analytics. Use `show_chart` for custom charts, rankings, breakdowns, distributions, and dashboard-style widgets where you choose the dataset, metric, dimension, chart type, area, comparison areas, time window, and limit. "
        'If the user asks for bottom, lowest, cheapest, least, or most affordable chart results, call `show_chart` with `sort_direction="asc"`; use `sort_direction="desc"` for top, highest, most, or largest results. '
        "If the user asks for sqft, square foot, or price per foot, use a `_sqft` metric instead of a `_sqm` metric. "
        'For citywide rental-yield area rankings, use `show_chart` with `dataset="areas"`, `metric="gross_yield_pct"`, `group_by="area"`, and `sort_direction="desc"`; do not use project-level yield averages for area yield rankings. '
        'For generic rental-yield rankings, default to apartment/flat yield; pass `property_type="all"` only if the user explicitly asks for all property types, and pass `property_type="Villa"` only for villa yield. '
        "When the user specifies a time horizon such as 90 days, 12 months, 3 years, YTD, or since a given year, convert it to the closest day count and pass it as `days` or `period_days`; use the 365-day default only when the user does not specify a period. "
        "The app will render these as typed rich message cards inline in the conversation. "
        "When you call a display tool that opens a rich card or artifact, keep the written response very short: one to three sentences, "
        "no long bullet list, and do not restate all rows or chart values that are visible in the card. "
        "Summarize the key takeaway and point the user to the card for the detailed records or chart. "
        "Conversation history may include a rendered-card context note; use that note as the source of truth for follow-up references like "
        '"that top area", "the bottom two", or "those listings".\n\n'
        "Important: `show_chart` returns a rendered card, not the underlying row values. After calling `show_chart`, do not invent or separately enumerate chart rankings or values in your text unless you also used a data tool that returns the same rows from the same metric/source. "
        "When in doubt, keep the text to a one-sentence description of what the card shows.\n\n"
        "When using `show_listings`, do not claim listings were definitely found, and do not invent counts, prices, or areas. "
        "The card is the source of truth for whether exact inventory matched the filters. "
        "After opening a listings card, keep the text to a neutral confirmation such as: "
        '"I opened the listings card for that area; the card shows the exact matches and count." '
        "If the rendered-card context in conversation history says a listings card had 0 exact matches, say that directly instead of describing available listings.\n\n"
        "**Tool Selection**: Use `get_area_snapshot` for one-neighborhood market context, `compare_areas` for side-by-side neighborhood decisions, "
        "`get_rental_market_pulse` for achieved rents and rental contract evidence, `search_development_projects` for finding projects by area/developer/status, "
        "and `get_developer_pipeline` for developer-specific pipeline questions.\n\n"
        "**Project Pipeline Questions**: For questions about upcoming projects, hot development areas, delivery pipeline, under-construction supply, or launch-heavy districts, "
        "use `rank_upcoming_project_areas` instead of transaction-only area rankings.\n\n"
        "## Formatting Rules\n\n"
        "Use only these markdown elements — nothing else:\n"
        "- **Bold** for key metrics and numbers\n"
        "- *Italic* for area names or secondary emphasis\n"
        "- Bullet lists and numbered lists for multiple data points or rankings\n"
        "- Blockquotes for notable highlights or important caveats\n\n"
        "Do NOT use headers (#, ##, ###), tables, horizontal rules, or any other markdown. "
        "Keep responses flowing and conversational.\n\n"
        "## Response Format\n\n"
        "Your response should be concise, professional, and data-focused. Structure it to include:\n\n"
        '- **Specific numbers** from your analysis with clear units (e.g., "Average sale price of AED 1.2M", "15% year-over-year increase")\n'
        '- **Context** for those numbers (e.g., "based on 347 transactions in Q1 2024", "across Dubai Marina")\n'
        '- **Trends and patterns** with supporting data (e.g., "Prices have been rising steadily since...", "Premium developments are concentrated in...")\n'
        "- **Data-backed considerations** when appropriate, without advising a purchase/sale decision.\n\n"
        "Example response structure:\n\n"
        "Based on analysis of [X] transactions over [time period], the average price in [area] is [number] [currency] per square foot. "
        "This represents a [percentage] change compared to [comparison period].\n\n"
        "Key trends include [trend description with supporting numbers]. [Area A] shows particularly strong performance with [specific metric], "
        "while [Area B] demonstrates [different pattern] with [supporting data].\n\n"
        "For investors examining [criteria mentioned in query], the data points to [areas/property types] as candidates for further review because [data-driven reasoning with specific numbers]."
    ),
)


@agent.tool_plain
async def show_listings(
    mode: str = "rent",
    area: str = "",
    property_type: str = "",
    bedrooms: str = "",
    bedrooms_min: int | None = None,
    bedrooms_max: int | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    price_period: str = "",
    price_basis: str = "raw",
    limit: int = 12,
) -> str:
    """Render a listing results card inline in the chat.

    Use this when the user asks to show, list, find, or browse matching sale/rental listings.
    Args:
        mode: "rent" or "sale". Use "rent" for generic listing/inventory/property requests unless
            the user explicitly asks for sale, buying, purchase, for-sale, resale, or off-plan.
        area: Dubai area/community name, e.g. "Business Bay".
        property_type: Listing type, e.g. "Apartment", "Villa", or leave blank.
        bedrooms: Exact bedroom value if a single value is requested, e.g. "1", "2", or "studio".
        bedrooms_min: Minimum bedrooms for a range request.
        bedrooms_max: Maximum bedrooms for a range request.
        price_min: Minimum price in AED.
        price_max: Maximum price in AED.
        price_period: Optional raw listing period such as "monthly" or "yearly"; usually leave blank.
        price_basis: Use "monthly" when the user asks for monthly rent even if listings are stored yearly.
        limit: Number of listings to show, up to 24.
    """
    subject = "rental listings" if mode == "rent" else "sales listings"
    location = f" in {area}" if area else ""
    return (
        f"Opening matching {subject}{location}. "
        "Do not describe availability, counts, prices, or example listings in your text; "
        "the inline card is the source of truth for exact matches."
    )


@agent.tool_plain
async def show_market_trend(
    area: str = "",
    property_usage: str = "Residential",
    property_type: str = "",
    days: int = 365,
) -> str:
    """Render a market trend chart inline in the chat.

    Use this when the user asks for analytics, charts, graphs, price trends, or market movement.
    Args:
        area: Dubai area/community name, e.g. "Business Bay". Leave blank for whole market.
        property_usage: "Residential" or "Commercial".
        property_type: Optional transaction property type, e.g. "Unit", "Villa", "Building", or "Land".
        days: Lookback window in days.
    """
    subject = area or "the Dubai market"
    return f"Showing price trend analytics for {subject}."


@agent.tool_plain
async def show_chart(
    dataset: str = "sales",
    metric: str = "transaction_count",
    group_by: str = "area",
    chart_type: str = "horizontal_bar",
    area: str = "",
    areas: AreaComparisonInput | None = None,
    sort_direction: Literal["desc", "asc"] = "desc",
    property_usage: str = "Residential",
    property_type: str = "",
    days: int = 365,
    limit: int = 8,
) -> str:
    """Render a configurable chart inline in the chat.

    Use this when the user asks for a custom graph, chart, dashboard widget,
    ranking, breakdown, distribution, or slice-and-dice style analysis.
    Args:
        dataset: "sales", "rentals", "areas", or "projects". Use "areas" for citywide
            area yield rankings.
        metric: Sales metrics: transaction_count, total_volume, avg_price, median_price,
            avg_price_sqm, median_price_sqm, avg_price_sqft, median_price_sqft. Rental
            metrics: contract_count, total_annual_value, avg_rent, median_rent,
            median_rent_sqm, median_rent_sqft. Area metrics: gross_yield_pct. Project
            metrics: project_count, active_projects, completed_projects, pipeline_units,
            units_delivering_next_12_months, sales_transaction_count_12m,
            rental_contract_count_12m, total_sales_volume_12m, gross_yield_pct,
            avg_completion_pct.
        group_by: Sales: time, area, property_type, bedrooms, project, master_project,
            transaction_type. Rentals: time, area, property_type, project, master_project,
            tenant_type. Projects: area, developer, completion_status, pipeline_status,
            master_project.
        chart_type: "line", "bar", "horizontal_bar", or "doughnut". Use line for time.
        area: Optional Dubai area/community filter, e.g. "JVC".
        areas: Optional array of 2-5 Dubai area/community names for comparisons, e.g.
            ["Dubai Marina", "JVC", "Business Bay"]. Use group_by="time" for trend
            comparisons or group_by="area" for side-by-side area comparisons.
        sort_direction: "desc" for top/highest/largest charts, "asc" for bottom/lowest/cheapest charts.
        property_usage: Optional usage filter, usually "Residential" or "Commercial".
        property_type: Optional sales/rental property type filter, e.g. "Unit", "Villa", "Flat".
            Area yield charts default to "Flat" unless the user explicitly asks for another type.
        days: Lookback window for sales/rental charts. Default is 365 only when no user period is specified.
        limit: Number of ranked categories to show.
    """
    return "Building a custom chart from the selected Dubai real estate data."


@agent.tool
async def get_area_snapshot(ctx: RunContext[None], area: str) -> dict[str, Any]:
    """Get a compact area-level market and project-pipeline snapshot.

    Use this for questions like "tell me about JVC", "what is happening in Business Bay",
    or when the user needs one neighborhood summarized before deciding on a next drilldown.

    Args:
        ctx: Runtime context (unused)
        area: Dubai area/community name, e.g. "JVC", "Dubai Marina", or "Business Bay".

    Returns:
        Area market, rental, yield, developer, and pipeline metrics.
    """
    resolved_area = await _resolve_area_name(area)
    try:
        rows = await query(
            """
            SELECT
                area_name_en,
                active_projects,
                completed_projects,
                overdue_projects,
                pipeline_units,
                units_delivering_next_12_months,
                active_developers,
                round(avg_completion_pct, 1) AS avg_completion_pct,
                round(avg_delivery_confidence, 2) AS avg_delivery_confidence,
                sales_transaction_count_12m,
                rental_contract_count_12m,
                round(total_sales_volume_12m, 0) AS total_sales_volume_12m,
                median_sale_price,
                median_annual_rent,
                avg_sale_price_sqm_12m,
                avg_rent_price_sqm_12m,
                gross_yield_pct,
                top_developers,
                top_master_projects
            FROM ch_area_fact
            WHERE area_name_en = {area:String}
            LIMIT 1
            """,
            {"area": resolved_area},
        )
        if not rows:
            return {"success": False, "error": f"No area data found for '{area}'"}

        project_rows = await query(
            """
            SELECT
                project_name_en,
                developer_name,
                master_project_en,
                completion_status,
                pipeline_status,
                no_of_units,
                round(percent_completed, 1) AS percent_completed,
                round(estimated_delivery_confidence, 2) AS delivery_confidence,
                sales_transaction_count_12m,
                round(total_sales_volume_12m, 0) AS total_sales_volume_12m
            FROM ch_project_fact
            WHERE area_name_en = {area:String}
            ORDER BY total_sales_volume_12m DESC, no_of_units DESC, project_name_en ASC
            LIMIT 8
            """,
            {"area": resolved_area},
        )

        row = rows[0]
        return {
            "success": True,
            "requested_area": area,
            "area": row["area_name_en"],
            "pipeline": {
                "active_projects": _int_value(row["active_projects"]),
                "completed_projects": _int_value(row["completed_projects"]),
                "overdue_projects": _int_value(row["overdue_projects"]),
                "pipeline_units": _int_value(row["pipeline_units"]),
                "units_delivering_next_12_months": _int_value(
                    row["units_delivering_next_12_months"]
                ),
                "active_developers": _int_value(row["active_developers"]),
                "avg_completion_pct": _float_or_none(row["avg_completion_pct"]),
                "avg_delivery_confidence": _float_or_none(row["avg_delivery_confidence"]),
            },
            "market": {
                "sales_transaction_count_12m": _int_value(row["sales_transaction_count_12m"]),
                "rental_contract_count_12m": _int_value(row["rental_contract_count_12m"]),
                "total_sales_volume_12m": _float_or_none(row["total_sales_volume_12m"]),
                "median_sale_price": _float_or_none(row["median_sale_price"]),
                "median_annual_rent": _float_or_none(row["median_annual_rent"]),
                "avg_sale_price_sqm_12m": _float_or_none(row["avg_sale_price_sqm_12m"]),
                "avg_rent_price_sqm_12m": _float_or_none(row["avg_rent_price_sqm_12m"]),
                "gross_yield_pct": _computed_area_yield_pct(row),
            },
            "top_developers": _string_list(row.get("top_developers")),
            "top_master_projects": _string_list(row.get("top_master_projects")),
            "notable_projects": [
                {
                    "project": project["project_name_en"],
                    "developer": project.get("developer_name") or None,
                    "master_project": project.get("master_project_en") or None,
                    "completion_status": project.get("completion_status") or None,
                    "pipeline_status": project.get("pipeline_status") or None,
                    "units": _int_value(project["no_of_units"]),
                    "percent_completed": _float_or_none(project["percent_completed"]),
                    "delivery_confidence": _float_or_none(project["delivery_confidence"]),
                    "sales_transaction_count_12m": _int_value(
                        project["sales_transaction_count_12m"]
                    ),
                    "total_sales_volume_12m": _float_or_none(project["total_sales_volume_12m"]),
                }
                for project in project_rows
            ],
        }
    except Exception as e:
        logger.exception("Error executing get_area_snapshot for %s", area)
        return {"success": False, "error": str(e)}


@agent.tool
async def compare_areas(
    ctx: RunContext[None],
    area_1: str,
    area_2: str,
    area_3: str = "",
    area_4: str = "",
) -> dict[str, Any]:
    """Compare two to four Dubai areas using sales, rent, yield, and project-pipeline metrics.

    Use this for side-by-side decisions like "Business Bay vs JVC", "compare Dubai Marina
    and Downtown", or "which of these areas has better pipeline and yield".

    Args:
        ctx: Runtime context (unused)
        area_1: First area/community.
        area_2: Second area/community.
        area_3: Optional third area/community.
        area_4: Optional fourth area/community.

    Returns:
        Comparable area rows with market and pipeline metrics.
    """
    requested_areas = [area for area in [area_1, area_2, area_3, area_4] if area.strip()]
    if len(requested_areas) < 2:
        return {"success": False, "error": "Provide at least two areas to compare."}

    comparisons: list[dict[str, Any]] = []
    try:
        for requested_area in requested_areas[:4]:
            resolved_area = await _resolve_area_name(requested_area)
            rows = await query(
                """
                SELECT
                    area_name_en,
                    active_projects,
                    pipeline_units,
                    units_delivering_next_12_months,
                    active_developers,
                    sales_transaction_count_12m,
                    rental_contract_count_12m,
                    round(total_sales_volume_12m, 0) AS total_sales_volume_12m,
                    median_sale_price,
                    median_annual_rent,
                    avg_sale_price_sqm_12m,
                    avg_rent_price_sqm_12m,
                    gross_yield_pct,
                    top_master_projects
                FROM ch_area_fact
                WHERE area_name_en = {area:String}
                LIMIT 1
                """,
                {"area": resolved_area},
            )
            if not rows:
                comparisons.append(
                    {
                        "requested_area": requested_area,
                        "area": resolved_area,
                        "success": False,
                        "error": "No area data found",
                    }
                )
                continue

            row = rows[0]
            comparisons.append(
                {
                    "requested_area": requested_area,
                    "area": row["area_name_en"],
                    "success": True,
                    "active_projects": _int_value(row["active_projects"]),
                    "pipeline_units": _int_value(row["pipeline_units"]),
                    "units_delivering_next_12_months": _int_value(
                        row["units_delivering_next_12_months"]
                    ),
                    "active_developers": _int_value(row["active_developers"]),
                    "sales_transaction_count_12m": _int_value(row["sales_transaction_count_12m"]),
                    "rental_contract_count_12m": _int_value(row["rental_contract_count_12m"]),
                    "total_sales_volume_12m": _float_or_none(row["total_sales_volume_12m"]),
                    "median_sale_price": _float_or_none(row["median_sale_price"]),
                    "median_annual_rent": _float_or_none(row["median_annual_rent"]),
                    "avg_sale_price_sqm_12m": _float_or_none(row["avg_sale_price_sqm_12m"]),
                    "avg_rent_price_sqm_12m": _float_or_none(row["avg_rent_price_sqm_12m"]),
                    "gross_yield_pct": _computed_area_yield_pct(row),
                    "top_master_projects": _string_list(row.get("top_master_projects")),
                }
            )

        return {"success": True, "areas": comparisons}
    except Exception as e:
        logger.exception("Error executing compare_areas")
        return {"success": False, "error": str(e)}


@agent.tool
async def get_rental_market_pulse(
    ctx: RunContext[None],
    area: str,
    property_usage: str = "Residential",
    property_type: str = "Flat",
    period_days: int = 365,
) -> dict[str, Any]:
    """Get achieved rental contract metrics for an area.

    Use this for rent, rental yield, leasing, or achieved annual rent questions.
    Defaults to residential flats/apartments; pass property_type="Villa" for villa rents
    or property_type="all" for the broader rental market.

    Args:
        ctx: Runtime context (unused)
        area: Dubai area/community name.
        property_usage: Rental usage, usually "Residential" or "Commercial".
        property_type: Ejari property type such as "Flat", "Villa", "Office", or "all".
        period_days: Lookback period ending at the latest non-future contract date.

    Returns:
        Rental contract count, annual rent, rent per sqm, area, and property-type breakdown.
    """
    resolved_area = await _resolve_area_name(area)
    resolved_property_type = _project_type_for_rent(property_type)
    safe_period_days = _clamp(period_days, 30, 3650)

    where = [
        "area_name_en = {area:String}",
        "property_usage_en = {property_usage:String}",
        "annual_amount > 0",
        "actual_area > 0",
        "contract_start_date <= today()",
    ]
    params: dict[str, Any] = {
        "area": resolved_area,
        "property_usage": property_usage,
        "period_days": safe_period_days,
    }
    if resolved_property_type:
        where.append("ejari_property_type_en = {property_type:String}")
        params["property_type"] = resolved_property_type

    where_sql = " AND ".join(where)
    try:
        rows = await query(
            f"""
            WITH (
                SELECT max(contract_start_date)
                FROM ch_rent_contracts
                WHERE {where_sql}
            ) AS max_date
            SELECT
                count() AS contract_count,
                round(median(annual_amount), 0) AS median_annual_rent,
                round(avg(annual_amount), 0) AS avg_annual_rent,
                round(median(actual_area), 1) AS median_area_sqm,
                round(median(annual_amount / nullIf(actual_area, 0)), 0) AS median_rent_per_sqm,
                min(contract_start_date) AS period_start,
                max(contract_start_date) AS period_end
            FROM ch_rent_contracts
            WHERE {where_sql}
              AND contract_start_date >= max_date - {{period_days:Int32}}
              AND contract_start_date <= max_date
            """,
            params,
        )
        row = rows[0] if rows else {}
        if _int_value(row.get("contract_count")) == 0:
            return {
                "success": False,
                "error": f"No rental contracts found for '{area}' in the last {safe_period_days} days.",
            }

        breakdown_rows = await query(
            f"""
            WITH (
                SELECT max(contract_start_date)
                FROM ch_rent_contracts
                WHERE {where_sql}
            ) AS max_date
            SELECT
                ejari_property_type_en AS property_type,
                count() AS contract_count,
                round(median(annual_amount), 0) AS median_annual_rent,
                round(median(annual_amount / nullIf(actual_area, 0)), 0) AS median_rent_per_sqm
            FROM ch_rent_contracts
            WHERE area_name_en = {{area:String}}
              AND property_usage_en = {{property_usage:String}}
              AND annual_amount > 0
              AND actual_area > 0
              AND contract_start_date <= today()
              AND contract_start_date >= max_date - {{period_days:Int32}}
              AND contract_start_date <= max_date
            GROUP BY ejari_property_type_en
            ORDER BY contract_count DESC
            LIMIT 6
            """,
            params,
        )

        return {
            "success": True,
            "requested_area": area,
            "area": resolved_area,
            "property_usage": property_usage,
            "property_type": resolved_property_type or "all",
            "period_days": safe_period_days,
            "contract_count": _int_value(row["contract_count"]),
            "median_annual_rent_aed": _float_or_none(row["median_annual_rent"]),
            "avg_annual_rent_aed": _float_or_none(row["avg_annual_rent"]),
            "median_area_sqm": _float_or_none(row["median_area_sqm"]),
            "median_rent_per_sqm_aed": _float_or_none(row["median_rent_per_sqm"]),
            "period_start": str(row["period_start"]),
            "period_end": str(row["period_end"]),
            "property_type_breakdown": [
                {
                    "property_type": item["property_type"] or "Unknown",
                    "contract_count": _int_value(item["contract_count"]),
                    "median_annual_rent_aed": _float_or_none(item["median_annual_rent"]),
                    "median_rent_per_sqm_aed": _float_or_none(item["median_rent_per_sqm"]),
                }
                for item in breakdown_rows
            ],
        }
    except Exception as e:
        logger.exception("Error executing get_rental_market_pulse for %s", area)
        return {"success": False, "error": str(e)}


@agent.tool
async def get_market_pulse(
    ctx: RunContext[None], area: str, period_days: int = 365
) -> dict[str, Any]:
    """Get vital market statistics for a specific area.

    Returns aggregate metrics including median price, average yield, transaction volume,
    and price trends for the specified area and time period.

    Args:
        ctx: Runtime context (unused)
        area: Area name (e.g., "Dubai Marina", "Downtown Dubai")
        period_days: Analysis period in days. Default is 365 when no user period is specified.

    Returns:
        Dictionary with price, yield, volume, and trend data
    """
    resolved_area = await _resolve_area_name(area)
    safe_period_days = _clamp(period_days, 30, 3650)
    sql = """
    WITH (
        SELECT max(instance_date)
        FROM ch_transactions
        WHERE trans_group_en = 'Sales' AND actual_worth > 0
    ) AS max_date
    SELECT
        count(*) as transaction_count,
        round(median(actual_worth), 0) as median_price,
        round(avg(actual_worth), 0) as avg_price,
        round(median(procedure_area), 1) as median_area_sqm,
        round(median(meter_sale_price), 0) as median_price_per_sqm,
        min(instance_date) as period_start,
        max(instance_date) as period_end
    FROM ch_transactions
    WHERE
        area_name_en = {area:String}
        AND instance_date >= max_date - {period_days:Int32}
        AND instance_date <= max_date
        AND trans_group_en = 'Sales'
        AND actual_worth > 0
        AND procedure_area > 0
    """

    try:
        rows = await query(
            sql,
            {
                "area": resolved_area,
                "period_days": safe_period_days,
            },
        )

        if not rows or int(rows[0].get("transaction_count") or 0) == 0:
            return {
                "success": False,
                "error": f"No data found for area '{area}' in the last {safe_period_days} days",
            }

        row = rows[0]
        return {
            "success": True,
            "requested_area": area,
            "area": resolved_area,
            "period_days": safe_period_days,
            "transaction_count": _int_value(row["transaction_count"]),
            "median_price_aed": _float_or_none(row["median_price"]),
            "avg_price_aed": _float_or_none(row["avg_price"]),
            "median_area_sqm": _float_or_none(row["median_area_sqm"]),
            "median_price_per_sqm_aed": _float_or_none(row["median_price_per_sqm"]),
            "period_start": str(row["period_start"]),
            "period_end": str(row["period_end"]),
        }
    except Exception as e:
        logger.exception(f"Error executing get_market_pulse for area {area}")
        return {"success": False, "error": str(e)}


@agent.tool
async def rank_areas(
    ctx: RunContext[None],
    metric: str = "volume",
    limit: int = 5,
    period_days: int = 365,
) -> dict[str, Any]:
    """Rank top areas by a specific metric.

    Args:
        ctx: Runtime context (unused)
        metric: Ranking metric - "volume" (transaction count), "price" (median price),
                "growth" (price change percentage), or "yield" (gross rental yield)
        limit: Number of top areas to return (default: 5)
        period_days: Analysis period in days. Default is 365 when no user period is specified.

    Returns:
        List of top areas with their respective metrics
    """
    if metric == "volume":
        sql = """
        WITH (
            SELECT max(instance_date)
            FROM ch_transactions
            WHERE trans_group_en = 'Sales' AND actual_worth > 0
        ) AS max_date
        SELECT
            area_name_en as area,
            count(*) as transaction_count,
            round(median(actual_worth), 0) as median_price
        FROM ch_transactions
        WHERE
            instance_date >= max_date - {period_days:Int32}
            AND instance_date <= max_date
            AND trans_group_en = 'Sales'
            AND actual_worth > 0
            AND area_name_en != ''
        GROUP BY area_name_en
        ORDER BY transaction_count DESC
        LIMIT {limit:Int32}
        """
    elif metric == "price":
        sql = """
        WITH (
            SELECT max(instance_date)
            FROM ch_transactions
            WHERE trans_group_en = 'Sales' AND actual_worth > 0
        ) AS max_date
        SELECT
            area_name_en as area,
            round(median(actual_worth), 0) as median_price,
            count(*) as transaction_count
        FROM ch_transactions
        WHERE
            instance_date >= max_date - {period_days:Int32}
            AND instance_date <= max_date
            AND trans_group_en = 'Sales'
            AND actual_worth > 0
            AND area_name_en != ''
        GROUP BY area_name_en
        HAVING transaction_count >= 10
        ORDER BY median_price DESC
        LIMIT {limit:Int32}
        """
    elif metric == "yield":
        sql = """
        WITH
            anchor AS (
                SELECT max(instance_date) AS max_date
                FROM ch_transactions
                WHERE trans_group_en = 'Sales' AND actual_worth > 0
            ),
            sales AS (
                SELECT
                    area_name_en AS area,
                    median(actual_worth) AS median_sale_price,
                    count() AS sales_count
                FROM ch_transactions
                WHERE
                    instance_date >= (SELECT max_date FROM anchor) - {period_days:Int32}
                    AND instance_date <= (SELECT max_date FROM anchor)
                    AND trans_group_en = 'Sales'
                    AND actual_worth > 0
                    AND property_usage_en = 'Residential'
                    AND property_type_en = 'Unit'
                    AND area_name_en != ''
                    AND lower(area_name_en) != 'unknown'
                GROUP BY area
                HAVING sales_count >= 250
            ),
            rentals AS (
                SELECT
                    area_name_en AS area,
                    median(annual_amount) AS median_annual_rent,
                    count() AS rental_count
                FROM ch_rent_contracts
                WHERE
                    contract_start_date >= (SELECT max_date FROM anchor) - {period_days:Int32}
                    AND contract_start_date <= (SELECT max_date FROM anchor)
                    AND contract_start_date <= today()
                    AND annual_amount > 0
                    AND property_usage_en = 'Residential'
                    AND ejari_property_type_en = 'Flat'
                    AND area_name_en != ''
                    AND lower(area_name_en) != 'unknown'
                GROUP BY area
                HAVING rental_count >= 250
            )
        SELECT
            s.area,
            round(r.median_annual_rent / nullIf(s.median_sale_price, 0) * 100, 2) AS gross_yield_pct,
            round(s.median_sale_price, 0) AS median_sale_price,
            round(r.median_annual_rent, 0) AS median_annual_rent,
            s.sales_count,
            r.rental_count
        FROM sales AS s
        INNER JOIN rentals AS r ON s.area = r.area
        WHERE gross_yield_pct BETWEEN 1 AND 25
        ORDER BY gross_yield_pct DESC
        LIMIT {limit:Int32}
        """
    elif metric == "growth":
        # Compare current period vs previous period
        sql = """
        WITH
            anchor AS (
                SELECT max(instance_date) AS max_date
                FROM ch_transactions
                WHERE trans_group_en = 'Sales' AND actual_worth > 0
            ),
            current_period AS (
                SELECT
                    area_name_en as area,
                    median(actual_worth) as current_median
                FROM ch_transactions
                WHERE
                    instance_date >= (SELECT max_date FROM anchor) - {period_days:Int32}
                    AND instance_date <= (SELECT max_date FROM anchor)
                    AND trans_group_en = 'Sales'
                    AND actual_worth > 0
                    AND area_name_en != ''
                GROUP BY area_name_en
                HAVING count(*) >= 10
            ),
            previous_period AS (
                SELECT
                    area_name_en as area,
                    median(actual_worth) as previous_median
                FROM ch_transactions
                WHERE
                    instance_date >= (SELECT max_date FROM anchor) - ({period_days:Int32} * 2)
                    AND instance_date < (SELECT max_date FROM anchor) - {period_days:Int32}
                    AND trans_group_en = 'Sales'
                    AND actual_worth > 0
                    AND area_name_en != ''
                GROUP BY area_name_en
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
            "error": f"Invalid metric '{metric}'. Use 'volume', 'price', 'growth', or 'yield'",
        }

    try:
        safe_period_days = _clamp(period_days, 30, 3650)
        rows = await query(sql, {"period_days": safe_period_days, "limit": limit})

        if not rows:
            return {
                "success": False,
                "error": f"No data found for metric '{metric}' in the last {safe_period_days} days",
            }

        areas = []
        for row in rows:
            if metric == "volume":
                areas.append(
                    {
                        "area": row["area"],
                        "transaction_count": _int_value(row["transaction_count"]),
                        "median_price_aed": _float_or_none(row["median_price"]),
                    }
                )
            elif metric == "price":
                areas.append(
                    {
                        "area": row["area"],
                        "median_price_aed": _float_or_none(row["median_price"]),
                        "transaction_count": _int_value(row["transaction_count"]),
                    }
                )
            elif metric == "yield":
                areas.append(
                    {
                        "area": row["area"],
                        "gross_yield_pct": _float_or_none(row["gross_yield_pct"]),
                        "median_sale_price_aed": _float_or_none(row["median_sale_price"]),
                        "median_annual_rent_aed": _float_or_none(row["median_annual_rent"]),
                        "sales_transaction_count": _int_value(row["sales_count"]),
                        "rental_contract_count": _int_value(row["rental_count"]),
                    }
                )
            elif metric == "growth":
                areas.append(
                    {
                        "area": row["area"],
                        "current_median_price_aed": _float_or_none(row["current_median_price"]),
                        "previous_median_price_aed": _float_or_none(row["previous_median_price"]),
                        "growth_percentage": _float_or_none(row["growth_percentage"]),
                    }
                )

        return {
            "success": True,
            "metric": metric,
            "period_days": safe_period_days,
            "top_areas": areas,
        }
    except Exception as e:
        logger.exception(f"Error executing rank_areas for metric {metric}")
        return {"success": False, "error": str(e)}


@agent.tool
async def rank_upcoming_project_areas(
    ctx: RunContext[None],
    limit: int = 8,
) -> dict[str, Any]:
    """Rank Dubai areas by active/upcoming project pipeline.

    Use this for questions about hot development areas, upcoming projects, under-construction
    supply, delivery pipeline, or launch-heavy districts.

    Args:
        ctx: Runtime context (unused)
        limit: Number of areas to return.

    Returns:
        Ranked areas with active project, pipeline unit, delivery, developer, and market signals.
    """
    sql = """
    SELECT
        area_name_en AS area,
        active_projects,
        pipeline_units,
        units_delivering_next_12_months,
        active_developers,
        round(avg_completion_pct, 1) AS avg_completion_pct,
        round(avg_delivery_confidence, 2) AS avg_delivery_confidence,
        sales_transaction_count_12m,
        round(total_sales_volume_12m, 0) AS total_sales_volume_12m,
        top_developers,
        top_master_projects
    FROM ch_area_fact
    WHERE area_name_en != ''
      AND lower(area_name_en) != 'unknown'
      AND active_projects > 0
    ORDER BY
        pipeline_units DESC,
        units_delivering_next_12_months DESC,
        sales_transaction_count_12m DESC
    LIMIT {limit:Int32}
    """

    try:
        rows = await query(sql, {"limit": max(1, min(limit, 15))})
        return {
            "success": True,
            "ranking_basis": "active projects, pipeline units, next-12-month deliveries, and market activity",
            "areas": [
                {
                    "area": row["area"],
                    "active_projects": _int_value(row["active_projects"]),
                    "pipeline_units": _int_value(row["pipeline_units"]),
                    "units_delivering_next_12_months": _int_value(
                        row["units_delivering_next_12_months"]
                    ),
                    "active_developers": _int_value(row["active_developers"]),
                    "avg_completion_pct": _float_or_none(row["avg_completion_pct"]),
                    "avg_delivery_confidence": _float_or_none(row["avg_delivery_confidence"]),
                    "sales_transaction_count_12m": _int_value(row["sales_transaction_count_12m"]),
                    "total_sales_volume_12m": _float_or_none(row["total_sales_volume_12m"]),
                    "top_developers": list(row.get("top_developers") or [])[:5],
                    "top_master_projects": list(row.get("top_master_projects") or [])[:5],
                }
                for row in rows
            ],
        }
    except Exception as e:
        logger.exception("Error executing rank_upcoming_project_areas")
        return {"success": False, "error": str(e)}


@agent.tool
async def search_development_projects(
    ctx: RunContext[None],
    search: str = "",
    area: str = "",
    developer: str = "",
    status: str = "active",
    limit: int = 8,
) -> dict[str, Any]:
    """Search Dubai development projects by project name, area, developer, and status.

    Use this when the user asks for specific upcoming projects, projects by a developer,
    projects in an area, or a list of under-construction/completed projects.

    Args:
        ctx: Runtime context (unused)
        search: Project or master project text to search for.
        area: Optional area/community filter.
        developer: Optional developer name filter.
        status: "active", "completed", or "any".
        limit: Number of projects to return.

    Returns:
        Matching projects with developer, area, units, completion, pipeline, and market signals.
    """
    clauses = ["project_name_en != ''"]
    params: dict[str, Any] = {"limit": _clamp(limit, 1, 20)}

    if search.strip():
        clauses.append(
            """
            (
                positionCaseInsensitive(project_name_en, {search:String}) > 0
                OR positionCaseInsensitive(master_project_en, {search:String}) > 0
            )
            """
        )
        params["search"] = search.strip()
    if area.strip():
        resolved_area = await _resolve_area_name(area)
        clauses.append("area_name_en = {area:String}")
        params["area"] = resolved_area
    if developer.strip():
        clauses.append(await _developer_where_clause(developer, params, "developer_match"))

    normalized_status = status.lower().strip()
    if normalized_status in {"active", "upcoming", "under construction", "pipeline"}:
        clauses.append("completion_status != 'FINISHED'")
    elif normalized_status in {"completed", "finished"}:
        clauses.append("completion_status = 'FINISHED'")
    elif normalized_status not in {"", "any", "all"}:
        return {
            "success": False,
            "error": "Invalid status. Use 'active', 'completed', or 'any'.",
        }

    try:
        rows = await query(
            f"""
            SELECT
                project_id,
                project_name_en,
                area_name_en,
                developer_name,
                master_project_en,
                completion_status,
                pipeline_status,
                no_of_units,
                round(percent_completed, 1) AS percent_completed,
                round(estimated_delivery_confidence, 2) AS delivery_confidence,
                sales_transaction_count_12m,
                rental_contract_count_12m,
                round(total_sales_volume_12m, 0) AS total_sales_volume_12m,
                median_sale_price,
                median_annual_rent,
                gross_yield_pct
            FROM ch_project_fact
            WHERE {" AND ".join(clauses)}
            ORDER BY
                total_sales_volume_12m DESC,
                no_of_units DESC,
                sales_transaction_count_12m DESC,
                project_name_en ASC
            LIMIT {{limit:Int32}}
            """,
            params,
        )
        return {
            "success": True,
            "filters": {
                "search": search or None,
                "area": params.get("area") or None,
                "developer": developer or None,
                "status": normalized_status or "active",
            },
            "projects": [
                {
                    "project_id": _int_value(row["project_id"]),
                    "project": row["project_name_en"],
                    "area": row.get("area_name_en") or None,
                    "developer": row.get("developer_name") or None,
                    "master_project": row.get("master_project_en") or None,
                    "completion_status": row.get("completion_status") or None,
                    "pipeline_status": row.get("pipeline_status") or None,
                    "units": _int_value(row["no_of_units"]),
                    "percent_completed": _float_or_none(row["percent_completed"]),
                    "delivery_confidence": _float_or_none(row["delivery_confidence"]),
                    "sales_transaction_count_12m": _int_value(row["sales_transaction_count_12m"]),
                    "rental_contract_count_12m": _int_value(row["rental_contract_count_12m"]),
                    "total_sales_volume_12m": _float_or_none(row["total_sales_volume_12m"]),
                    "median_sale_price": _float_or_none(row["median_sale_price"]),
                    "median_annual_rent": _float_or_none(row["median_annual_rent"]),
                    "gross_yield_pct": _float_or_none(row["gross_yield_pct"]),
                }
                for row in rows
            ],
        }
    except Exception as e:
        logger.exception("Error executing search_development_projects")
        return {"success": False, "error": str(e)}


@agent.tool
async def get_developer_pipeline(
    ctx: RunContext[None],
    developer: str,
    area: str = "",
    limit: int = 8,
) -> dict[str, Any]:
    """Summarize a developer's Dubai project pipeline and strongest project areas.

    Use this for questions like "what is Emaar building", "which Damac projects are active",
    or "show Sobha's pipeline in MBR City".

    Args:
        ctx: Runtime context (unused)
        developer: Developer name or partial developer name.
        area: Optional area/community filter.
        limit: Number of projects/areas to return.

    Returns:
        Developer aggregate metrics, top areas, and notable projects.
    """
    if not developer.strip():
        return {"success": False, "error": "Developer is required."}

    params: dict[str, Any] = {"limit": _clamp(limit, 1, 20)}
    clauses = [await _developer_where_clause(developer, params, "developer_match")]
    if area.strip():
        resolved_area = await _resolve_area_name(area)
        clauses.append("area_name_en = {area:String}")
        params["area"] = resolved_area

    where_sql = " AND ".join(clauses)
    try:
        summary_rows = await query(
            f"""
            SELECT
                any(developer_name) AS matched_developer_name,
                count() AS total_projects,
                countIf(completion_status != 'FINISHED') AS active_projects,
                countIf(completion_status = 'FINISHED') AS completed_projects,
                sum(no_of_units) AS total_units,
                sumIf(no_of_units, completion_status != 'FINISHED') AS pipeline_units,
                sumIf(
                    no_of_units,
                    pipeline_status = 'delivering_next_12_months'
                    AND completion_status != 'FINISHED'
                ) AS units_delivering_next_12_months,
                round(avgIf(percent_completed, completion_status != 'FINISHED'), 1)
                    AS avg_active_completion_pct,
                sum(sales_transaction_count_12m) AS sales_transaction_count_12m,
                round(sum(total_sales_volume_12m), 0) AS total_sales_volume_12m
            FROM ch_project_fact
            WHERE {where_sql}
            """,
            params,
        )
        summary = summary_rows[0] if summary_rows else {}
        if _int_value(summary.get("total_projects")) == 0:
            return {"success": False, "error": f"No projects found for '{developer}'."}

        area_rows = await query(
            f"""
            SELECT
                area_name_en,
                count() AS project_count,
                sum(no_of_units) AS units,
                round(sum(total_sales_volume_12m), 0) AS total_sales_volume_12m
            FROM ch_project_fact
            WHERE {where_sql}
            GROUP BY area_name_en
            ORDER BY units DESC, total_sales_volume_12m DESC
            LIMIT {{limit:Int32}}
            """,
            params,
        )
        project_rows = await query(
            f"""
            SELECT
                project_name_en,
                area_name_en,
                master_project_en,
                completion_status,
                pipeline_status,
                no_of_units,
                round(percent_completed, 1) AS percent_completed,
                round(estimated_delivery_confidence, 2) AS delivery_confidence,
                round(total_sales_volume_12m, 0) AS total_sales_volume_12m
            FROM ch_project_fact
            WHERE {where_sql}
            ORDER BY total_sales_volume_12m DESC, no_of_units DESC, project_name_en ASC
            LIMIT {{limit:Int32}}
            """,
            params,
        )
        return {
            "success": True,
            "developer": summary.get("matched_developer_name") or developer,
            "area_filter": params.get("area"),
            "summary": {
                "total_projects": _int_value(summary["total_projects"]),
                "active_projects": _int_value(summary["active_projects"]),
                "completed_projects": _int_value(summary["completed_projects"]),
                "total_units": _int_value(summary["total_units"]),
                "pipeline_units": _int_value(summary["pipeline_units"]),
                "units_delivering_next_12_months": _int_value(
                    summary["units_delivering_next_12_months"]
                ),
                "avg_active_completion_pct": _float_or_none(summary["avg_active_completion_pct"]),
                "sales_transaction_count_12m": _int_value(summary["sales_transaction_count_12m"]),
                "total_sales_volume_12m": _float_or_none(summary["total_sales_volume_12m"]),
            },
            "top_areas": [
                {
                    "area": row["area_name_en"],
                    "project_count": _int_value(row["project_count"]),
                    "units": _int_value(row["units"]),
                    "total_sales_volume_12m": _float_or_none(row["total_sales_volume_12m"]),
                }
                for row in area_rows
            ],
            "notable_projects": [
                {
                    "project": row["project_name_en"],
                    "area": row.get("area_name_en") or None,
                    "master_project": row.get("master_project_en") or None,
                    "completion_status": row.get("completion_status") or None,
                    "pipeline_status": row.get("pipeline_status") or None,
                    "units": _int_value(row["no_of_units"]),
                    "percent_completed": _float_or_none(row["percent_completed"]),
                    "delivery_confidence": _float_or_none(row["delivery_confidence"]),
                    "total_sales_volume_12m": _float_or_none(row["total_sales_volume_12m"]),
                }
                for row in project_rows
            ],
        }
    except Exception as e:
        logger.exception("Error executing get_developer_pipeline for %s", developer)
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
    WITH (
        SELECT max(instance_date)
        FROM ch_transactions
        WHERE trans_group_en = 'Sales' AND actual_worth > 0
    ) AS max_date
    SELECT
        master_project_en,
        area_name_en,
        property_type_en,
        round(median(actual_worth), 0) as median_price,
        round(median(procedure_area), 1) as median_area,
        count(*) as transaction_count
    FROM ch_transactions
    WHERE
        master_project_en ILIKE {project_name:String}
        AND trans_group_en = 'Sales'
        AND actual_worth > 0
        AND procedure_area > 0
        AND instance_date >= max_date - 365
        AND instance_date <= max_date
    GROUP BY master_project_en, area_name_en, property_type_en
    ORDER BY transaction_count DESC
    LIMIT 1
    """

    try:
        ref_rows = await query(ref_sql, {"project_name": f"%{project_name}%"})

        if not ref_rows:
            return {
                "success": False,
                "error": f"No data found for project '{project_name}'",
            }

        ref_row = ref_rows[0]
        ref_project = ref_row["master_project_en"]
        ref_area = ref_row["area_name_en"]
        ref_type = ref_row["property_type_en"]
        ref_price = _float_or_none(ref_row["median_price"]) or 0
        ref_area_sqm = _float_or_none(ref_row["median_area"])

        # Find similar projects
        similar_sql = """
        WITH (
            SELECT max(instance_date)
            FROM ch_transactions
            WHERE trans_group_en = 'Sales' AND actual_worth > 0
        ) AS max_date
        SELECT
            master_project_en,
            area_name_en,
            property_type_en,
            round(median(actual_worth), 0) as median_price,
            round(median(procedure_area), 1) as median_area,
            count(*) as transaction_count,
            abs(median(actual_worth) - {ref_price:Float64}) as price_diff
        FROM ch_transactions
        WHERE
            master_project_en != {ref_project:String}
            AND property_type_en = {ref_type:String}
            AND trans_group_en = 'Sales'
            AND actual_worth > 0
            AND procedure_area > 0
            AND instance_date >= max_date - 365
            AND instance_date <= max_date
            AND master_project_en != ''
        GROUP BY master_project_en, area_name_en, property_type_en
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
                    "project": row["master_project_en"],
                    "area": row["area_name_en"],
                    "property_type": row["property_type_en"],
                    "median_price_aed": _float_or_none(row["median_price"]),
                    "median_area_sqm": _float_or_none(row["median_area"]),
                    "transaction_count": _int_value(row["transaction_count"]),
                    "price_difference_aed": _float_or_none(row["price_diff"]),
                }
            )

        return {
            "success": True,
            "reference_project": {
                "name": ref_project,
                "area": ref_area,
                "property_type": ref_type,
                "median_price_aed": ref_price,
                "median_area_sqm": ref_area_sqm,
            },
            "similar_projects": similar_projects,
        }
    except Exception as e:
        logger.exception(f"Error executing get_similar_projects for {project_name}")
        return {"success": False, "error": str(e)}
