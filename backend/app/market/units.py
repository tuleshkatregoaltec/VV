"""Area units. The warehouse stores DLD-derived sizes in square metres; every figure the product
shows is in square feet: sizes in sq ft, prices and rents per area in AED per sq ft."""

from typing import Optional

SQM_TO_SQFT = 10.7639


def sqft(area_sqm: object) -> Optional[float]:
    """An area stored in m², in sq ft (2 decimals); None stays None."""
    return None if area_sqm is None else round(float(area_sqm) * SQM_TO_SQFT, 2)


def per_sqft(value_per_sqm: object) -> Optional[float]:
    """An amount per m², per sq ft (2 decimals); None stays None."""
    return None if value_per_sqm is None else round(float(value_per_sqm) / SQM_TO_SQFT, 2)
