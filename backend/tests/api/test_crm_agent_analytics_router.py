from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

from fastapi import HTTPException

from app.crm.analytics_models import (
    AgentAnalyticsDetail,
    AgentLeadMetrics,
    DailyActivity,
    TeamAnalyticsResponse,
)

NOW = datetime(2026, 11, 17, 9, tzinfo=timezone.utc)


async def test_team_analytics_accepts_only_the_agreed_windows(client, monkeypatch):
    service = AsyncMock(return_value=TeamAnalyticsResponse(days=7, generated_at=NOW, agents=[]))
    monkeypatch.setattr("app.crm.agent_analytics.team_analytics", service)

    bad = await client.get("/api/v1/crm/assignment/analytics?days=14")
    good = await client.get("/api/v1/crm/assignment/analytics?days=7")

    assert bad.status_code == 422
    assert good.status_code == 200 and good.json()["days"] == 7
    assert service.await_args.args[1:] == ("1", "test-user-id")
    assert service.await_args.kwargs == {"days": 7}


async def test_team_analytics_defaults_to_thirty_days(client, monkeypatch):
    service = AsyncMock(return_value=TeamAnalyticsResponse(days=30, generated_at=NOW, agents=[]))
    monkeypatch.setattr("app.crm.agent_analytics.team_analytics", service)

    await client.get("/api/v1/crm/assignment/analytics")

    assert service.await_args.kwargs == {"days": 30}


async def test_an_agent_is_refused_team_analytics(client, monkeypatch):
    service = AsyncMock(side_effect=HTTPException(status_code=403, detail="Managers only"))
    monkeypatch.setattr("app.crm.agent_analytics.team_analytics", service)

    response = await client.get("/api/v1/crm/assignment/analytics")

    assert response.status_code == 403


async def test_agent_analytics_asks_for_the_named_person(client, monkeypatch):
    detail = AgentAnalyticsDetail(
        days=30,
        metrics=AgentLeadMetrics(user_id="omar", name="Omar Khan", avg_first_response_minutes=14),
        sources=[],
        activity=[DailyActivity(date=date(2026, 11, 17), calls=2)],
        leads=[],
    )
    service = AsyncMock(return_value=detail)
    monkeypatch.setattr("app.crm.agent_analytics.agent_analytics", service)

    response = await client.get("/api/v1/crm/assignment/analytics/omar?days=30")

    assert response.status_code == 200
    assert response.json()["metrics"]["avg_first_response_minutes"] == 14
    assert service.await_args.args[1:] == ("1", "test-user-id", "omar")
