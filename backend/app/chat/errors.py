"""Stable error codes for assistant turns, shared by the SSE stream and the HTTP responses
before it. The browser maps the code to its message; `error` stays a safe fallback sentence for
clients that only show text. Raw exception text, provider responses and internal IDs never
leave the server: an unexpected failure is logged under a random reference the user can quote.
"""

import asyncio
import logging
import secrets

from pydantic_ai.exceptions import (
    IncompleteToolCall,
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)

from app.token_usage.service import DAILY_LIMIT_REACHED

logger = logging.getLogger(__name__)

# code -> (safe message, whether sending the same message again is reasonable)
ERRORS: dict[str, tuple[str, bool]] = {
    "conversation_not_found": ("This conversation no longer exists.", False),
    "assistant_disabled": ("The assistant is not enabled yet.", False),
    "account_unavailable": ("Your account could not be verified. Please sign in again.", False),
    "turn_in_progress": (
        "Another assistant answer is still running. Wait for it to finish, then send again.",
        True,
    ),
    "service_busy": (
        "The assistant is busy right now. Please try again in a moment.",
        True,
    ),
    "insufficient_allowance": (
        "Not enough of today's assistant allowance is left to start another answer.",
        False,
    ),
    "daily_limit_reached": (DAILY_LIMIT_REACHED, False),
    "turn_budget_exceeded": (
        "This question needed more research steps than one answer allows. "
        "Please ask about one area, project or record at a time.",
        False,
    ),
    "provider_rate_limited": (
        "The assistant service is busy right now. Please try again in a minute.",
        True,
    ),
    "provider_unavailable": (
        "The assistant service is temporarily unavailable. Please try again shortly.",
        True,
    ),
    "provider_timeout": (
        "The answer took too long and was stopped. Try again, or ask a narrower question.",
        True,
    ),
    "provider_invalid_response": (
        "The assistant service returned an unusable answer. Please try again.",
        True,
    ),
    "internal_error": ("Unable to complete this answer. Please try again.", True),
}


def error_payload(code: str, **details) -> dict:
    """An HTTP error detail in the API's structured form ({code, message}), with a retry hint
    and any safe details."""
    if code not in ERRORS:
        code = "internal_error"
    message, retryable = ERRORS[code]
    return {"code": code, "message": message, "retryable": retryable, **details}


def error_event(code: str, **details) -> dict:
    """An SSE error event; its text is in `error`, as stream clients read it."""
    payload = error_payload(code, **details)
    return {"type": "error", "code": payload["code"], "error": payload.pop("message"), **payload}


def classify(exc: BaseException) -> str:
    """The code for a failed turn. Only known provider and budget failures get their own."""
    if isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        return classify(exc.exceptions[0])
    if isinstance(exc, UsageLimitExceeded):
        return "turn_budget_exceeded"
    if isinstance(exc, ModelHTTPError):
        if exc.status_code == 429:
            return "provider_rate_limited"
        if exc.status_code in (408, 504):
            return "provider_timeout"
        if exc.status_code >= 500:
            return "provider_unavailable"
        return "internal_error"  # A 4xx from the provider is our request or configuration.
    if isinstance(exc, ModelAPIError):
        return "provider_unavailable"  # Connection failures before any HTTP status.
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "provider_timeout"
    if isinstance(exc, (UnexpectedModelBehavior, IncompleteToolCall)):
        return "provider_invalid_response"
    return "internal_error"


def failure_event(exc: BaseException, *, context: str, **log_fields) -> dict:
    """Classify, log under a fresh reference (type and counters only), and build the event."""
    code = classify(exc)
    reference = secrets.token_hex(6)
    status = getattr(exc, "status_code", None)
    logger.error(
        "%s failed: code=%s reference=%s exception=%s provider_status=%s %s",
        context,
        code,
        reference,
        type(exc).__name__,
        status,
        " ".join(f"{key}={value}" for key, value in log_fields.items()),
    )
    return error_event(code, reference=reference)
