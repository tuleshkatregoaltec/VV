"""Guard clauses added after live filter, inventory and report failures, not a model-quality score.

These contracts fail if a future edit removes the instructions required by those
observed failures. Whether a provider obeys them requires a separate live evaluation.
"""

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, SystemPromptPart, TextPart
from pydantic_ai.models.function import FunctionModel

from app.chat.prompts import CHAT_PROMPT_VERSION, CHAT_SYSTEM_PROMPT


def test_binding_covers_all_explicit_constraints_and_keeps_cohorts_paired():
    assert "Before any retrieval, successfully call bind_market_scope once" in CHAT_SYSTEM_PROMPT
    assert (
        "location, building/project, bedrooms, property_type, sale/rent mode, price bounds"
        in CHAT_SYSTEM_PROMPT
    )
    assert "Copy EVERY explicit filter into EVERY applicable tool call" in CHAT_SYSTEM_PROMPT
    assert "never mix values from different cohorts" in CHAT_SYSTEM_PROMPT
    assert "outer scope_id on retrieval calls" in CHAT_SYSTEM_PROMPT
    assert "Do not infer a property type, location" in CHAT_SYSTEM_PROMPT


def test_validation_repair_never_guesses_or_changes_bound_population():
    assert "Read error.details field paths and repair only the" in CHAT_SYSTEM_PROMPT
    assert "A missing period.months requires the user's explicit month count" in CHAT_SYSTEM_PROMPT
    assert "never guess a value or broaden the period" in CHAT_SYSTEM_PROMPT
    assert "conflicting values, including null clearing" in CHAT_SYSTEM_PROMPT
    assert "never become bounds on registered rents" in CHAT_SYSTEM_PROMPT
    assert "above/below are false, at least/at most" in CHAT_SYSTEM_PROMPT
    assert "price_band_upper_inclusive=[false,true]" in CHAT_SYSTEM_PROMPT


def test_unavailable_or_error_cannot_be_rewritten_as_zero_from_release_metadata():
    assert "An error or unavailable result\nis NOT a zero count" in CHAT_SYSTEM_PROMPT
    assert "unless a successful scoped result explicitly returned that count" in CHAT_SYSTEM_PROMPT
    assert "Release-observation row counts are metadata" in CHAT_SYSTEM_PROMPT
    assert (
        "a failed retrieval, unavailable evidence and a verified empty sample" in CHAT_SYSTEM_PROMPT
    )


async def test_provider_receives_required_composer_and_unpinned_report_rules():
    received = []

    def inspect(messages, _info):
        received.extend(
            part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, SystemPromptPart)
        )
        return ModelResponse(parts=[TextPart("Scripted transport check only")])

    agent = Agent(FunctionModel(inspect), system_prompt=CHAT_SYSTEM_PROMPT)
    await agent.run("Create a multi-source client report")
    prompt = "\n".join(received)
    assert CHAT_PROMPT_VERSION == "database-mcp-v6"
    assert "MUST call compose_market_report" in prompt
    assert (
        "Do not bypass\nit by assembling separate metrics, inventory and delivery calls" in prompt
    )
    assert "report cannot be completed" in prompt
    assert (
        "Do not present composite conclusions from unpinned sources, even with a disclaimer"
        in prompt
    )


def test_delivery_scope_and_listing_source_are_explicit():
    assert "delivery_statuses=['scheduled_in_horizon']" in CHAT_SYSTEM_PROMPT
    assert "Project status ACTIVE alone does not mean scheduled" in CHAT_SYSTEM_PROMPT
    assert "For missing/overdue date audits, explicitly select those" in CHAT_SYSTEM_PROMPT
    assert (
        "For current listing counts or asking prices, call get_listing_inventory directly"
        in CHAT_SYSTEM_PROMPT
    )
    assert "Do not call query_market_metrics for listing inventory" in CHAT_SYSTEM_PROMPT
    assert "or fallback for a listing-only question" in CHAT_SYSTEM_PROMPT


def test_listing_yield_scope_binds_comparable_period_without_switching_evidence_kind():
    assert "Include period on every cohort" in CHAT_SYSTEM_PROMPT
    assert "or null only when no applicable period was requested" in CHAT_SYSTEM_PROMPT
    assert "evidence_kind='listings' and mode='sale'" in CHAT_SYSTEM_PROMPT
    assert (
        "Bind any explicit comparable-rent period in that SAME listing cohort" in CHAT_SYSTEM_PROMPT
    )
    assert "only a successful binding freezes scope" in CHAT_SYSTEM_PROMPT


def test_inventory_zero_and_yield_unavailability_retain_the_actual_scoped_evidence():
    assert "data.inventory.total is the scoped" in CHAT_SYSTEM_PROMPT
    assert "report 0 as zero matching listings, not as an unavailable count" in CHAT_SYSTEM_PROMPT
    assert (
        "Never substitute evidence.release.observations row counts for inventory.total"
        in CHAT_SYSTEM_PROMPT
    )
    assert "Explain unavailable yields using the actual returned reason" in CHAT_SYSTEM_PROMPT
    assert (
        "Claim insufficient sample size only when scoped evidence establishes" in CHAT_SYSTEM_PROMPT
    )
    assert "Five or more contracts" in CHAT_SYSTEM_PROMPT


def test_explicit_yield_reason_codes_override_generic_sample_requirement_warnings():
    assert (
        "yield_unavailable_reason and unavailability_reasons codes over generic limitations"
        in CHAT_SYSTEM_PROMPT
    )
    assert "A generic minimum-sample warning does not prove" in CHAT_SYSTEM_PROMPT
    assert (
        "insufficient_comparables and must never be restated as an observed sample failure"
        in CHAT_SYSTEM_PROMPT
    )
