from fastapi import APIRouter, Query, Depends
from sqlmodel import select, func, col
from datetime import datetime, timedelta

from backend.app.core.cache import RedisCache
from backend.app.db.models import Transaction, RentContract
from backend.app.db.session import get_db_session
from backend.app.schemas.transactions import (
    TransactionResponse,
    TransactionListResponse,
    RentalContractResponse,
    RentalContractListResponse,
    FilterOptionsResponse,
    NumericRange,
)
from backend.app.routers.dependencies import require_auth

cache = RedisCache()
router = APIRouter(prefix="/transactions", tags=["transactions"])


def apply_filters(base_where, **filters):
    # Sales filter mapping
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


def apply_rental_filters(base_where, **filters):
    # Rentals filter mapping, match only frontend columns
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


def construct_cache_key(prefix, **params):
    return (
        prefix
        + ":"
        + ":".join(
            f"{key}={value if value is not None else 'all'}"
            for key, value in params.items()
        )
    )


def get_distinct_values(session, column, base_where):
    stmt = (
        select(column)
        .where(
            *base_where,
            column != None,  # type: ignore
            column != "",
        )
        .distinct()
        .order_by(column)
    )
    return [row for row in session.exec(stmt).all() if row]


def get_numeric_range(session, column, base_where):
    min_value = session.exec(select(func.min(column)).where(*base_where)).one()
    max_value = session.exec(select(func.max(column)).where(*base_where)).one()
    return NumericRange(min=min_value, max=max_value)


# --- SALES ENDPOINTS ---
@router.get("/sales", response_model=TransactionListResponse)
async def get_sales_transactions(
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
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
    current_user: dict = Depends(require_auth),
    session=Depends(get_db_session),
):
    cache_key = construct_cache_key(
        "sales",
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
    )
    cached = await cache.get(cache_key)
    if cached:
        return TransactionListResponse(**cached)

    base_where = apply_filters(
        [],
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
    )
    statement = (
        select(Transaction)
        .where(*base_where)
        .order_by(col(Transaction.instance_date).desc())
        .limit(limit)
        .offset(offset)
    )
    transactions = session.exec(statement).all()
    total = session.exec(
        select(func.count()).select_from(Transaction).where(*base_where)
    ).one()
    resp = TransactionListResponse(
        transactions=[TransactionResponse.model_validate(t) for t in transactions],
        total=total,
        limit=limit,
        offset=offset,
    )
    await cache.set(cache_key, resp.model_dump())
    return resp


@router.get("/sales/filter-options", response_model=FilterOptionsResponse)
async def get_sales_filter_options(
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
    current_user: dict = Depends(require_auth),
    session=Depends(get_db_session),
):
    cache_key = construct_cache_key(
        "sales:filter-options",
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
    )
    cached = await cache.get(cache_key)
    if cached:
        return FilterOptionsResponse(**cached)

    base_where = apply_filters(
        [],
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
    )
    resp = FilterOptionsResponse(
        projects=get_distinct_values(session, Transaction.project_name, base_where),
        buildings=get_distinct_values(session, Transaction.building_name, base_where),
        property_types=get_distinct_values(
            session, Transaction.property_type, base_where
        ),
        property_sub_types=get_distinct_values(
            session, Transaction.property_sub_type, base_where
        ),
        rooms=get_distinct_values(session, Transaction.rooms_description, base_where),
        registration_types=get_distinct_values(
            session, Transaction.reg_type, base_where
        ),
        area_range=get_numeric_range(session, Transaction.procedure_area, base_where),
        price_range=get_numeric_range(session, Transaction.actual_worth, base_where),
        price_per_sqft_range=get_numeric_range(
            session, Transaction.meter_sale_price, base_where
        ),
    )
    await cache.set(cache_key, resp.model_dump())
    return resp


# --- RENTALS ENDPOINTS ---
@router.get("/rentals", response_model=RentalContractListResponse)
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
    current_user: dict = Depends(require_auth),
    session=Depends(get_db_session),
):
    cache_key = construct_cache_key(
        "rentals",
        limit=limit,
        offset=offset,
        master_project=master_project,
        timeframe_days=timeframe_days,
        project=project,
        property_type=property_type,
        property_sub_type=property_sub_type,
        tenant_type=tenant_type,
        contract_reg_type=contract_reg_type,
    )
    cached = await cache.get(cache_key)
    if cached:
        return RentalContractListResponse(**cached)

    base_where = apply_rental_filters(
        [],
        master_project=master_project,
        timeframe_days=timeframe_days,
        project=project,
        property_type=property_type,
        property_sub_type=property_sub_type,
        tenant_type=tenant_type,
        contract_reg_type=contract_reg_type,
    )
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
    resp = RentalContractListResponse(
        contracts=[RentalContractResponse.model_validate(c) for c in contracts],
        total=total,
        limit=limit,
        offset=offset,
    )
    await cache.set(cache_key, resp.model_dump())
    return resp


@router.get(
    "/rentals/filter-options", response_model=FilterOptionsResponse
)
async def get_rental_filter_options(
    master_project: str = Query(default=None),
    timeframe_days: int = Query(default=None),
    project: str = Query(default=None),
    property_type: str = Query(default=None),
    property_sub_type: str = Query(default=None),
    tenant_type: str = Query(default=None),
    contract_reg_type: str = Query(default=None),
    current_user: dict = Depends(require_auth),
    session=Depends(get_db_session),
):
    cache_key = construct_cache_key(
        "rentals:filter-options",
        master_project=master_project,
        timeframe_days=timeframe_days,
        project=project,
        property_type=property_type,
        property_sub_type=property_sub_type,
        tenant_type=tenant_type,
        contract_reg_type=contract_reg_type,
    )
    cached = await cache.get(cache_key)
    if cached:
        return FilterOptionsResponse(**cached)

    base_where = apply_rental_filters(
        [],
        master_project=master_project,
        timeframe_days=timeframe_days,
        project=project,
        property_type=property_type,
        property_sub_type=property_sub_type,
        tenant_type=tenant_type,
        contract_reg_type=contract_reg_type,
    )
    resp = FilterOptionsResponse(
        projects=get_distinct_values(session, RentContract.project_name, base_where),
        property_types=get_distinct_values(
            session, RentContract.ejari_property_type, base_where
        ),
        property_sub_types=get_distinct_values(
            session, RentContract.ejari_property_sub_type, base_where
        ),
        tenant_types=get_distinct_values(session, RentContract.tenant_type, base_where),
        contract_reg_types=get_distinct_values(
            session, RentContract.contract_reg_type, base_where
        ),
        area_range=get_numeric_range(session, RentContract.actual_area, base_where),
        annual_rent_range=get_numeric_range(
            session, RentContract.annual_amount, base_where
        ),
    )
    await cache.set(cache_key, resp.model_dump())
    return resp
