"""Area units. The warehouse stores DLD-derived sizes in square metres; every figure the product
shows is in square feet: sizes in sq ft, prices and rents per area in AED per sq ft."""

from typing import overload

SQM_TO_SQFT = 10.7639


@overload
def sqft(area_sqm: float) -> float: ...
@overload
def sqft(area_sqm: float | None) -> float | None: ...
def sqft(area_sqm: float | None) -> float | None:
    """An area stored in m², in sq ft (2 decimals); None stays None."""
    return None if area_sqm is None else round(float(area_sqm) * SQM_TO_SQFT, 2)


@overload
def per_sqft(value_per_sqm: float) -> float: ...
@overload
def per_sqft(value_per_sqm: float | None) -> float | None: ...
def per_sqft(value_per_sqm: float | None) -> float | None:
    """An amount per m², per sq ft (2 decimals); None stays None."""
    return None if value_per_sqm is None else round(float(value_per_sqm) / SQM_TO_SQFT, 2)


@overload
def per_sqm(value_per_sqft: float) -> float: ...
@overload
def per_sqm(value_per_sqft: float | None) -> float | None: ...
def per_sqm(value_per_sqft: float | None) -> float | None:
    """An amount per sq ft, per m² again (for models kept in m², such as feasibility)."""
    return None if value_per_sqft is None else float(value_per_sqft) * SQM_TO_SQFT
