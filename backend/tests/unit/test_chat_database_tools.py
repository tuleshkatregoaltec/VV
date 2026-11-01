from datetime import date, datetime
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelRequest, ToolReturnPart
from pydantic_ai.models.test import TestModel

from app.analytics import market_metrics
from app.analytics.models import (
    ProjectAnalyticsResponse,
    ProjectRentalSummary,
    ProjectSalesSummary,
)
from app.chat import tools
from app.chat.workflows import market_agent as agent


@pytest.mark.parametrize("count", [0, 42])
async def test_coverage_preserves_load_evidence_and_hides_empty_aggregate_dates(monkeypatch, count):
    evidence = {"ranges": [{"from": "2026-09-01", "to": "2026-09-02", "status": "partial"}]}
    fetch = AsyncMock(
        return_value={
            "eligible_count": count,
            "data_from": date(2026, 9, 1) if count else date(1970, 1, 1),
            "data_to": date(2026, 9, 30) if count else date(1970, 1, 1),
            "built_at": datetime(2026, 10, 1),
            "release_id": "release-1",
            "coverage": evidence,
        }
    )
    monkeypatch.setattr(market_metrics.queries, "fetch_release", fetch)
    result = await tools.get_database_coverage(None, "sales")
    fetch.assert_awaited_once_with("sales")
    assert result["eligible_record_count"] == count
    assert result["data_from"] == ("2026-09-01" if count else None)
    assert result["data_to"] == ("2026-09-30" if count else None)
    assert result["load_evidence"] == evidence
    assert "do not prove complete coverage" in result["limitation"]


async def test_registered_agent_passes_database_evidence_back_to_the_model(monkeypatch):
    evidence = {"dataset": "sales", "eligible_record_count": 42, "data_to": "2026-09-30"}
    read = AsyncMock(return_value=evidence)
    monkeypatch.setattr(market_metrics, "get_market_data_coverage", read)
    with agent.override(model=TestModel(call_tools=["get_database_coverage"])):
        result = await agent.run("What sales data do we have?")
    read.assert_awaited_once_with("sales")
    returns = [
        part.content
        for message in result.all_messages()
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == "get_database_coverage"
    ]
    assert returns == [evidence]


def test_location_search_is_bounded_and_cannot_select_an_arbitrary_dataset():
    search = agent._function_toolset.tools["search_database_locations"]
    for arguments in ({"search": "Marina", "limit": 21}, {"search": ""}):
        with pytest.raises(ValidationError):
            search.function_schema.validator.validate_python(arguments)
    coverage = agent._function_toolset.tools["get_database_coverage"]
    with pytest.raises(ValidationError):
        coverage.function_schema.validator.validate_python({"dataset": "users"})


async def test_project_profile_keeps_missing_prices_unknown_and_uses_building_id(monkeypatch):
    summary = ProjectAnalyticsResponse(
        sales=ProjectSalesSummary(
            transaction_count=0, total_volume=0, avg_price=0, avg_price_sqft=0, median_price=0
        ),
        rentals=ProjectRentalSummary(
            contract_count=1,
            total_annual_value=120000,
            median_annual_rent=120000,
            median_rent_sqft=100,
        ),
        by_rooms=[],
        by_property_type=[],
        by_reg_type=[],
        unit_composition=[],
        configuration_analysis=[],
    )
    read = AsyncMock(return_value=summary)
    monkeypatch.setattr(tools.analytics_service, "get_project_summary", read)
    result = await tools.get_project_profile(None, "tower|marina", "building")
    read.assert_awaited_once_with("tower|marina", "building", usage="auto")
    assert result["sales"] == {"transaction_count": 0}
    assert result["rentals"]["median_annual_rent"] == 120000
    assert result["project"] is None
    assert result["source"] == "DXBI records"
    assert "unverified" in result["period"]
