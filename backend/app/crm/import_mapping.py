"""Column roles for owner workbooks: signatures, privacy-safe samples, saved and overridden maps.

Aliases map the known layouts. For a new layout the model maps what is still unmapped; its answer
is saved on the import by header signature and reused for later files with the same headers.
Nothing here calls the model or the database.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Any

from app.crm.import_parsing import (
    _CANONICAL_FIELDS,
    _CHANNEL_TOKENS,
    _IDENTITY_HEADER,
    SheetProfile,
    _header_token,
    _mapping_response,
    is_blank,
    refresh_unmapped_headers,
)

SAMPLE_LIMIT = 5
_SAMPLE_CHARS = 80
_REDACTED = "<redacted>"
_PERSONAL_FIELDS = ("contact_name", "phone_primary", "phone_alternate", "email_primary")
_SHEET_FAMILIES = {"transaction_party", "contact_list"}

_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_EMIRATES_ID = re.compile(r"(?<!\d)784[\s-]?\d{4}[\s-]?\d{7}[\s-]?\d(?!\d)")
_UAE_PHONE = re.compile(r"(?<!\d)(?:\+|00)?(?:971[\s-]?)?0?5\d[\s-]?\d{3}[\s-]?\d{4}(?!\d)")
_PHONE_SHAPED = re.compile(r"\+?[\d\s\-().]+")


def header_signature(headers: list[str]) -> str:
    """Stable id of a header set: order, case and punctuation do not change it."""
    tokens = sorted(_header_token(header) for header in headers)
    return hashlib.sha256("|".join(tokens).encode()).hexdigest()


def _redact(text: str) -> str:
    digits = sum(character.isdigit() for character in text)
    if (
        _EMAIL.search(text)
        or _EMIRATES_ID.search(text)
        or _UAE_PHONE.search(text)
        or (_PHONE_SHAPED.fullmatch(text) and 9 <= digits <= 15)
    ):
        return _REDACTED
    return text


def _sample_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()[:_SAMPLE_CHARS]


def column_samples(
    profile: SheetProfile, rows: list[tuple[Any, ...]], limit: int = SAMPLE_LIMIT
) -> dict[str, list[str]]:
    """Up to ``limit`` distinct sample values per non-personal column, keyed by header.

    Columns that hold owner or contact data are skipped entirely: those mapped to a name, phone or
    email field, and any header that names one (name, mobile, phone, email, passport, id number,
    birth, unified number, nationality, ...). Values that look like a phone number, email or
    Emirates ID are replaced with ``<redacted>``.
    """
    personal = {
        header
        for field_name in _PERSONAL_FIELDS
        for header in (
            profile.field_map.get(field_name),
            *profile.fallback_map.get(field_name, []),
        )
        if header
    }
    samples: dict[str, list[str]] = {}
    for header in profile.headers:
        token = _header_token(header.key)
        if header.key in personal or token in _CHANNEL_TOKENS or _IDENTITY_HEADER.search(token):
            continue
        values: list[str] = []
        for row in rows:
            if header.index >= len(row) or is_blank(row[header.index]):
                continue
            text = _redact(_sample_text(row[header.index]))
            if text and text not in values:
                values.append(text)
                if len(values) == limit:
                    break
        if values:
            samples[header.key] = values
    return samples


def needs_model_mapping(profile: SheetProfile) -> bool:
    """True when a data column has no role, or a field matching needs is still unmapped."""
    fields = profile.field_map
    if profile.unmapped_headers:
        return True
    return not (
        fields.get("transaction_price_aed")
        and any(fields.get(key) for key in ("unit_number", "plot_number", "building_number"))
        and any(
            fields.get(key)
            for key in ("building_name", "project_name", "master_project", "area_name")
        )
    )


def saved_sheet_mapping(profile: SheetProfile) -> dict[str, Any]:
    """What an import stores per sheet, so later files with the same headers can reuse it."""
    return {
        **_mapping_response(profile),
        "signature": header_signature([header.key for header in profile.headers]),
        "fallback_map": {key: list(value) for key, value in profile.fallback_map.items()},
        "unmapped_headers": list(profile.unmapped_headers),
    }


def _resolve_header(profile: SheetProfile, header: Any) -> str | None:
    """The profile's own key for a saved or supplied header: exact, else by normalized token."""
    if not isinstance(header, str):
        return None
    keys = [item.key for item in profile.headers]
    if header in keys:
        return header
    matches = [key for key in keys if _header_token(key) == _header_token(header)]
    return matches[0] if len(matches) == 1 and _header_token(header) else None


def _merge_fallbacks(profile: SheetProfile, fallbacks: Any) -> None:
    if not isinstance(fallbacks, dict):
        return
    for field_name, headers in fallbacks.items():
        if field_name not in _CANONICAL_FIELDS or not isinstance(headers, list):
            continue
        for header in headers:
            key = _resolve_header(profile, header)
            current = profile.fallback_map.get(field_name, [])
            if key and key != profile.field_map.get(field_name) and key not in current:
                profile.fallback_map[field_name] = [*current, key]


def _apply_field_map(profile: SheetProfile, field_map: Any, *, replace: bool) -> None:
    if not isinstance(field_map, dict):
        return
    for field_name, header in field_map.items():
        key = _resolve_header(profile, header)
        if (
            field_name in _CANONICAL_FIELDS
            and key
            and (replace or field_name not in profile.field_map)
        ):
            profile.field_map[field_name] = key


def apply_saved_mapping(
    profile: SheetProfile, saved: dict[str, Any], *, replace: bool, source: str
) -> SheetProfile:
    """Apply a mapping saved by an earlier import.

    A replay (``replace=True``) restores exactly what that import used. Reuse for a new file keeps
    today's aliases authoritative and only adds the roles the saved mapping found.
    """
    _apply_field_map(profile, saved.get("field_map"), replace=replace)
    _merge_fallbacks(profile, saved.get("fallback_map"))
    if saved.get("sheet_family") in _SHEET_FAMILIES and profile.field_map.get("party_role"):
        profile.sheet_family = saved["sheet_family"]
    profile.mapping_source = source
    refresh_unmapped_headers(profile)
    return profile


def saved_sheet_for(saved_sheets: list[dict[str, Any]] | None, profile: SheetProfile):
    """The saved sheet of this import that has the profile's name and header signature."""
    signature = header_signature([header.key for header in profile.headers])
    return next(
        (
            sheet
            for sheet in saved_sheets or []
            if isinstance(sheet, dict)
            and sheet.get("sheet_name") == profile.name
            and sheet.get("signature") == signature
        ),
        None,
    )


def override_for_sheet(override: dict[str, Any] | None, profile: SheetProfile):
    """The user's corrections for this sheet: ``{"sheets": [{"sheet", "field_map", ...}]}``."""
    sheets = override.get("sheets") if isinstance(override, dict) else None
    return next(
        (
            sheet
            for sheet in sheets or []
            if isinstance(sheet, dict)
            and (sheet.get("sheet") or sheet.get("sheet_name")) == profile.name
        ),
        None,
    )


def apply_override(profile: SheetProfile, override: dict[str, Any]) -> SheetProfile:
    """User corrections win over aliases; headers or fields that do not exist are ignored."""
    _apply_field_map(profile, override.get("field_map"), replace=True)
    _merge_fallbacks(profile, override.get("fallback_map"))
    profile.mapping_source = "override"
    refresh_unmapped_headers(profile)
    return profile
