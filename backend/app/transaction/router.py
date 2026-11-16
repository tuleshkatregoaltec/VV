"""DXBI transaction listing and export endpoints (the Transactions pages)."""

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.core.decorators import cached_endpoint
from app.core.dependencies import AuthContext, require_active_subscription
from app.transaction.dependencies import rental_filters, sales_filters
from app.transaction.exports import (
    ExportFile,
    export_rental_contracts,
    export_sales_transactions,
)
from app.transaction.models import (
    MAX_OFFSET,
    MAX_PAGE_SIZE,
    MAX_SELECTED_EXPORT_IDS,
    RentalContractListResponse,
    RentalFilters,
    SalesFilters,
    TransactionListResponse,
)
from app.transaction.service import fetch_rental_contracts, fetch_sales_transactions

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])


def _page_size():
    return Query(default=30, ge=1, le=MAX_PAGE_SIZE, description="Page size")


def _offset():
    return Query(default=0, ge=0, le=MAX_OFFSET, description="Page offset")


def _selected_ids(value: Optional[str], name: str) -> Optional[str]:
    """Selected rows for an export: at most MAX_SELECTED_EXPORT_IDS ids, else a 422."""
    if value is not None and len([item for item in value.split(",") if item.strip()]) > (
        MAX_SELECTED_EXPORT_IDS
    ):
        raise HTTPException(
            status_code=422,
            detail=f"{name} accepts at most {MAX_SELECTED_EXPORT_IDS:,} ids; "
            "export the filtered rows instead",
        )
    return value


def _file_response(export: ExportFile, *, name: str, export_format: str) -> StreamingResponse:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    headers = export.headers()
    return StreamingResponse(
        export.chunks(),
        media_type=export.media_type,
        headers={
            "Content-Disposition": f"attachment; filename={name}_{timestamp}.{export_format}",
            **headers,
            "Access-Control-Expose-Headers": ", ".join(["Content-Disposition", *headers]),
        },
    )


@router.get("/sales", response_model=TransactionListResponse)
@cached_endpoint(prefix="transactions:dxbi-sales:v5", expire=600, daily=True)
async def get_sales_transactions(
    context: AuthContext = Depends(require_active_subscription),
    limit: int = _page_size(),
    offset: int = _offset(),
    filters: SalesFilters = Depends(sales_filters),
):
    """DXBI sales, newest first (transaction date, then id, both descending)."""
    return await fetch_sales_transactions(filters, limit, offset)


@router.get("/rentals", response_model=RentalContractListResponse)
@cached_endpoint(prefix="transactions:dxbi-rentals:v5", expire=600, daily=True)
async def get_rental_contracts(
    context: AuthContext = Depends(require_active_subscription),
    limit: int = _page_size(),
    offset: int = _offset(),
    filters: RentalFilters = Depends(rental_filters),
):
    """DXBI leases, latest start first (lease start, then id, both descending)."""
    return await fetch_rental_contracts(filters, limit, offset)


@router.get("/sales/export", response_class=StreamingResponse)
async def export_sales_transactions_endpoint(
    context: AuthContext = Depends(require_active_subscription),
    export_format: Literal["xlsx", "csv"] = Query(
        default="xlsx", alias="format", description="Export file format: xlsx or csv"
    ),
    transaction_ids: Optional[str] = Query(
        default=None,
        max_length=100_000,
        description="Comma-separated transaction IDs, at most 1,000 (overrides the filters)",
    ),
    filters: SalesFilters = Depends(sales_filters),
):
    """DXBI sales as Excel or CSV: up to 50,000 filtered rows, or the selected ids. When more
    rows match, X-Export-Truncated is true and the file says so."""
    transaction_ids = _selected_ids(transaction_ids, "transaction_ids")
    export = await export_sales_transactions(filters, transaction_ids, export_format)
    return _file_response(export, name="sales_transactions", export_format=export_format)


@router.get("/rentals/export", response_class=StreamingResponse)
async def export_rental_contracts_endpoint(
    context: AuthContext = Depends(require_active_subscription),
    export_format: Literal["xlsx", "csv"] = Query(
        default="xlsx", alias="format", description="Export file format: xlsx or csv"
    ),
    contract_ids: Optional[str] = Query(
        default=None,
        max_length=100_000,
        description="Comma-separated contract IDs, at most 1,000 (overrides the filters)",
    ),
    filters: RentalFilters = Depends(rental_filters),
):
    """DXBI leases as Excel or CSV: up to 50,000 filtered rows, or the selected ids. When more
    rows match, X-Export-Truncated is true and the file says so."""
    contract_ids = _selected_ids(contract_ids, "contract_ids")
    export = await export_rental_contracts(filters, contract_ids, export_format)
    return _file_response(export, name="rental_contracts", export_format=export_format)
