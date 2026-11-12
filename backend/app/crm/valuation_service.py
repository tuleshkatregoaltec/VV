"""Value current-owner claims and store the estimate on each claim (owner valuation, 5 Nov 2026).

Each claim is joined to its DLD sale by the same (sale date, price, unit) signature the owner
profile uses, which gives the registry size, bedrooms, building and area. Size is never taken
from the imported file: some agency exports label square metres as square feet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import owner_queries, owner_repository, valuation_queries
from app.crm.identity import _normalize_unit
from app.crm.import_models import CrmPropertyContactClaim
from app.crm.owner_repository import CURRENT_OWNER_STATUSES
from app.crm.valuation import (
    RESIDENTIAL_TYPES,
    VALUATION_VERSION,
    CompStats,
    ValuationSubject,
    estimate,
)

logger = logging.getLogger(__name__)

_CHUNK = 2000
_WINDOW_DAYS = 365


@dataclass
class ValuationRunSummary:
    considered: int = 0
    valued: int = 0
    by_method: dict[str, int] = field(default_factory=dict)
    by_confidence: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)


def _unit_key(value: Any) -> str:
    return _normalize_unit(value).lower()


def _stats(row: dict[str, Any]) -> CompStats:
    p25, p50, p75 = (float(v) for v in row["psf"])
    prices = [float(v) for v in row.get("price") or []]
    size = float(row["size_p50"]) if row.get("size_p50") else None
    if len(prices) == 3:
        return CompStats(int(row["count"]), p25, p50, p75, *prices, size_p50=size)
    return CompStats(int(row["count"]), p25, p50, p75, size_p50=size)


def _quarter(day: date) -> date:
    return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)


def _clear(claim: CrmPropertyContactClaim, status: str) -> None:
    claim.estimated_value_aed = None
    claim.estimated_value_low_aed = None
    claim.estimated_value_high_aed = None
    claim.valuation = {"version": VALUATION_VERSION, "status": status}


async def _registry_rows(
    claims: list[CrmPropertyContactClaim],
) -> dict[int, dict[str, Any] | str]:
    """Each claim's unique registry sale, or the reason it has none."""
    signed = [c for c in claims if c.latest_sale_date and c.latest_sale_price_aed]
    if not signed:
        return {}
    rows = await owner_queries.fetch_owner_property_signatures(
        {
            "dates": sorted({c.latest_sale_date for c in signed}),
            "prices": sorted({int(c.latest_sale_price_aed or 0) for c in signed}),
        }
    )
    by_signature: dict[tuple[date, int, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row["transaction_date"], int(row["sale_amount_aed"]), str(row["unit_key"]))
        by_signature.setdefault(key, []).append(row)
    found: dict[int, dict[str, Any] | str] = {}
    for claim in signed:
        key = (
            claim.latest_sale_date,
            int(claim.latest_sale_price_aed or 0),
            _unit_key(claim.unit_number),
        )
        candidates = by_signature.get(key, [])
        identities = {(r.get("area_key"), r.get("building_key")) for r in candidates}
        if not candidates:
            found[claim.id or 0] = "no_registry_match"
        elif len(identities) > 1:
            found[claim.id or 0] = "ambiguous_registry_match"
        else:
            found[claim.id or 0] = candidates[0]
    return found


async def _value_chunk(
    claims: list[CrmPropertyContactClaim], valued_at: date, summary: ValuationRunSummary
) -> None:
    registry = await _registry_rows(claims)
    subjects: dict[int, ValuationSubject] = {}
    for claim in claims:
        row = registry.get(claim.id or 0, "no_registry_match")
        if isinstance(row, str):
            _clear(claim, row)
            summary.skipped[row] = summary.skipped.get(row, 0) + 1
            continue
        property_type = str(row.get("property_type") or "")
        if property_type not in RESIDENTIAL_TYPES:
            _clear(claim, "non_residential")
            summary.skipped["non_residential"] = summary.skipped.get("non_residential", 0) + 1
            continue
        size = float(row.get("size_sqft") or 0)
        subjects[claim.id or 0] = ValuationSubject(
            claim_id=claim.id or 0,
            purchase_price_aed=int(claim.latest_sale_price_aed or 0),
            purchase_date=claim.latest_sale_date or valued_at,
            property_type=property_type,
            bedrooms=str(row.get("bedrooms") or ""),
            size_sqft=size if size > 0 else None,
            building_key=str(row.get("building_key") or ""),
            area_key=str(row.get("area_key") or ""),
            market_status=str(row.get("market_status") or ""),
        )
    if not subjects:
        return
    stats: dict[tuple[str, str, str, str, str, bool], CompStats] = {}
    for ready in (True, False):
        group = [s for s in subjects.values() if (s.market_status == "Ready") == ready]
        if not group:
            continue
        stat_rows = await valuation_queries.fetch_comparable_stats(
            sorted({s.building_key for s in group if s.building_key}),
            sorted({s.area_key for s in group if s.area_key}),
            valued_at - timedelta(days=_WINDOW_DAYS),
            valued_at + timedelta(days=1),
            ready_only=ready,
        )
        for row in stat_rows:
            stats[
                (
                    row["level"],
                    row["building_key"],
                    row["area_key"],
                    row["property_type"],
                    row["bedrooms"],
                    ready,
                )
            ] = _stats(row)
    quarters = await valuation_queries.fetch_area_psf_by_quarter(
        sorted({s.area_key for s in subjects.values() if s.area_key}),
        sorted({s.property_type for s in subjects.values()}),
    )
    then: dict[tuple[str, str, date], CompStats] = {
        (r["area_key"], r["property_type"], r["quarter"]): CompStats(
            int(r["count"]), float(r["p50"]), float(r["p50"]), float(r["p50"])
        )
        for r in quarters
    }
    for claim in claims:
        subject = subjects.get(claim.id or 0)
        if subject is None:
            continue
        b, a, t, beds = (
            subject.building_key,
            subject.area_key,
            subject.property_type,
            subject.bedrooms,
        )
        r = subject.market_status == "Ready"
        comps = {
            "building_type_beds": stats.get(("building_type_beds", b, "", t, beds, r))
            if b and beds
            else None,
            "building_type": stats.get(("building_type", b, "", t, "", r)) if b else None,
            "area_type_beds": stats.get(("area_type_beds", "", a, t, beds, r))
            if a and beds
            else None,
            "area_type": stats.get(("area_type", "", a, t, "", r)) if a else None,
        }
        result = estimate(
            subject,
            comps,
            comps["area_type"],
            then.get((a, t, _quarter(subject.purchase_date))),
            valued_at,
        )
        if result is None:
            _clear(claim, "no_comparables")
            summary.skipped["no_comparables"] = summary.skipped.get("no_comparables", 0) + 1
            continue
        claim.estimated_value_aed = result.estimated_value_aed
        claim.estimated_value_low_aed = result.low_aed
        claim.estimated_value_high_aed = result.high_aed
        claim.valuation = result.detail
        summary.valued += 1
        summary.by_method[result.method] = summary.by_method.get(result.method, 0) + 1
        summary.by_confidence[result.confidence] = (
            summary.by_confidence.get(result.confidence, 0) + 1
        )


async def value_owner_claims(
    db: AsyncSession,
    *,
    organization_id: str,
    import_id: int | None = None,
    valued_at: date | None = None,
    commit: bool = True,
) -> ValuationRunSummary:
    """Estimate today's value of every current-owner claim and clear stale estimates.

    With `commit=False` nothing is committed, so the caller can roll back (a dry run).
    """
    valued_at = valued_at or date.today()
    summary = ValuationRunSummary()
    claims = list(await owner_repository.list_claims_for_valuation(db, organization_id, import_id))
    current = [c for c in claims if c.ownership_status in CURRENT_OWNER_STATUSES]
    for claim in claims:
        if claim.ownership_status not in CURRENT_OWNER_STATUSES:
            _clear(claim, "not_current_owner")
            db.add(claim)
    summary.considered = len(current)
    for start in range(0, len(current), _CHUNK):
        chunk = current[start : start + _CHUNK]
        await _value_chunk(chunk, valued_at, summary)
        for claim in chunk:
            db.add(claim)
        if commit:
            await db.commit()
    if commit:
        await db.commit()
    logger.info(
        "Owner valuation run",
        extra={
            "organization_id": organization_id,
            "import_id": import_id,
            "considered": summary.considered,
            "valued": summary.valued,
            "skipped": summary.skipped,
        },
    )
    return summary
