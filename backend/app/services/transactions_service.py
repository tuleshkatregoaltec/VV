"""Service for fetching sales and rental transaction data."""

from io import BytesIO

import pandas as pd
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.models import RentContract, Transaction
from app.schemas.transactions import (
    RentalContractListResponse,
    RentalContractResponse,
    TransactionListResponse,
    TransactionResponse,
)
from app.services.filter_builder import FilterBuilder


async def fetch_sales_transactions(
    db: AsyncSession, limit: int, offset: int, **filters
) -> TransactionListResponse:
    """Fetch paginated sales transactions with applied filters."""

    base_where = FilterBuilder.build_sales_filters([], **filters)

    stmt = (
        select(Transaction)
        .where(*base_where)
        .order_by(col(Transaction.instance_date).desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.exec(stmt)
    transactions = result.all()

    count_result = await db.exec(
        select(func.count()).select_from(Transaction).where(*base_where)
    )
    total = count_result.one()

    return TransactionListResponse(
        transactions=[TransactionResponse.model_validate(t) for t in transactions],
        total=total,
        limit=limit,
        offset=offset,
    )


async def fetch_rental_contracts(
    db: AsyncSession, limit: int, offset: int, **filters
) -> RentalContractListResponse:
    """Fetch paginated rental contracts with applied filters."""

    base_where = FilterBuilder.build_rental_filters([], **filters)

    stmt = (
        select(RentContract)
        .where(*base_where)
        .order_by(col(RentContract.contract_start_date).desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.exec(stmt)
    contracts = result.all()

    count_result = await db.exec(
        select(func.count()).select_from(RentContract).where(*base_where)
    )
    total = count_result.one()

    return RentalContractListResponse(
        contracts=[RentalContractResponse.model_validate(c) for c in contracts],
        total=total,
        limit=limit,
        offset=offset,
    )


async def export_sales_transactions(
    db: AsyncSession, max_rows: int = 10000, transaction_ids: str = None, **filters
) -> BytesIO:
    """Export sales transactions to Excel format with applied filters or specific IDs.

    Args:
        db: Database session
        max_rows: Maximum rows to export (default 10000, but will be limited to 100 when no IDs provided)
        transaction_ids: Comma-separated transaction IDs to export (overrides filters and limits)
        **filters: Filter parameters for querying transactions
    """

    if transaction_ids:
        # Export specific transactions by ID (ignore filters and limits)
        id_list = [id.strip() for id in transaction_ids.split(',') if id.strip()]

        stmt = (
            select(Transaction)
            .where(col(Transaction.transaction_id).in_(id_list))
            .order_by(col(Transaction.instance_date).desc())
        )
    else:
        # Export filtered transactions with 100-row default limit
        base_where = FilterBuilder.build_sales_filters([], **filters)

        # Apply 100-row limit when using default max_rows
        export_limit = 100 if max_rows == 10000 else max_rows

        stmt = (
            select(Transaction)
            .where(*base_where)
            .order_by(col(Transaction.instance_date).desc())
            .limit(export_limit)
        )

    result = await db.exec(stmt)
    transactions = result.all()

    data = [t.model_dump() for t in transactions]
    df = pd.DataFrame(data)

    export_columns = [
        "instance_date",
        "trans_group_en",
        "property_usage_en",
        "master_project_en",
        "project_name_en",
        "building_name_en",
        "property_type_en",
        "property_sub_type_en",
        "rooms_en",
        "procedure_area",
        "actual_worth",
        "meter_sale_price",
        "reg_type_en",
        "nearest_landmark_en",
        "nearest_metro_en",
        "nearest_mall_en",
    ]

    available_columns = [col for col in export_columns if col in df.columns]
    df = df[available_columns]

    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Sales Transactions")
    stream.seek(0)

    return stream


async def export_rental_contracts(
    db: AsyncSession, max_rows: int = 10000, contract_ids: str = None, **filters
) -> BytesIO:
    """Export rental contracts to Excel format with applied filters or specific IDs.

    Args:
        db: Database session
        max_rows: Maximum rows to export (default 10000, but will be limited to 100 when no IDs provided)
        contract_ids: Comma-separated contract IDs to export (overrides filters and limits)
        **filters: Filter parameters for querying rental contracts
    """

    if contract_ids:
        # Export specific contracts by ID (ignore filters and limits)
        id_list = [id.strip() for id in contract_ids.split(',') if id.strip()]

        stmt = (
            select(RentContract)
            .where(col(RentContract.contract_id).in_(id_list))
            .order_by(col(RentContract.contract_start_date).desc())
        )
    else:
        # Export filtered contracts with 100-row default limit
        base_where = FilterBuilder.build_rental_filters([], **filters)

        # Apply 100-row limit when using default max_rows
        export_limit = 100 if max_rows == 10000 else max_rows

        stmt = (
            select(RentContract)
            .where(*base_where)
            .order_by(col(RentContract.contract_start_date).desc())
            .limit(export_limit)
        )

    result = await db.exec(stmt)
    contracts = result.all()

    # Convert to DataFrame
    data = [c.model_dump() for c in contracts]
    df = pd.DataFrame(data)

    # Select and order relevant columns for export
    export_columns = [
        "contract_start_date",
        "contract_end_date",
        "property_usage_en",
        "master_project_en",
        "project_name_en",
        "ejari_property_type_en",
        "ejari_property_sub_type_en",
        "actual_area",
        "annual_amount",
        "tenant_type_en",
        "contract_reg_type_en",
        "nearest_landmark_en",
        "nearest_metro_en",
        "nearest_mall_en",
    ]

    available_columns = [col for col in export_columns if col in df.columns]
    df = df[available_columns]

    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Rental Contracts")
    stream.seek(0)

    return stream
