"""Filter options endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.db.session import get_db_session
from backend.app.db.models.transactions import Transaction
from backend.app.routers.dependencies import get_current_user
from backend.app.core.decorators import cached_endpoint
from backend.app.schemas.transactions import FilterOptionsResponse
from backend.app.services.transactions_service import (
    fetch_sales_filter_options,
    fetch_rental_filter_options,
    get_distinct_values,
)

router = APIRouter(prefix="/filters", dependencies=[Depends(get_current_user)])


@router.get("/master-projects")
@cached_endpoint(prefix="filters:master-projects", expire=3600)
async def get_master_projects(
    session: AsyncSession = Depends(get_db_session),
) -> list[str]:
    """Get distinct master project names for filter dropdowns."""
    return await get_distinct_values(session, Transaction.master_project_en, [])


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
    session: AsyncSession = Depends(get_db_session),
):
    """Get filter options for sales transactions."""
    return await fetch_sales_filter_options(
        session=session,
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
    )


@router.get("/rentals", response_model=FilterOptionsResponse)
@cached_endpoint(prefix="filters:rentals", expire=3600)
async def get_rental_filter_options(
    master_project: str = Query(default=None),
    timeframe_days: int = Query(default=None),
    project: str = Query(default=None),
    property_type: str = Query(default=None),
    property_sub_type: str = Query(default=None),
    tenant_type: str = Query(default=None),
    contract_reg_type: str = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
):
    """Get filter options for rental contracts."""
    return await fetch_rental_filter_options(
        session=session,
        master_project=master_project,
        timeframe_days=timeframe_days,
        project=project,
        property_type=property_type,
        property_sub_type=property_sub_type,
        tenant_type=tenant_type,
        contract_reg_type=contract_reg_type,
    )
