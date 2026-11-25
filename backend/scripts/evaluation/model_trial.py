"""Compare live models with the production prompt and synthetic-only tool implementations.

No application server, database, customer record, or real action is used. The canonical
HTTP/database benchmark remains a separate acceptance test. Run without --live to preview.
"""

import asyncio
import copy
import hashlib
import json
import re
import statistics
import time
from pathlib import Path

from pydantic_ai import ModelRetry, Tool
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.openrouter import OpenRouterModelSettings
from pydantic_ai.usage import UsageLimits

from app.config import settings
from app.crm.assistant.dependencies import ChatDependencies
from app.market_ai.workflows import crm_agent, market_agent, pricing_agent
from scripts.evaluation.dataset import load_benchmark

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
        all(
            call["arguments"].get("request", call["arguments"]).get(key) == value
            for key, value in filters.items()
        )
        for call in matching
    )
    prohibited = [
        marker
        for marker in case.get("forbidden_output", [])
        if (
            bool(re.search(r"base64,\s*[A-Za-z0-9+/=]{8,}", answer, re.IGNORECASE))
            if marker.lower() == "base64,"
            else marker.lower() in answer.lower()
        )
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
    from scripts.evaluation.campaign import live_trial as run_campaign

    return await run_campaign(args)


def main():
    from scripts.evaluation.campaign import main as campaign_main

    campaign_main()


if __name__ == "__main__":
    main()
