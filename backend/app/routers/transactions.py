from fastapi import APIRouter, Query, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.db.session import get_db_session
from backend.app.routers.dependencies import require_auth
from backend.app.core.decorators import cached_endpoint
from backend.app.schemas.transactions import (
    TransactionListResponse,
    RentalContractListResponse,
)

# Import from the new service file
from backend.app.services.transactions_service import (
    fetch_sales_transactions,
    fetch_rental_contracts,
)

router = APIRouter(
    prefix="/api/v1/transactions",
    tags=["transactions"],
    dependencies=[Depends(require_auth)],
)

# --- SALES ENDPOINTS ---


@router.get("/sales", response_model=TransactionListResponse)
@cached_endpoint(prefix="sales", expire=600)
async def get_sales_transactions(
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    # Filters
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
    # Range filters
    area_min: float = Query(default=None),
    area_max: float = Query(default=None),
    price_min: float = Query(default=None),
    price_max: float = Query(default=None),
    price_sqft_min: float = Query(default=None),
    price_sqft_max: float = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
):
    return await fetch_sales_transactions(
        session=session,
        limit=limit,
        offset=offset,
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
        price_sqft_min=price_sqft_min,
        price_sqft_max=price_sqft_max,
    )


# --- RENTALS ENDPOINTS ---


@router.get("/rentals", response_model=RentalContractListResponse)
@cached_endpoint(prefix="rentals", expire=600)
async def get_rental_contracts(
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    master_project: str = Query(default=None),
    timeframe_days: int = Query(default=None),
    project: str = Query(default=None),
    property_type: str = Query(default=None),
    property_sub_type: str = Query(default=None),
    tenant_type: str = Query(default=None),
    contract_reg_type: str = Query(default=None),
    # Range filters
    area_min: float = Query(default=None),
    area_max: float = Query(default=None),
    rent_min: float = Query(default=None),
    rent_max: float = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
):
    return await fetch_rental_contracts(
        session=session,
        limit=limit,
        offset=offset,
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
