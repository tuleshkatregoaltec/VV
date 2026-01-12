"""Filter options endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.decorators import cached_endpoint
from app.db.models.transactions import Transaction
from app.db.session import get_db_session
from app.routers.dependencies import require_auth
from app.schemas.filters import FilterOptionsResponse
from app.services.filters_service import (
    fetch_rental_filter_options,
    fetch_sales_filter_options,
    get_distinct_values,
)

router = APIRouter(
    prefix="/api/v1/filters",
    tags=["filters"],
    dependencies=[Depends(require_auth)],
)


@router.get("/master-projects")
@cached_endpoint(prefix="filters:master-projects", expire=3600)
async def get_master_projects(
    db: AsyncSession = Depends(get_db_session),
) -> list[str]:
    """Get distinct master project names for filter dropdowns."""
    return await get_distinct_values(db, Transaction.master_project_en, [])


@router.get("/sales", response_model=FilterOptionsResponse)
@cached_endpoint(prefix="filters:sales", expire=3600)
async def get_sales_filter_options(
    trans_group: str = Query(default=None),
    property_usage: str = Query(default=None),
    master_project: str = Query(default=None),
    timeframe_days: int = Query(default=None),
    project: str = Query(default=None),
    building: str = Query(default=None),
    property_type: str = Query(default=None),
    rooms: str = Query(default=None),
    property_sub_type: str = Query(default=None),
    registration_type: str = Query(default=None),
    area_min: float = Query(default=None),
    area_max: float = Query(default=None),
    price_min: float = Query(default=None),
    price_max: float = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Get filter options for sales transactions."""
    return await fetch_sales_filter_options(
        db=db,
        trans_group=trans_group,
        property_usage=property_usage,
        master_project=master_project,
        timeframe_days=timeframe_days,
        project=project,
        building=building,
        property_type=property_type,
        rooms=rooms,
        property_sub_type=property_sub_type,
        registration_type=registration_type,
        area_min=area_min,
        area_max=area_max,
        price_min=price_min,
        price_max=price_max,
    )


@router.get("/rentals", response_model=FilterOptionsResponse)
@cached_endpoint(prefix="filters:rentals", expire=3600)
async def get_rental_filter_options(
    property_usage: str = Query(default=None),
    master_project: str = Query(default=None),
    timeframe_days: int = Query(default=None),
    project: str = Query(default=None),
    property_type: str = Query(default=None),
    property_sub_type: str = Query(default=None),
    tenant_type: str = Query(default=None),
    contract_reg_type: str = Query(default=None),
    area_min: float = Query(default=None),
    area_max: float = Query(default=None),
    rent_min: float = Query(default=None),
    rent_max: float = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Get filter options for rental contracts."""
    return await fetch_rental_filter_options(
        db=db,
        property_usage=property_usage,
        master_project=master_project,
        timeframe_days=timeframe_days,
        project=project,
        property_type=property_type,
        property_sub_type=property_sub_type,
        tenant_type=tenant_type,
        contract_reg_type=contract_reg_type,
        area_min=area_min,
        area_max=area_max,
        rent_min=rent_min,
        rent_max=rent_max,
    )
