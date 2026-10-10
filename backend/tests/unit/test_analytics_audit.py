"""Audit regressions: projected deliveries must remain in later cumulative stock."""

from datetime import date

from app.analytics import queries, service


async def test_current_quarter_deliveries_carry_into_next_quarter(monkeypatch):
    def anchor():
        return date(2026, 10, 10)

    async def projects(*args, **kwargs):
        return [
            {"no_of_units": 100, "completion_date": date(2025, 1, 15)},
            {"no_of_units": 50, "project_end_date": date(2026, 11, 15)},
            {"no_of_units": 20, "project_end_date": date(2027, 2, 15)},
        ]

    monkeypatch.setattr(service, "business_today", anchor)
    monkeypatch.setattr(queries, "fetch_area_supply_projects", projects)
    result = await service.get_project_pipeline("Dubai", "market")
    quarters = {point.period: point for point in result.data}
    assert quarters[date(2026, 10, 1)].new_pipeline_units == 50
    # A delivery shown this quarter cannot disappear from the next quarter's stock.
    assert quarters[date(2027, 1, 1)].carried_stock_units == 150
    assert quarters[date(2027, 4, 1)].carried_stock_units == 170


async def test_missed_planned_handover_does_not_become_completed_stock(monkeypatch):
    def anchor():
        return date(2026, 10, 10)

    async def projects(*args, **kwargs):
        return [
            {
                "no_of_units": 100,
                "completion_date": None,
                "project_end_date": date(2026, 4, 1),
                "project_status": "ACTIVE",
                "percent_completed": 32.6,
            },
            {"no_of_units": 20, "completion_date": None, "project_end_date": None},
        ]

    monkeypatch.setattr(service, "business_today", anchor)
    monkeypatch.setattr(queries, "fetch_area_supply_projects", projects)
    result = await service.get_project_pipeline("Dubai", "market")
    # A missed planned date is an overdue delivery, not evidence that homes exist.
    assert all(point.existing_stock_units == 0 for point in result.data)
    assert result.overdue_units == 100
    assert result.undated_units == 20
    assert result.reference_date == date(2026, 10, 10)
