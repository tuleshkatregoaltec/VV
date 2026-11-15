"""A master's delivery pipeline is its DLD area's, and says so; it names no single developer.

Dubai Marina (160 projects) showed the pipeline of whichever DLD area ``any()`` returned and the
developer with the most units ("T F G REAL ESTATE L.L.C") as the master's.
"""

from datetime import date

from app.analytics import queries, service


async def test_master_pipeline_reads_its_records_dld_areas_and_no_single_developer(monkeypatch):
    seen: dict = {}

    async def meta(parameters, filter_type):
        return [{"area_name_en": "Somewhere Else", "developer_name_en": "T F G REAL ESTATE L.L.C",
                 "developer_names": ["T F G REAL ESTATE L.L.C", "EMAAR", "SELECT GROUP"]}]  # fmt: skip

    async def areas(parameters, filter_type):
        seen["areas_scope"] = (parameters, filter_type)
        return [{"area_name_en": "Marsa Dubai", "records": 950}, {"area_name_en": "Al Sufouh", "records": 30}]

    async def supply(parameters, filter_by_area=True):
        seen["supply"] = parameters
        return [{"no_of_units": 100, "completion_date": None, "project_end_date": date(2030, 1, 1)}]

    monkeypatch.setattr(queries, "fetch_pipeline_meta", meta)
    monkeypatch.setattr(queries, "fetch_scope_areas", areas)
    monkeypatch.setattr(queries, "fetch_area_supply_projects", supply)

    response = await service.get_project_pipeline("Dubai Marina", "master")

    assert seen["areas_scope"] == ({"project_name": "Dubai Marina"}, "master")
    # Al Sufouh holds 3% of the master's records: not its area.
    assert seen["supply"] == {"areas": ["marsa dubai"]}
    assert response.area_name == "Marsa Dubai"
    assert response.developer_name is None
    assert "Marsa Dubai" in response.basis and "DLD" in response.basis


async def test_a_single_developer_master_names_it(monkeypatch):
    async def meta(parameters, filter_type):
        return [{"area_name_en": "X", "developer_name_en": "EMAAR", "developer_names": ["EMAAR"]}]

    async def areas(parameters, filter_type):
        return [{"area_name_en": "Burj Khalifa", "records": 10}]

    async def supply(parameters, filter_by_area=True):
        return []

    monkeypatch.setattr(queries, "fetch_pipeline_meta", meta)
    monkeypatch.setattr(queries, "fetch_scope_areas", areas)
    monkeypatch.setattr(queries, "fetch_area_supply_projects", supply)

    response = await service.get_project_pipeline("Downtown Dubai", "master")

    assert response.developer_name == "EMAAR"
