"""DXBI extraction logic local to the DXBI source."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from holocron.framework.csv_utils import write_csv
from holocron.framework.models import DownloadResult, utc_now_sql

DXBI_BASE_URL = "https://dxbinteract.com"
LOCATION_LOV_URL = f"{DXBI_BASE_URL}/property/website/DLDLOV?RETURN_COLUMN=LOCATION_URL"
DEVELOPER_LOV_URL = f"{DXBI_BASE_URL}/property/dxb/lov-fam-developer"

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass(frozen=True)
class LocationRow:
    run_id: str
    location_id: int
    location_name: str
    location_slug: str
    location_flag: str
    is_featured: int
    seq: int | None
    scraped_at: str


@dataclass(frozen=True)
class DeveloperRow:
    run_id: str
    developer_id: int
    developer_name: str
    is_hot: int
    scraped_at: str


@dataclass(frozen=True)
class RankedAreaRow:
    run_id: str
    source_page: str
    scope_slug: str
    item_rank: int
    location_name: str
    location_slug: str
    transaction_count: int
    metric_label: str
    scraped_at: str


@dataclass(frozen=True)
class SaleTransactionRow:
    run_id: str
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


_now_iso = utc_now_sql


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(_DEFAULT_HEADERS)
    return session


def _fetch_json(url: str) -> dict:
    response = _session().get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def fetch_location_rows(run_id: str) -> list[LocationRow]:
    payload = _fetch_json(LOCATION_LOV_URL)
    scraped_at = _now_iso()
    rows = []
    for item in payload.get("items", []):
        rows.append(
            LocationRow(
                run_id=run_id,
                location_id=int(item.get("id", 0)),
                location_name=str(item.get("dv", "")).strip(),
                location_slug=str(item.get("rv", "")).strip(),
                location_flag=str(item.get("flag", "")).strip(),
                is_featured=1 if str(item.get("is_featured", "N")).upper() == "Y" else 0,
                seq=int(item["seq"]) if item.get("seq") is not None else None,
                scraped_at=scraped_at,
            )
        )
    return rows


def fetch_developer_rows(run_id: str) -> list[DeveloperRow]:
    payload = _fetch_json(DEVELOPER_LOV_URL)
    scraped_at = _now_iso()
    rows = []
    for item in payload.get("items", []):
        rows.append(
            DeveloperRow(
                run_id=run_id,
                developer_id=int(item.get("id", 0)),
                developer_name=str(item.get("developer", "")).strip(),
                is_hot=1 if str(item.get("is_hot", "N")).upper() == "Y" else 0,
                scraped_at=scraped_at,
            )
        )
    return rows


def parse_ranked_area_media_list(
    html: str,
    *,
    run_id: str,
    source_page: str,
    scope_slug: str,
    metric_label_default: str = "",
) -> list[RankedAreaRow]:
    soup = BeautifulSoup(html, "html.parser")
    scraped_at = _now_iso()
    rows: list[RankedAreaRow] = []
    for index, anchor in enumerate(soup.select("h3.t-MediaList-title a"), start=1):
        href = str(anchor.get("href", "")).strip()
        label = anchor.get_text(" ", strip=True)
        match = re.match(
            r"^(?P<name>.+?)\s+\((?P<count>[\d,]+)(?:\s+(?P<metric>[A-Za-z]+))?\)$",
            label,
        )
        if match:
            location_name = match.group("name").strip()
            transaction_count = int(match.group("count").replace(",", ""))
            metric_label = (match.group("metric") or metric_label_default).strip()
        else:
            location_name = label
            transaction_count = 0
            metric_label = metric_label_default
        rows.append(
            RankedAreaRow(
                run_id=run_id,
                source_page=source_page,
                scope_slug=scope_slug,
                item_rank=index,
                location_name=location_name,
                location_slug=href.rstrip("/").split("/")[-1] if href else "",
                transaction_count=transaction_count,
                metric_label=metric_label,
                scraped_at=scraped_at,
            )
        )
    return rows


def _extract_decimal(text: str) -> str:
    cleaned = text.replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return ""
    try:
        return str(Decimal(match.group(0)))
    except InvalidOperation:
        return ""


def _extract_date(text: str) -> str:
    cleaned = text.replace(",", "").strip()
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _extract_sale_row(cells: list) -> dict[str, str]:
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

    return {
        "location_path": location.get_text(" ", strip=True) if location else "",
        "status_text": status.get_text(" ", strip=True) if status else "",
        "price_aed": _extract_decimal(price_block),
        "capital_gain_text": re.search(r"\(([^)]+)\)", price_block).group(1)
        if "(" in price_block
        else "",
        "price_per_sqft_aed": _extract_decimal(ppsf_match.group(1)) if ppsf_match else "",
        "transaction_size_sqft": _extract_decimal(size_match.group(1)) if size_match else "",
        "bua_sqft": _extract_decimal(bua_matches[1]) if len(bua_matches) > 1 else "",
        "bedrooms_label": bed_match.group(1).strip() if bed_match else "",
        "transaction_date": _extract_date(date_match.group(1)) if date_match else "",
        "seller_type": date_block.splitlines()[-1].strip() if date_block else "",
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
    scraped_at = _now_iso()
    rows: list[SaleTransactionRow] = []
    for index, tr in enumerate(soup.select("#report_table_soldhistory tbody tr"), start=1):
        cells = tr.find_all("td")
        if len(cells) != 4:
            continue
        extracted = _extract_sale_row(cells)
        rows.append(
            SaleTransactionRow(
                run_id=run_id,
                source_page=source_page,
                scope_slug=scope_slug,
                listing_rank=index,
                scraped_at=scraped_at,
                filters_json=json.dumps(filters or {}, sort_keys=True),
                **extracted,
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
    scraped_at = _now_iso()
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
        duration_text = duration_block.splitlines()[-1].strip() if duration_block else ""
        bed_match = re.search(r"(Studio|\d+\s*Beds?|\d+\s*Bed)", specs, re.IGNORECASE)
        rows.append(
            RentalTransactionRow(
                run_id=run_id,
                source_page=source_page,
                scope_slug=scope_slug,
                listing_rank=index,
                location_path=location.get_text(" ", strip=True) if location else "",
                status_text=status.get_text(" ", strip=True) if status else "",
                bedrooms_label=bed_match.group(1).strip() if bed_match else "",
                size_sqft=_extract_decimal(specs),
                annual_rent_aed=_extract_decimal(rent_block),
                rental_yield_pct=_extract_decimal(
                    rent_block.splitlines()[1] if len(rent_block.splitlines()) > 1 else ""
                ),
                lease_start_date=_extract_date(dates[0]) if dates else "",
                lease_end_date=_extract_date(dates[1]) if len(dates) > 1 else "",
                duration_text=duration_text,
                purchase_price_aed=_extract_decimal(purchase_block),
                unit_is_locked=1 if cells[0].select_one(".lock-access") else 0,
                scraped_at=scraped_at,
                filters_json=json.dumps(filters or {}, sort_keys=True),
            )
        )
    return rows


def _write_dataclass_csv(path: Path, rows: list, row_cls) -> Path:
    write_csv(path, list(row_cls.__dataclass_fields__.keys()), (asdict(row) for row in rows))
    return path


def write_locations_csv(path: Path, rows: list[LocationRow]) -> Path:
    return _write_dataclass_csv(path, rows, LocationRow)


def write_developers_csv(path: Path, rows: list[DeveloperRow]) -> Path:
    return _write_dataclass_csv(path, rows, DeveloperRow)


def write_ranked_areas_csv(path: Path, rows: list[RankedAreaRow]) -> Path:
    return _write_dataclass_csv(path, rows, RankedAreaRow)


def write_sales_transactions_csv(path: Path, rows: list[SaleTransactionRow]) -> Path:
    return _write_dataclass_csv(path, rows, SaleTransactionRow)


def write_rental_transactions_csv(path: Path, rows: list[RentalTransactionRow]) -> Path:
    return _write_dataclass_csv(path, rows, RentalTransactionRow)


def download_all(dest_dir: Path, run_id: str) -> list[DownloadResult]:
    locations_path = dest_dir / "locations.csv"
    developers_path = dest_dir / "developers.csv"

    write_locations_csv(locations_path, fetch_location_rows(run_id))
    write_developers_csv(developers_path, fetch_developer_rows(run_id))

    return [
        DownloadResult(canonical_name="locations.csv", local_path=locations_path),
        DownloadResult(canonical_name="developers.csv", local_path=developers_path),
    ]


def capture_root_page_regions(*args, **kwargs):
    raise NotImplementedError(
        "Root-page APEX region capture requires a browser session that has already passed "
        "Cloudflare and a pagination strategy that avoids triggering challenges."
    )


def paginate_sales_transactions(*args, **kwargs):
    raise NotImplementedError(
        "Sales pagination is intentionally stubbed until we settle on a Cloudflare-safe "
        "browser/session strategy."
    )


def paginate_rental_transactions(*args, **kwargs):
    raise NotImplementedError(
        "Rental pagination is intentionally stubbed until we settle on a Cloudflare-safe "
        "browser/session strategy."
    )
