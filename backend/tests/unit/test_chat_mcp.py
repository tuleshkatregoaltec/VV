"""Real MCP transport tests; domain reads are deterministic, not paid model calls."""

import asyncio
from dataclasses import FrozenInstanceError
from datetime import date
from unittest.mock import AsyncMock

import httpx
import pytest

from app.chat import mcp


def context(user="user-a", org="org-a"):
    return mcp.ChatToolContext(user, org, date(2026, 10, 3), f"turn-{user}")


@pytest.fixture
def domain(monkeypatch):
    monkeypatch.setattr(mcp, "_observe", AsyncMock(return_value={"sales": {"built_at": "fixture"}}))
    operation = AsyncMock(
        return_value={
            "total": {"count": 3, "values": {"mean_aed": 2000000}},
            "coverage": {"status": "unverified"},
            "limitations": [],
        }
    )
    monkeypatch.setattr(mcp, "get_market_evidence", operation)
    return operation


ARGS = {"request": {"dataset": "sales", "period": {"type": "previous_month"}}}


async def bind_scope(client, cohorts=None):
    """Bind through the real tool before exercising an existing retrieval contract."""
    call = getattr(client, "direct_call_tool", None) or client.call
    result = await call(
        "bind_market_scope",
        {"request": {"cohorts": cohorts or [{"id": "sales", "evidence_kind": "sales"}]}},
    )
    assert result["status"] == "ok", result


async def test_sdk_streamable_http_initialize_list_call_with_trusted_context(domain, monkeypatch):
    methods = []
    handle = mcp.AuthenticatedMCPApp.__call__

    async def observed(self, scope, receive, send):
        async def inspect_receive():
            import json

            message = await receive()
            if message.get("body"):
                methods.append(json.loads(message["body"]).get("method"))
            return message

        return await handle(self, scope, inspect_receive, send)

    monkeypatch.setattr(mcp.AuthenticatedMCPApp, "__call__", observed)
    auth = AsyncMock(return_value=True)
    actor = context()
    async with mcp.market_mcp(actor, auth) as client:
        await bind_scope(client)
        auth.reset_mock()
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == set(mcp.TOOL_MODELS)
        result = await client.direct_call_tool("query_market_metrics", ARGS)
    assert result["data"]["total"]["values"]["mean_aed"] == 2000000
    assert result["evidence"]["reference_date"] == "2026-10-03"
    assert result["evidence"]["release"]["id"] is None
    assert {"initialize", "notifications/initialized", "tools/list", "tools/call"} <= set(methods)
    assert domain.call_args.kwargs["context"] is actor
    assert auth.await_count == 2
    with pytest.raises(FrozenInstanceError):
        actor.organization_id = "other"


async def test_invalid_and_spoofed_arguments_are_rejected_over_protocol(domain):
    async with mcp.market_mcp(context(), AsyncMock(return_value=True)) as client:
        await bind_scope(client)
        for request in [
            ARGS | {"organization_id": "other"},
            {"request": ARGS["request"] | {"user_id": "other"}},
            {"request": ARGS["request"] | {"reference_date": "2020-01-01"}},
            {
                "request": ARGS["request"]
                | {"period": {"type": "previous_month", "organization_id": "other"}}
            },
        ]:
            result = await client.direct_call_tool("query_market_metrics", request)
            assert result["error"]["code"] == "invalid_arguments"
    domain.assert_not_awaited()


async def test_disabled_access_cannot_read_and_revocation_cannot_disclose(domain):
    async with mcp.market_mcp(context(), AsyncMock(return_value=False)) as client:
        result = await client.direct_call_tool("query_market_metrics", ARGS)
        assert result["error"]["code"] == "unauthorized"
    domain.assert_not_awaited()
    auth = AsyncMock(return_value=True)
    async with mcp.market_mcp(context(), auth) as client:
        await bind_scope(client)
        auth.side_effect = [True, False]
        result = await client.direct_call_tool("query_market_metrics", ARGS)
        assert result["error"]["code"] == "unauthorized"
        assert result["data"] is None


async def test_transport_rejects_missing_or_wrong_secret():
    manager = AsyncMock()
    app = mcp.AuthenticatedMCPApp(manager, "opaque-server-secret")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://market-mcp.local"
    ) as client:
        assert (await client.post("/mcp", json={"method": "initialize"})).status_code == 401
        assert (
            await client.post("/mcp", headers={"Authorization": "Bearer other"}, json={})
        ).status_code == 401
    manager.handle_request.assert_not_awaited()


async def test_concurrent_tenants_keep_separate_trusted_contexts(domain):
    seen = []

    async def evidence(request, *, context):
        await asyncio.sleep(0)
        seen.append((context.user_id, context.organization_id))
        return {"total": {"count": 1}}

    domain.side_effect = evidence

    async def run(user, org):
        async with mcp.market_mcp(context(user, org), AsyncMock(return_value=True)) as client:
            await bind_scope(client)
            return await client.direct_call_tool("query_market_metrics", ARGS)

    results = await asyncio.gather(run("a", "one"), run("b", "two"))
    assert all(result["status"] == "ok" for result in results)
    assert set(seen) == {("a", "one"), ("b", "two")}


async def test_placeholders_do_not_trigger_domain_reads(domain):
    async with mcp.market_mcp(context(), AsyncMock(return_value=True)) as client:
        await bind_scope(
            client,
            [{"id": "report", "evidence_kind": "report", "location": "JLT", "bedrooms": ["2"]}],
        )
        result = await client.direct_call_tool(
            "compose_market_report",
            {
                "request": {
                    "kind": "rental_appraisal",
                    "building": "[building]",
                    "location": "JLT",
                    "bedrooms": "2",
                }
            },
        )
        assert result["status"] == "clarification_required"
        assert result["data"]["required_bindings"] == ["building"]
    domain.assert_not_awaited()


async def test_timeout_release_change_result_and_call_budgets(domain, monkeypatch):
    executor = mcp.MarketToolExecutor(context(), AsyncMock(return_value=True))
    await bind_scope(executor)
    monkeypatch.setattr(mcp, "TOOL_TIMEOUT_SECONDS", 0.01)

    async def slow(*args, **kwargs):
        await asyncio.sleep(10)

    domain.side_effect = slow
    assert (await executor.call("query_market_metrics", ARGS))["error"]["code"] == "tool_timeout"
    domain.side_effect = None
    monkeypatch.setattr(
        mcp,
        "_observe",
        AsyncMock(side_effect=[{"sales": {"built_at": "a"}}, {"sales": {"built_at": "b"}}]),
    )
    executor = mcp.MarketToolExecutor(context(), AsyncMock(return_value=True))
    await bind_scope(executor)
    assert (await executor.call("query_market_metrics", ARGS))["error"]["code"] == "release_changed"
    monkeypatch.setattr(mcp, "_observe", AsyncMock(return_value={}))
    domain.return_value = {"large": "x" * mcp.MAX_RESULT_BYTES}
    assert (await executor.call("query_market_metrics", ARGS))["error"][
        "code"
    ] == "evidence_budget_exceeded"
    executor.calls = mcp.MAX_TOOL_CALLS
    assert (await executor.call("query_market_metrics", ARGS))["error"][
        "code"
    ] == "tool_budget_exceeded"


async def test_private_failure_details_are_never_returned(domain):
    domain.side_effect = RuntimeError("SELECT secret FROM contacts password=private")
    async with mcp.market_mcp(context(), AsyncMock(return_value=True)) as client:
        await bind_scope(client)
        result = await client.direct_call_tool("query_market_metrics", ARGS)
    assert result["error"]["code"] == "capability_unavailable"
    assert "private" not in str(result)


async def test_cancellation_closes_release_lease_and_transport(domain, monkeypatch):
    from contextlib import asynccontextmanager

    from app.market import evidence

    entered, closed = asyncio.Event(), asyncio.Event()

    @asynccontextmanager
    async def release(context):
        try:
            yield None
        finally:
            closed.set()

    async def wait_forever(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(evidence, "acquire_market_release", release)
    domain.side_effect = wait_forever

    async def run():
        async with mcp.market_mcp(context(), AsyncMock(return_value=True)) as client:
            await bind_scope(client)
            await client.direct_call_tool("query_market_metrics", ARGS)

    task = asyncio.create_task(run())
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


async def test_total_evidence_budget_and_missing_release_sources_fail_closed(domain, monkeypatch):
    from app.market.evidence import MarketRelease

    monkeypatch.setattr(mcp, "MAX_TURN_BYTES", 10000)
    domain.return_value = {"sample": "x" * 600}
    executor = mcp.MarketToolExecutor(context(), AsyncMock(return_value=True))
    await bind_scope(executor)
    assert (await executor.call("query_market_metrics", ARGS))["status"] == "ok"
    monkeypatch.setattr(mcp, "MAX_TURN_BYTES", executor.result_bytes + 1)
    assert (await executor.call("query_market_metrics", ARGS))["error"][
        "code"
    ] == "evidence_budget_exceeded"
    lease = MarketRelease("rentals-only", frozenset({"rentals"}))
    executor = mcp.MarketToolExecutor(context(), AsyncMock(return_value=True), lease)
    await bind_scope(executor)
    assert (await executor.call("query_market_metrics", ARGS))["error"][
        "code"
    ] == "release_source_unavailable"


def test_discovered_input_schemas_cannot_accept_account_or_release_authority():
    for tool in mcp.tool_definitions():
        schema = tool.inputSchema
        assert schema["additionalProperties"] is False
        props = schema["properties"]["request"]["properties"]
        assert (
            not {"user_id", "organization_id", "reference_date", "release_id", "database", "sql"}
            & props.keys()
        )


async def test_downstream_validation_and_serialization_errors_are_not_bad_user_arguments(domain):
    from pydantic import BaseModel, ValidationError

    class DomainOutput(BaseModel):
        count: int

    try:
        DomainOutput.model_validate({"count": "unknown"})
    except ValidationError as error:
        domain.side_effect = error
    async with mcp.market_mcp(context(), AsyncMock(return_value=True)) as client:
        await bind_scope(client)
        response = await client.direct_call_tool("query_market_metrics", ARGS)
        assert response["error"]["code"] == "capability_unavailable"
    domain.side_effect = None
    domain.return_value = {"value": float("nan")}
    async with mcp.market_mcp(context(), AsyncMock(return_value=True)) as client:
        await bind_scope(client)
        response = await client.direct_call_tool("query_market_metrics", ARGS)
        assert response["error"]["code"] == "capability_unavailable"


async def test_invalid_calendar_period_is_an_input_error_before_any_read(domain, monkeypatch):
    observed = AsyncMock()
    monkeypatch.setattr(mcp, "_observe", observed)
    async with mcp.market_mcp(context(), AsyncMock(return_value=True)) as client:
        await bind_scope(client)
        response = await client.direct_call_tool(
            "query_market_metrics", {"request": {"dataset": "sales", "period": {"type": "range"}}}
        )
        assert response["error"]["code"] == "invalid_arguments"
    observed.assert_not_awaited()
    domain.assert_not_awaited()


async def test_unpinned_turn_cannot_combine_successive_source_families(domain, monkeypatch):
    from contextlib import asynccontextmanager

    from app.market import evidence

    observed = AsyncMock(
        side_effect=lambda sources: {source: {"snapshot": "fixed"} for source in sources}
    )
    monkeypatch.setattr(mcp, "_observe", observed)
    rentals = {"request": {"dataset": "rentals", "period": {"type": "previous_month"}}}
    async with mcp.market_mcp(context(), AsyncMock(return_value=True)) as client:
        await bind_scope(
            client,
            [
                {"id": "sales", "evidence_kind": "sales"},
                {"id": "rentals", "evidence_kind": "rentals"},
            ],
        )
        assert (await client.direct_call_tool("query_market_metrics", ARGS))["status"] == "ok"
        assert (await client.direct_call_tool("query_market_metrics", ARGS))["status"] == "ok"
        reads_before = observed.await_count
        response = await client.direct_call_tool("query_market_metrics", rentals)
        assert response["status"] == "unavailable"
        assert response["error"]["code"] == "release_unavailable"
        assert response["data"] is None
        assert observed.await_count == reads_before

    @asynccontextmanager
    async def lease(context):
        yield evidence.MarketRelease("immutable", frozenset({"sales", "rentals"}))

    monkeypatch.setattr(evidence, "acquire_market_release", lease)
    async with mcp.market_mcp(context(), AsyncMock(return_value=True)) as client:
        await bind_scope(
            client,
            [
                {"id": "sales", "evidence_kind": "sales"},
                {"id": "rentals", "evidence_kind": "rentals"},
            ],
        )
        assert (await client.direct_call_tool("query_market_metrics", ARGS))["status"] == "ok"
        assert (await client.direct_call_tool("query_market_metrics", rentals))["status"] == "ok"


def test_default_delivery_ranking_excludes_overdue_and_later_units():
    # A horizon alone must never rank completed/overdue/later units as upcoming delivery.
    request = mcp.DeliveryRequest()
    assert request.delivery_statuses == ["scheduled_in_horizon"]
    assert mcp.DeliveryRequest(delivery_statuses=["missing_date", "overdue"]).delivery_statuses == [
        "missing_date",
        "overdue",
    ]


async def test_unpinned_report_observations_cannot_authorize_followup_source_mixing(domain):
    executor = mcp.MarketToolExecutor(context(), AsyncMock(return_value=True))
    await bind_scope(executor)
    # A report's individually observed sources are not an immutable release lease.
    executor.observations = {"sales": {"built_at": "a"}, "rentals": {"built_at": "a"}}
    response = await executor.call("query_market_metrics", ARGS)
    assert response["status"] == "unavailable"
    assert response["error"]["code"] == "release_unavailable"
    domain.assert_not_awaited()
