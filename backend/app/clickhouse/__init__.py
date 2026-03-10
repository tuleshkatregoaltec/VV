from app.clickhouse.client import close_clickhouse, get_client, query, query_df
from app.clickhouse.queries import (
    distinct_areas,
    distinct_master_projects,
    # Filters
    distinct_property_types,
    distinct_rooms,
    # Comparables
    find_comparable_units,
    get_project_details,
    list_buildings_for_project,
    list_developers,
    # Projects
    list_projects,
    list_units_for_building,
    price_trends,
    recent_rentals_for_area,
    recent_transactions_for_area,
    # Analytics - Rentals
    rentals_summary,
    sales_by_area,
    sales_by_property_type,
    sales_by_rooms,
    # Analytics - Sales
    sales_summary,
)
from app.clickhouse.types import (
    AreaStats,
    BuildingListItem,
    ComparableRentalContract,
    ComparableTransaction,
    # Comparables
    ComparableUnit,
    DeveloperListItem,
    # Filters
    FilterOption,
    FilterOptions,
    PriceTrend,
    ProjectDetails,
    # Projects
    ProjectListItem,
    PropertyTypeBreakdown,
    RentalContractDetail,
    RentalSummary,
    RoomsBreakdown,
    # Analytics
    SalesSummary,
    # Transactions
    TransactionDetail,
    UnitListItem,
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
