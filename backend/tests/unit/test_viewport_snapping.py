"""Map viewports snap outward to a grid, so a small pan reuses the cached response.

The map rounds each corner to 0.001 degrees; with the raw values in the cache key every pan was a
miss (live audit 2026-11-15). Snapping happens before the query, so the response still covers the
whole viewport the user sees.
"""

from unittest.mock import AsyncMock

from app.project.viewport import snap_viewport


def test_snapped_viewport_contains_the_requested_one():
    snapped = snap_viewport(west=55.1234, south=25.1011, east=55.2345, north=25.2012)

    assert snapped.west <= 55.1234 and snapped.south <= 25.1011
    assert snapped.east >= 55.2345 and snapped.north >= 25.2012


def test_snapping_grows_each_side_by_at_most_an_eighth_of_the_span():
    west, south, east, north = 55.1234, 25.1011, 55.2345, 25.2012
    span = max(east - west, north - south)

    snapped = snap_viewport(west=west, south=south, east=east, north=north)

    assert west - snapped.west <= span / 8
    assert snapped.east - east <= span / 8


def test_a_small_pan_lands_on_the_same_snapped_viewport():
    first = snap_viewport(west=55.141, south=25.071, east=55.243, north=25.130)
    panned = snap_viewport(west=55.142, south=25.072, east=55.244, north=25.131)

    assert first == panned


def test_snapped_viewport_stays_inside_the_supported_bounds():
    snapped = snap_viewport(west=54.0001, south=24.0001, east=54.2, north=24.2)

    assert snapped.west >= 54 and snapped.south >= 24


async def test_radar_pins_cache_one_entry_for_nearby_viewports(client, monkeypatch):
    keys = []

    async def fake_get(key):
        keys.append(key)
        return None

    pins = AsyncMock(return_value=[])
    monkeypatch.setattr("app.core.decorators.cache.get", fake_get)
    monkeypatch.setattr("app.core.decorators.cache.set", AsyncMock())
    monkeypatch.setattr("app.project.router.get_project_radar_pins", pins)

    for corner in (
        "west=55.141&south=25.071&east=55.243&north=25.130",
        "west=55.142&south=25.072&east=55.244&north=25.131",
    ):
        response = await client.get(f"/api/v1/projects/radar/pins?{corner}&limit=100")
        assert response.status_code == 200, response.text

    assert keys[0] == keys[1]
    first, second = (call.kwargs for call in pins.await_args_list)
    assert first == second
    assert first["west"] <= 55.141 and first["east"] >= 55.244
