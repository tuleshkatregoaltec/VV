"""Normalize rows from the DXB sales backfill."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from holocron.sources.dxbi.rental_events import canonical_area_name

_AGENT_PREFIX = re.compile(r"^(?:Buyer's|Seller's)\s+agent\s+", re.IGNORECASE)
# "<location> Ready Apartment, Floor 3, No. 301". A sale whose unit DXBI hides, or of a whole
# building, can end at the type: "Emaar Square 3, Downtown Dubai Ready Building".
_LOCATION_SUFFIX = re.compile(
    r"\s+(?P<status>Offplan|Ready)\s+(?P<property_type>[^,]+?)\s*(?:,\s*(?:Floor|No\.)\b.*)?$",
    re.IGNORECASE,
)
# Plot rows carry no market status: "Al Jafliya Plot, Floor u-hidden, No. 630".
_PLOT_SUFFIX = re.compile(
    r"\s+(?P<property_type>Plot)\s*(?:,\s*(?:Floor|No\.)\b.*)?$", re.IGNORECASE
)
# The location as DXBI shows it: <span class="bold-title" title="Burj Vista Tower 1, Downtown
# Dubai">. The cell's text also holds what DXBI hides on screen, such as the buyer's agent's name
# right before the building ("Hajar Binghatti Royale").
_BEDROOMS = re.compile(r"(?P<count>\d+)\s*Beds?\b", re.IGNORECASE)
_SIZE = re.compile(r"(?P<size>[\d,]+(?:\.\d+)?)\s*sqft", re.IGNORECASE)
_PRICE = re.compile(r"AED\s*(?P<price>[\d,]+)", re.IGNORECASE)
_PRICE_PER_SQFT = re.compile(
    r"AED\s*(?P<price>[\d,]+(?:\.\d+)?)\s*/sqft",
    re.IGNORECASE,
)
_CAPITAL_GAIN = re.compile(r"\((?P<sign>[+-])(?P<value>\d+(?:\.\d+)?)%\)")
_LTV = re.compile(r"(?<![\w-])(?P<value>\d+(?:\.\d+)?)%\s*LTV", re.IGNORECASE)
_BALCONY = re.compile(r"Balcony\s+(?P<size>[\d,]+(?:\.\d+)?)\s*sqft", re.IGNORECASE)
_BUA = re.compile(r"[•·]\s*(?P<size>[\d,]+(?:\.\d+)?)\s*sqft\s*BUA", re.IGNORECASE)
_SOLD_BY = re.compile(
    r"\d{4}\s+(?P<seller>Developer|Individual)"
    r"(?:\s+\((?P<count>\d+)\s+Times?\))?",
    re.IGNORECASE,
)
_SALE_DATE = re.compile(r"(?P<day>\d{1,2}),\s*(?P<month>[A-Za-z]{3})\s*(?P<year>\d{4})")
# The last "No. <unit>" of the location text; units can hold spaces ("No. RETAIL 06"), as the
# sales scraper (dxbi_sales_dynamic_bucket_runner.js) reads them.
_UNIT_NUMBER = re.compile(r"\bNo\.\s*(?P<unit>[^,]+)", re.IGNORECASE)


def normalize_sales_row(payload: dict[str, Any], *, source_file: str = "") -> dict[str, Any] | None:
    """One DXBI sale, or None when the row lacks a location, date, size or price.

    A sale whose unit DXBI hides is kept with an empty unit number: it is still a sale on the
    date and at the price DXBI lists, and DXBInteract counts it.
    """
    unit_number = str(payload.get("unit_number") or "").strip()
    if unit_number.lower() == "u-hidden":
        unit_number = ""

    raw_location = str(payload.get("location_text") or "").strip()
    agent_side = (
        "buyer"
        if raw_location.lower().startswith("buyer's agent")
        else "seller"
        if raw_location.lower().startswith("seller's agent")
        else ""
    )
    location = _AGENT_PREFIX.sub("", raw_location)
    suffix = _LOCATION_SUFFIX.search(location) or _PLOT_SUFFIX.search(location)
    property_type = ""
    market_status = ""
    if suffix:
        property_type = suffix.group("property_type").strip()
        market_status = (suffix.groupdict().get("status") or "").strip().title()
        location = location[: suffix.start()].strip(" ,")
    location = str(payload.get("location_title") or "").strip() or location

    parts = [part.strip() for part in location.split(",") if part.strip()]
    building_name = parts[0] if parts else ""
    # A plot named by its area alone ("Al Jafliya Plot") is in that area.
    area_part = parts[-1] if len(parts) >= 2 or property_type == "Plot" else ""
    area_name = canonical_area_name(area_part) if area_part else ""
    project_name = ", ".join(parts[1:-1]) if len(parts) >= 3 else ""
    specs = str(payload.get("specs_text") or "")
    bedrooms = _bedroom_label(specs)
    size_match = _SIZE.search(specs)
    amount_text = str(payload.get("amount_text") or "")
    date_text = str(payload.get("date_text") or "")
    price_match = _PRICE.search(amount_text)
    price_per_sqft_match = _PRICE_PER_SQFT.search(amount_text)
    capital_gain_match = _CAPITAL_GAIN.search(amount_text)
    ltv_match = _LTV.search(amount_text)
    balcony_match = _BALCONY.search(specs)
    bua_match = _BUA.search(specs)
    sold_by_match = _SOLD_BY.search(date_text)
    transaction_date = _parse_date(date_text)
    if not building_name or not transaction_date or not size_match or not price_match:
        return None

    size_sqft = float(size_match.group("size").replace(",", ""))
    sale_amount = int(price_match.group("price").replace(",", ""))
    capital_gain_pct = None
    if capital_gain_match:
        direction = -1 if capital_gain_match.group("sign") == "-" else 1
        capital_gain_pct = direction * float(capital_gain_match.group("value"))
    detail_url = str(payload.get("detail_url") or "").strip()
    sale_key = _digest(
        detail_url
        or "|".join(
            (
                transaction_date.isoformat(),
                unit_number,
                building_name,
                str(sale_amount),
                f"{size_sqft:.1f}",
            )
        )
    )
    # A placeholder DXBI prints in the cell ('-', 'N/A') is no registration number.
    registration = str(payload.get("dld_transaction_number") or "").strip()
    if not re.search(r"\d", registration):
        registration = ""
    return {
        "sale_key": sale_key,
        # Preserve the explicit registration number verbatim. A /sold/t-* token and the
        # hashed sale_key identify DXBI records, not DLD registrations.
        "dld_transaction_number": registration,
        "transaction_date": transaction_date,
        "unit_number": unit_number,
        "building_name": building_name,
        "building_key": location_key(building_name),
        "project_name": project_name,
        "area_name": area_name,
        "area_key": location_key(area_name),
        "address_normalization_version": 5,
        "property_type": property_type,
        "market_status": market_status,
        "bedrooms": bedrooms,
        "size_sqft": size_sqft,
        "size_key": round(size_sqft),
        "built_up_area_sqft": (
            float(bua_match.group("size").replace(",", "")) if bua_match else None
        ),
        "balcony_sqft": (
            float(balcony_match.group("size").replace(",", "")) if balcony_match else None
        ),
        "sale_amount_aed": sale_amount,
        "price_per_sqft_aed": (
            float(price_per_sqft_match.group("price").replace(",", ""))
            if price_per_sqft_match
            else None
        ),
        "capital_gain_pct": capital_gain_pct,
        "ltv_pct": float(ltv_match.group("value")) if ltv_match else None,
        "seller_type": sold_by_match.group("seller").title() if sold_by_match else "",
        "seller_transaction_count": (
            int(sold_by_match.group("count"))
            if sold_by_match and sold_by_match.group("count")
            else None
        ),
        "agent_side": agent_side,
        "detail_url": detail_url,
        "source_file": source_file,
    }


def compact_payload(line: str) -> dict[str, Any]:
    """Return the normalized input shape from old compact or current raw rows.

    Both shapes keep DXBI's report cells in ``columns``; the location cell's HTML gives the
    location as DXBI shows it (``location_title``). A row whose ``columns`` array is cut off keeps
    its text fields.
    """
    try:
        record = json.loads(line)
    except ValueError:
        record = json.loads(line.split(',"columns":', 1)[0] + "}")
    columns = {
        str(column.get("id") or ""): column
        for column in record.pop("columns", None) or []
        if isinstance(column, dict)
    }
    title = _location_title(str(columns.get("PATH_NAME", {}).get("html") or ""))
    registration = str(
        record.get("dld_transaction_number")
        or columns.get("TRANSACTION_NUMBER", {}).get("text")
        or ""
    ).strip()
    if registration:
        record["dld_transaction_number"] = registration
    if "unit_number" in record:
        return {**record, "location_title": title} if title else record

    location_text = str(columns.get("PATH_NAME", {}).get("text") or "")
    units = [match.group("unit").strip() for match in _UNIT_NUMBER.finditer(location_text)]
    # A hidden final unit must not fall back to an earlier building number.
    unit = units[-1] if units and units[-1].lower() != "u-hidden" else ""
    detail_url = ""
    for column in columns.values():
        for link in column.get("links") or []:
            candidate = str(link.get("href") or "")
            if "/sold/" in candidate:
                detail_url = candidate
                break
        if detail_url:
            break
    return {
        "unit_number": unit,
        "location_text": location_text,
        "amount_text": str(columns.get("TOTAL_PRICE", {}).get("text") or ""),
        "specs_text": str(columns.get("BEDROOM", {}).get("text") or ""),
        "date_text": str(columns.get("SOLD_BY", {}).get("text") or ""),
        "detail_url": detail_url,
        **({"dld_transaction_number": registration} if registration else {}),
        **({"location_title": title} if title else {}),
    }


class _LocationTitleParser(HTMLParser):
    """Read only the provider's property title, never adjacent agent text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.titles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "span" and "bold-title" in (values.get("class") or "").split():
            title = " ".join((values.get("title") or "").split())
            if title:
                self.titles.append(title)


def _location_title(cell_html: str) -> str:
    parser = _LocationTitleParser()
    parser.feed(cell_html)
    titles = set(parser.titles)
    # Conflicting titles are not evidence for choosing an arbitrary property.
    return next(iter(titles)) if len(titles) == 1 else ""


_LOCATION_KEY_REPLACEMENTS = {
    "jumeriah": "jumeirah",
    "residences": "residence",
    "apartments": "apartment",
}


def location_key(value: str) -> str:
    normalized = value.lower()
    for source, target in _LOCATION_KEY_REPLACEMENTS.items():
        normalized = normalized.replace(source, target)
    return re.sub(r"[^a-z0-9]+", "", normalized)


def location_key_sql(expr: str) -> str:
    """``location_key`` as a ClickHouse expression."""
    normalized = f"lowerUTF8({expr})"
    for source, target in _LOCATION_KEY_REPLACEMENTS.items():
        normalized = f"replaceAll({normalized}, '{source}', '{target}')"
    return f"replaceRegexpAll({normalized}, '[^a-z0-9]+', '')"


def _bedroom_label(value: str) -> str:
    if re.search(r"\bStudio\b", value, re.IGNORECASE):
        return "Studio"
    match = _BEDROOMS.search(value)
    return f"{match.group('count')} Bed" if match else ""


def _parse_date(value: str) -> date | None:
    match = _SALE_DATE.search(value)
    if not match:
        return None
    try:
        return datetime.strptime(
            f"{match.group('day')} {match.group('month')} {match.group('year')}", "%d %b %Y"
        ).date()
    except ValueError:
        return None


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def source_name(path: Path) -> str:
    return path.name
