"""Fail-closed customer topic/risk rules; no identity, persistence or model access."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.chat.operations import channel_input, channel_output_allowed
from app.whatsapp.customer_evidence import CustomerEvidence, CustomerRetrieval
from app.whatsapp.customer_screen import _INJECTION

Risk = Literal["routine", "approval"]
QualificationDetail = Literal["transaction", "budget", "timeframe"]
QUALIFICATION_QUESTIONS: dict[QualificationDetail, str] = {
    "transaction": "Are you looking to buy or rent?",
    "budget": "What budget do you have in mind, and in which currency?",
    "timeframe": "When are you looking to move?",
}
_SHORT_ANSWERS: dict[QualificationDetail, re.Pattern] = {
    "transaction": re.compile(r"(?i)(?:to )?(?:buy|purchase|rent)(?: please)?[.!]?"),
    "budget": re.compile(
        r"(?i)(?:(?:AED|USD|GBP|EUR|DHS|د.إ)\s*)?"
        r"\d[\d,]*(?:\.\d+)?\s*(?:k|m|million|thousand)?"
        r"(?:\s*(?:AED|USD|GBP|EUR|DHS|د.إ))?"
        r"(?:\s*(?:per year|per month|annually|monthly|yearly))?[.!]?"
    ),
    "timeframe": re.compile(
        r"(?i)(?:next (?:week|month|year)|this (?:week|month|year)|"
        r"immediately|asap|in \d+ (?:days?|weeks?|months?)|"
        r"(?:january|february|march|april|may|june|july|august|september|october|"
        r"november|december)(?: \d{4})?)[.!]?"
    ),
}


def short_answer_detail(text: str) -> QualificationDetail | None:
    return next(
        (detail for detail, pattern in _SHORT_ANSWERS.items() if pattern.fullmatch(text.strip())),
        None,
    )


class ApprovedFact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    text: str = Field(min_length=1, max_length=3500)


class TopicDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    topic: Literal["property", "personal", "mixed", "uncertain"]
    risk: Risk
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    reason: str = Field(min_length=1, max_length=500)
    next_question: QualificationDetail | None = None
    retrieval: CustomerRetrieval | None = None
    asks_if_automated: bool = False


class CustomerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    # None only for a silent handoff: the customer asked if this is a bot, so we say nothing.
    reply: str | None = Field(default=None, min_length=1, max_length=3500)
    risk: Risk
    evidence_ids: list[str] = Field(max_length=20)
    auto_eligible: bool
    silent: bool = False
    # False when the message is not an admitted property enquiry: the receipt then keeps no
    # text, only the pause and a content-free notification (identity questions).
    store_content: bool = True
    summary: str | None = Field(default=None, max_length=400)
    reason: str | None = Field(default=None, max_length=64)
    # Content-free diagnostic for a message that could not be processed.
    error_code: str | None = Field(default=None, max_length=64)
    asked: QualificationDetail | None = None
    evidence_snapshots: list[CustomerEvidence] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def approval_cannot_be_automatic(self):
        if self.risk == "approval" and self.auto_eligible:
            raise ValueError("Sensitive drafts require explicit approval")
        if (self.reply is None) != self.silent:
            raise ValueError("Only a silent handoff may have no reply")
        if self.silent and (self.risk != "approval" or self.auto_eligible):
            raise ValueError("A silent handoff always goes to the agent")
        return self


_PERSONAL = re.compile(
    r"(?i)\b(?:happy birthday|birthday party|dinner plans?|let.s have dinner|how (?:is|are) your "
    r"(?:family|wife|husband|kids)|love you|miss you|football|cricket|video games?|recipe|horoscope|"
    r"let.s (?:get|have) lunch|dinner tonight|how are you)\b"
    r"|عيد ميلاد|أحبك|احبك|كرة القدم"
)
_HUMAN = re.compile(
    r"(?i)\b(?:(?:speak|talk) (?:to|with) (?:a |the |your )?\w+|"
    r"(?:human|real person|actual person|agent|broker) (?:please|instead)|"
    r"(?:want|need) (?:a |the |your )?(?:human|person|agent|broker))\b"
)
_SENSITIVE = re.compile(
    r"(?i)\b(?:negotiat\w*|discount\w*|counter[- ]?offer|best price|lowest price|offer\w*|"
    r"accept\w*|agree\w*|guarantee\w*|promise\w*|commit\w*|contract\w*|legal|lawyer|"
    r"mortgage\w*|loan\w*|tax\w*|refund\w*|deposit\w*|payment\w*|bank\w*|passport\w*|"
    r"visa\w*|emirates id|reserve\w*|reservation\w*|book\w*|confirm\w*|cancel\w*|"
    r"sign\w*|viewing|appointment|complaint\w*|disput\w*|commission\w*)\b"
    r"|\b(?:lower|reduce|drop|waive).{0,25}\b(?:price|rent|fee|amount)\b"
    r"|\b(?:i(?:.ll| will) pay|special deal|price flexible)\b"
    r"|خصم|تفاوض|عقد|دفعة|عربون|حجز|احجز|تأكيد|قرض|جواز|ضريبة|ضمان"
)


def unsafe_reply(text: str) -> bool:
    """A generated reply may be personal in tone, but never an attack or unsafe output."""
    return not text.strip() or not channel_output_allowed(text) or bool(_INJECTION.search(text))


def rejected_text(text: str) -> bool:
    return (
        not text.strip()
        or channel_input(text) is None
        or not channel_output_allowed(text)
        or bool(_INJECTION.search(text) or _PERSONAL.search(text))
    )


def requests_human(text: str) -> bool:
    return bool(_HUMAN.search(text))


def requires_approval(text: str) -> bool:
    return bool(_SENSITIVE.search(text)) or requests_human(text)


def admitted(decision: TopicDecision) -> bool:
    return decision.topic == "property" and decision.confidence >= 0.95
