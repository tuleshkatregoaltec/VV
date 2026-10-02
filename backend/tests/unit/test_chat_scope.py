"""Follow-up retrieval must not widen a bound user cohort, even after a failed call."""

from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.chat import mcp
from app.chat.scope import BindMarketScopeRequest, ScopeError, TurnScope

COHORT = {
    "id": "income",
    "evidence_kind": "listings",
    "location": "JVC",
    "bedrooms": ["1"],
    "property_type": "apartment",
    "mode": "sale",
    "price_min": 800000,
    "price_min_inclusive": True,
    "price_max": 1200000,
    "price_max_inclusive": False,
    "period": {"type": "previous_months", "months": 6},
}


def scope(*cohorts):
    result = TurnScope(date(2026, 10, 3))
    result.bind(BindMarketScopeRequest(cohorts=list(cohorts)))
    return result


@pytest.fixture
def executor(monkeypatch):
    monkeypatch.setattr(mcp, "_observe", AsyncMock(return_value={}))
    operation = AsyncMock(return_value={"status": "ok", "listings": []})
    monkeypatch.setattr(mcp, "get_listing_inventory", operation)
    monkeypatch.setattr(mcp, "compare_listing_rents", operation)
    result = mcp.MarketToolExecutor(
        mcp.ChatToolContext("u", "o", date(2026, 10, 3), "turn"),
        AsyncMock(return_value=True),
    )
    return result, operation


async def test_q11_failed_period_does_not_release_price_or_cohort_constraints(executor):
    server, operation = executor
    assert (await server.call("bind_market_scope", {"request": {"cohorts": [COHORT]}}))[
        "status"
    ] == "ok"
    inventory = await server.call("get_listing_inventory", {"request": {}})
    assert inventory["status"] == "ok"
    assert inventory["evidence"]["scope"]["deferred"]
    request = operation.call_args.args[0]
    assert request.price_max == 1200000 and request.price_max_inclusive is False
    bad = await server.call(
        "compare_listing_rents", {"request": {"period": {"type": "previous_months"}}}
    )
    assert bad["error"]["code"] == "invalid_arguments"
    assert bad["error"]["details"][0]["field"] == "period.months"
    assert operation.await_count == 1  # Rejection is safe handling, not retrieved coverage.
    repaired = await server.call(
        "compare_listing_rents", {"request": {"period": {"type": "previous_months", "months": 6}}}
    )
    assert repaired["status"] == "ok"
    request = operation.call_args.args[0]
    assert (request.location, request.bedrooms, request.property_type, request.mode) == (
        "JVC",
        "1",
        "Apartment",
        "sale",
    )
    assert (request.price_min, request.price_max, request.price_max_inclusive) == (
        800000,
        1200000,
        False,
    )
    assert request.period.months == 6


@pytest.mark.parametrize(
    "field,value",
    [
        ("location", "Business Bay"),
        ("location", None),
        ("bedrooms", "2"),
        ("property_type", "Villa"),
        ("mode", "rent"),
        ("price_min", 1),
        ("price_max", 1400000),
        ("price_max", None),
        ("price_max_inclusive", True),
        ("price_min_inclusive", False),
        ("period", {"type": "rolling_days", "days": 180}),
        ("period", None),
    ],
)
async def test_followup_conflicting_or_null_constraints_never_reach_database(
    executor, field, value
):
    server, operation = executor
    await server.call("bind_market_scope", {"request": {"cohorts": [COHORT]}})
    result = await server.call("compare_listing_rents", {"request": {field: value}})
    assert result["error"]["code"] == "scope_conflict"
    assert result["error"]["details"][0]["field"] == field
    operation.assert_not_awaited()


async def test_no_retrieval_before_scope_and_no_scope_reset_after_validation_failure(executor):
    server, operation = executor
    assert (await server.call("get_listing_inventory", {"request": {}}))["error"][
        "code"
    ] == "scope_required"
    args = {"request": {"cohorts": [COHORT]}}
    assert (await server.call("bind_market_scope", args))["status"] == "ok"
    assert (await server.call("bind_market_scope", args))["status"] == "ok"
    bad = {"request": {"cohorts": [COHORT | {"price_max": 2000000}]}}
    assert (await server.call("bind_market_scope", bad))["error"]["code"] == "scope_conflict"
    operation.assert_not_awaited()


async def test_q09_and_paired_cohorts_require_explicit_selection(executor):
    server, operation = executor
    cohorts = [COHORT | {"id": bedroom, "bedrooms": [bedroom]} for bedroom in ("studio", "1", "2")]
    cohorts.append(
        COHORT | {"id": "bay", "location": "Business Bay", "bedrooms": ["2"], "price_max": 2000000}
    )
    await server.call("bind_market_scope", {"request": {"cohorts": cohorts}})
    assert (await server.call("get_listing_inventory", {"request": {}}))["error"][
        "code"
    ] == "scope_required"
    for cohort in cohorts:
        result = await server.call(
            "get_listing_inventory", {"scope_id": cohort["id"], "request": {}}
        )
        assert result["status"] == "ok"
        request = operation.call_args.args[0]
        assert (request.location, request.bedrooms, request.price_max) == (
            cohort["location"],
            cohort["bedrooms"][0],
            cohort["price_max"],
        )


def test_metrics_inherit_source_and_map_explicit_bounds_without_default_semantic_changes():
    bound = COHORT | {"evidence_kind": "sales"}
    result, _ = scope(bound).apply(
        "query_market_metrics", {}, mcp.TOOL_MODELS["query_market_metrics"], None
    )
    assert result["dataset"] == "sales"
    assert result["min_value_aed"] == 800000 and result["min_value_inclusive"] is True
    assert result["max_value_aed"] == 1200000 and result["max_value_inclusive"] is False
    assert result["bedrooms"] == ["1"]


def test_equivalent_alias_and_calendar_range_reuse_frozen_interpretation():
    result, _ = scope(COHORT).apply(
        "compare_listing_rents",
        {
            "location": "Jumeirah Village Circle (JVC)",
            "period": {"type": "range", "start": "2026-04-01", "end": "2026-09-30"},
        },
        mcp.TOOL_MODELS["compare_listing_rents"],
        None,
    )
    assert result["location"] == "JVC"
    assert result["period"] == {"type": "previous_months", "months": 6}


def test_unsupported_constraint_cannot_be_dropped_or_switched_to_other_source():
    report = COHORT | {"evidence_kind": "report"}
    with pytest.raises(ScopeError, match="does not apply"):
        scope(report).apply(
            "compose_market_report",
            {"kind": "monthly_area"},
            mcp.TOOL_MODELS["compose_market_report"],
            None,
        )
    with pytest.raises(ScopeError, match="frozen cohort"):
        scope(COHORT).apply(
            "query_market_metrics",
            {"dataset": "sales"},
            mcp.TOOL_MODELS["query_market_metrics"],
            None,
        )


@pytest.mark.parametrize(
    "period,path",
    [
        ({"type": "previous_months"}, "months"),
        ({"type": "rolling_days"}, "days"),
        ({"type": "month"}, "month"),
        ({"type": "quarter"}, "quarter"),
        ({"type": "range", "start": "2026-01-01"}, "end"),
    ],
)
async def test_period_feedback_names_missing_parameter_without_binding_guessed_scope(
    executor, period, path
):
    server, operation = executor
    result = await server.call(
        "bind_market_scope", {"request": {"cohorts": [COHORT | {"period": period}]}}
    )
    assert result["error"]["details"][0]["field"] == f"cohorts.0.period.{path}"
    assert not server.scope.cohorts
    operation.assert_not_awaited()


@pytest.mark.parametrize(
    "constraint",
    [
        {"location": "JVC"},
        {"building": "Tower"},
        {"bedrooms": ["1"]},
        {"property_type": "apartment"},
    ],
)
def test_off_plan_report_does_not_pretend_to_apply_unsupported_filters(constraint):
    bound = {"id": "report", "evidence_kind": "report", "projects": ["Alpha", "Beta"], **constraint}
    with pytest.raises(ScopeError, match="does not apply"):
        scope(bound).apply(
            "compose_market_report",
            {"kind": "off_plan_comparison"},
            mcp.TOOL_MODELS["compose_market_report"],
            None,
        )


def test_report_project_bindings_are_preserved_only_for_supported_report_kind():
    bound = {"id": "report", "evidence_kind": "report", "projects": ["Alpha", "Beta"]}
    result, _ = scope(bound).apply(
        "compose_market_report",
        {"kind": "off_plan_comparison"},
        mcp.TOOL_MODELS["compose_market_report"],
        None,
    )
    assert result["projects"] == ["Alpha", "Beta"]
    with pytest.raises(ScopeError, match="does not apply"):
        scope(bound).apply(
            "compose_market_report",
            {"kind": "monthly_area"},
            mcp.TOOL_MODELS["compose_market_report"],
            None,
        )


async def test_malformed_bedroom_list_is_not_misreported_as_retrieval_failure(executor):
    server, operation = executor
    await server.call(
        "bind_market_scope", {"request": {"cohorts": [COHORT | {"evidence_kind": "sales"}]}}
    )
    result = await server.call("query_market_metrics", {"request": {"bedrooms": [{}]}})
    assert result["error"]["code"] == "scope_conflict"
    assert result["error"]["details"][0]["field"] == "bedrooms"
    assert result["error"]["retryable"] is False
    operation.assert_not_awaited()


def test_wire_schema_allows_inheritance_but_domain_model_still_requires_fields():
    from jsonschema import validate
    from pydantic import ValidationError

    schemas = {tool.name: tool.inputSchema for tool in mcp.tool_definitions()}
    for name in ("query_market_metrics", "compare_listing_rents"):
        validate({"request": {}, "scope_id": "income"}, schemas[name])
        with pytest.raises(ValidationError):
            mcp.TOOL_MODELS[name].model_validate({})
