"""Keeps collection share tokens (bearer secrets) out of log files."""

from __future__ import annotations

import copy
import logging
import re
from typing import Any

# A share token: 32 random bytes, url-safe base64 without padding.
SHARE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
REDACTED = "[redacted]"


def redact_params(value: Any) -> Any:
    """Copy of a bound-parameter structure with token-shaped strings replaced."""
    if isinstance(value, str):
        return REDACTED if SHARE_TOKEN_PATTERN.match(value) else value
    if isinstance(value, tuple):
        return tuple(redact_params(v) for v in value)
    if isinstance(value, list):
        return [redact_params(v) for v in value]
    if isinstance(value, dict):
        return {k: redact_params(v) for k, v in value.items()}
    inner = getattr(value, "params", None)
    if inner is not None and type(value).__name__ == "_repr_params":
        # SQLAlchemy's lazy repr wrapper: keep its truncation, swap in clean params.
        clone = copy.copy(value)
        clone.params = redact_params(inner)
        return clone
    return value


class RedactSqlParameters(logging.Filter):
    """Redact token-shaped bound parameters from SQLAlchemy engine records.

    The engine logs `"[%s] %r", stats, params`; `record.args` carries the params object.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(redact_params(arg) for arg in record.args)
        return True
