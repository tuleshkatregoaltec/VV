"""Authenticated per-turn MCP Streamable HTTP server and Pydantic AI client.

The in-process ASGI transport still runs the supported MCP wire protocol: initialize,
notifications/initialized, tools/list and tools/call. A fresh opaque transport credential,
server, client and immutable actor context belong to each turn; no HTTP listener or shared
model-controlled identity exists. Domain services own all database access and arithmetic.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from mcp import types
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai.mcp import MCPServerStreamableHTTP
from starlette.responses import JSONResponse

from app.analytics.evidence import get_market_evidence, get_market_observation
from app.analytics.models import MarketMetricsRequest
from app.listings.capabilities import (
    compare_listing_age,
    compare_listing_rents,
    get_listing_inventory,
    get_listing_observation,
)
from app.listings.capability_models import (
    ListingAgeRequest,
    ListingEvidenceRequest,
    ListingRentRequest,
)
from app.market import evidence as market_evidence
from app.market.evidence import COVERAGE_NOTE, RELEASE_NOTE, MarketAccessContext
from app.market.reports import ReportRequest, compose_market_report, required_bindings
from app.project.delivery import ALL_DELIVERY_STATUSES, get_delivery_summary
from app.project.evidence import get_project_observation
from app.project.models import DeliveryStatus

ChatToolContext = MarketAccessContext
AuthorizeChatTool = Callable[[ChatToolContext], Awaitable[bool]]
TOOL_TIMEOUT_SECONDS = 20
MAX_TOOL_CALLS = 12
MAX_RESULT_BYTES = 64 * 1024
MAX_TURN_BYTES = 192 * 1024
MAX_ARGUMENT_BYTES = 16 * 1024


class DeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location: str | None = Field(default=None, max_length=120)
    group_by: Literal["developer", "delivery_status", "delivery_year", "project"] = "developer"
    delivery_statuses: list[DeliveryStatus] = Field(
        default_factory=lambda: list(ALL_DELIVERY_STATUSES), max_length=6
    )
    horizon_months: int = Field(default=24, ge=1, le=120)
    project_statuses: list[Literal["ACTIVE", "NOT_STARTED", "PENDING", "FINISHED"]] = Field(
        default_factory=lambda: ["ACTIVE"], max_length=4
    )
    limit: int = Field(default=20, ge=1, le=50)


TOOL_MODELS = {
    "query_market_metrics": MarketMetricsRequest,
    "get_listing_inventory": ListingEvidenceRequest,
    "get_project_delivery_summary": DeliveryRequest,
    "compare_listing_age": ListingAgeRequest,
    "compare_listing_rents": ListingRentRequest,
    "compose_market_report": ReportRequest,
}
DESCRIPTIONS = {
    "query_market_metrics": "Shared canonical sales or annual registered-rent metrics. Average=mean_aed; mean, median, total and per-area are distinct. Last month/quarter use previous_month/previous_quarter; last six complete months use previous_months with months=6. Evidence retains units, counts, sources and explicit coverage. Never replace unavailable values.",
    "get_listing_inventory": "Current Property Finder inventory and asking prices; rent is annualized. Snapshot asking prices are not achieved sales. Exact building filters return bounded contact-free listing evidence. Bayut/Reelly are unavailable.",
    "get_project_delivery_summary": "DLD project/unit counts by developer/status/year/project; distinguishes missing/overdue/scheduled delivery. Defaults to ACTIVE, horizon 24 months. Scheduled dates are not delivery guarantees.",
    "compare_listing_age": "Sale listings older than a threshold at capture, with unknown ages separately. Compare exact building, bedrooms, property type and 100-sqft size-band newer peers. Posting, first-observation and capture dates are distinct.",
    "compare_listing_rents": "Bounded sale listings with comparable registered annual-rent evidence, samples and supported gross-yield IQR. Requires known bedrooms; no silent building fallback. Estimates are withheld without a pinned shared release, complete coverage and at least five contracts.",
    "compose_market_report": "Compose rental_appraisal, seller_competition, monthly_area or off_plan_comparison from domain evidence. Supply explicit building/project bindings; placeholders require clarification. Missing sources/coverage and unpinned composites remain unavailable.",
}


def _strict_schema(schema: dict) -> dict:
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
    for value in schema.values():
        if isinstance(value, dict):
            _strict_schema(value)
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, dict):
                    _strict_schema(child)
    return schema


def _tools() -> list[types.Tool]:
    tools = []
    for name, model in TOOL_MODELS.items():
        request = _strict_schema(model.model_json_schema())
        if name == "query_market_metrics":
            request["properties"].pop("reference_date", None)
        definitions = request.pop("$defs", {})
        schema = {
            "type": "object",
            "properties": {"request": request},
            "required": ["request"],
            "additionalProperties": False,
        }
        if definitions:
            schema["$defs"] = definitions
        tools.append(
            types.Tool(
                name=name,
                description=DESCRIPTIONS[name],
                inputSchema=schema,
                annotations=types.ToolAnnotations(
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            )
        )
    return tools


def _placeholder(value: str) -> bool:
    normalized = value.strip().casefold()
    return (
        not normalized
        or ("[" in normalized and "]" in normalized)
        or normalized
        in {"building", "project a", "project b", "project c", "your building", "unknown", "tbd"}
    )


def _bindings(request: BaseModel) -> list[str]:
    missing = []
    fields = request.model_dump()
    for field in ("building", "project", "location"):
        if fields.get(field) is not None and _placeholder(fields[field]):
            missing.append(field)
    for index, name in enumerate(fields.get("projects", [])):
        if len(name) > 160 or _placeholder(name):
            missing.append(f"projects[{index}]")
    if isinstance(request, ReportRequest):
        missing.extend(required_bindings(request))
    return list(dict.fromkeys(missing))


def _sources(name: str, request: BaseModel) -> tuple[str, ...]:
    if name == "query_market_metrics":
        return (request.dataset,)
    if name in {"get_listing_inventory", "compare_listing_age"}:
        return ("listings",)
    if name == "get_project_delivery_summary":
        return ("projects",)
    if name == "compare_listing_rents":
        return ("listings", "rentals")
    return {
        "rental_appraisal": ("rentals", "listings"),
        "seller_competition": ("sales", "listings"),
        "monthly_area": ("sales", "rentals", "listings", "projects"),
        "off_plan_comparison": ("projects", "sales"),
    }[request.kind]


async def _observe(sources: tuple[str, ...]) -> dict:
    result = {}
    for source in sources:
        if source in {"sales", "rentals"}:
            result[source] = await get_market_observation(source)
        elif source == "listings":
            result[source] = await get_listing_observation()
        else:
            result[source] = await get_project_observation()
    return result


class MarketToolExecutor:
    """One server owns one authorization scope, sequential release observations and budgets."""

    def __init__(self, context: ChatToolContext, authorize: AuthorizeChatTool, release=None):
        self.context = context
        self.authorize = authorize
        self.release = release
        self.calls = 0
        self.result_bytes = 0
        self.observations = {}
        self.lock = asyncio.Lock()

    def envelope(self, status: str, data=None, *, code=None, message=None, retryable=False):
        result = {
            "status": status,
            "data": data,
            "evidence": {
                "reference_date": self.context.reference_date.isoformat(),
                "release": {
                    "id": self.release.release_id if self.release else None,
                    "consistency": "pinned" if self.release else "observed_snapshot_only",
                    "observations": self.observations.copy(),
                },
                "coverage": {"status": "unverified", "note": COVERAGE_NOTE},
                "limitations": [] if self.release else [RELEASE_NOTE],
                "sources": [],
            },
        }
        if code:
            result["error"] = {"code": code, "message": message, "retryable": retryable}
        return result

    async def call(self, name: str, arguments: dict) -> dict:
        self.calls += 1
        if self.calls > MAX_TOOL_CALLS:
            return self.envelope(
                "error",
                code="tool_budget_exceeded",
                message="This turn reached its tool-call limit.",
            )
        try:
            async with asyncio.timeout(TOOL_TIMEOUT_SECONDS):
                async with self.lock:
                    if await self.authorize(self.context) is not True:
                        return self.envelope(
                            "error",
                            code="unauthorized",
                            message="Current account access does not authorize this operation.",
                        )
                    if name not in TOOL_MODELS or set(arguments) != {"request"}:
                        return self.envelope(
                            "error",
                            code="invalid_arguments",
                            message="Use a registered tool and its typed request only.",
                        )
                    if len(json.dumps(arguments).encode()) > MAX_ARGUMENT_BYTES:
                        return self.envelope(
                            "error",
                            code="invalid_arguments",
                            message="Tool arguments exceed the permitted size.",
                        )
                    raw = arguments["request"]
                    if not isinstance(raw, dict) or "reference_date" in raw:
                        return self.envelope(
                            "error",
                            code="invalid_arguments",
                            message="Reference dates and execution identity are server-owned; use explicit period fields for historical dates.",
                        )
                    request = TOOL_MODELS[name].model_validate(raw, extra="forbid")
                    if missing := _bindings(request):
                        return self.envelope(
                            "clarification_required", {"required_bindings": missing}
                        )
                    sources = _sources(name, request)
                    with (
                        market_evidence.bounded_market_read(),
                        market_evidence.use_market_release(self.release),
                    ):
                        before = await _observe(sources)
                        if any(
                            source in self.observations and self.observations[source] != observation
                            for source, observation in before.items()
                        ):
                            return self.envelope(
                                "error",
                                code="release_changed",
                                message="The observed source changed during this turn; retry in a new turn.",
                                retryable=True,
                            )
                        self.observations.update(before)
                        data = await self.dispatch(name, request)
                        if await _observe(sources) != before:
                            return self.envelope(
                                "error",
                                code="release_changed",
                                message="The observed source changed during retrieval; retry in a new turn.",
                                retryable=True,
                            )
                    # Revalidation after retrieval prevents disclosure after an access revocation.
                    if await self.authorize(self.context) is not True:
                        return self.envelope(
                            "error",
                            code="unauthorized",
                            message="Account access changed during retrieval.",
                        )
                    status = data.get(
                        "status",
                        "unavailable"
                        if data.get("coverage", {}).get("status") == "unavailable"
                        else "ok",
                    )
                    result = self.envelope(status, data)
                    result["evidence"]["sources"] = list(sources)
                    result["evidence"]["coverage"] = data.get(
                        "coverage",
                        {
                            "status": "per_component",
                            "note": "Inspect each component's period coverage; no completeness is inferred.",
                        },
                    )
                    result["evidence"]["limitations"] += data.get("limitations", [])
                    size = len(json.dumps(result, allow_nan=False).encode())
                    if size > MAX_RESULT_BYTES or self.result_bytes + size > MAX_TURN_BYTES:
                        return self.envelope(
                            "error",
                            code="evidence_budget_exceeded",
                            message="Evidence exceeds this turn's size limit; narrow the request.",
                        )
                    self.result_bytes += size
                    return result
        except TimeoutError:
            return self.envelope(
                "error",
                code="tool_timeout",
                message="The bounded retrieval timed out; narrow the request or retry.",
                retryable=True,
            )
        except (ValidationError, ValueError, TypeError):
            return self.envelope(
                "error",
                code="invalid_arguments",
                message="The typed request is invalid. Check its allowed fields, period and bounds.",
            )
        except Exception:
            # Never expose database SQL, credentials, raw exception content or record payloads.
            return self.envelope(
                "error",
                code="capability_unavailable",
                message="The requested evidence could not be retrieved.",
                retryable=True,
            )

    async def dispatch(self, name, request):
        operations = {
            "query_market_metrics": get_market_evidence,
            "get_listing_inventory": get_listing_inventory,
            "compare_listing_age": compare_listing_age,
            "compare_listing_rents": compare_listing_rents,
            "compose_market_report": compose_market_report,
        }
        if name in operations:
            return await operations[name](request, context=self.context)
        result = await get_delivery_summary(
            **request.model_dump(), reference_date=self.context.reference_date
        )
        return result.model_dump(mode="json")


class AuthenticatedMCPApp:
    def __init__(self, manager: StreamableHTTPSessionManager, credential: str):
        self.manager = manager
        self.credential = credential

    async def __call__(self, scope, receive, send):
        headers = dict(scope.get("headers", []))
        supplied = headers.get(b"authorization", b"")
        expected = f"Bearer {self.credential}".encode()
        if (
            scope["type"] != "http"
            or scope.get("path") != "/mcp"
            or not hmac.compare_digest(supplied, expected)
        ):
            await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
            return
        await self.manager.handle_request(scope, receive, send)


class MarketMCPClient(MCPServerStreamableHTTP):
    @asynccontextmanager
    async def client_streams(self):
        # Pydantic AI 1.38 uses the SDK's deprecated client-factory signature, which
        # changed in MCP 1.25. Use the supported direct http_client transport API.
        async with streamable_http_client(self.url, http_client=self.http_client) as (
            read,
            write,
            _,
        ):
            yield read, write


@asynccontextmanager
async def market_mcp(
    context: ChatToolContext, authorize: AuthorizeChatTool
) -> AsyncIterator[MCPServerStreamableHTTP]:
    """Create and close a real authenticated MCP server/client for exactly one chat turn."""
    async with market_evidence.acquire_market_release(context) as release:
        executor = MarketToolExecutor(context, authorize, release)
        server = Server("vitevue-market", version="1")

        @server.list_tools()
        async def list_tools():
            return _tools()

        # Typed validation in the executor returns stable, sanitized structured failures.
        @server.call_tool(validate_input=False)
        async def call_tool(name: str, arguments: dict[str, Any]):
            return await executor.call(name, arguments)

        manager = StreamableHTTPSessionManager(
            server,
            json_response=True,
            stateless=True,
            security_settings=TransportSecuritySettings(
                enable_dns_rebinding_protection=True, allowed_hosts=["market-mcp.local"]
            ),
        )
        credential = secrets.token_urlsafe(32)
        app = AuthenticatedMCPApp(manager, credential)
        async with manager.run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://market-mcp.local",
                headers={"Authorization": f"Bearer {credential}"},
                timeout=TOOL_TIMEOUT_SECONDS + 5,
            ) as client:
                toolset = MarketMCPClient(
                    "http://market-mcp.local/mcp",
                    http_client=client,
                    timeout=TOOL_TIMEOUT_SECONDS + 5,
                    read_timeout=TOOL_TIMEOUT_SECONDS + 5,
                    allow_sampling=False,
                    max_retries=0,
                    id="market-evidence",
                )
                async with toolset:
                    await toolset.list_tools()
                    yield toolset
