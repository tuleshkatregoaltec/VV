"""Service for fetching sales and rental transaction data."""

from sqlmodel import select, func, col
from sqlmodel.ext.asyncio.session import AsyncSession
import pandas as pd
from io import BytesIO

from backend.app.db.models import Transaction, RentContract
from backend.app.schemas.transactions import (
    TransactionResponse,
    TransactionListResponse,
    RentalContractResponse,
    RentalContractListResponse,
)
from backend.app.services.filter_builder import FilterBuilder


async def fetch_sales_transactions(
    session: AsyncSession, limit: int, offset: int, **filters
) -> TransactionListResponse:
    """Fetch paginated sales transactions with applied filters."""

    base_where = FilterBuilder.build_sales_filters([], **filters)

    # Fetch data
    statement = (
        select(Transaction)
        .where(*base_where)
        .order_by(col(Transaction.instance_date).desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.exec(statement)
    transactions = result.all()

    # Fetch count
    count_result = await session.exec(
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
    session: AsyncSession, limit: int, offset: int, **filters
) -> RentalContractListResponse:
    """Fetch paginated rental contracts with applied filters."""

    base_where = FilterBuilder.build_rental_filters([], **filters)

    statement = (
        select(RentContract)
        .where(*base_where)
        .order_by(col(RentContract.contract_start_date).desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.exec(statement)
    contracts = result.all()

    count_result = await session.exec(
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
    session: AsyncSession, max_rows: int = 10000, **filters
) -> BytesIO:
    """Export sales transactions to Excel format with applied filters."""
    
    base_where = FilterBuilder.build_sales_filters([], **filters)
    
    # Fetch data with export limit
    statement = (
        select(Transaction)
        .where(*base_where)
        .order_by(col(Transaction.instance_date).desc())
        .limit(max_rows)
    )
    result = await session.exec(statement)
    transactions = result.all()
    
    # Convert to DataFrame
    data = [t.model_dump() for t in transactions]
    df = pd.DataFrame(data)
    
    # Select and order relevant columns for export
    export_columns = [
        'instance_date',
        'trans_group_en',
        'property_usage_en',
        'master_project_en',
        'project_name_en',
        'building_name_en',
        'property_type_en',
        'property_sub_type_en',
        'rooms_en',
        'procedure_area',
        'actual_worth',
        'meter_sale_price',
        'reg_type_en',
        'nearest_landmark_en',
        'nearest_metro_en',
        'nearest_mall_en',
    ]
    
    # Only include columns that exist in the dataframe
    available_columns = [col for col in export_columns if col in df.columns]
    df = df[available_columns]
    
    # Write to BytesIO (Excel requires binary mode)
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sales Transactions')
    stream.seek(0)
    
    return stream


async def export_rental_contracts(
    session: AsyncSession, max_rows: int = 10000, **filters
) -> BytesIO:
    """Export rental contracts to Excel format with applied filters."""
    
    base_where = FilterBuilder.build_rental_filters([], **filters)
    
    # Fetch data with export limit
    statement = (
        select(RentContract)
        .where(*base_where)
        .order_by(col(RentContract.contract_start_date).desc())
        .limit(max_rows)
    )
    result = await session.exec(statement)
    contracts = result.all()
    
    # Convert to DataFrame
    data = [c.model_dump() for c in contracts]
    df = pd.DataFrame(data)
    
    # Select and order relevant columns for export
    export_columns = [
        'contract_start_date',
        'contract_end_date',
        'property_usage_en',
        'master_project_en',
        'project_name_en',
        'ejari_property_type_en',
        'ejari_property_sub_type_en',
        'actual_area',
        'annual_amount',
        'tenant_type_en',
        'contract_reg_type_en',
        'nearest_landmark_en',
        'nearest_metro_en',
        'nearest_mall_en',
    ]
    
    # Only include columns that exist in the dataframe
    available_columns = [col for col in export_columns if col in df.columns]
    df = df[available_columns]
    
    # Write to BytesIO (Excel requires binary mode)
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Rental Contracts')
    stream.seek(0)
    
    return stream