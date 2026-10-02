"""Guard clauses added after live q11/q14 failures, not a model-quality score.

These contracts fail if a future edit removes the instructions required by those
observed failures. Whether a provider obeys them requires a separate live evaluation.
"""

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, SystemPromptPart, TextPart
from pydantic_ai.models.function import FunctionModel

from app.chat.prompts import CHAT_PROMPT_VERSION, CHAT_SYSTEM_PROMPT


def test_retry_scope_keeps_price_bounds_and_inventory_evidence_type():
    assert "Copy EVERY explicit filter into EVERY applicable tool call" in CHAT_SYSTEM_PROMPT
    assert (
        "price_max into both get_listing_inventory and compare_listing_rents" in CHAT_SYSTEM_PROMPT
    )
    assert "never permits dropping a price bound" in CHAT_SYSTEM_PROMPT
    assert "substituting registered sales for listing inventory" in CHAT_SYSTEM_PROMPT
    assert "State inclusive/exclusive price-band boundaries" in CHAT_SYSTEM_PROMPT
    assert "requested strict boundary is unsupported, disclose the mismatch" in CHAT_SYSTEM_PROMPT


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
    assert CHAT_PROMPT_VERSION == "database-mcp-v2"
    assert "MUST call compose_market_report" in prompt
    assert (
        "Do not bypass\nit by assembling separate metrics, inventory and delivery calls" in prompt
    )
    assert "report cannot be completed" in prompt
    assert (
        "Do not present composite conclusions from unpinned sources, even with a disclaimer"
        in prompt
    )
