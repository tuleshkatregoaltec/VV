"""
Geocoding service using Nominatim (OpenStreetMap) API
Handles fetching coordinates and area polygons for projects and areas
"""

import httpx
import logging
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from app.schemas.projects import GeoPoint, GeoPolygon

logger = logging.getLogger(__name__)

# Nominatim API endpoint
NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org"
# User agent (required by Nominatim)
USER_AGENT = "ViteVue-Platform/1.0"


async def search_location(
    query: str,
    limit: int = 1,
    area_filter: Optional[str] = "Dubai, United Arab Emirates",
) -> Optional[GeoPoint]:
    """
    Search for a location by name using Nominatim.
    Returns the first result's coordinates.

    Args:
        query: Location name to search for (e.g., "Marina, Dubai")
        limit: Number of results to return
        area_filter: Restrict search to a specific area

    Returns:
        GeoPoint with latitude and longitude, or None if not found
    """
    try:
        async with httpx.AsyncClient() as client:
            params = {
                "q": query,
                "limit": limit,
                "format": "json",
            }

            if area_filter:
                params["viewbox"] = "51.4,23.8,55.8,26"  # Dubai bounding box
                params["bounded"] = "1"

            headers = {"User-Agent": USER_AGENT}

            logger.debug(f"Searching Nominatim for: {query}")
            response = await client.get(
                f"{NOMINATIM_BASE_URL}/search",
                params=params,
                headers=headers,
                timeout=10.0,
            )

            if response.status_code != 200:
                logger.error(
                    f"Nominatim search failed: {response.status_code} - {response.text}"
                )
                return None

            results = response.json()
            if not results:
                logger.debug(f"No results found for: {query}")
                return None

            result = results[0]
            geo_point = GeoPoint(
                latitude=float(result["lat"]), longitude=float(result["lon"])
            )
            logger.debug(
                f"Found location: {query} -> {geo_point.latitude}, {geo_point.longitude}"
            )
            return geo_point

    except Exception as e:
        logger.error(f"Error geocoding '{query}': {str(e)}")
        return None


async def search_location_with_polygon(
    query: str, limit: int = 1
) -> Optional[tuple[GeoPoint, Optional[GeoPolygon]]]:
    """
    Search for a location and get its polygon (boundary).
    Useful for areas and districts.

    Args:
        query: Location name to search for
        limit: Number of results to return

    Returns:
        Tuple of (GeoPoint, GeoPolygon) or None if not found
    """
    try:
        async with httpx.AsyncClient() as client:
            params = {
                "q": query,
                "limit": limit,
                "format": "json",
                "polygon_geojson": "1",  # Get polygon geometry
                "viewbox": "51.4,23.8,55.8,26",  # Dubai bounding box
                "bounded": "1",
            }

            headers = {"User-Agent": USER_AGENT}

            logger.debug(f"Searching Nominatim for polygon: {query}")
            response = await client.get(
                f"{NOMINATIM_BASE_URL}/search",
                params=params,
                headers=headers,
                timeout=10.0,
            )

            if response.status_code != 200:
                logger.error(
                    f"Nominatim polygon search failed: {response.status_code} - {response.text}"
                )
                return None

            results = response.json()
            if not results:
                logger.debug(f"No polygon results found for: {query}")
                return None

            result = results[0]
            geo_point = GeoPoint(
                latitude=float(result["lat"]), longitude=float(result["lon"])
            )

            # Try to extract polygon from geojson
            polygon = None
            if result.get("geojson") and result["geojson"].get("type") == "Polygon":
                coords = result["geojson"]["coordinates"][0]
                polygon = GeoPolygon(coordinates=coords)
                logger.debug(f"Found Polygon with {len(coords)} points")
            elif (
                result.get("geojson")
                and result["geojson"].get("type") == "MultiPolygon"
            ):
                # For multipolygons, use the first polygon
                coords = result["geojson"]["coordinates"][0][0]
                polygon = GeoPolygon(coordinates=coords)
                logger.debug(
                    f"Found MultiPolygon, using first with {len(coords)} points"
                )
            else:
                logger.debug(f"No polygon geometry found for {query}")

            return geo_point, polygon

    except Exception as e:
        logger.error(f"Error geocoding with polygon '{query}': {str(e)}")
        return None


async def reverse_geocode(latitude: float, longitude: float) -> Optional[str]:
    """
    Reverse geocode coordinates to get address/location name.

    Args:
        latitude: Latitude coordinate
        longitude: Longitude coordinate

    Returns:
        Address/location name or None if not found
    """
    try:
        async with httpx.AsyncClient() as client:
            params = {
                "lat": latitude,
                "lon": longitude,
                "format": "json",
            }

            headers = {"User-Agent": USER_AGENT}

            response = await client.get(
                f"{NOMINATIM_BASE_URL}/reverse",
                params=params,
                headers=headers,
                timeout=10.0,
            )

            if response.status_code != 200:
                return None

            result = response.json()
            return result.get("display_name")

    except Exception as e:
        logger.error(f"Error reverse geocoding [{latitude}, {longitude}]: {str(e)}")
        return None
