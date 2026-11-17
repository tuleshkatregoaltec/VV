"""Estimate what an owner's property is worth today (client call, 5 Nov 2026).

Imported owner records carry the price paid, often years ago, so buyer budgets cannot be
matched against them. A unit is valued from sales of similar units in the last year, falling
back to its own purchase price moved by the area's price index. Pure logic only: callers fetch
the statistics (see valuation_queries) and store the result (see valuation_service).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

VALUATION_VERSION = "owner-value-v3"
RESIDENTIAL_TYPES = frozenset({"Apartment", "Villa", "Townhouse"})
PRICED_BY_BEDROOM = frozenset({"Villa", "Townhouse"})
# Comparable groups from the most to the least specific: (name, minimum sales, confidence).
LADDER: tuple[tuple[str, int, Literal["high", "medium", "low"]], ...] = (
    ("building_type_beds", 5, "high"),
    ("building_type", 5, "medium"),
    ("area_type_beds", 10, "medium"),
    ("area_type", 10, "low"),
)
INDEX_MIN_SALES = 10
INDEX_RANGE = 0.15
# A comparables range is never narrower than this on either side of the estimate.
MIN_RANGE = 0.05
# An estimate this far from the price paid is kept but marked low confidence.
SANE_RATIO = (0.6, 2.5)

Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class CompStats:
    """Price-per-sqft statistics of a group of sales."""

    count: int
    p25: float
    p50: float
    p75: float
    # Sale-price quartiles of the same group. Villas and townhouses at a bedroom level are valued
    # from these: DLD often records a villa's plot as its size, which breaks price x size.
    price_p25: float | None = None
    price_p50: float | None = None
    price_p75: float | None = None
    # Typical size of the sales, so a caller can tell whether a home is comparable in size.
    size_p50: float | None = None


@dataclass(frozen=True)
class ValuationSubject:
    claim_id: int
    purchase_price_aed: int
    purchase_date: date
    property_type: str  # registry type
    bedrooms: str  # registry value, "" when unknown
    size_sqft: float | None  # registry size only; imported files may give sq m
    building_key: str
    area_key: str
    # DLD market status of the unit's own record. A "Ready" home is valued from ready sales only;
    # off-plan launches sell at a premium. Off-plan or unknown homes use all sales.
    market_status: str = ""


@dataclass(frozen=True)
class Valuation:
    estimated_value_aed: int
    low_aed: int
    high_aed: int
    method: Literal["comparables", "indexed_purchase"]
    confidence: Confidence
    detail: dict[str, Any]


def _aed(value: float) -> int:
    return int(round(value / 1000) * 1000)


def _from_comparables(
    subject: ValuationSubject, comps: dict[str, CompStats | None]
) -> Valuation | None:
    if not subject.size_sqft or subject.size_sqft <= 0:
        return None
    for level, minimum, confidence in LADDER:
        stats = comps.get(level)
        if stats is None or stats.count < minimum:
            continue
        size = subject.size_sqft
        by_price = (
            subject.property_type in PRICED_BY_BEDROOM
            and level.endswith("_beds")
            and stats.price_p50 is not None
        )
        if by_price:
            value = float(stats.price_p50)
            low, high = float(stats.price_p25 or value), float(stats.price_p75 or value)
        else:
            value, low, high = stats.p50 * size, stats.p25 * size, stats.p75 * size
        return Valuation(
            estimated_value_aed=_aed(value),
            low_aed=_aed(min(low, value * (1 - MIN_RANGE))),
            high_aed=_aed(max(high, value * (1 + MIN_RANGE))),
            method="comparables",
            confidence=confidence,
            detail={
                "level": level,
                "comparable_count": stats.count,
                "psf_p50": round(stats.p50, 1),
                "size_sqft": round(size, 1),
                "basis": "bedroom_price" if by_price else "psf_size",
                "comparable_size_sqft": round(stats.size_p50) if stats.size_p50 else None,
            },
        )
    return None


def _from_index(
    subject: ValuationSubject, index_now: CompStats | None, index_then: CompStats | None
) -> Valuation | None:
    if (
        not subject.purchase_price_aed
        or index_now is None
        or index_then is None
        or index_now.count < INDEX_MIN_SALES
        or index_then.count < INDEX_MIN_SALES
        or index_then.p50 <= 0
    ):
        return None
    ratio = index_now.p50 / index_then.p50
    value = subject.purchase_price_aed * ratio
    return Valuation(
        estimated_value_aed=_aed(value),
        low_aed=_aed(value * (1 - INDEX_RANGE)),
        high_aed=_aed(value * (1 + INDEX_RANGE)),
        method="indexed_purchase",
        confidence="low",
        detail={"level": "area_index", "index_ratio": round(ratio, 4)},
    )


def estimate(
    subject: ValuationSubject,
    comps: dict[str, CompStats | None],
    index_now: CompStats | None,
    index_then: CompStats | None,
    valued_at: date,
) -> Valuation | None:
    """Value one unit, or None when it is not residential or the evidence is too thin."""
    if subject.property_type not in RESIDENTIAL_TYPES:
        return None
    result = _from_comparables(subject, comps) or _from_index(subject, index_now, index_then)
    if result is None:
        return None
    detail = {
        "version": VALUATION_VERSION,
        "method": result.method,
        "confidence": result.confidence,
        "property_type": subject.property_type,
        "bedrooms": subject.bedrooms,
        "valued_at": valued_at.isoformat(),
        **result.detail,
    }
    confidence = result.confidence
    if subject.purchase_price_aed:
        ratio = result.estimated_value_aed / subject.purchase_price_aed
        if not SANE_RATIO[0] <= ratio <= SANE_RATIO[1]:
            confidence = "low"
            detail["confidence"] = "low"
            detail["flag"] = "far_from_purchase"
    return Valuation(
        estimated_value_aed=result.estimated_value_aed,
        low_aed=result.low_aed,
        high_aed=result.high_aed,
        method=result.method,
        confidence=confidence,
        detail=detail,
    )
