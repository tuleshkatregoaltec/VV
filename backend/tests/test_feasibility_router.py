from unittest.mock import AsyncMock, patch

from app.feasibility.models import ComparableData, LandPlot, UnitTypeData

MOCK_LAND_PLOT = LandPlot(
    plot_number="L001",
    community_name="Downtown Dubai",
    project_name="Burj Vista",
    plot_area_sqm=1000.0,
    max_gfa_sqm=4000.0,
    max_height="G+20",
    max_coverage="60%",
    gfa_type="Residential",
    is_verified=True,
)

MOCK_COMPARABLE = ComparableData(
    project_id=1,
    project_name="Test Tower",
    area_name="JVC",
    no_of_buildings=2,
    avg_floors=10.0,
    unit_mix=[
        UnitTypeData(
            type="1BR", count=50, percentage=50.0, avg_size_sqm=70.0, avg_price_sqm=15000.0
        )
    ],
    price_per_sqm_by_type={"1BR": 15000.0},
)


# ── Auth enforcement ─────────────────────────────────────────────────────────


async def test_areas_requires_auth(client_no_auth):
    resp = await client_no_auth.get("/api/v1/feasibility/areas")
    assert resp.status_code == 401


async def test_land_requires_auth(client_no_auth):
    resp = await client_no_auth.get("/api/v1/feasibility/land?area=Downtown Dubai&size_sqm=1000")
    assert resp.status_code == 401


async def test_comparable_requires_auth(client_no_auth):
    resp = await client_no_auth.get("/api/v1/feasibility/comparable?project_ids=1")
    assert resp.status_code == 401


# ── /areas ───────────────────────────────────────────────────────────────────


async def test_areas_returns_list(client):
    with patch(
        "app.feasibility.router.get_areas", new=AsyncMock(return_value=["Downtown Dubai", "JVC"])
    ):
        resp = await client.get("/api/v1/feasibility/areas")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert "Downtown Dubai" in data


# ── /land ─────────────────────────────────────────────────────────────────────


async def test_land_returns_plots(client):
    with patch(
        "app.feasibility.router.get_land_plots", new=AsyncMock(return_value=[MOCK_LAND_PLOT])
    ):
        resp = await client.get("/api/v1/feasibility/land?area=Downtown Dubai&size_sqm=1000")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["plot_number"] == "L001"
    assert data[0]["plot_area_sqm"] == 1000.0


async def test_land_missing_params_returns_422(client):
    resp = await client.get("/api/v1/feasibility/land")
    assert resp.status_code == 422


async def test_land_tolerance_out_of_range_returns_422(client):
    resp = await client.get("/api/v1/feasibility/land?area=JVC&size_sqm=500&tolerance=1.5")
    assert resp.status_code == 422


# ── /land/search ──────────────────────────────────────────────────────────────


async def test_land_search_returns_plots(client):
    with patch(
        "app.feasibility.router.search_land_plots", new=AsyncMock(return_value=[MOCK_LAND_PLOT])
    ):
        resp = await client.get("/api/v1/feasibility/land/search?area=Downtown Dubai&q=L001")

    assert resp.status_code == 200
    assert resp.json()[0]["plot_number"] == "L001"


async def test_land_search_empty_query_returns_422(client):
    resp = await client.get("/api/v1/feasibility/land/search?area=Downtown Dubai&q=")
    assert resp.status_code == 422


# ── /comparable ───────────────────────────────────────────────────────────────


async def test_comparable_returns_data(client):
    with patch(
        "app.feasibility.router.get_comparable_data", new=AsyncMock(return_value=MOCK_COMPARABLE)
    ):
        resp = await client.get("/api/v1/feasibility/comparable?project_ids=1")

    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] == 1
    assert data["area_name"] == "JVC"
    assert len(data["unit_mix"]) == 1


async def test_comparable_returns_404_when_no_data(client):
    with patch("app.feasibility.router.get_comparable_data", new=AsyncMock(return_value=None)):
        resp = await client.get("/api/v1/feasibility/comparable?project_ids=9999")

    assert resp.status_code == 404


async def test_comparable_ignores_non_digit_ids(client):
    # "abc" should be filtered out, leaving an empty list -> 404
    with patch("app.feasibility.router.get_comparable_data", new=AsyncMock(return_value=None)):
        resp = await client.get("/api/v1/feasibility/comparable?project_ids=abc")

    assert resp.status_code == 404
