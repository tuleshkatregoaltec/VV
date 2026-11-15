"""Strip personal contact details that scraped listing text can carry."""

import re

REDACTION_MARKER = "[contact removed]"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_CANDIDATE = re.compile(r"(?<![\w.])\+?\d[\d\s().-]{6,}\d(?![\w])")
# Fewer digits than this reads as a price, size or date rather than a phone number.
_MIN_PHONE_DIGITS = 9


def _redact_phone(match: re.Match[str]) -> str:
    digits = sum(character.isdigit() for character in match.group(0))
    return REDACTION_MARKER if digits >= _MIN_PHONE_DIGITS else match.group(0)


def redact_contacts(value: str | None) -> str | None:
    if not value:
        return value
    return _PHONE_CANDIDATE.sub(_redact_phone, _EMAIL.sub(REDACTION_MARKER, value))
