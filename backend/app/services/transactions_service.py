from sqlmodel import Session, select, func, col
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
        "trans_group": Transaction.trans_group,
        "property_usage": Transaction.property_usage,
        "master_project": Transaction.master_project,
        "timeframe_days": lambda value: Transaction.instance_date is not None
        and Transaction.instance_date >= (datetime.now() - timedelta(days=value)),
        "project": Transaction.project_name,
        "building": Transaction.building_name,
        "property_type": Transaction.property_type,
        "rooms": Transaction.rooms_description,
        "property_sub_type": Transaction.property_sub_type,
        "registration_type": Transaction.reg_type,
    }
    for key, value in filters.items():
        if value is not None:
            if key == "timeframe_days":
                base_where.append(filter_mapping[key](value))
            else:
                base_where.append(filter_mapping[key] == value)
    return base_where

def apply_rental_filters(base_where: List[Any], **filters) -> List[Any]:
    filter_mapping = {
        "master_project": RentContract.master_project,
        "timeframe_days": lambda value: RentContract.contract_start_date is not None
        and RentContract.contract_start_date
        >= (datetime.now() - timedelta(days=value)),
        "project": RentContract.project_name,
        "property_type": RentContract.ejari_property_type,
        "property_sub_type": RentContract.ejari_property_sub_type,
        "tenant_type": RentContract.tenant_type,
        "contract_reg_type": RentContract.contract_reg_type,
    }
    for key, value in filters.items():
        if value is not None:
            if key == "timeframe_days":
                base_where.append(filter_mapping[key](value))
            else:
                base_where.append(filter_mapping[key] == value)
    return base_where

# --- Helper: Aggregations ---

def get_distinct_values(session: Session, column, base_where: List[Any]) -> List[str]:
    stmt = (
        select(column)
        .where(*base_where, column != None, column != "")
        .distinct()
        .order_by(column)
    )
    return [row for row in session.exec(stmt).all() if row]

def get_numeric_range(session: Session, column, base_where: List[Any]) -> NumericRange:
    min_val = session.exec(select(func.min(column)).where(*base_where)).one()
    max_val = session.exec(select(func.max(column)).where(*base_where)).one()
    return NumericRange(min=min_val, max=max_val)

# --- Main Service Functions: Sales ---

def fetch_sales_transactions(
    session: Session, 
    limit: int, 
    offset: int, 
    **filters
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
    transactions = session.exec(statement).all()
    
    # Fetch Count
    total = session.exec(
        select(func.count()).select_from(Transaction).where(*base_where)
    ).one()
    
    return TransactionListResponse(
        transactions=[TransactionResponse.model_validate(t) for t in transactions],
        total=total,
        limit=limit,
        offset=offset,
    )

def fetch_sales_filter_options(session: Session, **filters) -> FilterOptionsResponse:
    base_where = apply_sales_filters([], **filters)
    
    return FilterOptionsResponse(
        projects=get_distinct_values(session, Transaction.project_name, base_where),
        buildings=get_distinct_values(session, Transaction.building_name, base_where),
        property_types=get_distinct_values(session, Transaction.property_type, base_where),
        property_sub_types=get_distinct_values(session, Transaction.property_sub_type, base_where),
        rooms=get_distinct_values(session, Transaction.rooms_description, base_where),
        registration_types=get_distinct_values(session, Transaction.reg_type, base_where),
        area_range=get_numeric_range(session, Transaction.procedure_area, base_where),
        price_range=get_numeric_range(session, Transaction.actual_worth, base_where),
        price_per_sqft_range=get_numeric_range(session, Transaction.meter_sale_price, base_where),
    )

# --- Main Service Functions: Rentals ---

def fetch_rental_contracts(
    session: Session, 
    limit: int, 
    offset: int, 
    **filters
) -> RentalContractListResponse:
    
    base_where = apply_rental_filters([], **filters)
    
    statement = (
        select(RentContract)
        .where(*base_where)
        .order_by(col(RentContract.contract_start_date).desc())
        .limit(limit)
        .offset(offset)
    )
    contracts = session.exec(statement).all()
    
    total = session.exec(
        select(func.count()).select_from(RentContract).where(*base_where)
    ).one()
    
    return RentalContractListResponse(
        contracts=[RentalContractResponse.model_validate(c) for c in contracts],
        total=total,
        limit=limit,
        offset=offset,
    )

def fetch_rental_filter_options(session: Session, **filters) -> FilterOptionsResponse:
    base_where = apply_rental_filters([], **filters)
    
    return FilterOptionsResponse(
        projects=get_distinct_values(session, RentContract.project_name, base_where),
        property_types=get_distinct_values(session, RentContract.ejari_property_type, base_where),
        property_sub_types=get_distinct_values(session, RentContract.ejari_property_sub_type, base_where),
        tenant_types=get_distinct_values(session, RentContract.tenant_type, base_where),
        contract_reg_types=get_distinct_values(session, RentContract.contract_reg_type, base_where),
        area_range=get_numeric_range(session, RentContract.actual_area, base_where),
        annual_rent_range=get_numeric_range(session, RentContract.annual_amount, base_where),
    )
