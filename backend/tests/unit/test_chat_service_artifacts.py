from datetime import date

import pytest

from app.chat import service as chat_service


@pytest.mark.asyncio
async def test_resolve_transaction_area_uses_master_project_alias(monkeypatch):
    seen: dict[str, object] = {}

    async def fake_query(sql: str, params: dict[str, object]):
        seen["sql"] = sql
        seen["params"] = params
        return [{"area_name_en": "Marsa Dubai"}]

    monkeypatch.setattr(chat_service, "ch_query", fake_query)

    area = await chat_service._resolve_transaction_area("Dubai Marina")

    assert area == "Marsa Dubai"
    assert "master_project_en" in str(seen["sql"])
    assert seen["params"] == {
        "area": "Dubai Marina",
        "search_text": "Dubai Marina",
        "pattern": "%Dubai Marina%",
    }


@pytest.mark.asyncio
async def test_latest_transaction_date_applies_market_filters(monkeypatch):
    seen: dict[str, object] = {}

    async def fake_query(sql: str, params: dict[str, object]):
        seen["sql"] = sql
        seen["params"] = params
        return [{"max_date": "2026-01-20"}]

    monkeypatch.setattr(chat_service, "ch_query", fake_query)

    max_date = await chat_service._latest_transaction_date(
        property_usage="Residential",
        property_type="Unit",
        area="Marsa Dubai",
    )

    assert max_date == date(2026, 1, 20)
    assert "property_usage_en = {property_usage:String}" in str(seen["sql"])
    assert "property_type_en = {property_type:String}" in str(seen["sql"])
    assert "area_name_en = {area_name:String}" in str(seen["sql"])
    assert seen["params"] == {
        "property_usage": "Residential",
        "property_type": "Unit",
        "area_name": "Marsa Dubai",
    }


@pytest.mark.asyncio
async def test_market_trend_artifact_anchors_to_latest_matching_transaction_date(monkeypatch):
    seen: dict[str, object] = {}

    async def fake_resolve_area(area: str | None):
        assert area == "Dubai Marina"
        return "Marsa Dubai"

    async def fake_latest_date(
        *,
        property_usage: str | None,
        property_type: str | None,
        area: str | None,
    ):
        seen["latest_args"] = {
            "property_usage": property_usage,
            "property_type": property_type,
            "area": area,
        }
        return date(2026, 1, 20)

    async def fake_query(sql: str, params: dict[str, object]):
        seen["trend_sql"] = sql
        seen["trend_params"] = params
        return [
            {
                "period": date(2025, 1, 1),
                "transaction_count": 10,
                "avg_price": 1_000_000,
                "avg_price_sqm": 10_000,
            },
            {
                "period": date(2026, 1, 1),
                "transaction_count": 20,
                "avg_price": 1_200_000,
                "avg_price_sqm": 12_000,
            },
        ]

    monkeypatch.setattr(chat_service, "_resolve_transaction_area", fake_resolve_area)
    monkeypatch.setattr(chat_service, "_latest_transaction_date", fake_latest_date)
    monkeypatch.setattr(chat_service, "ch_query", fake_query)

    artifact = await chat_service._fetch_market_trend_artifact(
        {
            "id": "artifact-1",
            "type": "market_trend",
            "status": "loading",
            "title": "Market trend",
            "created_at": "2026-05-05T00:00:00+00:00",
            "query": {},
        },
        {
            "area": "Dubai Marina",
            "property_usage": "Residential",
            "property_type": "Unit",
            "days": 365,
        },
    )

    assert seen["latest_args"] == {
        "property_usage": "Residential",
        "property_type": "Unit",
        "area": "Marsa Dubai",
    }
    assert seen["trend_params"]["end_date"] == "2026-01-20"
    assert seen["trend_params"]["start_date"] == "2025-01-20"
    assert artifact["status"] == "ready"
    assert artifact["query"]["area"] == "Marsa Dubai"
    assert artifact["data"]["total_transactions"] == 30
    assert artifact["data"]["avg_price_sqm_change_pct"] == 20.0
