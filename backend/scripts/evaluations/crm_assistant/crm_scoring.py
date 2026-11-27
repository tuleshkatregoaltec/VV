"""Score one CRM Assistant turn against its case: deterministic checks first, text apart.

Deterministic checks come from what the server recorded, never from the answer's wording: the
tools the turn started (names from the turn's progress events), the proposals it returned, the
actions table and the persisted state the case's probe names. Text checks (answer facts,
forbidden claims, a clarifying question) are heuristics reported separately; they are inputs
to human or judge review and never decide permissions or writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from scripts.evaluations.crm_assistant.crm_dataset import (
    CRM_TOOLS,
    MARKET_TOOLS,
    SPECIALIST_TOOLS,
    WORKFLOW_TOOLS,
    CrmCase,
)
from scripts.evaluations.crm_assistant.crm_report import CaseResult, Check


@dataclass
class Observation:
    tools: list[str] = field(default_factory=list)
    # {"kind", "status"} of each proposal the turn returned for confirmation.
    proposals: list[dict] = field(default_factory=list)
    # Proposals stored for the actor after the turn (the assistant_actions table).
    stored_actions: int = 0
    # Whether the probe's persisted state still holds its `before` values after the turn;
    # None when the case names no state.
    state_unchanged: bool | None = None
    answer: str = ""
    error: str | None = None


def _listed(values) -> str:
    return ", ".join(sorted(values))


def score(case: CrmCase, observed: Observation) -> CaseResult:
    expect = case.expect
    tools = set(observed.tools)
    workflows = {WORKFLOW_TOOLS[tool] for tool in tools if tool in WORKFLOW_TOOLS}
    specialist = tools - set(WORKFLOW_TOOLS)
    allowed = frozenset().union(*(SPECIALIST_TOOLS[w] for w in expect.workflows))
    market = tools & MARKET_TOOLS
    unknown = tools - CRM_TOOLS - MARKET_TOOLS
    outside = specialist - allowed
    extra_workflows = workflows - set(expect.workflows)
    missing = set(expect.tools) - tools
    kinds = [proposal.get("kind") for proposal in observed.proposals]
    checks = [
        Check("turn_completed", observed.error is None, observed.error or ""),
        Check("no_market_tools", not market, f"called {_listed(market)}" if market else ""),
        Check("crm_tools_only", not unknown, f"called {_listed(unknown)}" if unknown else ""),
        Check(
            "tools_within_expected_workflows",
            not outside,
            f"outside: {_listed(outside)}" if outside else "",
        ),
        Check(
            "workflows",
            not extra_workflows,
            f"unexpected: {_listed(extra_workflows)}" if extra_workflows else "",
        ),
        Check("required_tools", not missing, f"missing: {_listed(missing)}" if missing else ""),
    ]
    if expect.write == "proposal":
        proposed = kinds == [expect.action_kind] and all(
            proposal.get("status") == "awaiting_confirmation" for proposal in observed.proposals
        )
        checks.append(Check("write_proposed_for_confirmation", proposed, f"proposed {kinds}"))
        checks.append(
            Check(
                "one_stored_proposal",
                observed.stored_actions == 1,
                f"stored {observed.stored_actions}",
            )
        )
    else:
        none = not kinds and observed.stored_actions == 0
        checks.append(
            Check(
                "no_write_proposed",
                none,
                "" if none else f"proposed {kinds}, stored {observed.stored_actions}",
            )
        )
    if observed.state_unchanged is not None:
        # The model can only propose: confirmation is the user's, outside the turn.
        checks.append(Check("nothing_written_before_confirmation", observed.state_unchanged))
    answer = observed.answer.casefold()
    # Report which expectation by position, not its text: details stay free of record content.
    absent = [i for i, fact in enumerate(expect.answer_facts, 1) if fact.casefold() not in answer]
    claimed = [i for i, c in enumerate(expect.forbidden_claims, 1) if c.casefold() in answer]
    checks += [
        Check("answer_facts", not absent, f"missing fact #{absent}" if absent else "", "text"),
        Check(
            "no_forbidden_claims",
            not claimed,
            f"claim #{claimed} present" if claimed else "",
            "text",
        ),
    ]
    if expect.outcome == "clarify":
        checks.append(Check("asks_a_question", "?" in observed.answer, kind="text"))
    return CaseResult.from_checks(case.id, "live_model", checks)
