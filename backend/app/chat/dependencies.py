from dataclasses import dataclass, field
from typing import Any


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

    def __post_init__(self):
        if not self.user_id or not self.organization_id:
            raise ValueError("Chat requires a user and organization")
