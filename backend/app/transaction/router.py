"""DXBI transaction listing and export endpoints (the Transactions pages)."""

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.decorators import cached_endpoint
from app.core.dependencies import AuthContext, require_active_subscription
from app.transaction.dependencies import rental_filters, sales_filters
from app.transaction.exports import export_rental_contracts, export_sales_transactions
from app.transaction.models import (
    RentalContractListResponse,
    RentalFilters,
    SalesFilters,
    TransactionListResponse,
)
from app.transaction.service import fetch_rental_contracts, fetch_sales_transactions

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])


def _file_response(stream, *, name: str, export_format: str) -> StreamingResponse:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    media_type = (
        "text/csv; charset=utf-8"
        if export_format == "csv"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return StreamingResponse(
        iter([stream.getvalue()]),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename={name}_{timestamp}.{export_format}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/sales", response_model=TransactionListResponse)
@cached_endpoint(prefix="transactions:dxbi-sales:v2", expire=600)
async def get_sales_transactions(
    context: AuthContext = Depends(require_active_subscription),
    limit: int = Query(default=30, ge=1, le=1000, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    filters: SalesFilters = Depends(sales_filters),
):
    """DXBI sales, newest first (transaction date, then id)."""
    return await fetch_sales_transactions(filters, limit, offset)


@router.get("/rentals", response_model=RentalContractListResponse)
@cached_endpoint(prefix="transactions:dxbi-rentals:v2", expire=600)
async def get_rental_contracts(
    context: AuthContext = Depends(require_active_subscription),
    limit: int = Query(default=30, ge=1, le=1000, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    filters: RentalFilters = Depends(rental_filters),
):
    """DXBI leases, latest start first (lease start, then id)."""
    return await fetch_rental_contracts(filters, limit, offset)


@router.get("/sales/export", response_class=StreamingResponse)
async def export_sales_transactions_endpoint(
    context: AuthContext = Depends(require_active_subscription),
    export_format: Literal["xlsx", "csv"] = Query(
        default="xlsx", alias="format", description="Export file format: xlsx or csv"
    ),
    transaction_ids: Optional[str] = Query(
        default=None, description="Comma-separated transaction IDs (overrides filters and limit)"
    ),
    filters: SalesFilters = Depends(sales_filters),
):
    """DXBI sales as Excel or CSV: up to 50,000 filtered rows, or the selected ids."""
    stream = await export_sales_transactions(filters, transaction_ids, export_format)
    return _file_response(stream, name="sales_transactions", export_format=export_format)


@router.get("/rentals/export", response_class=StreamingResponse)
async def export_rental_contracts_endpoint(
    context: AuthContext = Depends(require_active_subscription),
    export_format: Literal["xlsx", "csv"] = Query(
        default="xlsx", alias="format", description="Export file format: xlsx or csv"
    ),
    contract_ids: Optional[str] = Query(
        default=None, description="Comma-separated contract IDs (overrides filters and limit)"
    ),
    filters: RentalFilters = Depends(rental_filters),
):
    """DXBI leases as Excel or CSV: up to 50,000 filtered rows, or the selected ids."""
    stream = await export_rental_contracts(filters, contract_ids, export_format)
    return _file_response(stream, name="rental_contracts", export_format=export_format)
