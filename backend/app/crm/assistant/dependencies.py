from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.usage import UsageLimits


@dataclass(frozen=True)
class ChatDependencies:
    """Trusted identity plus evidence and proposals local to one authenticated turn."""

    user_id: str
    organization_id: str
    conversation_id: int | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list, compare=False)
    proposals: list[dict[str, Any]] = field(default_factory=list, compare=False)
    retrieval_budget: dict[str, int] = field(
        default_factory=lambda: {"crm_detail_rows": 10}, compare=False
    )
    # CRM reads already made this turn, by exact query: an identical repeat reuses the result.
    crm_reads: dict[str, Any] = field(default_factory=dict, compare=False)
    # The request the previous answer left waiting for the user's reply (rechecked when the
    # history loaded), then whatever this turn holds instead: kind, lead_id and typed details.
    pending: dict[str, Any] = field(default_factory=dict, compare=False)
    # The admitted turn's cumulative limits, shared by nested workflow runs.
    usage_limits: UsageLimits | None = field(default=None, compare=False)
    # Receives tool progress events (names only, never arguments or model text).
    progress: Callable[[dict[str, Any]], None] | None = field(default=None, compare=False)

    def __post_init__(self):
        if not self.user_id or not self.organization_id:
            raise ValueError("Chat requires a user and organization")
