from fastapi import APIRouter, Query, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from datetime import datetime
from fastapi.responses import StreamingResponse

from backend.app.db.session import get_db_session
from backend.app.routers.dependencies import require_auth
from backend.app.core.decorators import cached_endpoint
from backend.app.schemas.transactions import (
    TransactionListResponse,
    RentalContractListResponse,
)

from backend.app.services.transactions_service import (
    fetch_sales_transactions,
    fetch_rental_contracts,
    export_rental_contracts as export_rental_contracts_service,
    export_sales_transactions as export_sales_transactions_service
)

router = APIRouter(
    prefix="/api/v1/transactions",
    tags=["transactions"],
    dependencies=[Depends(require_auth)],
)


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

@router.get("/sales/export")
async def export_sales_transactions(
    max_rows: int = Query(default=10000, ge=1, le=50000, description="Maximum rows to export"),
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
    """Export sales transactions to Excel with applied filters."""
    
    stream = await export_sales_transactions_service(
        session=session,
        max_rows=max_rows,
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
    
    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"sales_transactions_{timestamp}.xlsx"
    
    return StreamingResponse(
        iter([stream.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )


@router.get("/rentals/export")
async def export_rental_contracts(
    max_rows: int = Query(default=10000, ge=1, le=50000, description="Maximum rows to export"),
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
    """Export rental contracts to Excel with applied filters."""
    
    stream = await export_rental_contracts_service(
        session=session,
        max_rows=max_rows,
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
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"rental_contracts_{timestamp}.xlsx"
    
    return StreamingResponse(
        iter([stream.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )