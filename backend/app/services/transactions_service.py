"""Service for fetching sales and rental transaction data."""

from sqlmodel import select, func, col
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import List, Any

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
