"""Normalize the DXB rental backfill JSONL format into CRM lease events."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_PROPERTY_TYPES = (
    "Hotel Apartment",
    "Commercial",
    "Apartment",
    "Villa",
    "Townhouse",
    "Office",
    "Shop",
    "Warehouse",
    "Land",
)
_DATE_RANGE = re.compile(
    r"(?P<start>\d{1,2} [A-Za-z]{3}, \d{4})\s*-\s*"
    r"(?P<end>\d{1,2} [A-Za-z]{3}, \d{4})"
)
_SIZE = re.compile(r"(?P<size>[\d,]+(?:\.\d+)?)\s*sqft", re.IGNORECASE)
_BEDROOMS = re.compile(r"(?P<bedrooms>Studio|\d+\s*Bed)", re.IGNORECASE)
_FIRST_NUMBER = re.compile(r"(?P<value>[\d,]+(?:\.\d+)?)")
_PURCHASE_PRICE = re.compile(r"AED\s*(?P<value>[\d,.]+)\s*(?P<suffix>[KMB]?)", re.IGNORECASE)


def normalize_rental_row(
    payload: dict[str, Any],
    *,
    source_file: str = "",
    source_account: str = "",
) -> dict[str, Any] | None:
    columns = {
        str(column.get("id") or ""): str(column.get("text") or "").strip()
        for column in payload.get("columns") or []
    }
    location_text = columns.get("PATH_NAME", "")
    specs_text = columns.get("PROP_SIZES", "")
    price_text = columns.get("TOTAL_PRICES", "")
    duration_text = columns.get("START_DATE", "")
    if not location_text or not duration_text:
        return None

    date_match = _DATE_RANGE.search(duration_text)
    if not date_match:
        return None
    lease_start = datetime.strptime(date_match.group("start"), "%d %b, %Y").date()
    lease_end = datetime.strptime(date_match.group("end"), "%d %b, %Y").date()
    if lease_end < lease_start:
        return None

    location_name, building_name, project_name, area_name, property_type = _parse_location(
        location_text
    )
    bedrooms_match = _BEDROOMS.search(specs_text)
    size_match = _SIZE.search(specs_text)
    bedrooms = bedrooms_match.group("bedrooms").title() if bedrooms_match else ""
    size_sqft = float(size_match.group("size").replace(",", "")) if size_match else 0.0
    annual_rent_aed = _first_amount(price_text)
    purchase_price_aed = _purchase_price(columns.get("PURCHASE_PRICE", ""))
    contract_state = "Renewed" if re.search(r"\bRenewed\b", price_text, re.IGNORECASE) else "New"

    shard = payload.get("shard") if isinstance(payload.get("shard"), dict) else {}
    shard_date = _safe_date(str(shard.get("date") or "")) or lease_start
    scraped_at = _safe_datetime(str(payload.get("scraped_at") or ""))

    cohort_parts = (
        _key_text(building_name or location_name),
        _key_text(project_name),
        _key_text(area_name),
        _key_text(property_type),
        _key_text(bedrooms),
        f"{size_sqft:.1f}",
    )
    unit_cohort_key = _digest(cohort_parts)
    candidate_parts = cohort_parts + (
        str(int(round(purchase_price_aed / 1_000) * 1_000)) if purchase_price_aed else "unknown",
    )
    unit_candidate_key = _digest(candidate_parts)
    event_key = _digest(
        candidate_parts
        + (
            lease_start.isoformat(),
            lease_end.isoformat(),
            str(annual_rent_aed),
            contract_state.lower(),
        )
    )

    return {
        "event_key": event_key,
        "unit_candidate_key": unit_candidate_key,
        "unit_cohort_key": unit_cohort_key,
        "location_name": location_name,
        "building_name": building_name,
        "project_name": project_name,
        "area_name": area_name,
        "property_type": property_type,
        "bedrooms": bedrooms,
        "size_sqft": size_sqft,
        "annual_rent_aed": annual_rent_aed,
        "purchase_price_aed": purchase_price_aed,
        "lease_start": lease_start,
        "lease_end": lease_end,
        "contract_state": contract_state,
        "source_account": source_account,
        "source_shard_date": shard_date,
        "source_file": source_file,
        "scraped_at": scraped_at,
    }


def _parse_location(value: str) -> tuple[str, str, str, str, str]:
    cleaned = re.sub(r",?\s*Floor No\..*$", "", value, flags=re.IGNORECASE).strip(" ,")
    property_type = ""
    for candidate in _PROPERTY_TYPES:
        match = re.search(rf"\b{re.escape(candidate)}\b\s*$", cleaned, re.IGNORECASE)
        if match:
            property_type = candidate
            cleaned = cleaned[: match.start()].strip(" ,")
            break

    parts = [part.strip() for part in cleaned.split(",") if part.strip()]
    if len(parts) >= 3:
        building_name = parts[0]
        project_name = parts[-2]
        area_name = parts[-1]
    elif len(parts) == 2:
        building_name, area_name = parts
        project_name = ""
    elif parts:
        building_name = ""
        project_name = ""
        area_name = parts[0]
    else:
        building_name = project_name = area_name = ""
    return cleaned, building_name, project_name, area_name, property_type


def _first_amount(value: str) -> int:
    match = _FIRST_NUMBER.search(value)
    return int(round(float(match.group("value").replace(",", "")))) if match else 0


def _purchase_price(value: str) -> int:
    match = _PURCHASE_PRICE.search(value)
    if not match:
        return 0
    amount = float(match.group("value").replace(",", ""))
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    return int(round(amount * multiplier[match.group("suffix").upper()]))


def _safe_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _safe_datetime(value: str) -> datetime:
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _key_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _digest(parts: tuple[str, ...]) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]


def source_account_from_path(path: Path) -> str:
    for part in path.parts:
        if part.startswith("account-"):
            return part
    return ""
