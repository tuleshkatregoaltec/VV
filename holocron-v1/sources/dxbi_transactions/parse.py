"""DXBI transaction parsing helpers kept local to the source package."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup

from holocron.framework.models import utc_now_sql


@dataclass(frozen=True)
class SaleTransactionRow:
    run_id: str
    transaction_key: str
    source_page: str
    scope_slug: str
    listing_rank: int
    location_path: str
    status_text: str
    price_aed: str
    capital_gain_text: str
    price_per_sqft_aed: str
    transaction_size_sqft: str
    bua_sqft: str
    bedrooms_label: str
    transaction_date: str
    seller_type: str
    unit_is_locked: int
    scraped_at: str
    filters_json: str


@dataclass(frozen=True)
class RentalTransactionRow:
    run_id: str
    transaction_key: str
    source_page: str
    scope_slug: str
    listing_rank: int
    location_path: str
    status_text: str
    bedrooms_label: str
    size_sqft: str
    annual_rent_aed: str
    rental_yield_pct: str
    lease_start_date: str
    lease_end_date: str
    duration_text: str
    purchase_price_aed: str
    unit_is_locked: int
    scraped_at: str
    filters_json: str


_now_sql = utc_now_sql


def normalized_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def scope_slug_from_url(url: str) -> str:
    path = url.split("?", 1)[0].rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def extract_decimal(text: str) -> str:
    cleaned = text.replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return ""
    try:
        return str(Decimal(match.group(0)))
    except InvalidOperation:
        return ""


def extract_date(text: str) -> str:
    cleaned = text.replace(",", "").strip()
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def transaction_key(*parts: object) -> str:
    payload = "|".join(str(part).strip() for part in parts)
    return hashlib.sha1(payload.encode("utf-8"), usedforsecurity=False).hexdigest()


def extract_sale_row(cells: list) -> dict[str, str | int]:
    location = cells[0].select_one(".bold-title")
    status = cells[0].select_one("p")
    price_block = cells[1].get_text("\n", strip=True)
    specs_block = cells[2].get_text("\n", strip=True)
    date_block = cells[3].get_text("\n", strip=True)

    size_match = re.search(r"([\d,]+)\s*sqft", specs_block, flags=re.IGNORECASE)
    bua_matches = re.findall(r"([\d,]+)\s*sqft", specs_block, flags=re.IGNORECASE)
    bed_match = re.search(r"(Studio|\d+\s*Beds?|\d+\s*Bed)", specs_block, flags=re.IGNORECASE)
    ppsf_match = re.search(r"AED\s*([\d,]+(?:\.\d+)?)\s*/sqft", price_block, flags=re.IGNORECASE)
    date_match = re.search(r"(\d{1,2},?\s+[A-Za-z]{3,9}\s+\d{4})", date_block)
    gain_match = re.search(r"\(([^)]+)\)", price_block)
    date_lines = normalized_lines(date_block)

    return {
        "location_path": location.get_text(" ", strip=True) if location else "",
        "status_text": status.get_text(" ", strip=True) if status else "",
        "price_aed": extract_decimal(price_block),
        "capital_gain_text": gain_match.group(1).strip() if gain_match else "",
        "price_per_sqft_aed": extract_decimal(ppsf_match.group(1)) if ppsf_match else "",
        "transaction_size_sqft": extract_decimal(size_match.group(1)) if size_match else "",
        "bua_sqft": extract_decimal(bua_matches[1]) if len(bua_matches) > 1 else "",
        "bedrooms_label": bed_match.group(1).strip() if bed_match else "",
        "transaction_date": extract_date(date_match.group(1)) if date_match else "",
        "seller_type": date_lines[-1] if date_lines else "",
        "unit_is_locked": 1 if cells[0].select_one(".lock-access") else 0,
    }


def parse_sales_transactions_html(
    html: str,
    *,
    run_id: str,
    source_page: str,
    scope_slug: str,
    filters: dict | None = None,
) -> list[SaleTransactionRow]:
    soup = BeautifulSoup(html, "html.parser")
    scraped_at = _now_sql()
    rows: list[SaleTransactionRow] = []
    for index, tr in enumerate(soup.select("#report_table_soldhistory tbody tr"), start=1):
        cells = tr.find_all("td")
        if len(cells) != 4:
            continue
        extracted = extract_sale_row(cells)
        rows.append(
            SaleTransactionRow(
                run_id=run_id,
                transaction_key=transaction_key(
                    source_page,
                    extracted["location_path"],
                    extracted["transaction_date"],
                    extracted["price_aed"],
                    extracted["transaction_size_sqft"],
                    extracted["seller_type"],
                ),
                source_page=source_page,
                scope_slug=scope_slug,
                listing_rank=index,
                location_path=str(extracted["location_path"]),
                status_text=str(extracted["status_text"]),
                price_aed=str(extracted["price_aed"]),
                capital_gain_text=str(extracted["capital_gain_text"]),
                price_per_sqft_aed=str(extracted["price_per_sqft_aed"]),
                transaction_size_sqft=str(extracted["transaction_size_sqft"]),
                bua_sqft=str(extracted["bua_sqft"]),
                bedrooms_label=str(extracted["bedrooms_label"]),
                transaction_date=str(extracted["transaction_date"]),
                seller_type=str(extracted["seller_type"]),
                unit_is_locked=int(extracted["unit_is_locked"]),
                scraped_at=scraped_at,
                filters_json=json.dumps(filters or {}, sort_keys=True),
            )
        )
    return rows


def parse_rental_transactions_html(
    html: str,
    *,
    run_id: str,
    source_page: str,
    scope_slug: str,
    filters: dict | None = None,
) -> list[RentalTransactionRow]:
    soup = BeautifulSoup(html, "html.parser")
    scraped_at = _now_sql()
    rows: list[RentalTransactionRow] = []
    for index, tr in enumerate(soup.select("#report_table_rentHistory tbody tr"), start=1):
        cells = tr.find_all("td")
        if len(cells) != 5:
            continue
        location = cells[0].select_one(".bold-title")
        status = cells[0].select_one("p")
        specs = cells[1].get_text("\n", strip=True)
        rent_block = cells[2].get_text("\n", strip=True)
        duration_block = cells[3].get_text("\n", strip=True)
        purchase_block = cells[4].get_text("\n", strip=True)
        dates = re.findall(r"\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4}", duration_block)
        duration_lines = normalized_lines(duration_block)
        rent_lines = normalized_lines(rent_block)
        bed_match = re.search(r"(Studio|\d+\s*Beds?|\d+\s*Bed)", specs, re.IGNORECASE)

        location_path = location.get_text(" ", strip=True) if location else ""
        annual_rent_aed = extract_decimal(rent_block)
        lease_start_date = extract_date(dates[0]) if dates else ""
        lease_end_date = extract_date(dates[1]) if len(dates) > 1 else ""

        rows.append(
            RentalTransactionRow(
                run_id=run_id,
                transaction_key=transaction_key(
                    source_page,
                    location_path,
                    lease_start_date,
                    annual_rent_aed,
                    extract_decimal(specs),
                    extract_decimal(purchase_block),
                ),
                source_page=source_page,
                scope_slug=scope_slug,
                listing_rank=index,
                location_path=location_path,
                status_text=status.get_text(" ", strip=True) if status else "",
                bedrooms_label=bed_match.group(1).strip() if bed_match else "",
                size_sqft=extract_decimal(specs),
                annual_rent_aed=annual_rent_aed,
                rental_yield_pct=extract_decimal(rent_lines[1]) if len(rent_lines) > 1 else "",
                lease_start_date=lease_start_date,
                lease_end_date=lease_end_date,
                duration_text=duration_lines[-1] if duration_lines else "",
                purchase_price_aed=extract_decimal(purchase_block),
                unit_is_locked=1 if cells[0].select_one(".lock-access") else 0,
                scraped_at=scraped_at,
                filters_json=json.dumps(filters or {}, sort_keys=True),
            )
        )
    return rows
