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
from fastapi import HTTPException
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
from app.chat.broker_scope import BrokerTurnScope, verify_quotation_charges
from app.chat.scope import BindMarketScopeRequest, ScopeError, TurnScope, validate_period
from app.crm.broker import BROKER_DESCRIPTIONS, BROKER_TOOL_MODELS, execute_broker_tool
from app.crm.documents import DOCUMENT_DESCRIPTIONS, DOCUMENT_TOOL_MODELS, execute_document_tool
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
from app.project.delivery import get_delivery_summary
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
        default_factory=lambda: ["scheduled_in_horizon"], min_length=1, max_length=6
    )
    horizon_months: int = Field(default=24, ge=1, le=120)
    project_statuses: list[Literal["ACTIVE", "NOT_STARTED", "PENDING", "FINISHED"]] = Field(
        default_factory=lambda: ["ACTIVE"], max_length=4
    )
    limit: int = Field(default=20, ge=1, le=50)


TOOL_MODELS = {
    "bind_market_scope": BindMarketScopeRequest,
    "query_market_metrics": MarketMetricsRequest,
    "get_listing_inventory": ListingEvidenceRequest,
    "get_project_delivery_summary": DeliveryRequest,
    "compare_listing_age": ListingAgeRequest,
    "compare_listing_rents": ListingRentRequest,
    "compose_market_report": ReportRequest,
}
DESCRIPTIONS = {
    "bind_market_scope": "Before retrieval, bind ALL explicit user constraints once. Declare separate cohorts for requested comparisons, retaining paired location/bedroom/price/period constraints. Price flags must state strict or inclusive boundaries. Do not infer scope from tool output or invent missing parameters. Later calls inherit omitted fields and reject conflicts; scope is immutable for this turn.",
    "query_market_metrics": "Shared canonical sales or annual registered-rent metrics. Average=mean_aed; mean, median, total and per-area are distinct. Last month/quarter use previous_month/previous_quarter; last six complete months use previous_months with months=6. Evidence retains units, counts, sources and explicit coverage. Never replace unavailable values.",
    "get_listing_inventory": "Use for current listing counts and median ASKING prices by bedroom, including studio/1/2 comparisons. Current Property Finder inventory; rent is annualized. Snapshot asking prices are not achieved sales. Exact building filters return bounded contact-free listing evidence. Bayut/Reelly are unavailable.",
    "get_project_delivery_summary": "DLD project/unit counts by developer/status/year/project; distinguishes missing/overdue/scheduled delivery. Defaults to ACTIVE and scheduled_in_horizon for the next 24 months. Select missing_date/overdue/scheduled_later explicitly for audits; by_delivery_status also describes all categories. Scheduled dates are not delivery guarantees.",
    "compare_listing_age": "Sale listings older than a threshold at capture, with unknown ages separately. Compare exact building, bedrooms, property type and 100-sqft size-band newer peers. Posting, first-observation and capture dates are distinct.",
    "compare_listing_rents": "Bounded sale listings with comparable registered annual-rent evidence, samples and supported gross-yield IQR. Reuse the listing scope_id: asking-price bounds remain sale-listing filters, not rental-contract amounts. An omitted rent-evidence period defaults to rolling_days with days=90; previous_months REQUIRES months. Requires known bedrooms; no silent building fallback. Estimates are withheld without a pinned shared release, complete coverage and at least five contracts.",
    "compose_market_report": "Compose rental_appraisal, seller_competition, monthly_area or off_plan_comparison from domain evidence. Supply explicit building/project bindings; placeholders require clarification. Missing sources/coverage and unpinned composites remain unavailable.",
}


CRM_TOOL_MODELS = {**BROKER_TOOL_MODELS, **DOCUMENT_TOOL_MODELS}
TOOL_MODELS.update(CRM_TOOL_MODELS)
DESCRIPTIONS.update(BROKER_DESCRIPTIONS)
DESCRIPTIONS.update(DOCUMENT_DESCRIPTIONS)


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


def tool_definitions() -> list[types.Tool]:
    tools = []
    for name, model in TOOL_MODELS.items():
        request = _strict_schema(model.model_json_schema())
        if name == "query_market_metrics":
            request["properties"].pop("reference_date", None)
        if name not in CRM_TOOL_MODELS and name != "bind_market_scope" and "required" in request:
            # These fields may come from a frozen cohort. The merged request still
            # passes the unchanged domain model and period validation before reads.
            inherited = {"dataset", "location", "bedrooms", "period"}
            request["required"] = [field for field in request["required"] if field not in inherited]
        definitions = request.pop("$defs", {})
        schema = {
            "type": "object",
            "properties": {"request": request},
            "required": ["request"],
            "additionalProperties": False,
        }
        if name not in CRM_TOOL_MODELS and name != "bind_market_scope":
            schema["properties"]["scope_id"] = {
                "type": "string",
                "description": "Id from bind_market_scope. May be omitted only when exactly one cohort matches this capability's evidence_kind. Omitted scoped request fields are inherited; conflicting values are rejected.",
                "maxLength": 40,
            }
        if definitions:
            period = definitions.get("MarketPeriodRequest")
            if period:
                period["description"] += (
                    " Required parameters: previous_months needs months; rolling_days needs days; "
                    "month needs month; quarter needs quarter; range needs start and end. "
                    "Never guess a missing value or substitute a different period after validation failure."
                )
                for field, description in {
                    "months": "Required for previous_months: requested number of complete calendar months (1–120).",
                    "days": "Required for rolling_days: requested number of calendar days (1–3660).",
                    "start": "Required for range, inclusive start date; must not exceed end.",
                    "end": "Required for range, inclusive end date; must not precede start.",
                }.items():
                    period["properties"][field]["description"] = description
            schema["$defs"] = definitions
        tools.append(
            types.Tool(
                name=name,
                description=DESCRIPTIONS[name],
                inputSchema=schema,
                annotations=types.ToolAnnotations(
                    readOnlyHint=name not in {"prepare_broker_action", "create_broker_document"},
                    destructiveHint=False,
                    idempotentHint=name != "prepare_broker_action",
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
    for index, name in enumerate(fields.get("projects") or []):
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

    def __init__(
        self,
        context: ChatToolContext,
        authorize: AuthorizeChatTool,
        release=None,
        *,
        user_instruction=None,
    ):
        self.context = context
        self.user_instruction = user_instruction
        self.authorize = authorize
        self.release = release
        self.calls = 0
        self.result_bytes = 0
        self.observations = {}
        self.lock = asyncio.Lock()
        self.scope = TurnScope(context.reference_date)
        self.broker_scope = BrokerTurnScope()

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

    def bounded_result(self, result: dict) -> dict:
        size = len(json.dumps(result, allow_nan=False).encode())
        if size > MAX_RESULT_BYTES or self.result_bytes + size > MAX_TURN_BYTES:
            return self.envelope(
                "error",
                code="evidence_budget_exceeded",
                message="Evidence exceeds this turn's size limit; narrow the request.",
            )
        self.result_bytes += size
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
                    if (
                        name not in TOOL_MODELS
                        or "request" not in arguments
                        or set(arguments) - {"request", "scope_id"}
                        or ("scope_id" in arguments and not isinstance(arguments["scope_id"], str))
                    ):
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
                    try:
                        if name in CRM_TOOL_MODELS:
                            if "scope_id" in arguments:
                                raise HTTPException(
                                    422,
                                    "Broker tools use authorized enquiry IDs, not market cohorts",
                                )
                            request = TOOL_MODELS[name].model_validate(raw, extra="forbid")
                            request = self.broker_scope.apply(request)
                            if name == "create_broker_document":
                                verify_quotation_charges(
                                    request.charges,
                                    self.user_instruction,
                                    request.missing_charges
                                    if request.kind == "quotation"
                                    else None,
                                )
                            operation = (
                                execute_document_tool
                                if name in DOCUMENT_TOOL_MODELS
                                else execute_broker_tool
                            )
                            with (
                                market_evidence.bounded_market_read(),
                                market_evidence.use_market_release(self.release),
                            ):
                                if name in DOCUMENT_TOOL_MODELS:
                                    data = await operation(
                                        name,
                                        request,
                                        self.context,
                                        requirements=self.broker_scope.for_enquiry(
                                            getattr(request, "enquiry_id", None)
                                        ),
                                    )
                                else:
                                    data = await operation(
                                        name,
                                        request,
                                        self.context,
                                        requirements=self.broker_scope.for_enquiry(
                                            getattr(request, "enquiry_id", None)
                                        ),
                                    )
                            if await self.authorize(self.context) is not True:
                                return self.envelope(
                                    "error",
                                    code="unauthorized",
                                    message="Account access changed during retrieval.",
                                )
                            result = self.envelope(
                                data.get("status")
                                if data.get("status")
                                in {"error", "unavailable", "clarification_required"}
                                else "ok",
                                data,
                            )
                            result["evidence"].update(
                                sources=["crm"],
                                coverage={
                                    "status": "recorded",
                                    "note": "Authorized stored CRM records; current interest and availability require explicit evidence.",
                                },
                                limitations=data.get("limitations", []),
                            )
                            return self.bounded_result(result)
                        if name == "bind_market_scope":
                            request = BindMarketScopeRequest.model_validate(raw, extra="forbid")
                            for cohort in request.cohorts:
                                if missing := _bindings(cohort):
                                    return self.envelope(
                                        "clarification_required", {"required_bindings": missing}
                                    )
                            self.scope.bind(request)
                            return self.bounded_result(
                                self.envelope(
                                    "ok",
                                    {
                                        "cohorts": [
                                            cohort.model_dump(mode="json", exclude_none=True)
                                            for cohort in self.scope.cohorts
                                        ]
                                    },
                                )
                            )
                        raw, scope = self.scope.apply(
                            name, raw, TOOL_MODELS[name], arguments.get("scope_id")
                        )
                        request = TOOL_MODELS[name].model_validate(raw, extra="forbid")
                        if period := getattr(request, "period", None):
                            validate_period(period, self.context.reference_date)
                    except ScopeError as error:
                        result = self.envelope("error", code=error.code, message=str(error))
                        result["error"]["details"] = error.details
                        return result
                    except ValidationError as error:
                        result = self.envelope(
                            "error",
                            code="invalid_arguments",
                            message="Correct the indicated fields without removing constraints. Ask for clarification when a required value is unknown.",
                        )
                        result["error"]["details"] = [
                            {
                                "field": ".".join(str(part) for part in issue["loc"]),
                                "message": issue["msg"],
                            }
                            for issue in error.errors(include_url=False, include_input=False)
                        ]
                        return result
                    if missing := _bindings(request):
                        return self.envelope(
                            "clarification_required", {"required_bindings": missing}
                        )
                    sources = _sources(name, request)
                    if (
                        self.release is None
                        and self.observations
                        and len(set(sources) | self.observations.keys()) > 1
                    ):
                        return self.envelope(
                            "unavailable",
                            code="release_unavailable",
                            message="A shared immutable release is required before combining different sources in one turn.",
                        )
                    if self.release and not set(sources) <= self.release.sources:
                        return self.envelope(
                            "unavailable",
                            code="release_source_unavailable",
                            message="The pinned release does not include every requested source.",
                        )
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
                    result["evidence"]["scope"] = scope
                    result["evidence"]["coverage"] = data.get(
                        "coverage",
                        {
                            "status": "per_component",
                            "note": "Inspect each component's period coverage; no completeness is inferred.",
                        },
                    )
                    result["evidence"]["limitations"] += data.get("limitations", [])
                    return self.bounded_result(result)
        except HTTPException as error:
            return self.envelope(
                "error",
                code="unauthorized"
                if error.status_code in {403, 404}
                else "invalid_arguments"
                if error.status_code in {409, 422}
                else "capability_unavailable",
                message=str(error.detail),
                retryable=False,
            )
        except TimeoutError:
            return self.envelope(
                "error",
                code="tool_timeout",
                message="The bounded retrieval timed out; narrow the request or retry.",
                retryable=True,
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
    context: ChatToolContext, authorize: AuthorizeChatTool, *, user_instruction: str | None = None
) -> AsyncIterator[MCPServerStreamableHTTP]:
    """Create and close a real authenticated MCP server/client for exactly one chat turn."""
    async with market_evidence.acquire_market_release(context) as release:
        executor = MarketToolExecutor(
            context, authorize, release, user_instruction=user_instruction
        )
        server = Server("vitevue-market", version="1")

        @server.list_tools()
        async def list_tools():
            return tool_definitions()

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
