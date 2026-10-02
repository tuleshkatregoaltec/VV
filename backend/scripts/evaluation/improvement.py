"""Offline behavioral preparation and strict promotion gate; never starts training."""

import json
import re
from pathlib import Path

from scripts.evaluation.dataset import load_benchmark
from scripts.evaluation.evaluate import compare
from scripts.evaluation.tracing import fingerprint, private_directory, private_write

EXAMPLES = Path(__file__).with_name("behavioral_examples.json")
QUALITY_DIMENSIONS = {
    "numerical_correctness",
    "filters",
    "tool_arguments",
    "completeness",
    "clarification",
    "freshness",
    "privacy",
    "grounding",
}
PROVIDER_SUPPORT = {
    "checked_on": "2026-10-03",
    "runtime_provider": "openrouter",
    "runtime_model": "google/gemini-3.1-flash-lite",
    "canonical_model": "google/gemini-3.1-flash-lite-20260507",
    "tool_use_supported": True,
    "runtime_training_endpoint_verified": False,
    "training_authorized": False,
    "evaluation_budget_usd": 5,
    "sources": [
        "https://openrouter.ai/api/v1/models",
        "https://openrouter.ai/docs/guides/features/tool-calling",
        "https://ai.google.dev/gemini-api/docs/model-tuning",
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-flash-lite",
        "https://cloud.google.com/vertex-ai/generative-ai/docs/models/tune-function-calling",
    ],
    "blocker": "No training authorized. No verified training or tuned-endpoint serving path in the deployed OpenRouter adapter. Google Cloud supports tuning for this model family, but requires a separate approved provider integration, credentials and budget.",
}


def load_examples(path=EXAMPLES):
    payload = json.loads(Path(path).read_text())
    if (
        payload.get("origin")
        != "manually authored synthetic behavior; no private records or market-price targets"
    ):
        raise ValueError(
            "Only the curated synthetic corpus is accepted; raw traces require separate privacy review"
        )
    questions = {case.question for case in load_benchmark().cases}
    seen_ids, seen_questions, families = set(), set(), {}
    for split in ("train", "heldout"):
        for example in payload[split]:
            text = json.dumps(example)
            if (
                example["id"] in seen_ids
                or example["user"] in seen_questions
                or example["user"] in questions
            ):
                raise ValueError(
                    "Training, heldout and canonical benchmark inputs must remain distinct"
                )
            if example["family"] in families and families[example["family"]] != split:
                raise ValueError("Behavior families must not cross training/heldout splits")
            if re.search(
                r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|Bearer\s|\beyJ\w+\.|sk-[A-Za-z0-9]|https?://)",
                text,
            ):
                raise ValueError("Potential private identifier or credential in training example")
            if set(example) - {"id", "family", "user", "tool", "arguments", "answer"}:
                raise ValueError("Unexpected training data field")
            if bool(example.get("answer")) == bool(example.get("tool")):
                raise ValueError("Expected one answer or tool-selection target")
            seen_ids.add(example["id"])
            seen_questions.add(example["user"])
            families[example["family"]] = split
    return payload


def prepare(directory: Path):
    from jsonschema import Draft202012Validator

    from app.chat import mcp
    from app.chat.prompts import CHAT_PROMPT_VERSION, CHAT_SYSTEM_PROMPT

    definitions = mcp.tool_definitions()
    schemas = {tool.name: tool.inputSchema for tool in definitions}
    examples = load_examples()
    if directory.exists():
        raise ValueError("Use a new preparation directory")
    private_directory(directory)
    hashes = {}
    for split in ("train", "heldout"):
        records = []
        for example in examples[split]:
            messages = [
                {"role": "system", "content": CHAT_SYSTEM_PROMPT},
                {"role": "user", "content": example["user"]},
            ]
            if example.get("tool"):
                Draft202012Validator(schemas[example["tool"]]).validate(example["arguments"])
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "synthetic-call",
                                "type": "function",
                                "function": {
                                    "name": example["tool"],
                                    "arguments": json.dumps(example["arguments"], sort_keys=True),
                                },
                            }
                        ],
                    }
                )
            else:
                messages.append({"role": "assistant", "content": example["answer"]})
            records.append({"id": example["id"], "family": example["family"], "messages": messages})
        hashes[split] = fingerprint(records)
        private_write(directory / f"{split}.json", records)
    manifest = {
        "format": "behavioral-staging-v1; not a provider upload format",
        "prompt_version": CHAT_PROMPT_VERSION,
        "prompt_sha256": fingerprint(CHAT_SYSTEM_PROMPT),
        "tool_schema_sha256": fingerprint(schemas),
        "corpus_sha256": fingerprint(examples),
        "split_sha256": hashes,
        "support": PROVIDER_SUPPORT,
        "training_started": False,
        "promoted": False,
    }
    private_write(directory / "manifest.json", manifest)
    return manifest


def promotion_gate(baseline, candidate):
    comparison = compare(baseline, candidate)
    blockers = list(comparison["mismatches"])
    if comparison["regressions"]:
        blockers.append("quality_regression")
    if comparison["changes"] and any(
        item.get("change") == "assessment_method_changed" for item in comparison["changes"]
    ):
        blockers.append("assessment_method_changed")
    # Full explicit quality coverage is required; an absent/unsupported dimension
    # cannot be silently dropped from the denominator to improve a score.
    for case in candidate["cases"]:
        for dimension in QUALITY_DIMENSIONS:
            finding = case["checks"].get(dimension, {})
            if finding.get("status") != "pass":
                blockers.append(f"{case['case_id']}.{dimension}:not_pass")
    improvements = [
        item
        for item in comparison["changes"]
        if item.get("dimension") in QUALITY_DIMENSIONS
        and item.get("before") == "fail"
        and item.get("after") == "pass"
    ]
    if not improvements:
        blockers.append("no_measured_improvement")
    return {
        "promote": not blockers,
        "blockers": blockers,
        "improvements": improvements,
        "configuration_changed": False,
        "rollback": baseline.get("runtime", {}),
    }
