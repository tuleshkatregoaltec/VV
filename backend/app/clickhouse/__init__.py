"""ClickHouse query layer for analytics and real estate data.

Async client for FastAPI with parameter binding for security.

Example usage:
    from app.clickhouse import query, sales_summary, SalesSummary

    sql = sales_summary(
        property_usage="Residential",
        start_date="2024-01-01",
        end_date="2024-12-31"
    )
    results = await query(sql, {
        "property_usage": "Residential",
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 12, 31)
    })
    summary = SalesSummary(**results[0])
"""

from app.clickhouse.client import get_client, query, query_df, close_clickhouse
from app.clickhouse.queries import (
    # Analytics - Sales
    sales_summary,
    price_trends,
    sales_by_area,
    sales_by_property_type,
    sales_by_rooms,
    # Analytics - Rentals
    rentals_summary,
    # Filters
    distinct_property_types,
    distinct_areas,
    distinct_master_projects,
    distinct_rooms,
    # Projects
    list_projects,
    get_project_details,
    list_developers,
    list_buildings_for_project,
    list_units_for_building,
    # Comparables
    find_comparable_units,
    recent_transactions_for_area,
    recent_rentals_for_area,
)
from app.clickhouse.types import (
    # Analytics
    SalesSummary,
    RentalSummary,
    AreaStats,
    PriceTrend,
    PropertyTypeBreakdown,
    RoomsBreakdown,
    # Projects
    ProjectListItem,
    ProjectDetails,
    DeveloperListItem,
    BuildingListItem,
    UnitListItem,
    # Comparables
    ComparableUnit,
    ComparableTransaction,
    ComparableRentalContract,
    # Filters
    FilterOption,
    FilterOptions,
    # Transactions
    TransactionDetail,
    RentalContractDetail,
)

__all__ = [
    # Client functions
    "get_client",
    "query",
    "query_df",
    "close_clickhouse",
    # Query templates - Analytics
    "sales_summary",
    "price_trends",
    "sales_by_area",
    "sales_by_property_type",
    "sales_by_rooms",
    "rentals_summary",
    # Query templates - Filters
    "distinct_property_types",
    "distinct_areas",
    "distinct_master_projects",
    "distinct_rooms",
    # Query templates - Projects
    "list_projects",
    "get_project_details",
    "list_developers",
    "list_buildings_for_project",
    "list_units_for_building",
    # Query templates - Comparables
    "find_comparable_units",
    "recent_transactions_for_area",
    "recent_rentals_for_area",
    # Response types - Analytics
    "SalesSummary",
    "RentalSummary",
    "AreaStats",
    "PriceTrend",
    "PropertyTypeBreakdown",
    "RoomsBreakdown",
    # Response types - Projects
    "ProjectListItem",
    "ProjectDetails",
    "DeveloperListItem",
    "BuildingListItem",
    "UnitListItem",
    # Response types - Comparables
    "ComparableUnit",
    "ComparableTransaction",
    "ComparableRentalContract",
    # Response types - Filters
    "FilterOption",
    "FilterOptions",
    # Response types - Transactions
    "TransactionDetail",
    "RentalContractDetail",
]
