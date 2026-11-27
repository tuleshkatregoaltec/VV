"""One durable USD 10 campaign ledger, reserved before every provider request.

SQLite transactions serialize separate processes. Pending reservations survive errors,
timeouts, cancellation and process death; there is deliberately no reset/reclaim CLI.
"""

import math
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager, contextmanager
from copy import deepcopy
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from pydantic_ai.models.wrapper import WrapperModel

from scripts.evaluations.market_ai.tracing import private_directory

CANDIDATES = (
    "qwen/qwen3.8-flash",
    "qwen/qwen3.7-plus",
    "openai/gpt-6-luna",
    "anthropic/claude-haiku-5.5",
    "deepseek/deepseek-v4.1-flash",
    "z-ai/glm-5.3-flash",
)
STAGE_LIMITS = {"screen": 3_000_000, "challenge": 2_000_000, "flows": 5_000_000}
TOTAL_LIMIT = 10_000_000
DEFAULT_LEDGER = Path(__file__).resolve().parents[3] / ".evaluation/assistant-selection.sqlite3"
MAX_OUTPUT = 3000
# Explicit ceilings allow eligible privacy-preserving routes above the cheapest
# catalog endpoint. These remain hard provider caps, not spend estimates.
PRICE_CEILINGS_PER_MILLION = {
    "deepseek/deepseek-v4.1-flash": {"prompt": Decimal("0.20"), "completion": Decimal("1")},
    "z-ai/glm-5.3-flash": {"prompt": Decimal("0.20"), "completion": Decimal("1")},
}


class BudgetExhausted(RuntimeError):
    pass


def microdollars(value) -> int:
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError("Costs must be finite and nonnegative")
    return int((number * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


class TrialLedger:
    def __init__(self, path=DEFAULT_LEDGER):
        self.path = Path(path)
        private_directory(self.path.parent)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        os.close(fd)
        with self.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS campaign (id INTEGER PRIMARY KEY, blocked TEXT)")
            db.execute("INSERT OR IGNORE INTO campaign VALUES (1, NULL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS reservations ("
                "id TEXT PRIMARY KEY, stage TEXT NOT NULL, model TEXT NOT NULL, "
                "run_id TEXT NOT NULL, case_id TEXT NOT NULL, reserve INTEGER NOT NULL, "
                "accounted INTEGER NOT NULL, actual INTEGER, state TEXT NOT NULL, "
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )

    @contextmanager
    def transaction(self):
        with sqlite3.connect(self.path, timeout=30, isolation_level=None) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def reserve(self, *, stage, model, run_id, case_id, amount):
        if stage not in STAGE_LIMITS or model not in CANDIDATES:
            raise ValueError("Unapproved trial stage or candidate")
        reserve = microdollars(amount)
        if reserve <= 0:
            raise ValueError("Reserve must be positive")
        with self.transaction() as db:
            if db.execute("SELECT blocked FROM campaign WHERE id=1").fetchone()[0]:
                raise BudgetExhausted("Campaign blocked after inconsistent provider cost")
            total = db.execute("SELECT COALESCE(SUM(accounted), 0) FROM reservations").fetchone()[0]
            stage_total = db.execute(
                "SELECT COALESCE(SUM(accounted), 0) FROM reservations WHERE stage=?", (stage,)
            ).fetchone()[0]
            if total + reserve > TOTAL_LIMIT or stage_total + reserve > STAGE_LIMITS[stage]:
                raise BudgetExhausted(
                    "Cumulative campaign/stage reserve exhausted; evidence retained"
                )
            reservation_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO reservations "
                "(id,stage,model,run_id,case_id,reserve,accounted,state) VALUES (?,?,?,?,?,?,?,?)",
                (reservation_id, stage, model, run_id, case_id, reserve, reserve, "pending"),
            )
        return reservation_id

    def settle(self, reservation_id, actual=None):
        cost = microdollars(actual) if actual is not None else None
        exceeded = False
        with self.transaction() as db:
            row = db.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone()
            if row is None or row["state"] != "pending":
                raise ValueError("Reservation missing or already settled")
            if cost is not None and cost > row["reserve"]:
                exceeded = True
                db.execute(
                    "UPDATE campaign SET blocked='provider cost exceeded reserve' WHERE id=1"
                )
            db.execute(
                "UPDATE reservations SET accounted=?,actual=?,state=? WHERE id=?",
                (
                    cost if cost is not None else row["reserve"],
                    cost,
                    "settled" if cost is not None else "unknown",
                    reservation_id,
                ),
            )
        if exceeded:
            raise BudgetExhausted("Provider cost exceeded enforced price bound; campaign blocked")

    def snapshot(self):
        with self.transaction() as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM reservations ORDER BY rowid")]
            blocked = db.execute("SELECT blocked FROM campaign WHERE id=1").fetchone()[0]
        return {
            "limit_usd": TOTAL_LIMIT / 1_000_000,
            "accounted_usd": sum(row["accounted"] for row in rows) / 1_000_000,
            "stage_accounted_usd": {
                stage: sum(row["accounted"] for row in rows if row["stage"] == stage) / 1_000_000
                for stage in STAGE_LIMITS
            },
            "blocked": blocked,
            "requests": rows,
        }


def price_bound(entry):
    """Reserve a full model context, plus all completion/reasoning and request fees.

    Provider max_price caps enforce these rates even for context-dependent tiers.
    Nontext modalities and extra billable features are never enabled by this harness.
    """
    context = entry.get("context_length")
    if not isinstance(context, int) or context < 1:
        raise ValueError("A published positive context length is required")
    prices = entry["pricing"]
    # Catalog overrides describe higher context tiers and are not scalar prices.
    # We enforce the base caps on every request; routes charging a higher tier
    # must be excluded by OpenRouter rather than silently widening our reserve.
    parsed = {key: Decimal(str(value)) for key, value in prices.items() if key != "overrides"}
    if any(not price.is_finite() or price < 0 for price in parsed.values()):
        raise ValueError("Unknown or invalid catalog pricing")
    prompt = max(parsed["prompt"], parsed.get("input_cache_read", Decimal(0)))
    completion = max(parsed["completion"], parsed.get("internal_reasoning", Decimal(0)))
    ceiling = PRICE_CEILINGS_PER_MILLION.get(entry.get("id"), {})
    prompt = max(prompt, ceiling.get("prompt", Decimal(0)) / 1_000_000)
    completion = max(completion, ceiling.get("completion", Decimal(0)) / 1_000_000)
    request = parsed.get("request", Decimal(0))
    permitted = {"prompt", "completion", "request", "input_cache_read", "internal_reasoning"}
    # Image/audio/search/cache writes are not used. Unknown billable text components fail closed.
    unused = {
        "image",
        "web_search",
        "audio",
        "input_audio",
        "output_audio",
        "input_cache_write",
        "input_cache_write_1h",
    }
    if any(value and key not in permitted | unused for key, value in parsed.items()):
        raise ValueError("Unrecognized billable pricing component")
    amount = context * prompt + MAX_OUTPUT * completion + request
    # Tiny positive reserve also handles truly free candidates without a zero-cost bypass.
    return max(amount, Decimal("0.000001")), {
        "prompt": float(prompt * 1_000_000),
        "completion": float(completion * 1_000_000),
        "request": float(request),
    }


def validate_trial_settings(value):
    value = value or {}
    forbidden = {
        "model",
        "models",
        "model_name",
        "preset",
        "route",
        "openrouter_models",
        "openrouter_preset",
        "openrouter_route",
        "openrouter_transforms",
    }
    if forbidden.intersection(value) or value.get("extra_body"):
        raise ValueError("Evaluation forbids model, preset, route and extra_body overrides")


class BudgetedModel(WrapperModel):
    def __init__(self, wrapped, *, ledger, entry, stage, run_id, case_id):
        super().__init__(wrapped)
        if wrapped.model_name not in CANDIDATES or entry["id"] != wrapped.model_name:
            raise ValueError("Only exact approved candidate IDs may be requested")
        self.ledger, self.stage, self.run_id, self.case_id = ledger, stage, run_id, case_id
        self.reserve_usd, self.price_caps = price_bound(entry)
        self.responses = []
        self.request_ids = []
        self.failures = []
        self.failure_statuses = []

    def prepare_request(self, model_settings, model_request_parameters):
        validate_trial_settings(self.wrapped.settings)
        validate_trial_settings(model_settings)
        # Instrumentation prepares settings before forwarding the original request.
        # OpenRouter mutates its input, so never give it the caller/default dictionaries.
        configured = deepcopy({**(self.wrapped.settings or {}), **(model_settings or {})})
        return self.wrapped.prepare_request(configured, model_request_parameters)

    async def request(self, messages, model_settings, model_request_parameters):
        validate_trial_settings(self.wrapped.settings)
        validate_trial_settings(model_settings)
        # Override caller settings, including every nested specialist and retry.
        configured = dict(model_settings or {})
        configured["max_tokens"] = min(configured.get("max_tokens", MAX_OUTPUT), MAX_OUTPUT)
        configured["openrouter_provider"] = {
            "zdr": True,
            "data_collection": "deny",
            "allow_fallbacks": False,
            "require_parameters": True,
            "max_price": self.price_caps,
        }
        # The only model route is the wrapped exact ID; no SDK/server model fallback.
        configured.pop("extra_body", None)
        reservation_id = self.ledger.reserve(
            stage=self.stage,
            model=self.model_name,
            run_id=self.run_id,
            case_id=self.case_id,
            amount=self.reserve_usd,
        )
        self.request_ids.append(reservation_id)
        try:
            response = await self.wrapped.request(messages, configured, model_request_parameters)
        except BaseException as exc:
            self.failures.append(type(exc).__name__)
            if isinstance(getattr(exc, "status_code", None), int):
                self.failure_statuses.append(exc.status_code)
            self.ledger.settle(reservation_id)
            raise
        self.responses.append(response)
        raw_cost = (response.provider_details or {}).get("cost")
        cost = None
        if isinstance(raw_cost, (float, int)) and not isinstance(raw_cost, bool):
            if math.isfinite(raw_cost) and raw_cost >= 0:
                cost = raw_cost
        self.ledger.settle(reservation_id, cost)
        if response.model_name and response.model_name != self.model_name:
            # Resolved model version labels can differ; preserve evidence but never continue silently.
            self.failures.append("ResolvedModelMismatch")
            raise RuntimeError("Provider returned a different model; inspect private evidence")
        return response

    @asynccontextmanager
    async def request_stream(self, *args, **kwargs):
        # This runner is explicitly non-streaming. Never bypass accounting via inherited API.
        raise RuntimeError("Streaming is unsupported in the synthetic campaign")
        yield  # pragma: no cover

    def metrics(self):
        costs = [(response.provider_details or {}).get("cost") for response in self.responses]
        complete = len(self.responses) == len(self.request_ids) and all(
            isinstance(cost, (float, int))
            and not isinstance(cost, bool)
            and math.isfinite(cost)
            and cost >= 0
            for cost in costs
        )
        return {
            "model_requests": len(self.request_ids),
            "input_tokens": sum(response.usage.input_tokens for response in self.responses),
            "output_tokens": sum(response.usage.output_tokens for response in self.responses),
            "usage_details": [response.usage.details for response in self.responses],
            "provider_reported_cost_usd": sum(costs) if complete else None,
            "cost_reporting_complete": complete,
            "request_failures": self.failures,
            **({"http_status": self.failure_statuses[-1]} if self.failure_statuses else {}),
            "reservation_ids": self.request_ids,
            "response_models": sorted({response.model_name for response in self.responses}),
        }
