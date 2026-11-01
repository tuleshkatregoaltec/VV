"""Compare live models with the production prompt and synthetic-only tool implementations.

No application server, database, customer record, or real action is used. The canonical
HTTP/database benchmark remains a separate acceptance test. Run without --live to preview.
"""

import argparse
import asyncio
import copy
import hashlib
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic_ai import ModelRetry, Tool
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.openrouter import OpenRouterModelSettings
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.usage import UsageLimits

from app.chat.agent import agent
from app.chat.dependencies import ChatDependencies
from app.chat.workflows import crm_agent, market_agent, pricing_agent
from app.config import settings
from app.core.openrouter import CompatibleOpenRouterModel
from scripts.evaluation.dataset import load_benchmark
from scripts.evaluation.tracing import private_directory, private_write

FIXTURES = Path(__file__).with_name("model_trial_cases.json")
MAX_TOKENS = 24000
MAX_OUTPUT = 1800


def load_cases():
    canonical = {case.id: case.question for case in load_benchmark().cases}
    cases = json.loads(FIXTURES.read_text())
    for case in cases:
        if case["id"] in canonical:
            case["question"] = canonical[case["id"]]
    return cases


def selected_workflow(case):
    """Synthetic trials screen a specialist; orchestrator routing has separate offline tests."""
    names = set(case.get("tools", {}))
    if "query_my_crm_records" in names:
        return crm_agent
    if names & {"get_listing_inventory", "get_similar_projects"}:
        return pricing_agent
    return market_agent


def synthetic_tools(case, calls):
    """Replace every registered tool; there is no fallback to its production function."""
    replaced = []
    for name, original in selected_workflow(case)._function_toolset.tools.items():

        def build(name, original):
            async def execute(**arguments):
                try:
                    original.function_schema.validator.validate_python(arguments)
                except ValueError:
                    calls.append({"tool": name, "arguments": arguments, "valid": False})
                    raise ModelRetry("Arguments do not satisfy this tool's schema") from None
                calls.append({"tool": name, "arguments": arguments, "valid": True})
                evidence = case.get("tools", {}).get(name)
                if evidence is None:
                    return {
                        "available": False,
                        "limitation": "No evidence available for this request",
                    }
                if name == "get_listing_inventory" and "by_bedrooms" in evidence:
                    return copy.deepcopy(
                        evidence["by_bedrooms"].get(str(arguments.get("bedrooms")), {"total": 0})
                    )
                if name == "query_my_crm_records":
                    evidence = copy.deepcopy(evidence)
                    if arguments.get("resource") != evidence.get("resource"):
                        return {
                            "available": False,
                            "limitation": "No evidence available for this resource",
                        }
                    records = evidence.get("records", [])
                    for field in ("status", "record_id", "search"):
                        if arguments.get(field) is not None:
                            value = arguments[field]
                            if field == "status":
                                records = [row for row in records if row.get("status") == value]
                            elif field == "record_id":
                                records = [row for row in records if row.get("id") == value]
                            else:
                                records = [
                                    row
                                    for row in records
                                    if str(value).lower() in row.get("contact_name", "").lower()
                                ]
                    evidence["total"] = len(records)
                    evidence["counts_by_status"] = {
                        status: sum(row.get("status") == status for row in records)
                        for status in {row.get("status") for row in records}
                    }
                    evidence["records"] = (
                        []
                        if arguments.get("summary_only")
                        else records[: arguments.get("limit", 20)]
                    )
                    return evidence
                return copy.deepcopy(evidence)

            return execute

        replaced.append(
            Tool.from_schema(
                build(name, original),
                name=name,
                description=original.description,
                json_schema=original.function_schema.json_schema,
            )
        )
    return replaced


def checks(case, calls, answer):
    expected = case.get("expected_tool")
    matching = [call for call in calls if call["tool"] == expected and call["valid"]]
    filters = case.get("expected_arguments", {})
    arguments_ok = bool(matching) and any(
        all(call["arguments"].get(key) == value for key, value in filters.items())
        for call in matching
    )
    prohibited = [
        marker for marker in case.get("forbidden_output", []) if marker.lower() in answer.lower()
    ]
    return {
        "expected_tool": arguments_ok if expected else None,
        "invalid_calls": sum(not call["valid"] for call in calls),
        "forbidden_output": prohibited,
        "semantic_review": "required",
    }


async def run_case(case, model, *, timeout=90):
    calls, run = [], None
    workflow = selected_workflow(case)
    started = time.monotonic()
    record = {"case_id": case["id"], "question": case["question"], "category": case["category"]}
    record["workflow"] = workflow.name
    record["prompt_sha256"] = hashlib.sha256(str(workflow._system_prompts).encode()).hexdigest()
    try:
        async with asyncio.timeout(timeout):
            with workflow.override(
                model=model,
                tools=synthetic_tools(case, calls),
                toolsets=[],
                instructions="Today's date in Asia/Dubai is 2026-10-31. Resolve relative dates from this date.",
            ):
                async with workflow.iter(
                    case["question"],
                    deps=ChatDependencies("synthetic-agent", "synthetic-organization"),
                    usage_limits=UsageLimits(
                        request_limit=5, tool_calls_limit=8, total_tokens_limit=MAX_TOKENS
                    ),
                    model_settings=OpenRouterModelSettings(
                        max_tokens=MAX_OUTPUT,
                        openrouter_reasoning={"effort": "low"},
                        openrouter_provider={"zdr": True, "data_collection": "deny"},
                    ),
                ) as run:
                    async for _ in run:
                        pass
                    record["answer"] = run.result.output
    except Exception as exc:
        # Never retain an exception string or headers. Redact the credential from provider diagnostics.
        record["error_type"] = type(exc).__name__
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            record["http_status"] = status
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            error = body.get("error", body)
            if isinstance(error, dict):
                record["provider_error_code"] = error.get("code")
                message = str(error.get("message", ""))
                if settings.OPENROUTER_API_KEY:
                    message = message.replace(settings.OPENROUTER_API_KEY, "[redacted]")
                record["provider_error_message"] = message[:400]
    record["seconds"] = round(time.monotonic() - started, 3)
    record["calls"] = calls
    record["checks"] = checks(case, calls, record.get("answer", ""))
    if run is not None:
        usage = run.usage()
        record["input_tokens"], record["output_tokens"] = usage.input_tokens, usage.output_tokens
        responses = [m for m in run.all_messages() if isinstance(m, ModelResponse)]
        costs = [(m.provider_details or {}).get("cost") for m in responses]
        record["provider_reported_cost_usd"] = (
            sum(costs) if costs and all(cost is not None for cost in costs) else None
        )
        record["response_models"] = sorted({m.model_name for m in responses if m.model_name})
    return record


def summarise(records):
    result = {}
    for model in dict.fromkeys(row["model"] for row in records):
        rows = [row for row in records if row["model"] == model]
        costs = [row.get("provider_reported_cost_usd") for row in rows]
        result[model] = {
            "cases": len(rows),
            "completed": sum("answer" in row for row in rows),
            "expected_tool_passes": sum(row["checks"]["expected_tool"] is True for row in rows),
            "expected_tool_cases": sum(row["checks"]["expected_tool"] is not None for row in rows),
            "invalid_calls": sum(row["checks"]["invalid_calls"] for row in rows),
            "forbidden_output_cases": sum(bool(row["checks"]["forbidden_output"]) for row in rows),
            "error_types": sorted({row["error_type"] for row in rows if row.get("error_type")}),
            "median_seconds": round(statistics.median(row["seconds"] for row in rows), 3),
            "provider_reported_cost_usd": round(sum(costs), 6)
            if all(cost is not None for cost in costs)
            else None,
            "cost_reporting_complete": all(cost is not None for cost in costs),
            "semantic_review": "required; structural scores do not establish answer quality",
        }
    return result


async def live_trial(args):
    if settings.ENVIRONMENT != "local":
        raise ValueError("Model trials require ENVIRONMENT=local")
    if args.repeat < 1 or args.repeat > 3 or not 0 < args.budget_usd <= 5:
        raise ValueError("Use 1-3 repeats and a budget at most USD 5")
    models = args.model or [
        settings.DEFAULT_CHAT_MODEL,
        "anthropic/claude-haiku-5.5",
        "openai/gpt-6-luna",
        "openai/gpt-6.1-sol",
    ]
    if len(models) != len(set(models)) or len(models) > 4:
        raise ValueError("Choose at most four distinct models")
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.get("https://openrouter.ai/api/v1/models")
        response.raise_for_status()
        catalog = {m["id"]: m for m in response.json()["data"]}
    cases = load_cases()
    if args.case:
        cases = [case for case in cases if case["id"] in args.case]
        if {case["id"] for case in cases} != set(args.case):
            raise ValueError("Unknown case selection")
    for model in models:
        if model not in catalog or "tools" not in catalog[model].get("supported_parameters", []):
            raise ValueError("Candidate must be listed and support tools")
    directory = Path(args.directory)
    if directory.exists():
        raise ValueError("Use a fresh evidence directory")
    private_directory(directory)
    manifest = {
        "synthetic_only": True,
        "scope": "Focused specialist quality; orchestrator acceptance is tested separately offline",
        "workflows": {
            workflow.name: {
                "prompt_sha256": hashlib.sha256(str(workflow._system_prompts).encode()).hexdigest(),
                "tools": sorted(workflow._function_toolset.tools),
            }
            for workflow in (market_agent, pricing_agent, crm_agent)
        },
        "started_at": datetime.now(UTC).isoformat(),
        "models": models,
        "case_ids": [case["id"] for case in cases],
        "repeat": args.repeat,
        "budget_usd": args.budget_usd,
        "prompt_sha256": hashlib.sha256(str(agent._system_prompts).encode()).hexdigest(),
        "fixtures_sha256": hashlib.sha256(FIXTURES.read_bytes()).hexdigest(),
        "benchmark_sha256": load_benchmark().digest,
        "reference_date": "2026-10-31",
        "tools_sha256": hashlib.sha256(
            json.dumps(
                {
                    name: {
                        "description": tool.description,
                        "schema": tool.function_schema.json_schema,
                    }
                    for name, tool in agent._function_toolset.tools.items()
                },
                sort_keys=True,
            ).encode()
        ).hexdigest(),
        "policy": "ZDR, no data collection, all tools replaced, no customer data or actions",
        "prices": {model: catalog[model]["pricing"] for model in models},
    }
    private_write(directory / "manifest.json", manifest)
    records, accounted = [], 0.0
    # Sequential execution bounds spending, keeps failure evidence, and avoids load bias.
    for repeat in range(args.repeat):
        for case in cases:
            for model_id in models:
                price = catalog[model_id]["pricing"]
                reservation = (MAX_TOKENS + MAX_OUTPUT + 16000) * max(
                    float(price["prompt"]), float(price["completion"])
                )
                if accounted + reservation > args.budget_usd:
                    private_write(directory / "summary.json", summarise(records))
                    raise RuntimeError("Budget reserve exhausted; partial evidence retained")
                model = CompatibleOpenRouterModel(
                    model_id, provider=OpenRouterProvider(api_key=settings.OPENROUTER_API_KEY)
                )
                record = await run_case(case, model)
                record.update(model=model_id, repeat=repeat)
                cost = record.get("provider_reported_cost_usd")
                accounted += float(cost) if cost is not None else reservation
                records.append(record)
                private_write(directory / "results.json", records)
                private_write(directory / "summary.json", summarise(records))
                print(
                    json.dumps(
                        {
                            "model": model_id,
                            "case": case["id"],
                            "repeat": repeat,
                            "seconds": record["seconds"],
                            "error": record.get("error_type"),
                            "accounted_usd": round(accounted, 5),
                        }
                    ),
                    flush=True,
                )
                if record.get("http_status") in {401, 402, 403}:
                    raise RuntimeError(
                        "Provider authentication, credits or access blocked the trial; inspect private results.json"
                    )
    print(json.dumps(summarise(records), indent=2))
    if any("answer" not in record for record in records):
        raise RuntimeError("Some model requests failed; this is not a complete comparison")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--model", action="append")
    parser.add_argument("--case", action="append")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--budget-usd", type=float, default=5)
    parser.add_argument(
        "--directory",
        default="../.evaluation/model-trial-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S"),
    )
    args = parser.parse_args()
    if args.live:
        asyncio.run(live_trial(args))
    else:
        print(
            json.dumps(
                {
                    "live": False,
                    "configured_model": settings.DEFAULT_CHAT_MODEL,
                    "cases": [
                        {"id": case["id"], "category": case["category"]} for case in load_cases()
                    ],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
