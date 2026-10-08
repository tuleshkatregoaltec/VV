import re

from app.transaction import queries
from app.transaction.models import FilterOptionsResponse, RentalFilters, SalesFilters


def _bedrooms_sort_key(label: str) -> tuple:
    """Studio first, then bedroom counts in numeric order."""
    match = re.match(r"^(\d+)", label)
    return (0, 0) if label == "Studio" else (1, int(match.group(1))) if match else (2, 0)


def _options(values: list | None) -> list[str]:
    """Alphabetical regardless of case; names differing only in case keep a fixed order."""
    cleaned = {str(value).strip() for value in values or [] if str(value).strip()}
    return sorted(cleaned, key=lambda value: (value.casefold(), value))


def _bedrooms(values: list | None) -> list[str]:
    return sorted(_options(values), key=_bedrooms_sort_key)


async def get_sales_filter_options(filters: SalesFilters) -> FilterOptionsResponse:
    """Options for the DXBI sales filters, narrowed by the current filters."""
    facets = await queries.fetch_sales_facets(filters)
    return FilterOptionsResponse(
        locations=_options(facets.get("location_options")),
        buildings=_options(facets.get("building_options")),
        property_types=_options(facets.get("property_type_options")),
        bedrooms=_bedrooms(facets.get("bedroom_options")),
        statuses=_options(facets.get("status_options")),
    )


async def get_rental_filter_options(filters: RentalFilters) -> FilterOptionsResponse:
    """Options for the DXBI rental filters, narrowed by the current filters."""
    facets = await queries.fetch_rental_facets(filters)
    return FilterOptionsResponse(
        locations=_options(facets.get("location_options")),
        buildings=_options(facets.get("building_options")),
        property_types=_options(facets.get("property_type_options")),
        bedrooms=_bedrooms(facets.get("bedroom_options")),
        contract_types=_options(facets.get("contract_type_options")),
    )
