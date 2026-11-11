"""Exercise application routing and customer drafting with synthetic leaf evidence.

These are real application call graphs, explicitly not HTTP/DB acceptance. Every
registered leaf tool is replaced and customer budget persistence is isolated.
"""

import asyncio
import copy
import hashlib
import json
import time
from contextlib import ExitStack, asynccontextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch

from pydantic_ai import ModelRetry, Tool
from pydantic_ai.usage import RunUsage, UsageLimits

from app.chat import routing, workflows
from app.chat.agent import _convert_to_pydantic_messages
from app.chat.dependencies import ChatDependencies
from app.chat.models import Message
from app.whatsapp import customer_agent
from scripts.evaluation.model_trial import checks, load_cases, synthetic_tools

FLOW_FIXTURES = Path(__file__).with_name("flow_trial_cases.json")
WORKFLOWS = (
    workflows.market_agent,
    workflows.pricing_agent,
    workflows.crm_agent,
    workflows.followup_agent,
    workflows.action_agent,
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


@asynccontextmanager
async def synthetic_channel_budget(**kwargs):
    # Production usage persistence is not exercised by this synthetic call-graph run.
    yield RunUsage()


async def run_flow_case(case, model, *, timeout=180):
    # Mutation is deliberate within a multi-turn case, never shared across candidates.
    case = copy.deepcopy(case)
    started = time.monotonic()
    calls, turns, history = [], [], []

    async def retrieve_evidence(request):
        from app.whatsapp.customer_evidence import CustomerEvidence

        arguments = request.model_dump(mode="json")
        valid = all(
            arguments.get(key) == value for key, value in case.get("expected_retrieval", {}).items()
        )
        calls.append({"tool": "customer_retrieval", "arguments": arguments, "valid": valid})
        allowed = case.get("retrieval_enabled", True)
        calls[-1]["allowed"] = allowed
        if not valid or not allowed:
            return []
        return [
            CustomerEvidence.model_validate(value) for value in case.get("retrieved_evidence", [])
        ]

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
                if case["flow"] == "customer":
                    stack.enter_context(
                        patch.object(customer_agent.settings, "ASSISTANT_ENABLED", True)
                    )
                    for current in (customer_agent.classifier(), customer_agent.drafter()):
                        stack.enter_context(current.override(model=model, tools=[], toolsets=[]))
                    stack.enter_context(
                        patch.object(
                            customer_agent.operations, "channel_budget", synthetic_channel_budget
                        )
                    )
                else:
                    for current in WORKFLOWS:
                        stack.enter_context(
                            current.override(
                                model=model, tools=leaf_tools(case, calls, current), toolsets=[]
                            )
                        )
                    for current in (routing.router_agent, routing.coordinator_agent):
                        stack.enter_context(current.override(model=model, tools=[], toolsets=[]))
                    stack.enter_context(
                        patch.object(routing, "business_today", lambda: date(2026, 10, 31))
                    )
                for index, question in enumerate(case.get("turns", [case["question"]])):
                    call_start = len(calls)
                    if case["flow"] == "customer":
                        draft = await customer_agent.build_customer_draft(
                            message=question,
                            knowledge=case.get("knowledge", []),
                            history=history,
                            user_id="synthetic-agent",
                            organization_id="synthetic-organization",
                            conversation_id=1,
                            retrieve_evidence=retrieve_evidence
                            if "retrieved_evidence" in case
                            else None,
                        )
                        answer = draft.reply if draft else ""
                        detail = {"draft": draft.model_dump(mode="json") if draft else None}
                        if draft:
                            history.extend(
                                [
                                    {"role": "user", "content": question},
                                    {"role": "assistant", "content": answer},
                                ]
                            )
                    else:
                        deps = ChatDependencies("synthetic-agent", "synthetic-organization", 1)
                        routed = await routing.run_routed_turn(
                            question,
                            deps=deps,
                            usage=RunUsage(),
                            message_history=_convert_to_pydantic_messages(history),
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
                                        "guardrail_version": 1,
                                        "private": any(
                                            call["tool"] == "query_my_crm_records"
                                            for call in calls[call_start:]
                                        ),
                                        "_retrieval_context": case.get("authorized_handles", []),
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
    record["checks"]["observed_routes"] = (
        [turn.get("decision", {}).get("workflows") for turn in turns]
        if case["flow"] != "customer"
        else None
    )
    record["fixture_sha256"] = hashlib.sha256(FLOW_FIXTURES.read_bytes()).hexdigest()
    return record
