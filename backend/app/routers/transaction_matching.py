"""
Router for on-demand transaction-to-unit matching.

Endpoints:
- GET /api/v1/transactions/{transaction_id}/match-units - Match transaction to units
- GET /api/v1/transactions/units/{unit_id}/history - Get all transactions for a unit
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.decorators import cached_endpoint
from app.postgres import get_db_session
from app.routers.dependencies import require_auth
from app.schemas.transactions import (
    MatchedUnitsResponse,
    MatchedUnit,
    ComparableTransactionsResponse,
    UnitDetails,
    ComparableTransactionItem,
    TransactionResponse,
)
from app.services.transaction_matching_service import (
    TransactionMatchingService,
    MatchedUnitResult,
)
from app.postgres.models.properties import Unit
from sqlalchemy import select


router = APIRouter(
    prefix="/api/v1/transactions",
    tags=["transaction-matching"],
    dependencies=[Depends(require_auth)],
)


@router.get("/{transaction_id}/match-units", response_model=MatchedUnitsResponse)
@cached_endpoint(prefix="transaction_matching", expire=3600)  # Cache for 1 hour
async def match_transaction_to_units(
    transaction_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> MatchedUnitsResponse:
    """
    Match a transaction to units using AI.

    This endpoint:
    1. Pre-filters candidate units using SQL (area, size, project, rooms)
    2. Uses Claude LLM to intelligently match to specific units
    3. Returns matches with confidence scores and reasoning
    4. Results are cached for 1 hour to save costs and improve performance

    Args:
        transaction_id: ID of transaction to match

    Returns:
        MatchedUnitsResponse with list of matched units, confidence scores, and metadata

    Raises:
        HTTPException 404: Transaction not found
        HTTPException 500: Matching service error

    Note:
        Results are cached in Redis. Subsequent requests for the same transaction
        will return cached results without calling the LLM, saving ~$0.001 per request.
    """
    service = TransactionMatchingService(db)

    try:
        result = await service.match_transaction(transaction_id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error matching transaction: {str(e)}"
        )

    # Get transaction details for response
    transaction = await service._get_transaction(transaction_id)
    if not transaction:
        raise HTTPException(
            status_code=404, detail=f"Transaction {transaction_id} not found"
        )

    # Convert service result to response schema
    matched_units = [
        MatchedUnit(
            unit_id=match.unit_id,
            unit_number=match.unit_number,
            building_number=match.building_number,
            floor=match.floor,
            actual_area=match.actual_area,
            rooms=match.rooms,
            confidence=match.confidence,
            reasoning=match.reasoning,
        )
        for match in result.matches
    ]

    transaction_details = TransactionResponse.model_validate(transaction)

    return MatchedUnitsResponse(
        transaction_id=transaction_id,
        transaction_details=transaction_details,
        matched=result.matched,
        matches=matched_units,
        total_candidates=result.total_candidates,
        processing_time_seconds=result.processing_time_seconds,
    )


@router.get(
    "/units/{unit_id}/comparable", response_model=ComparableTransactionsResponse
)
@cached_endpoint(
    prefix="unit_comparable_transactions", expire=1800
)  # Cache for 30 minutes
async def get_unit_comparable_transactions(
    unit_id: int,
    db: AsyncSession = Depends(get_db_session),
) -> ComparableTransactionsResponse:
    """
    Get comparable transactions for a specific unit.

    This performs a reverse lookup - finding transactions with similar characteristics
    (same building, similar size, same property type, same rooms).
    These are not guaranteed to be the exact same unit, but are highly comparable.

    Args:
        unit_id: ID of unit to find comparable transactions for

    Returns:
        ComparableTransactionsResponse with unit details and comparable transactions

    Raises:
        HTTPException 404: Unit not found
        HTTPException 500: Service error

    Note:
        Results are cached in Redis for 30 minutes to improve performance
        for repeated requests.
    """
    # Get unit details
    stmt = select(Unit).where(Unit.property_id == unit_id)
    result = await db.execute(stmt)
    unit = result.scalar_one_or_none()

    if not unit:
        raise HTTPException(status_code=404, detail=f"Unit {unit_id} not found")

    # Get comparable transactions
    service = TransactionMatchingService(db)
    try:
        transactions = await service.get_comparable_transactions(unit_id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error fetching comparable transactions: {str(e)}"
        )

    # Convert to response schema
    unit_details = UnitDetails(
        unit_number=unit.unit_number,
        building_number=unit.building_number,
        actual_area=unit.actual_area,
        rooms=unit.rooms_en,
    )

    transaction_items = [
        ComparableTransactionItem(
            transaction_id=t.transaction_id,
            instance_date=t.instance_date,
            actual_worth=t.actual_worth,
            meter_sale_price=t.meter_sale_price,
            building_name_en=t.building_name_en,
            procedure_area=t.procedure_area,
        )
        for t in transactions
    ]

    return ComparableTransactionsResponse(
        unit_id=unit_id,
        unit_details=unit_details,
        transactions=transaction_items,
        total_transactions=len(transactions),
    )
