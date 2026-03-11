"""Filter options endpoints - redesigned for ClickHouse LowCardinality columns."""

from fastapi import APIRouter, Depends, Query

from app.core.decorators import cached_endpoint
from app.core.dependencies import AuthContext, require_active_subscription
from app.filters.models import FilterOptionsResponse
from app.filters.service import (
    get_rental_filter_options as get_rental_filters_service,
)
from app.filters.service import (
    get_sales_filter_options as get_sales_filters_service,
)

router = APIRouter(prefix="/api/v1/filters", tags=["filters"])


@router.get("/sales", response_model=FilterOptionsResponse)
@cached_endpoint(prefix="filters:sales", expire=3600)
async def get_sales_filter_options(
    context: AuthContext = Depends(require_active_subscription),
    property_usage: str = Query(default=None, description="Residential or Commercial"),
    project: str = Query(default=None, description="Filter buildings by project"),
    filter_type: str = Query(
        default="project",
        description="Project filter type: master, virtual_master, or project",
    ),
    property_type: str = Query(default=None, description="Filter subtypes and rooms"),
    area: str = Query(default=None, description="Filter by area"),
):
    """
    Get filter options for sales transactions.

    Optimized for ClickHouse LowCardinality columns (<10ms queries).
    Supports dynamic narrowing (e.g., project → buildings in that project).
    """
    return await get_sales_filters_service(
        property_usage=property_usage,
        project=project,
        filter_type=filter_type,
        property_type=property_type,
        area=area,
    )


@router.get("/rentals", response_model=FilterOptionsResponse)
@cached_endpoint(prefix="filters:rentals", expire=3600)
async def get_rental_filter_options(
    context: AuthContext = Depends(require_active_subscription),
    property_usage: str = Query(default=None, description="Residential or Commercial"),
    project: str = Query(default=None, description="Filter buildings by project"),
    filter_type: str = Query(
        default="project",
        description="Project filter type: master, virtual_master, or project",
    ),
    property_type: str = Query(default=None, description="Filter subtypes"),
    area: str = Query(default=None, description="Filter by area"),
):
    """
    Get filter options for rental contracts.

    Optimized for ClickHouse LowCardinality columns (<10ms queries).
    """
    return await get_rental_filters_service(
        property_usage=property_usage,
        project=project,
        filter_type=filter_type,
        property_type=property_type,
        area=area,
    )
