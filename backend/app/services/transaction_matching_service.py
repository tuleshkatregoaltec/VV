"""
Service for on-demand transaction-to-unit matching using LLM.

This service:
1. Pre-filters candidate units using SQL (area, project, rooms)
2. Uses Claude LLM to intelligently match transaction to specific units
3. Returns matches with confidence scores and reasoning
"""

import json
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from decimal import Decimal

from openai import AsyncOpenAI
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.postgres.models.transactions import Transaction
from app.postgres.models.properties import Unit, Project


# Configuration
AREA_TOLERANCE_SQM = 10.0
MAX_CANDIDATES_PER_TRANSACTION = 50
MIN_CONFIDENCE_THRESHOLD = 0.6


class MatchedUnitResult:
    """Result of matching a single unit"""

    def __init__(
        self,
        unit_id: int,
        unit_number: str,
        building_number: str,
        floor: Optional[str],
        actual_area: Decimal,
        rooms: Optional[str],
        confidence: float,
        reasoning: str,
    ):
        self.unit_id = unit_id
        self.unit_number = unit_number
        self.building_number = building_number
        self.floor = floor
        self.actual_area = actual_area
        self.rooms = rooms
        self.confidence = confidence
        self.reasoning = reasoning


class TransactionMatchingResult:
    """Complete result of transaction matching"""

    def __init__(
        self,
        transaction_id: str,
        matched: bool,
        matches: List[MatchedUnitResult],
        total_candidates: int,
        processing_time_seconds: float,
        cost: float = 0.0,
    ):
        self.transaction_id = transaction_id
        self.matched = matched
        self.matches = matches
        self.total_candidates = total_candidates
        self.processing_time_seconds = processing_time_seconds
        self.cost = cost


class TransactionMatchingService:
    """Service for matching transactions to units using LLM"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.client = AsyncOpenAI(
            api_key=settings.OPENROUTER_API_KEY, base_url=settings.OPENROUTER_BASE_URL
        )

    async def match_transaction(self, transaction_id: str) -> TransactionMatchingResult:
        """
        Main entry point for on-demand matching.

        Args:
            transaction_id: ID of transaction to match

        Returns:
            TransactionMatchingResult with matches and metadata
        """
        start_time = datetime.now()

        # 1. Get transaction from DB
        transaction = await self._get_transaction(transaction_id)
        if not transaction:
            return TransactionMatchingResult(
                transaction_id=transaction_id,
                matched=False,
                matches=[],
                total_candidates=0,
                processing_time_seconds=0.0,
            )

        # 2. Pre-filter candidate units
        candidates = await self._get_candidate_units(transaction)

        if not candidates:
            elapsed = (datetime.now() - start_time).total_seconds()
            return TransactionMatchingResult(
                transaction_id=transaction_id,
                matched=False,
                matches=[],
                total_candidates=0,
                processing_time_seconds=elapsed,
            )

        # 3. Call LLM to match
        matches, cost = await self._match_with_llm(transaction, candidates)

        elapsed = (datetime.now() - start_time).total_seconds()

        return TransactionMatchingResult(
            transaction_id=transaction_id,
            matched=len(matches) > 0,
            matches=matches,
            total_candidates=len(candidates),
            processing_time_seconds=elapsed,
            cost=cost,
        )

    async def _get_transaction(self, transaction_id: str) -> Optional[Transaction]:
        """Get transaction by ID"""
        stmt = select(Transaction).where(Transaction.transaction_id == transaction_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_candidate_units(self, transaction: Transaction) -> List[Unit]:
        """
        Pre-filter units using database queries.

        Filters by:
        - Area (same area as transaction)
        - Size (±10 sqm tolerance, larger for villas/land/townhouses)
        - Property type (if available)
        - Project (if available, but not required for villas/land)
        - Rooms (if available, but not for villas/land)
        """
        if not transaction.area_id or not transaction.procedure_area:
            return []

        trans_area = float(transaction.procedure_area)

        # Check if this is a villa, land, or townhouse (property types without traditional buildings)
        property_type_lower = (transaction.property_type_en or "").lower()
        is_standalone_property = any(
            pt in property_type_lower
            for pt in ["villa", "land", "townhouse", "town house"]
        )

        # Use larger tolerance for standalone properties (they vary more in size)
        tolerance = 25.0 if is_standalone_property else AREA_TOLERANCE_SQM
        min_area = trans_area - tolerance
        max_area = trans_area + tolerance

        conditions = [
            Unit.area_id == transaction.area_id,
            Unit.actual_area.isnot(None),
            Unit.actual_area >= min_area,
            Unit.actual_area <= max_area,
        ]

        # Property type filter (always apply if available)
        if transaction.property_type_id:
            conditions.append(Unit.property_type_id == transaction.property_type_id)

        # Project filter (more lenient for standalone properties)
        if transaction.project_number and not is_standalone_property:
            # For apartments/offices, project is important
            try:
                project_stmt = select(Project.project_id).where(
                    Project.project_number == int(transaction.project_number)
                )
                project_result = await self.session.execute(project_stmt)
                project_id = project_result.scalar_one_or_none()
                if project_id:
                    conditions.append(Unit.project_id == project_id)
            except (ValueError, TypeError):
                pass
        elif transaction.project_number and is_standalone_property:
            # For villas/land, project is optional but helpful if available
            try:
                project_stmt = select(Project.project_id).where(
                    Project.project_number == int(transaction.project_number)
                )
                project_result = await self.session.execute(project_stmt)
                project_id = project_result.scalar_one_or_none()
                if project_id:
                    # Don't require it, but prefer it (handled by LLM)
                    pass
            except (ValueError, TypeError):
                pass

        # Rooms filter (skip for land, more lenient for villas)
        if transaction.rooms_en and not is_standalone_property:
            # For apartments/offices, rooms must match
            conditions.append(Unit.rooms_en == transaction.rooms_en)

        stmt = (
            select(Unit).where(and_(*conditions)).limit(MAX_CANDIDATES_PER_TRANSACTION)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _match_with_llm(
        self, transaction: Transaction, candidates: List[Unit]
    ) -> tuple[List[MatchedUnitResult], float]:
        """
        Use LLM to intelligently match transaction to units.

        Returns:
            Tuple of (matches, cost)
        """
        # Build prompt
        prompt = self._build_matching_prompt(transaction, candidates)

        # Call LLM
        try:
            response = await self.client.chat.completions.create(
                model=settings.CHAT_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a real estate data matching specialist.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,  # Low temperature for consistent results
            )
        except Exception as e:
            # Log error in production
            print(f"LLM API error: {e}")
            return [], 0.0

        # Parse response
        response_text = response.choices[0].message.content

        # Estimate cost (rough approximation for Haiku)
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        cost = (input_tokens * 0.00025 / 1000) + (output_tokens * 0.00125 / 1000)

        # Parse JSON response
        try:
            matches_data = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if json_match:
                try:
                    matches_data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    return [], cost
            else:
                return [], cost

        if not matches_data.get("matches"):
            return [], cost

        # Convert to MatchedUnitResult objects
        results = []
        for match in matches_data["matches"]:
            confidence = match.get("confidence", 0.0)
            unit_id = match.get("unit_id")
            reasoning = match.get("reasoning", "")

            # Only include matches above threshold
            if confidence < MIN_CONFIDENCE_THRESHOLD:
                continue

            # Find unit in candidates
            unit = next((u for u in candidates if u.property_id == unit_id), None)
            if not unit:
                continue

            results.append(
                MatchedUnitResult(
                    unit_id=unit.property_id,
                    unit_number=unit.unit_number,
                    building_number=unit.building_number,
                    floor=unit.floor,
                    actual_area=unit.actual_area,
                    rooms=unit.rooms_en,
                    confidence=confidence,
                    reasoning=reasoning,
                )
            )

        return results, cost

    def _build_matching_prompt(
        self, transaction: Transaction, candidates: List[Unit]
    ) -> str:
        """Build prompt for LLM matching"""

        # Format candidate units as JSON
        candidates_data = []
        for unit in candidates:
            candidates_data.append(
                {
                    "unit_id": unit.property_id,
                    "unit_number": unit.unit_number,
                    "building_number": unit.building_number,
                    "floor": unit.floor,
                    "area_sqm": float(unit.actual_area) if unit.actual_area else None,
                    "rooms": unit.rooms_en,
                    "property_type_id": unit.property_type_id,
                }
            )

        prompt = f"""Match this Dubai real estate transaction to the most likely unit from the candidate list.

TRANSACTION:
- ID: {transaction.transaction_id}
- Date: {transaction.instance_date}
- Building: {transaction.building_name_en}
- Project: {transaction.project_name_en}
- Area: {transaction.procedure_area} sqm
- Rooms: {transaction.rooms_en}
- Price: {transaction.actual_worth} AED

CANDIDATE UNITS (pre-filtered by area, project, size):
{json.dumps(candidates_data, indent=2)}

INSTRUCTIONS:
1. Parse the building name to extract building number (e.g., "TOWER B" → Building 2, "Building A" → Building 1)
2. Match based on:
   - Building number (highest priority if extractable)
   - Area size (±3 sqm is excellent, ±10 sqm acceptable)
   - Room count
   - Property type

3. Return JSON with up to 5 matches, sorted by confidence:

{{
  "building_number_extracted": "2",
  "matches": [
    {{
      "unit_id": 12345,
      "confidence": 0.92,
      "reasoning": "Building 2 extracted from 'TOWER B', area 85.5 sqm matches 85.2 sqm, 2BR match"
    }}
  ]
}}

Confidence scale:
- 0.95-1.00: Exact match on all criteria
- 0.80-0.94: Strong match with building + area + rooms
- 0.60-0.79: Good match with area + rooms, uncertain building
- 0.40-0.59: Partial match, multiple possibilities
- 0.00-0.39: Weak match

Return ONLY valid JSON, no other text."""

        return prompt

    async def get_comparable_transactions(self, unit_id: int) -> List[Transaction]:
        """
        Get comparable transactions for a specific unit (reverse lookup).

        Finds transactions with similar characteristics:
        - Same area (location)
        - Same building (using building number)
        - Similar size (±5 sqm - tighter than candidate filtering)
        - Same property type
        - Same room count
        - Same project

        Note: These are comparable transactions, not guaranteed to be the exact same unit.
        """
        # Get unit with project info
        unit_stmt = select(Unit).where(Unit.property_id == unit_id)
        unit_result = await self.session.execute(unit_stmt)
        unit = unit_result.scalar_one_or_none()

        if not unit or not unit.actual_area:
            return []

        # Build query to find matching transactions
        # Use tighter tolerance for transaction history (we want same unit, not similar units)
        trans_area = float(unit.actual_area)
        history_tolerance = 5.0  # Tighter than candidate filtering
        min_area = trans_area - history_tolerance
        max_area = trans_area + history_tolerance

        conditions = [
            Transaction.area_id == unit.area_id,
            Transaction.procedure_area.isnot(None),
            Transaction.procedure_area >= min_area,
            Transaction.procedure_area <= max_area,
        ]

        # Required filters (these should all match for transaction history)
        if unit.property_type_id:
            conditions.append(Transaction.property_type_id == unit.property_type_id)

        if unit.rooms_en:
            conditions.append(Transaction.rooms_en == unit.rooms_en)

        # Building number filter - CRITICAL for accurate history
        # Match transactions where building name contains the unit's building number
        if unit.building_number:
            # Try to match building number in transaction's building_name_en
            # This will catch "Building 5", "Tower 5", "Block 5", etc.
            building_filter = f"%{unit.building_number}%"
            conditions.append(Transaction.building_name_en.like(building_filter))

        # Project filter - helps narrow down results significantly
        if unit.project_id:
            # Get project number for this unit
            project_stmt = select(Project.project_number).where(
                Project.project_id == unit.project_id
            )
            project_result = await self.session.execute(project_stmt)
            project_number = project_result.scalar_one_or_none()

            if project_number:
                conditions.append(Transaction.project_number == str(project_number))

        stmt = (
            select(Transaction)
            .where(and_(*conditions))
            .order_by(Transaction.instance_date.desc())
            .limit(50)  # Limit to 50 most recent transactions
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
