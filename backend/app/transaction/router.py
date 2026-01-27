"""Transaction listing and export endpoints - redesigned for ClickHouse."""

from datetime import datetime
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.decorators import cached_endpoint
from app.core.dependencies import require_active_subscription, AuthContext
from app.transaction.models import (
    RentalContractListResponse,
    TransactionListResponse,
)
from app.transaction.service import (
    export_rental_contracts,
    export_sales_transactions,
    fetch_rental_contracts,
    fetch_sales_transactions,
)

router = APIRouter(
    prefix="/api/v1/transactions",
    tags=["transactions"],
)


@router.get("/sales", response_model=TransactionListResponse)
@cached_endpoint(prefix="transactions:sales", expire=600)
async def get_sales_transactions(
    context: AuthContext = Depends(require_active_subscription),
    limit: int = Query(default=30, ge=1, le=1000, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    # Category filters
    property_usage: str = Query(default=None, description="Residential or Commercial"),
    property_type: str = Query(default=None, description="Property type"),
    property_sub_type: str = Query(default=None, description="Property sub-type"),
    rooms: str = Query(default=None, description="Number of rooms"),
    registration_type: str = Query(default=None, description="Registration type"),
    # Location filters
    area: str = Query(default=None, description="Area name"),
    project: str = Query(default=None, description="Project name"),
    building: str = Query(default=None, description="Building name"),
    # Range filters
    timeframe_days: int = Query(default=None, description="Days back from today"),
    area_min: float = Query(default=None, description="Minimum property area (sqm)"),
    area_max: float = Query(default=None, description="Maximum property area (sqm)"),
    price_min: float = Query(default=None, description="Minimum price"),
    price_max: float = Query(default=None, description="Maximum price"),
    price_per_sqm_min: float = Query(default=None, description="Minimum price per sqm"),
    price_per_sqm_max: float = Query(default=None, description="Maximum price per sqm"),
):
    """
    List sales transactions with filtering and pagination.

    Default sort: instance_date DESC (most recent first), split by property_usage_en.
    """
    return await fetch_sales_transactions(
        limit=limit,
        offset=offset,
        property_usage=property_usage,
        property_type=property_type,
        property_sub_type=property_sub_type,
        rooms=rooms,
        registration_type=registration_type,
        area=area,
        project=project,
        building=building,
        timeframe_days=timeframe_days,
        area_min=area_min,
        area_max=area_max,
        price_min=price_min,
        price_max=price_max,
        price_per_sqm_min=price_per_sqm_min,
        price_per_sqm_max=price_per_sqm_max,
    )


@router.get("/rentals", response_model=RentalContractListResponse)
@cached_endpoint(prefix="transactions:rentals", expire=600)
async def get_rental_contracts(
    context: AuthContext = Depends(require_active_subscription),
    limit: int = Query(default=30, ge=1, le=1000, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    # Category filters
    property_usage: str = Query(default=None, description="Residential or Commercial"),
    property_type: str = Query(default=None, description="Property type (ejari)"),
    property_sub_type: str = Query(
        default=None, description="Property sub-type (ejari)"
    ),
    tenant_type: str = Query(default=None, description="Tenant type"),
    contract_reg_type: str = Query(
        default=None, description="Contract registration type"
    ),
    # Location filters
    area: str = Query(default=None, description="Area name"),
    project: str = Query(default=None, description="Project name"),
    # Range filters
    timeframe_days: int = Query(default=None, description="Days back from today"),
    area_min: float = Query(default=None, description="Minimum property area (sqm)"),
    area_max: float = Query(default=None, description="Maximum property area (sqm)"),
    rent_min: float = Query(default=None, description="Minimum annual rent"),
    rent_max: float = Query(default=None, description="Maximum annual rent"),
):
    """
    List rental contracts with filtering and pagination.

    Default sort: contract_start_date DESC (most recent first), split by property_usage_en.
    """
    return await fetch_rental_contracts(
        limit=limit,
        offset=offset,
        property_usage=property_usage,
        property_type=property_type,
        property_sub_type=property_sub_type,
        tenant_type=tenant_type,
        contract_reg_type=contract_reg_type,
        area=area,
        project=project,
        timeframe_days=timeframe_days,
        area_min=area_min,
        area_max=area_max,
        rent_min=rent_min,
        rent_max=rent_max,
    )


@router.get("/sales/export")
async def export_sales_transactions_endpoint(
    context: AuthContext = Depends(require_active_subscription),
    transaction_ids: str = Query(
        default=None,
        description="Comma-separated transaction IDs (overrides filters and limit)",
    ),
    # Category filters
    property_usage: str = Query(default=None, description="Residential or Commercial"),
    property_type: str = Query(default=None, description="Property type"),
    property_sub_type: str = Query(default=None, description="Property sub-type"),
    rooms: str = Query(default=None, description="Number of rooms"),
    registration_type: str = Query(default=None, description="Registration type"),
    # Location filters
    area: str = Query(default=None, description="Area name"),
    project: str = Query(default=None, description="Project name"),
    building: str = Query(default=None, description="Building name"),
    # Range filters
    timeframe_days: int = Query(default=None, description="Days back from today"),
    area_min: float = Query(default=None, description="Minimum property area (sqm)"),
    area_max: float = Query(default=None, description="Maximum property area (sqm)"),
    price_min: float = Query(default=None, description="Minimum price"),
    price_max: float = Query(default=None, description="Maximum price"),
    price_per_sqm_min: float = Query(default=None, description="Minimum price per sqm"),
    price_per_sqm_max: float = Query(default=None, description="Maximum price per sqm"),
):
    """
    Export sales transactions to Excel.

    Limit: 100 rows max (or specific transaction_ids if provided).
    """
    stream = await export_sales_transactions(
        transaction_ids=transaction_ids,
        property_usage=property_usage,
        property_type=property_type,
        property_sub_type=property_sub_type,
        rooms=rooms,
        registration_type=registration_type,
        area=area,
        project=project,
        building=building,
        timeframe_days=timeframe_days,
        area_min=area_min,
        area_max=area_max,
        price_min=price_min,
        price_max=price_max,
        price_per_sqm_min=price_per_sqm_min,
        price_per_sqm_max=price_per_sqm_max,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"sales_transactions_{timestamp}.xlsx"

    return StreamingResponse(
        iter([stream.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/rentals/export")
async def export_rental_contracts_endpoint(
    context: AuthContext = Depends(require_active_subscription),
    contract_ids: str = Query(
        default=None,
        description="Comma-separated contract IDs (overrides filters and limit)",
    ),
    # Category filters
    property_usage: str = Query(default=None, description="Residential or Commercial"),
    property_type: str = Query(default=None, description="Property type (ejari)"),
    property_sub_type: str = Query(
        default=None, description="Property sub-type (ejari)"
    ),
    tenant_type: str = Query(default=None, description="Tenant type"),
    contract_reg_type: str = Query(
        default=None, description="Contract registration type"
    ),
    # Location filters
    area: str = Query(default=None, description="Area name"),
    project: str = Query(default=None, description="Project name"),
    # Range filters
    timeframe_days: int = Query(default=None, description="Days back from today"),
    area_min: float = Query(default=None, description="Minimum property area (sqm)"),
    area_max: float = Query(default=None, description="Maximum property area (sqm)"),
    rent_min: float = Query(default=None, description="Minimum annual rent"),
    rent_max: float = Query(default=None, description="Maximum annual rent"),
):
    """
    Export rental contracts to Excel.

    Limit: 100 rows max (or specific contract_ids if provided).
    """
    stream = await export_rental_contracts(
        contract_ids=contract_ids,
        property_usage=property_usage,
        property_type=property_type,
        property_sub_type=property_sub_type,
        tenant_type=tenant_type,
        contract_reg_type=contract_reg_type,
        area=area,
        project=project,
        timeframe_days=timeframe_days,
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
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )
