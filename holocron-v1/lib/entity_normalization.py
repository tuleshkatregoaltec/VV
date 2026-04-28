"""Shared deterministic normalization helpers for silver entity-resolution assets."""

from __future__ import annotations

from datetime import date
import json
import re
from typing import Any

_SEPARATOR_RE = re.compile(r"[/|>]+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_SPACE_RE = re.compile(r"\s+")
_ROMAN_RE = re.compile(r"\b(x|ix|viii|vii|vi|iv|iii|ii|v|i)\b")
_LOCATION_PATH_RE = re.compile(r"\s*,\s*|\s*/\s*|\s*\|\s*|\s*>\s*")

_TOKEN_REPLACEMENTS = {
    "twr": "tower",
    "bldg": "building",
    "bld": "building",
    "ph": "phase",
    "apt": "apartment",
    "jvc": "jumeirah village circle",
    "jvt": "jumeirah village triangle",
    "pjsc": "",
    "fz llc": "",
    "fzllc": "",
    "l l c": "",
    "llc": "",
}

_ROMAN_NUMERALS = {
    "i": "1",
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
}

_PHRASE_REPLACEMENTS = (
    (re.compile(r"\bfz\s+llc\b"), ""),
    (re.compile(r"\bl\s+l\s+c\b"), ""),
)


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = _SEPARATOR_RE.sub(" ", text)
    text = text.replace("-", " ").replace("_", " ").replace("&", " and ")
    text = _ROMAN_RE.sub(lambda match: _ROMAN_NUMERALS[match.group(1)], text)
    text = _NON_ALNUM_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    if not text:
        return ""
    needs_cleanup = False
    for pattern, replacement in _PHRASE_REPLACEMENTS:
        text, n = pattern.subn(replacement, text)
        if n:
            needs_cleanup = True
    if needs_cleanup:
        text = _SPACE_RE.sub(" ", text).strip()
        if not text:
            return ""

    tokens: list[str] = []
    for token in text.split(" "):
        replacement = _TOKEN_REPLACEMENTS.get(token, token)
        if replacement:
            tokens.extend(part for part in replacement.split(" ") if part)
    return " ".join(tokens)


def normalize_identifier(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    return text.replace(" ", "")


def token_bag(value: Any) -> list[str]:
    normalized = normalize_text(value)
    if not normalized:
        return []
    return normalized.split(" ")


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def split_location_path(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = _LOCATION_PATH_RE.split(text)
    return [part.strip() for part in parts if part and part.strip()]


def dedupe_preserve_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        stripped = value.strip()
        if not stripped:
            continue
        marker = stripped.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(stripped)
    return deduped


def parse_json_list(value: Any) -> list:
    try:
        parsed = json.loads(str(value or "") or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
