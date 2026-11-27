"""Bind authenticated HTTP evaluation to the same durable campaign allowance."""

import hashlib
import json
import os
import re
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path

from openai import AsyncOpenAI
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from sqlalchemy.engine import make_url

from scripts.evaluations.market_ai.campaign import choose_leaders
from scripts.evaluations.market_ai.tracing import private_write
from scripts.evaluations.market_ai.trial_budget import (
    BudgetedModel,
    TrialLedger,
    price_bound,
    validate_trial_settings,
)

CURRENT_CASE = ContextVar("evaluation_http_case", default=None)


def application_plan(*, model, prior, snapshot_path, data_context, settings, routing_mode="typed"):
    if routing_mode not in {"existing", "typed"}:
        raise ValueError("Unknown evaluation routing mode")
    if not model or not prior or not snapshot_path:
        raise ValueError("Live HTTP evaluation requires --model, --prior and --snapshot")
    manifest, leaders = choose_leaders(prior)
    from scripts.evaluations.market_ai.trial_context import execution_context

    context = execution_context()
    if not manifest.get("execution_context") or manifest["execution_context"] != context:
        raise ValueError("HTTP selection requires unchanged recorded execution context")
    if manifest["stage"] != "challenge" or model not in leaders:
        raise ValueError("HTTP flows may use only the two qualified challenge leaders")
    snapshot_bytes = Path(snapshot_path).read_bytes()
    snapshot = json.loads(snapshot_bytes)
    required = {"snapshot_id", "postgres_database", "clickhouse_database", "reference_sha256"}
    if not required <= snapshot.keys() or not re.fullmatch(
        r"[a-f0-9]{64}", snapshot["reference_sha256"]
    ):
        raise ValueError(
            "Snapshot requires an ID, both isolated database names and reference_sha256"
        )
    if data_context != "pinned:" + snapshot["snapshot_id"]:
        raise ValueError("Data context must identify the pinned snapshot")
    url = make_url(str(settings.POSTGRES_URL))
    if url.host not in {"localhost", "127.0.0.1", "::1"} or settings.CLICKHOUSE_HOST not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError("HTTP evaluation databases must be local")
    if (
        url.database != snapshot["postgres_database"]
        or settings.CLICKHOUSE_DATABASE != snapshot["clickhouse_database"]
    ):
        raise ValueError("Configured databases do not match the pinned snapshot")
    if any(
        not name.startswith(("eval_", "vv_migration_test_"))
        for name in (url.database, settings.CLICKHOUSE_DATABASE)
    ):
        raise ValueError("Use isolated eval_ or vv_migration_test_ databases")
    entry = manifest["catalog"][model]
    _, provider_price_caps = price_bound(entry)
    return {
        "model": model,
        "routing_mode": routing_mode,
        "execution_context": context,
        "stage": "flows",
        "catalog_entry": entry,
        "provider_price_caps": provider_price_caps,
        "snapshot": snapshot,
        "snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
        "snapshot_path": str(Path(snapshot_path).resolve()),
        "selection_manifest_sha256": hashlib.sha256(
            (Path(prior) / "manifest.json").read_bytes()
        ).hexdigest(),
    }


class HTTPBudgetedModel(WrapperModel):
    """Separate request accounting under the current HTTP case, including nested calls."""

    def __init__(self, wrapped, *, plan, directory, ledger):
        super().__init__(wrapped)
        self.plan, self.directory, self.ledger = plan, directory, ledger

    def prepare_request(self, model_settings, model_request_parameters):
        validate_trial_settings(self.wrapped.settings)
        validate_trial_settings(model_settings)
        configured = deepcopy({**(self.wrapped.settings or {}), **(model_settings or {})})
        return self.wrapped.prepare_request(configured, model_request_parameters)

    async def request(self, messages, model_settings, model_request_parameters):
        case_id = CURRENT_CASE.get()
        if case_id is None:
            raise RuntimeError(
                "Provider execution requires an authenticated evaluation case context"
            )
        model = BudgetedModel(
            self.wrapped,
            ledger=self.ledger,
            entry=self.plan["catalog_entry"],
            stage="flows",
            run_id=self.plan["run_id"],
            case_id=case_id,
        )
        try:
            return await model.request(messages, model_settings, model_request_parameters)
        finally:
            value = {"case_id": case_id, "model": self.model_name, **model.metrics()}
            fd = os.open(
                self.directory / "request-costs.jsonl",
                os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(fd, "a") as stream:
                stream.write(json.dumps(value, default=str) + "\n")

    @asynccontextmanager
    async def request_stream(self, *args, **kwargs):
        # The approved typed application path produces SSE from run_routed_turn;
        # its nested provider calls use request(), never a provider stream.
        raise RuntimeError("HTTP evaluation requires the typed non-streaming provider path")
        yield  # pragma: no cover


class CaseBudgetContext:
    def __init__(self, app, plan):
        self.app, self.case_ids = app, set(plan["case_ids"])
        self.plan = plan
        self.verified = False

    async def __call__(self, scope, receive, send):
        case_id = None
        if scope["type"] == "http" and scope.get("path", "").endswith("/messages/stream"):
            headers = dict(scope.get("headers", []))
            supplied = headers.get(b"x-vv-evaluation-case", b"").decode("ascii", errors="ignore")
            if supplied in self.case_ids:
                case_id = supplied
        token = CURRENT_CASE.set(case_id)
        try:
            if case_id is None:
                await self.app(scope, receive, send)
            else:
                from app.config import settings
                from app.market.releases import pin_market_release
                from scripts.evaluations.market_ai.fixture_snapshot import use_snapshot

                if not self.verified:
                    await use_snapshot(
                        path=self.plan["snapshot_path"], postgres_url=str(settings.POSTGRES_URL)
                    )
                    self.verified = True
                async with pin_market_release() as pinned:
                    release_ids = {key: value.release_id for key, value in pinned.versions.items()}
                    if pinned.missing or release_ids != self.plan["snapshot"]["release_ids"]:
                        raise RuntimeError(
                            "Published release changed; HTTP evaluation stopped before model execution"
                        )
                    await self.app(scope, receive, send)
        finally:
            CURRENT_CASE.reset(token)


def install_http_budget(directory, settings):
    """Call before any application agent imports its model factory; subprocess only."""
    from app.core import openrouter

    plan = json.loads((directory / "campaign.json").read_text())
    if plan["stage"] != "flows":
        raise ValueError("Application evaluations use the flows stage allowance")
    ledger = TrialLedger()
    if ledger.snapshot()["blocked"]:
        raise RuntimeError("Campaign ledger is blocked")
    client = AsyncOpenAI(
        api_key=settings.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        max_retries=0,
        timeout=90,
    )
    provider = OpenRouterProvider(openai_client=client)

    def factory(*args, **kwargs):
        return HTTPBudgetedModel(
            openrouter.CompatibleOpenRouterModel(plan["model"], provider=provider),
            plan=plan,
            directory=directory,
            ledger=ledger,
        )

    openrouter.create_assistant_model = factory
    openrouter.create_openrouter_model = factory
    settings.ASSISTANT_ENABLED = True
    settings.ASSISTANT_TYPED_ROUTING_ENABLED = plan["routing_mode"] == "typed"
    return plan


def case_costs(directory, *, run_id, case_id):
    path = Path(directory) / "request-costs.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    rows = [row for row in rows if row["case_id"] == case_id]
    ledger = TrialLedger().snapshot()
    reservations = [
        row for row in ledger["requests"] if row["run_id"] == run_id and row["case_id"] == case_id
    ]
    captured = {request_id for row in rows for request_id in row["reservation_ids"]}
    complete = all(row["cost_reporting_complete"] for row in rows) and captured == {
        row["id"] for row in reservations
    }
    result = {
        "model_requests": len(reservations),
        "input_tokens": sum(row["input_tokens"] for row in rows),
        "output_tokens": sum(row["output_tokens"] for row in rows),
        "usage_details": [row["usage_details"] for row in rows],
        "cost_reporting_complete": complete,
        "provider_reported_cost_usd": sum(row["provider_reported_cost_usd"] for row in rows)
        if complete
        else None,
        "accounted_cost_upper_bound_usd": sum(row["accounted"] for row in reservations) / 1_000_000,
        "reservation_ids": [row["id"] for row in reservations],
    }
    private_write(Path(directory) / "ledger.json", ledger)
    return result


def load_http_flow_cases(case_ids):
    from dataclasses import dataclass, field

    from scripts.evaluations.market_ai.flow_trial import load_flow_cases

    @dataclass
    class FlowCase:
        id: str
        question: str
        turns: list[str]
        parameters: list[str] = field(default_factory=list)

        def bind(self, parameters=None):
            if parameters:
                raise ValueError("Application flow cases have no template parameters")
            return self.question

    selected = [
        case
        for case in load_flow_cases()
        if case["id"] in case_ids and case["flow"] == "routed" and case.get("assistant") == "market"
    ]
    if {case["id"] for case in selected} != set(case_ids):
        raise ValueError("HTTP flow cases must be routed Market AI cases")
    return [
        FlowCase(case["id"], case["question"], case.get("turns", [case["question"]]))
        for case in selected
    ]
