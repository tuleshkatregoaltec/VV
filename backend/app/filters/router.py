"""Filter options for the DXBI Transactions pages."""

from fastapi import APIRouter, Depends

from app.core.decorators import cached_endpoint
from app.core.dependencies import AuthContext, require_active_subscription
from app.transaction.dependencies import rental_filters, sales_filters
from app.transaction.facets import get_rental_filter_options as get_rental_filters_service
from app.transaction.facets import get_sales_filter_options as get_sales_filters_service
from app.transaction.models import FilterOptionsResponse, RentalFilters, SalesFilters

router = APIRouter(prefix="/api/v1/filters", tags=["filters"])


@router.get("/sales", response_model=FilterOptionsResponse)
@cached_endpoint(prefix="filters:dxbi-sales:v2", expire=3600)
async def get_sales_filter_options(
    context: AuthContext = Depends(require_active_subscription),
    filters: SalesFilters = Depends(sales_filters),
):
    """Options for the DXBI sales filters, narrowed by the filters already applied."""
    return await get_sales_filters_service(filters)


@router.get("/rentals", response_model=FilterOptionsResponse)
@cached_endpoint(prefix="filters:dxbi-rentals:v2", expire=3600)
async def get_rental_filter_options(
    context: AuthContext = Depends(require_active_subscription),
    filters: RentalFilters = Depends(rental_filters),
):
    """Options for the DXBI rental filters, narrowed by the filters already applied."""
    return await get_rental_filters_service(filters)
