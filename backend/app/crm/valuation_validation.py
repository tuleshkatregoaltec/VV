"""Read-only helpers for validating owner valuations against exact comparables and live listings.

Nothing here writes to a database or changes how a valuation is computed.
"""

from __future__ import annotations

import random
import statistics
from collections import defaultdict
from typing import Any

from app.market.comparables import closest_sales as closest_sales

# Estimate / median asking price: asking prices sit above achieved prices, so a sound estimate
# lands somewhat below them, not on them.
LISTING_BAND = (0.85, 1.00)
COMPARABLES_MAX_MEDIAN_GAP = 10.0


def _aed(value: float) -> int:
    return int(round(value / 1000.0)) * 1000


def gap_pct(estimate: int, reference: int) -> float:
    return round((estimate - reference) / reference * 100.0, 1)


def pick_sample(
    claims: list[dict[str, Any]], size: int = 25, seed: int = 7
) -> list[dict[str, Any]]:
    """Deterministic round-robin across area x confidence groups, so every mix is represented."""
    rng = random.Random(seed)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for claim in sorted(claims, key=lambda c: c["id"]):
        groups[(str(claim["area"]), str(claim["confidence"]))].append(claim)
    queues = []
    for key in sorted(groups):
        members = groups[key][:]
        rng.shuffle(members)
        queues.append(members)
    picked: list[dict[str, Any]] = []
    while len(picked) < size and any(queues):
        for queue in queues:
            if queue and len(picked) < size:
                picked.append(queue.pop())
    return picked


def listing_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Asking-price spread after dropping off-plan stock and the same unit listed twice."""
    kept: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("off_plan") or "").lower() == "yes" or not row.get("asking_aed"):
            continue
        price, sqft = int(row["asking_aed"]), float(row.get("size_sqft") or 0)
        duplicate = any(
            int(k["asking_aed"]) == price
            and abs(float(k.get("size_sqft") or 0) - sqft) <= max(sqft, 1.0) * 0.01
            for k in kept
        )
        if not duplicate:
            kept.append(row)
    prices = sorted(int(r["asking_aed"]) for r in kept)
    if not prices:
        return {"count": 0, "low": None, "median": None, "high": None}
    return {
        "count": len(prices),
        "low": prices[0],
        "median": _aed(statistics.median(prices)),
        "high": prices[-1],
    }


def summarise(
    comparables: list[dict[str, Any]], listings: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    gaps = [abs(r["gap_pct"]) for r in comparables if r.get("gap_pct") is not None]
    by_confidence: dict[str, list[float]] = defaultdict(list)
    for r in comparables:
        if r.get("gap_pct") is not None:
            by_confidence[str(r.get("confidence"))].append(abs(r["gap_pct"]))
    ratios = [
        v["estimate"] / v["median"]
        for v in listings.values()
        if v.get("median") and v.get("estimate")
    ]
    low, high = LISTING_BAND
    median_gap = round(statistics.median(gaps), 1) if gaps else None
    median_ratio = round(statistics.median(ratios), 3) if ratios else None
    return {
        "comparables": {
            "n": len(gaps),
            "median_abs_gap": median_gap,
            "within_10": round(sum(g <= 10 for g in gaps) / len(gaps), 2) if gaps else None,
            "within_20": round(sum(g <= 20 for g in gaps) / len(gaps), 2) if gaps else None,
            "by_confidence": {
                k: {"n": len(v), "median_abs_gap": round(statistics.median(v), 1)}
                for k, v in sorted(by_confidence.items())
            },
        },
        "listings": {
            "n": len(ratios),
            "median_ratio": median_ratio,
            "inside_band": round(sum(low <= r <= high for r in ratios) / len(ratios), 2)
            if ratios
            else None,
        },
        "verdicts": {
            "comparables": median_gap is not None and median_gap <= COMPARABLES_MAX_MEDIAN_GAP,
            "listings": median_ratio is not None and low <= median_ratio <= high,
        },
    }
