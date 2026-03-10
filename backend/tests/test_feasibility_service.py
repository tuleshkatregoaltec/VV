from unittest.mock import AsyncMock, patch

from app.feasibility.service import get_comparable_data, get_land_plots, search_land_plots

MOCK_LAND_ROW = {
    "plot_number": "L001",
    "community_name": "Downtown Dubai",
    "project_name": "Burj Vista",
    "plot_area_sqm": 1000.0,
    "max_gfa_sqm": 4000.0,
    "max_height": "G+20",
    "max_coverage": "60%",
    "gfa_type": "Residential",
    "is_verified": True,
    "land_use": '[{"type":"Residential","use":"Apartment"}]',
}


async def test_get_comparable_data_empty_returns_none():
    assert await get_comparable_data([]) is None


async def test_get_land_plots_maps_rows_to_land_plot_models():
    with patch("app.feasibility.service.query", new=AsyncMock(return_value=[MOCK_LAND_ROW])):
        plots = await get_land_plots("Downtown Dubai", 1000.0)

    assert len(plots) == 1
    assert plots[0].plot_number == "L001"
    assert plots[0].plot_area_sqm == 1000.0
    assert plots[0].community_name == "Downtown Dubai"
    assert plots[0].is_verified is True


async def test_get_land_plots_empty_db_returns_empty_list():
    with patch("app.feasibility.service.query", new=AsyncMock(return_value=[])):
        plots = await get_land_plots("Downtown Dubai", 1000.0)

    assert plots == []


async def test_get_land_plots_null_optional_fields():
    row = {
        **MOCK_LAND_ROW,
        "plot_number": "",
        "project_name": "",
        "gfa_type": "",
        "land_use": "",
    }
    with patch("app.feasibility.service.query", new=AsyncMock(return_value=[row])):
        plots = await get_land_plots("Downtown Dubai", 1000.0)

    assert plots[0].plot_number == ""
    assert plots[0].project_name == ""
    assert plots[0].gfa_type == ""
    assert plots[0].land_use_summary == []


async def test_search_land_plots_maps_rows():
    with patch("app.feasibility.service.query", new=AsyncMock(return_value=[MOCK_LAND_ROW])):
        plots = await search_land_plots("Downtown Dubai", "L001")

    assert len(plots) == 1
    assert plots[0].plot_number == "L001"


async def test_get_comparable_data_unit_percentages():
    buildings_rows = [{"no_of_buildings": 2, "avg_floors": 10.0}]
    project_rows = [{"project_id": 1, "project_name_en": "Test Tower", "area_name_en": "JVC"}]
    units_rows = [
        {"unit_type": "1BR", "cnt": 40, "avg_size_sqm": 70.0},
        {"unit_type": "2BR", "cnt": 60, "avg_size_sqm": 100.0},
    ]

    with patch(
        "app.feasibility.service.query",
        new=AsyncMock(side_effect=[buildings_rows, project_rows, units_rows, []]),
    ):
        result = await get_comparable_data([1])

    assert result is not None
    one_br = next(u for u in result.unit_mix if u.type == "1BR")
    two_br = next(u for u in result.unit_mix if u.type == "2BR")
    assert one_br.percentage == 40.0
    assert two_br.percentage == 60.0
    assert one_br.count + two_br.count == 100


async def test_get_comparable_data_price_by_type():
    buildings_rows = [{"no_of_buildings": 1, "avg_floors": 5.0}]
    project_rows = [{"project_id": 1, "project_name_en": "Test Tower", "area_name_en": "JVC"}]
    units_rows = [{"unit_type": "Studio", "cnt": 10, "avg_size_sqm": 40.0}]
    price_rows = [{"unit_type": "Studio", "median_price_sqm": 15000.0}]

    with patch(
        "app.feasibility.service.query",
        new=AsyncMock(side_effect=[buildings_rows, project_rows, units_rows, price_rows]),
    ):
        result = await get_comparable_data([1])

    assert result is not None
    studio = result.unit_mix[0]
    assert studio.avg_price_sqm == 15000.0
    assert result.price_per_sqm_by_type["Studio"] == 15000.0


async def test_get_comparable_data_project_name_joined():
    buildings_rows = [{"no_of_buildings": 2, "avg_floors": 8.0}]
    project_rows = [
        {"project_id": 1, "project_name_en": "Alpha", "area_name_en": "JLT"},
        {"project_id": 2, "project_name_en": "Beta", "area_name_en": "JLT"},
    ]
    units_rows = [{"unit_type": "1BR", "cnt": 20, "avg_size_sqm": 75.0}]

    with patch(
        "app.feasibility.service.query",
        new=AsyncMock(side_effect=[buildings_rows, project_rows, units_rows, []]),
    ):
        result = await get_comparable_data([1, 2])

    assert result is not None
    assert "Alpha" in result.project_name
    assert "Beta" in result.project_name
