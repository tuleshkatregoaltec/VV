"""Shared exact-sale selection for owner and listing valuation evidence."""

from __future__ import annotations

import statistics
from typing import Any

_PSF_MIN, _PSF_MAX = 200.0, 12_000.0


def _aed(value: float) -> int:
    return int(round(value / 1000.0)) * 1000


def closest_sales(
    subject: dict[str, Any], sales: list[dict[str, Any]], size_band: float = 0.15, limit: int = 5
) -> dict[str, Any]:
    """The nearest-in-size recent sales of the same type and bedrooms in the same building."""
    size = float(subject.get("size_sqft") or 0)
    own_unit = str(subject.get("unit_key") or "")
    same_unit: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for sale in sales:
        sale_size = float(sale.get("size_sqft") or 0)
        price = float(sale.get("sale_amount_aed") or 0)
        if sale_size <= 0 or not _PSF_MIN <= price / sale_size <= _PSF_MAX:
            continue
        row = {**sale, "psf": round(price / sale_size, 1)}
        if own_unit and str(sale.get("unit_key") or "") == own_unit:
            same_unit.append(row)
        elif size > 0 and abs(sale_size - size) <= size * size_band:
            candidates.append(row)
    candidates.sort(key=lambda r: r["transaction_date"], reverse=True)
    candidates.sort(key=lambda r: abs(float(r["size_sqft"]) - size))
    chosen = candidates[:limit]
    median = _aed(statistics.median(r["psf"] for r in chosen) * size) if chosen else None
    resale = max(same_unit, key=lambda r: r["transaction_date"]) if same_unit else None
    return {"comparables": chosen, "same_unit_resale": resale, "median_adjusted_aed": median}
