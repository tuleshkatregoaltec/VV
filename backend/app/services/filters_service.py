"""Service for fetching filter options based on current selections."""

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import List, Any, Optional
import asyncio
import time

from backend.app.db.session import async_session
from backend.app.db.models import Transaction, RentContract
from backend.app.schemas.filters import FilterOptionsResponse
from backend.app.services.filter_builder import FilterBuilder


async def get_distinct_values(
    session: AsyncSession, column, base_where: List[Any], limit: int = 250
) -> List[str]:
    """Fetch distinct non-null values from a column with filters applied."""
    stmt = (
        select(column)
        .where(*base_where, column.isnot(None), column != "")
        .distinct()
        .order_by(column)
        .limit(limit)
    )
    result = await session.exec(stmt)
    # FIX 1: Use list comprehension instead of double iteration
    return [str(row) for row in result if row]


async def _get_distinct_with_new_session(
    column, base_where: List[Any], limit: int = 250
) -> List[str]:
    """Execute get_distinct_values in a fresh session for safe concurrency."""
    start = time.perf_counter()  # FIX 2: Use perf_counter for better precision

    async with async_session() as session:
        result = await get_distinct_values(session, column, base_where, limit=limit)

    elapsed = time.perf_counter() - start
    if elapsed > 0.1:
        # FIX 3: Add filter context for better debugging
        print(f"SLOW QUERY ({elapsed:.3f}s): {column.key} | filters={len(base_where)}")

    return result


async def fetch_sales_filter_options(
    session: AsyncSession, **filters
) -> FilterOptionsResponse:
    """Fetch available filter options for sales, excluding self-filters."""

    def get_constraints(exclude_key: Optional[str] = None) -> List[Any]:
        """Build WHERE clause, optionally excluding one filter to prevent self-filtering."""
        filters_copy = filters.copy()
        if exclude_key:  # FIX 4: No need to check 'in' dict - just set to None
            filters_copy[exclude_key] = None
        return FilterBuilder.build_sales_filters([], **filters_copy)

    # Define filter column mappings
    filter_tasks = [
        (Transaction.project_name_en, "project"),
        (Transaction.building_name_en, "building"),
        (Transaction.property_type_en, "property_type"),
        (Transaction.property_sub_type_en, "property_sub_type"),
        (Transaction.master_project_en, "master_project"),
        (Transaction.rooms_en, "rooms"),
        (Transaction.reg_type_en, "registration_type"),
    ]

    # Execute all queries concurrently
    results = await asyncio.gather(
        *[
            _get_distinct_with_new_session(column, get_constraints(exclude_key))
            for column, exclude_key in filter_tasks
        ]
    )

    return FilterOptionsResponse(
        projects=results[0],
        buildings=results[1],
        property_types=results[2],
        property_sub_types=results[3],
        master_projects=results[4],
        rooms=results[5],
        registration_types=results[6],
    )


async def fetch_rental_filter_options(
    session: AsyncSession, **filters
) -> FilterOptionsResponse:
    """Fetch available filter options for rentals, excluding self-filters."""

    def get_constraints(exclude_key: Optional[str] = None) -> List[Any]:
        """Build WHERE clause, optionally excluding one filter to prevent self-filtering."""
        filters_copy = filters.copy()
        if exclude_key:
            filters_copy[exclude_key] = None
        return FilterBuilder.build_rental_filters([], **filters_copy)

    # Define filter column mappings
    filter_tasks = [
        (RentContract.project_name_en, "project"),
        (RentContract.ejari_property_type_en, "property_type"),
        (RentContract.ejari_property_sub_type_en, "property_sub_type"),
        (RentContract.tenant_type_en, "tenant_type"),
        (RentContract.contract_reg_type_en, "contract_reg_type"),
    ]

    # Execute all queries concurrently
    results = await asyncio.gather(
        *[
            _get_distinct_with_new_session(column, get_constraints(exclude_key))
            for column, exclude_key in filter_tasks
        ]
    )

    return FilterOptionsResponse(
        projects=results[0],
        property_types=results[1],
        property_sub_types=results[2],
        tenant_types=results[3],
        contract_reg_types=results[4],
    )
