"""Map viewports as the map endpoints query and cache them.

The map sends each corner rounded to 0.001 degrees, so every pan was a new cache key and a new
warehouse query. A viewport snaps outward to a grid of about an eighth of its span (a power of two,
so the snapped corners are exact in JSON): the response still covers the whole visible map, and
nearby viewports at the same zoom share one cached response.
"""

import math
from typing import Optional

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict

# Dubai and its surroundings: the supported range of every map endpoint.
MIN_LONGITUDE, MAX_LONGITUDE = 54.0, 57.0
MIN_LATITUDE, MAX_LATITUDE = 24.0, 26.0
_FINEST_STEP = 2.0**-10  # ~100 m, the map's own rounding
_COARSEST_STEP = 2.0**-3


class Viewport(BaseModel):
    model_config = ConfigDict(frozen=True)

    west: float
    south: float
    east: float
    north: float

    @property
    def span(self) -> float:
        return max(self.east - self.west, self.north - self.south)


def snap_viewport(*, west: float, south: float, east: float, north: float) -> Viewport:
    span = max(east - west, north - south, _FINEST_STEP)
    step = min(max(2.0 ** math.floor(math.log2(span / 8)), _FINEST_STEP), _COARSEST_STEP)
    return Viewport(
        west=max(math.floor(west / step) * step, MIN_LONGITUDE),
        south=max(math.floor(south / step) * step, MIN_LATITUDE),
        east=min(math.ceil(east / step) * step, MAX_LONGITUDE),
        north=min(math.ceil(north / step) * step, MAX_LATITUDE),
    )


def _corner(minimum: float, maximum: float, description: str, required: bool):
    return Query(
        ... if required else None,
        ge=minimum,
        le=maximum,
        allow_inf_nan=False,
        description=description,
    )


def _validated(west, south, east, north) -> Optional[Viewport]:
    corners = (west, south, east, north)
    if all(value is None for value in corners):
        return None
    if any(value is None for value in corners):
        raise HTTPException(
            status_code=422, detail="Viewport bounds must include west, south, east, and north"
        )
    if west >= east or south >= north:
        raise HTTPException(status_code=422, detail="Viewport bounds are invalid")
    return snap_viewport(west=west, south=south, east=east, north=north)


def optional_viewport(
    west: Optional[float] = _corner(MIN_LONGITUDE, MAX_LONGITUDE, "Viewport west longitude", False),
    south: Optional[float] = _corner(MIN_LATITUDE, MAX_LATITUDE, "Viewport south latitude", False),
    east: Optional[float] = _corner(MIN_LONGITUDE, MAX_LONGITUDE, "Viewport east longitude", False),
    north: Optional[float] = _corner(MIN_LATITUDE, MAX_LATITUDE, "Viewport north latitude", False),
) -> Optional[Viewport]:
    """A snapped viewport when all four corners are given, None when none are."""
    return _validated(west, south, east, north)


def required_viewport(
    west: float = _corner(MIN_LONGITUDE, MAX_LONGITUDE, "Viewport west longitude", True),
    south: float = _corner(MIN_LATITUDE, MAX_LATITUDE, "Viewport south latitude", True),
    east: float = _corner(MIN_LONGITUDE, MAX_LONGITUDE, "Viewport east longitude", True),
    north: float = _corner(MIN_LATITUDE, MAX_LATITUDE, "Viewport north latitude", True),
) -> Viewport:
    """A snapped viewport; all four corners are required."""
    return _validated(west, south, east, north)
