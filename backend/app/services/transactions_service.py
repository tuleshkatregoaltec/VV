from sqlmodel import select, func, col
from sqlmodel.ext.asyncio.session import AsyncSession
from datetime import datetime, timedelta
from typing import List, Any

from backend.app.db.models import Transaction, RentContract
from backend.app.schemas.transactions import (
    TransactionResponse,
    TransactionListResponse,
    RentalContractResponse,
    RentalContractListResponse,
    FilterOptionsResponse,
    NumericRange,
)

# --- Helper: Query Builders ---


def apply_sales_filters(base_where: List[Any], **filters) -> List[Any]:
    filter_mapping = {
        "trans_group": Transaction.trans_group_en,
        "property_usage": Transaction.property_usage_en,
        "master_project": Transaction.master_project_en,
        "timeframe_days": lambda value: Transaction.instance_date is not None
        and Transaction.instance_date >= (datetime.now() - timedelta(days=value)),
        "project": Transaction.project_name_en,
        "building": Transaction.building_name_en,
        "property_type": Transaction.property_type_en,
        "rooms": Transaction.rooms_en,
        "property_sub_type": Transaction.property_sub_type_en,
        "registration_type": Transaction.reg_type_en,
    }
    
    # Range filter mappings
    range_filters = {
        "area_min": lambda v: Transaction.procedure_area >= v,
        "area_max": lambda v: Transaction.procedure_area <= v,
        "price_min": lambda v: Transaction.actual_worth >= v,
        "price_max": lambda v: Transaction.actual_worth <= v,
        "price_sqft_min": lambda v: Transaction.meter_sale_price >= v,
        "price_sqft_max": lambda v: Transaction.meter_sale_price <= v,
    }
    
    for key, value in filters.items():
        if value is not None:
            if key == "timeframe_days":
                base_where.append(filter_mapping[key](value))
            elif key in range_filters:
                base_where.append(range_filters[key](value))
            elif key in filter_mapping:
                base_where.append(filter_mapping[key] == value)
    return base_where


def apply_rental_filters(base_where: List[Any], **filters) -> List[Any]:
    filter_mapping = {
        "master_project": RentContract.master_project_en,
        "timeframe_days": lambda value: RentContract.contract_start_date is not None
        and RentContract.contract_start_date
        >= (datetime.now() - timedelta(days=value)),
        "project": RentContract.project_name_en,
        "property_type": RentContract.ejari_property_type_en,
        "property_sub_type": RentContract.ejari_property_sub_type_en,
        "tenant_type": RentContract.tenant_type_en,
        "contract_reg_type": RentContract.contract_reg_type_en,
    }
    
    # Range filter mappings for rentals
    range_filters = {
        "area_min": lambda v: RentContract.actual_area >= v,
        "area_max": lambda v: RentContract.actual_area <= v,
        "rent_min": lambda v: RentContract.annual_amount >= v,
        "rent_max": lambda v: RentContract.annual_amount <= v,
    }
    
    for key, value in filters.items():
        if value is not None:
            if key == "timeframe_days":
                base_where.append(filter_mapping[key](value))
            elif key in range_filters:
                base_where.append(range_filters[key](value))
            elif key in filter_mapping:
                base_where.append(filter_mapping[key] == value)
    return base_where


# --- Helper: Aggregations ---


async def get_distinct_values(
    session: AsyncSession, column, base_where: List[Any]
) -> List[str]:
    stmt = (
        select(column)
        .where(*base_where, column is not None, column != "")
        .distinct()
        .order_by(column)
    )
    result = await session.exec(stmt)
    return [row for row in result.all() if row]


async def get_numeric_range(
    session: AsyncSession, column, base_where: List[Any]
) -> NumericRange:
    min_result = await session.exec(select(func.min(column)).where(*base_where))
    min_val = min_result.one()
    max_result = await session.exec(select(func.max(column)).where(*base_where))
    max_val = max_result.one()
    return NumericRange(min=min_val, max=max_val)


# --- Main Service Functions: Sales ---


async def fetch_sales_transactions(
    session: AsyncSession, limit: int, offset: int, **filters
) -> TransactionListResponse:
    base_where = apply_sales_filters([], **filters)

    # Fetch Data
    statement = (
        select(Transaction)
        .where(*base_where)
        .order_by(col(Transaction.instance_date).desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.exec(statement)
    transactions = result.all()

    # Fetch Count
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


async def fetch_sales_filter_options(
    session: AsyncSession, **filters
) -> FilterOptionsResponse:
    base_where = apply_sales_filters([], **filters)

    return FilterOptionsResponse(
        projects=await get_distinct_values(
            session, Transaction.project_name_en, base_where
        ),
        buildings=await get_distinct_values(
            session, Transaction.building_name_en, base_where
        ),
        property_types=await get_distinct_values(
            session, Transaction.property_type_en, base_where
        ),
        property_sub_types=await get_distinct_values(
            session, Transaction.property_sub_type_en, base_where
        ),
        master_projects=await get_distinct_values(
            session, Transaction.master_project_en, base_where
        ),
        rooms=await get_distinct_values(session, Transaction.rooms_en, base_where),
        registration_types=await get_distinct_values(
            session, Transaction.reg_type_en, base_where
        ),
        area_range=await get_numeric_range(
            session, Transaction.procedure_area, base_where
        ),
        price_range=await get_numeric_range(
            session, Transaction.actual_worth, base_where
        ),
        price_per_sqft_range=await get_numeric_range(
            session, Transaction.meter_sale_price, base_where
        ),
    )


# --- Main Service Functions: Rentals ---


async def fetch_rental_contracts(
    session: AsyncSession, limit: int, offset: int, **filters
) -> RentalContractListResponse:
    base_where = apply_rental_filters([], **filters)

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


async def fetch_rental_filter_options(
    session: AsyncSession, **filters
) -> FilterOptionsResponse:
    base_where = apply_rental_filters([], **filters)

    return FilterOptionsResponse(
        projects=await get_distinct_values(
            session, RentContract.project_name_en, base_where
        ),
        property_types=await get_distinct_values(
            session, RentContract.ejari_property_type_en, base_where
        ),
        property_sub_types=await get_distinct_values(
            session, RentContract.ejari_property_sub_type_en, base_where
        ),
        tenant_types=await get_distinct_values(
            session, RentContract.tenant_type_en, base_where
        ),
        contract_reg_types=await get_distinct_values(
            session, RentContract.contract_reg_type_en, base_where
        ),
        area_range=await get_numeric_range(
            session, RentContract.actual_area, base_where
        ),
        annual_rent_range=await get_numeric_range(
            session, RentContract.annual_amount, base_where
        ),
    )
