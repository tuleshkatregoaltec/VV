"""Instruction-injection screening shared by policy and the agent-authored voice fields."""

import re

from app.chat.operations import channel_input

# Negative defense in depth; positive property admission always requires the classifier.
_INJECTION = re.compile(
    r"(?is)(?:ignore|override|forget|disregard).{0,70}(?:instructions?|rules?|policy|previous|above)"
    r"|(?:system|developer)\s*(?:message|prompt|:)|(?:act|pretend)\s+as\b"
    r"|\b(?:classify|label|mark)\b.{0,45}(?:routine|property|safe|confidence)"
    r"|تجاهل.{0,40}(?:تعليمات|قواعد)|اكشف.{0,30}(?:كلمة|سر)"
)


def injected(text: str) -> bool:
    """Instruction-like text only (no topic screening), for agent-authored style fields."""
    return channel_input(text) is None or bool(_INJECTION.search(text))
