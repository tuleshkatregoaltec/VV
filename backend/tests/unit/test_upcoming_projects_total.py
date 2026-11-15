"""The dashboard's Active projects card shows /supply/upcoming-projects total.

The list was capped at 1,000 rows and the total was the length of that list, so the card showed
exactly 1,000 (live audit 2026-11-15). The total counts every active project.
"""

from unittest.mock import AsyncMock


async def test_upcoming_projects_total_counts_every_active_project(client, monkeypatch):
    project = {"project_id": 1, "project_name_en": "Tower", "no_of_units": 10}
    monkeypatch.setattr("app.core.decorators.cache.get", AsyncMock(return_value=None))
    monkeypatch.setattr("app.core.decorators.cache.set", AsyncMock())
    monkeypatch.setattr("app.supply.service._latest_sales_date", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.supply.queries.fetch_upcoming_projects", AsyncMock(return_value=[project])
    )
    count = AsyncMock(return_value=[{"total": 1873}])
    monkeypatch.setattr("app.supply.queries.count_upcoming_projects", count, raising=False)

    response = await client.get("/api/v1/supply/upcoming-projects?limit=1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1873
    assert len(body["projects"]) == 1
