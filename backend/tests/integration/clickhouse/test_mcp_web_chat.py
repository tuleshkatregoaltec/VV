"""Real web-chat SSE → MCP HTTP → shared service → disposable ClickHouse.

The model and external identity lookup are scripted. This proves protocol, persistence
and numerical plumbing, not live-model judgment or Chat2's final release acceptance.
"""

import json
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from test_market_metrics import SALE_COLUMNS, SALES, sale

from app.chat import mcp, service
from app.chat.agent import agent
from app.core.dependencies import AuthContext, require_active_subscription, require_token_quota
from app.organization.models import Organization, OrganizationMembership
from app.postgres import get_db_session


async def test_average_sale_price_last_month_through_web_chat(
    warehouse, install_serving, pg_session, monkeypatch
):
    from app.main import app

    await install_serving(tables=("market_sale_events",), views=("ch_transactions",))
    await warehouse.insert("market_sale_events", SALES, column_names=SALE_COLUMNS)
    # A superseded correction must not inflate the corrected canonical sale's amount/count.
    await warehouse.insert(
        "market_sale_events",
        [
            sale(
                "S2-superseded",
                datetime(2026, 9, 15),
                "Sales",
                9_000_000,
                100,
                "JUMEIRAH VILLAGE CIRCLE",
                served=0,
                status="superseded",
            )
        ],
        column_names=SALE_COLUMNS,
    )
    user, org = str(uuid4()), str(uuid4())
    pg_session.add(Organization(id=org, name="Isolated MCP test", subscription_status="active"))
    pg_session.add(OrganizationMembership(user_id=user, organization_id=org))
    await pg_session.commit()
    actor = SimpleNamespace(id=user, is_authenticated=True, daily_token_limit=500000)
    monkeypatch.setattr(service, "get_user_by_id", AsyncMock(return_value=actor))
    monkeypatch.setattr(service, "business_today", lambda: date(2026, 10, 3))
    auth = AuthContext(actor, SimpleNamespace(id=org), SimpleNamespace(role="member"), None)

    async def session():
        yield pg_session

    app.dependency_overrides[get_db_session] = session
    app.dependency_overrides[require_active_subscription] = lambda: auth
    app.dependency_overrides[require_token_quota] = lambda: None
    methods, results = [], []
    original = mcp.AuthenticatedMCPApp.__call__

    async def observe(self, scope, receive, send):
        async def read():
            message = await receive()
            if message.get("body"):
                methods.append(json.loads(message["body"]).get("method"))
            return message

        return await original(self, scope, read, send)

    monkeypatch.setattr(mcp.AuthenticatedMCPApp, "__call__", observe)
    request = {
        "dataset": "sales",
        "period": {"type": "previous_month"},
        "metrics": ["count", "mean_aed", "median_aed", "total_aed"],
    }

    async def scripted(messages, info):
        returned = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if not returned:
            yield {
                0: DeltaToolCall(
                    name="query_market_metrics",
                    json_args=json.dumps({"request": request}),
                    tool_call_id="sales",
                )
            }
        else:
            payload = returned[-1].content
            if isinstance(payload, str):
                payload = json.loads(payload)
            results.append(payload)
            data = payload["data"]
            values = data["total"]["values"]
            yield (
                f"September 2026: {data['total']['count']} eligible sales; mean AED {values['mean_aed']:,.2f}; "
                f"median AED {values['median_aed']:,.2f}; total AED {values['total_aed']:,.2f}. Coverage is unverified."
            )

    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            api = await client.post(
                "/api/v1/analytics/market-metrics", json=request | {"reference_date": "2026-10-03"}
            )
            assert api.status_code == 200
            created = await client.post("/api/v1/chat/conversations", json={})
            assert created.status_code == 200
            cid = created.json()["id"]
            body = {
                "message": "What was the average sale price last month?",
                "request_id": str(uuid4()),
            }
            with agent.override(model=FunctionModel(stream_function=scripted)):
                response = await client.post(
                    f"/api/v1/chat/conversations/{cid}/messages/stream", json=body
                )
                replay = await client.post(
                    f"/api/v1/chat/conversations/{cid}/messages/stream", json=body
                )
            events = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            assert events[-1] == {"type": "done"}, events
            assert {"initialize", "tools/list", "tools/call"} <= set(methods)
            assert methods.count("tools/call") == 1  # Retry never calls model/tools again.
            assert len(results) == 1
            expected = {
                "mean_aed": 3_250_000.0,
                "median_aed": 2_500_000.0,
                "total_aed": 13_000_000.0,
            }
            for result in (api.json(), results[0]["data"]):
                assert result["total"]["count"] == 4
                assert result["total"]["values"] == expected
                assert result["period"]["start"] == "2026-09-01"
                assert result["period"]["end"] == "2026-09-30"
                assert result["period"]["timezone"] == "Asia/Dubai"
                assert {metric["unit"] for metric in result["definitions"]} == {
                    "records",
                    "AED",
                }
            assert results[0]["evidence"]["coverage"]["status"] == "unverified"
            cards = [event["artifact"] for event in events if event["type"] == "artifact_updated"]
            assert len(cards) == 1
            assert cards[0]["data"]["points"][0]["value"] == 3_250_000
            assert cards[0]["query"]["coverage"]["status"] == "unverified"
            answer = "".join(event.get("content", "") for event in events)
            assert (
                answer
                == "September 2026: 4 eligible sales; mean AED 3,250,000.00; median AED 2,500,000.00; total AED 13,000,000.00. Coverage is unverified."
            )
            assert answer in replay.text
            persisted = (await client.get(f"/api/v1/chat/conversations/{cid}/messages")).json()
            assert [message["role"] for message in persisted] == ["user", "assistant"]
            assert persisted[0]["meta_data"]["turn_status"] == "complete"
            assert persisted[1]["meta_data"]["artifacts"] == cards
            replay_events = [
                json.loads(line[6:])
                for line in replay.text.splitlines()
                if line.startswith("data: ")
            ]
            assert [
                event["artifact"] for event in replay_events if event["type"] == "artifact_updated"
            ] == cards
            assert (
                persisted[1]["meta_data"]["evidence"][0]["result"]["data"]["total"]["values"]
                == expected
            )
    finally:
        app.dependency_overrides.clear()
