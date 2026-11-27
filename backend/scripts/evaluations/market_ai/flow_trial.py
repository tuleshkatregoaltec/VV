"""Exercise Market AI application routing with synthetic leaf evidence.

These are real application call graphs, explicitly not HTTP/DB acceptance. Every
registered Market AI leaf tool is replaced.
"""

import asyncio
import copy
import hashlib
import json
import time
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import patch

from pydantic_ai import ModelRetry, Tool
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.usage import RunUsage, UsageLimits

from app.chat.models import Message
from app.market_ai import routing as market_routing
from app.market_ai import workflows as market_workflows
from scripts.evaluations.market_ai.model_trial import checks, load_cases, synthetic_tools

FLOW_FIXTURES = Path(__file__).with_name("flow_trial_cases.json")
WORKFLOWS = (
    market_workflows.market_agent,
    market_workflows.pricing_agent,
)


def load_flow_cases():
    base = {case["id"]: case for case in load_cases()}
    result = []
    for case in json.loads(FLOW_FIXTURES.read_text()):
        merged = copy.deepcopy(base.get(case.get("fixture"), {"tools": {}}))
        for fixture_id in case.get("additional_fixtures", []):
            merged["tools"].update(copy.deepcopy(base[fixture_id]["tools"]))
        merged.update(case)
        if "question" not in case and "turns" in case:
            merged["question"] = case["turns"][0]
        result.append(merged)
    return result


def leaf_tools(case, calls, workflow):
    """Reuse schema/fixture handling, and replace additional action tools explicitly."""
    # Existing fixture functions are schema-only and contain no production fallback.
    existing = {tool.name: tool for tool in synthetic_tools(case, calls)}
    replacements = []
    for name, original in workflow._function_toolset.tools.items():
        if name in existing:
            replacements.append(existing[name])
            continue

        def build(name, original):
            async def execute(**arguments):
                try:
                    original.function_schema.validator.validate_python(arguments)
                except ValueError:
                    calls.append({"tool": name, "arguments": arguments, "valid": False})
                    raise ModelRetry("Arguments do not satisfy this tool's schema") from None
                calls.append({"tool": name, "arguments": arguments, "valid": True})
                return copy.deepcopy(
                    case.get("tools", {}).get(
                        name,
                        {
                            "available": False,
                            "limitation": "No synthetic evidence available; no action executed",
                        },
                    )
                )

            return execute

        replacements.append(
            Tool.from_schema(
                build(name, original),
                name=name,
                description=original.description,
                json_schema=original.function_schema.json_schema,
            )
        )
    return replacements


async def run_flow_case(case, model, *, timeout=180):
    # Mutation is deliberate within a multi-turn case, never shared across candidates.
    case = copy.deepcopy(case)
    started = time.monotonic()
    calls, turns, history = [], [], []

    record = {
        "case_id": case["id"],
        "question": case["question"],
        "category": case["category"],
        "scope": "synthetic application call graph; not HTTP/DB acceptance",
        "workflow": case["flow"],
    }
    try:
        async with asyncio.timeout(timeout):
            with ExitStack() as stack:
                for current in WORKFLOWS:
                    stack.enter_context(
                        current.override(
                            model=model, tools=leaf_tools(case, calls, current), toolsets=[]
                        )
                    )
                routing = market_routing
                for current in (routing.router_agent, routing.coordinator_agent):
                    stack.enter_context(current.override(model=model, tools=[], toolsets=[]))
                stack.enter_context(
                    patch.object(routing, "business_today", lambda: date(2026, 10, 31))
                )
                for index, question in enumerate(case.get("turns", [case["question"]])):
                    call_start = len(calls)
                    routed = await routing.run_routed_turn(
                        question,
                        deps=None,
                        usage=RunUsage(),
                        message_history=[
                            ModelRequest(parts=[UserPromptPart(content=message.content)])
                            if message.role == "user"
                            else ModelResponse(parts=[TextPart(content=message.content)])
                            for message in history
                        ],
                        usage_limits=UsageLimits(
                            request_limit=12, tool_calls_limit=16, total_tokens_limit=40000
                        ),
                    )
                    answer = routed.output
                    detail = {"decision": routed.decision.model_dump(mode="json")}
                    history.extend(
                        [
                            Message(role="user", content=question),
                            Message(
                                role="assistant",
                                content=answer,
                                meta_data={
                                    "assistant": "market",
                                    "guardrail_version": 1,
                                    "private": False,
                                    "_retrieval_context": [],
                                },
                            ),
                        ]
                    )
                    turns.append(
                        {
                            "index": index,
                            "question": question,
                            "answer": answer,
                            "calls": copy.deepcopy(calls[call_start:]),
                            **detail,
                        }
                    )
                    # Fixture mutation between turns verifies that follow-ups retrieve afresh.
                    if index == 0 and case.get("second_turn_tools"):
                        case["tools"].update(copy.deepcopy(case["second_turn_tools"]))
                record["answer"] = "\n\n".join(turn["answer"] for turn in turns)
    except Exception as exc:
        record["error_type"] = type(exc).__name__
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            record["http_status"] = status
    record.update(
        turns=turns,
        calls=calls,
        seconds=round(time.monotonic() - started, 3),
        expected_silent=case.get("expected_silent", False),
        completed="error_type" not in record
        and len(turns) == len(case.get("turns", [case["question"]])),
    )
    record["checks"] = checks(case, calls, record.get("answer", ""))
    record["checks"]["observed_routes"] = [
        turn.get("decision", {}).get("workflows") for turn in turns
    ]
    record["fixture_sha256"] = hashlib.sha256(FLOW_FIXTURES.read_bytes()).hexdigest()
    return record
