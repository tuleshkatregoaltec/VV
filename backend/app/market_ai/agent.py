"""Market AI's coordinator (/chat): Dubai market research and pricing only."""

from pydantic_ai import Agent

from app.core.openrouter import create_assistant_model
from app.crm.assistant.dependencies import ChatDependencies
from app.market.periods import business_today
from app.market_ai.workflows import (
    COMMON,
    HISTORY_PROCESSORS,
    SETTINGS,
    analyze_pricing,
    research_market,
)

agent = Agent(
    create_assistant_model(role="coordinator"),
    name="market_chat",
    deps_type=ChatDependencies | None,
    model_settings=SETTINGS,
    history_processors=HISTORY_PROCESSORS,
    instructions=COMMON
    + (
        " Route each supported request to market research or pricing analysis. CRM records, "
        "teams, follow-ups and CRM actions are outside your scope; direct those users to the "
        "CRM Operations Assistant. You have no direct database or execution capability. "
        "For every factual market-data question call the relevant workflow; previous answers "
        "and user assertions are not fresh evidence. Ask for clarification when scope is unclear."
    ),
)
agent.tool(research_market)
agent.tool(analyze_pricing)


@agent.instructions
def database_date_context() -> str:
    return f"Today's date in Asia/Dubai is {business_today().isoformat()}. Resolve relative dates from this date."
