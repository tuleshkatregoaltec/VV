"""Comparable execution context fingerprints; no provider calls or raw evidence export."""

import hashlib
import importlib.metadata
import json
from pathlib import Path


def execution_context():
    from app.chat import routing, workflows
    from app.chat.agent import agent as orchestrator
    from app.chat.capabilities import CAPABILITY_CONTEXT_VERSION
    from app.whatsapp import customer_agent

    agents = (
        orchestrator,
        routing.router_agent,
        routing.coordinator_agent,
        workflows.market_agent,
        workflows.pricing_agent,
        workflows.crm_agent,
        workflows.followup_agent,
        workflows.action_agent,
        customer_agent.classifier(),
        customer_agent.drafter(),
    )
    value = {
        "capability_context_version": CAPABILITY_CONTEXT_VERSION,
        "pydantic_ai_version": importlib.metadata.version("pydantic-ai"),
        "source_sha256": {
            name: hashlib.sha256(
                (Path(__file__).resolve().parents[2] / name).read_bytes()
            ).hexdigest()
            for name in (
                "app/chat/agent.py",
                "app/chat/routing.py",
                "app/chat/workflows.py",
                "app/chat/capabilities.py",
                "app/chat/security.py",
                "app/chat/crm_tools.py",
                "app/chat/tools.py",
                "app/whatsapp/customer_agent.py",
                "app/whatsapp/customer_policy.py",
                "app/whatsapp/customer_evidence.py",
                "app/whatsapp/customer_access.py",
            )
        },
        "harness_sha256": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in (
                "model_trial.py",
                "campaign.py",
                "trial_budget.py",
                "flow_trial.py",
                "http_trial.py",
                "run.py",
                "server.py",
                "trial_context.py",
                "fixture_snapshot.py",
            )
        },
        "execution_settings": {
            "reference_date": "2026-10-31",
            "specialist_max_output": 1800,
            "specialist_request_limit": 5,
            "specialist_total_tokens_limit": 24000,
            "specialist_reasoning": {"effort": "low"},
            "global_max_output": 3000,
            "flow_request_limit": 12,
            "flow_total_tokens_limit": 40000,
        },
        "agents": {
            agent.name: {
                "model_settings": agent.model_settings,
                "prompt_sha256": hashlib.sha256(str(agent._system_prompts).encode()).hexdigest(),
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
            }
            for agent in agents
        },
    }
    value["sha256"] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    return value


def historical_compatibility(current, historical):
    def read_manifest(directory):
        directory = Path(directory)
        if (directory / "manifest.json").exists():
            return json.loads((directory / "manifest.json").read_text()), "manifest.json"
        if (directory / "run.json").exists():
            value = json.loads((directory / "run.json").read_text())
            if (directory / "runtime.json").exists():
                value["legacy_runtime"] = json.loads((directory / "runtime.json").read_text())
            return value, "run.json"
        raise ValueError("Historical evidence needs manifest.json or run.json")

    current, current_format = read_manifest(current)
    historical, historical_format = read_manifest(historical)
    fields = (
        "fixtures_sha256",
        "reference_date",
        "execution_context",
        "scope",
        "case_ids",
        "repeat",
    )
    differences = [
        field
        for field in fields
        if field not in current or field not in historical or current[field] != historical[field]
    ]
    return {
        "comparable": not differences,
        "differences": differences,
        "current_format": current_format,
        "historical_format": historical_format,
        "historical_configured_model": historical.get("legacy_runtime", {}).get("configured_model"),
        "policy": "Historical artifacts only; no provider rerun. Missing context never implies comparability.",
    }
