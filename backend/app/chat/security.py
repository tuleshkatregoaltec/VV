"""Bounded, deterministic defenses supplement scoped tools and model instructions."""

import hashlib
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

MAX_INPUT = 8000
MAX_OUTPUT = 16000
MAX_TOOL_OUTPUT = 24000
MAX_DETAIL_ROWS = 10
REFUSAL = "I can help with Dubai property research and your own CRM in this chat. I cannot provide files, downloads, credentials, internal schemas, or raw database dumps."
RESTRICTED_HISTORY = "This earlier answer is unavailable because its private source records have changed or are no longer accessible."
# These are defense in depth, not a complete prompt-injection classifier. Authorization is
# enforced by repository predicates and the proposal/confirmation boundary.
_SECRET = re.compile(
    r"(?i)(?:sk-(?:or-v1-)?[a-z0-9_-]{16,}|bearer\s+[a-z0-9._-]{16,}|-----BEGIN .*PRIVATE KEY|(?:password|api[_ -]?key|secret|access[_ -]?token)\s*[:=]\s*\S+)"
)
_INTERNAL = re.compile(
    r"(?i)(?:\b(?:create|alter)\s+table\b|\binformation_schema\b|\bselect\s+.+?\s+from\b|/api/v\d|\b(?:release_id|raw_payload|connection_string|organization_id|user_id|tool_call_id)\b)"
)
_LINK = re.compile(
    r"(?i)(?:[a-z][a-z0-9+.-]*://|(?:data|javascript|blob|file|sandbox):|www\.|\[[^\]]*\]\s*\([^)]*\))"
)
_FILE_REQUEST = re.compile(
    r"(?i)(?:\b(?:generate|create|export|download|attach|write|make|produce|give|send)\b.{0,100}\b(?:files?|pdf|docx?|word document|spreadsheet|csv|xlsx|download|documents?)\b|\b(?:schema|credentials?|api keys?|system prompt|database dump|raw data dump)\b)"
)
_BULK_CONTACT_REQUEST = re.compile(
    r"(?is)(?=.*\b(?:all|every|entire|complete|bulk)\b)(?=.*\b(?:contacts?|leads?|customers?|owners?|crm)\b)(?=.*\b(?:names?|emails?|phones?|mobiles?|addresses|one per line|one contact per line)\b)"
)
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_PHONE = re.compile(r"(?<!\w)(?:\+\d[\d ()-]{6,}\d|(?:00971|971|05)\d{7,11})(?!\w)")
_CONTACT_FIELD = re.compile(
    r"\b(?:name|contact|customer|lead|owner|email|phone|mobile|address)\b", re.I
)
_PRIVATE_KEYS = {
    "release_id",
    "raw_payload",
    "field_sources",
    "sql",
    "query",
    "password",
    "api_key",
    "secret",
    "token",
    "organization_id",
    "user_id",
    "created_by_user_id",
    "assigned_user_id",
}


def input_refusal(text: str) -> str | None:
    if (
        len(text) > MAX_INPUT
        or _SECRET.search(text)
        or _FILE_REQUEST.search(text)
        or _BULK_CONTACT_REQUEST.search(text)
    ):
        return REFUSAL
    return None


def bulk_record_output(text: str) -> bool:
    """Bound recognizable record/contact dumps; this is not a general DLP classifier.

    Numeric market series and aggregate tables are allowed. Personal details are
    additionally limited before retrieval, independently of this output defense.
    """
    if max(len(_EMAIL.findall(text)), len(_PHONE.findall(text))) > MAX_DETAIL_ROWS:
        return True
    lines = [
        line.strip() for line in text.splitlines() if line.strip() and not line.startswith("```")
    ]
    if len(lines) > MAX_DETAIL_ROWS + 1:
        # CSV/TSV/Markdown tables bearing contact fields represent individual records.
        if _CONTACT_FIELD.search(lines[0]):
            for delimiter in (",", "\t", "|"):
                if (
                    delimiter in lines[0]
                    and sum(delimiter in line for line in lines[1:]) > MAX_DETAIL_ROWS
                ):
                    return True
        # Labelled one-record-per-line dumps need no punctuation or code fence.
        if sum(bool(_CONTACT_FIELD.search(line)) for line in lines) > MAX_DETAIL_ROWS:
            return True
    try:
        value = json.loads("\n".join(lines))
    except (ValueError, RecursionError):
        return False

    def records(item, depth=0):
        if depth > 8:
            return True
        if isinstance(item, list):

            def aggregate(row):
                if not isinstance(row, dict):
                    return True
                keys = {str(key).lower() for key in row}
                personal = {
                    "email",
                    "phone",
                    "mobile",
                    "full_name",
                    "contact_name",
                    "lead_id",
                    "owner_name",
                }
                metrics = {"count", "total", "average", "median", "mean", "avg", "min", "max"}
                return not keys.intersection(personal) and any(
                    key in metrics or key.endswith(("_count", "_price", "_rent")) for key in keys
                )

            return (len(item) > MAX_DETAIL_ROWS and any(not aggregate(row) for row in item)) or any(
                records(row, depth + 1) for row in item
            )
        if isinstance(item, dict):
            return any(records(child, depth + 1) for child in item.values())
        return False

    return records(value)


def safe_answer(text: str) -> bool:
    return (
        len(text) <= MAX_OUTPUT
        and not bulk_record_output(text)
        and not any(pattern.search(text) for pattern in (_SECRET, _INTERNAL, _LINK))
    )


# An internal name (a table, schema or source key such as "raw_physical_table" or
# "dld/matched"): lower-case words joined by underscores, dots or slashes.
_INTERNAL_NAME = re.compile(r"[a-z0-9]+(?:[_./][a-z0-9]+)+")


def source_label(value: Any) -> str:
    """A readable source: CRM evidence by name, a record's own source (a lead's channel, such
    as "Property Finder") as stored, and never an internal table or source key."""
    text = str(value).strip()
    if "crm" in text.lower():
        return "Your CRM records"
    if not text or _INTERNAL_NAME.fullmatch(text):
        return "Stored records"
    return text[:120]


def source_evidence(value: Any) -> Any:
    if isinstance(value, dict):
        counts = {}
        for source, count in list(value.items())[:20]:
            if isinstance(count, (int, float)):
                label = source_label(source)
                counts[label] = counts.get(label, 0) + count
        return counts
    if isinstance(value, list):
        return list(dict.fromkeys(source_label(item) for item in value[:20]))
    return source_label(value)


class EvidenceTooLarge(ValueError):
    pass


def safe_data(value: Any, depth: int = 0) -> Any:
    """Project bounded tool DTOs, excluding technical metadata and unsafe free text."""
    if depth > 8:
        return "[omitted]"
    if isinstance(value, dict):
        if len(value) > 80:
            raise EvidenceTooLarge("Narrow the evidence scope; dictionary exceeds the safe bound")
        return {
            str(k): (
                source_evidence(v)
                if str(k) in {"source", "sources", "source_table", "source_name"}
                else safe_data(v, depth + 1)
            )
            for k, v in list(value.items())[:80]
            if str(k).lower() not in _PRIVATE_KEYS
            and not str(k).lower().endswith(("_sql", "_table", "_path"))
        }
    if isinstance(value, list):
        if len(value) > 50:
            raise EvidenceTooLarge("Narrow the evidence scope; records exceed the safe bound")
        return [safe_data(v, depth + 1) for v in value]
    if isinstance(value, str):
        if not safe_answer(value):
            return "[restricted source text]"
        return value if len(value) <= 2000 else value[:2000] + " [source text truncated]"
    return value


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


_progress_event: ContextVar[dict | None] = ContextVar("tool_progress_event", default=None)


def mark_cached() -> None:
    """Report that this call reused an identical earlier result of the turn, not a new read."""
    event = _progress_event.get()
    if event is not None:
        event["cached"] = True


@contextmanager
def tool_progress(ctx: Any, tool: str):
    """Report a tool's start and finish to the turn's stream: names only, no arguments."""
    deps = getattr(ctx, "deps", None)
    progress = getattr(deps, "progress", None)
    if progress is None:
        yield
        return
    # Provider call IDs are opaque; a digest pairs start/finish without echoing them.
    call_id = getattr(ctx, "tool_call_id", None) or tool
    event = {"tool": tool, "tool_call_id": hashlib.sha256(call_id.encode()).hexdigest()[:12]}
    progress({"type": "tool_call_start", **event})
    token = _progress_event.set(event)
    try:
        yield
    finally:
        _progress_event.reset(token)
        progress({"type": "tool_call_result", **event})


# A Markdown contact link: [label](mailto:address) or [label](tel:number).
_CONTACT_LINK = re.compile(r"\[([^\]\n]{1,200})\]\((mailto|tel):([^)\s]{1,200})\)", re.I)


def plain_contact_links(text: str) -> str:
    """Show a contact link as its plain text when the link only repeats it.

    Models write a lead's phone or email as a tel:/mailto: link. The link guard would refuse the
    whole answer, so a self-link becomes plain text instead. Any other link, including a contact
    link whose target differs from what is shown (a query, another address), is left to be
    refused.
    """

    def plain(match: re.Match) -> str:
        label, scheme, target = match.group(1), match.group(2).lower(), match.group(3)
        if scheme == "mailto":
            same = label.strip().casefold() == target.casefold()
        else:
            same = re.sub(r"[\s().-]", "", label) == re.sub(r"[().-]", "", target)
        return label if same else match.group(0)

    return _CONTACT_LINK.sub(plain, text)


def guarded_answer(text: str) -> str:
    """Model text as it may be shown, or the refusal when it fails the output guard."""
    text = plain_contact_links(text)
    return text if safe_answer(text) else REFUSAL


def safe_tool(function):
    """Do not expose service exceptions or unbounded/debug payloads to a model."""
    import functools
    import logging

    @functools.wraps(function)
    async def wrapped(*args, **kwargs):
        with tool_progress(args[0] if args else None, function.__name__):
            return await _guarded(*args, **kwargs)

    async def _guarded(*args, **kwargs):
        try:
            result = safe_data(await function(*args, **kwargs))
            if isinstance(result, dict) and "error" in result:
                return {"available": False, "reason": "Stored data is temporarily unavailable"}
            serialized = json.dumps(result, default=str)
            if len(serialized) > MAX_TOOL_OUTPUT:
                return {
                    "available": False,
                    "reason": "Narrow the requested scope to retrieve bounded evidence",
                }
            return result
        except EvidenceTooLarge:
            return {
                "available": False,
                "reason": "Narrow the requested scope; the complete evidence exceeds the safe response limit",
            }
        except Exception as exc:
            logging.getLogger(__name__).warning("Chat tool failed (%s)", type(exc).__name__)
            return {"available": False, "reason": "This scoped operation is unavailable"}

    return wrapped
