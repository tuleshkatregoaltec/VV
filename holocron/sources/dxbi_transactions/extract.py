"""DXBI transaction extraction logic local to the DXBI transactions source."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import Browser, BrowserContext, Playwright, TimeoutError, sync_playwright

from holocron.framework.csv_utils import write_csv
from holocron.framework.models import DownloadResult, utc_now_sql

DXBI_BASE_URL = "https://dxbinteract.com/"
SALE_TABLE_SELECTOR = "#report_table_soldhistory"
RENTAL_TABLE_SELECTOR = "#report_table_rentHistory"
_PAGINATE_LINK_PATTERN = re.compile(
    r"apex\.widget\.report\.paginate\('(?P<region_id>[^']+)',\s*'(?P<checksum>[^']+)',\s*\{"
    r"min:(?P<min>\d+),max:(?P<max>\d+),fetched:(?P<fetched>\d+)\}\);"
)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
)
BROWSER_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
)


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


def _resolve_browser_executable(chrome_path: str) -> str | None:
    candidate = chrome_path.strip()
    if candidate:
        resolved = shutil.which(candidate) if "/" not in candidate else candidate
        if resolved and Path(resolved).exists():
            return resolved
        raise FileNotFoundError(f"DXBI browser executable not found: {chrome_path}")

    for name in BROWSER_CANDIDATES:
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


def _normalized_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _scope_slug_from_url(url: str) -> str:
    path = url.split("?", 1)[0].rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


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


def _transaction_key(*parts: object) -> str:
    payload = "|".join(str(part).strip() for part in parts)
    return hashlib.sha1(payload.encode("utf-8"), usedforsecurity=False).hexdigest()


def _extract_sale_row(cells: list) -> dict[str, str | int]:
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
    date_lines = _normalized_lines(date_block)

    return {
        "location_path": location.get_text(" ", strip=True) if location else "",
        "status_text": status.get_text(" ", strip=True) if status else "",
        "price_aed": _extract_decimal(price_block),
        "capital_gain_text": gain_match.group(1).strip() if gain_match else "",
        "price_per_sqft_aed": _extract_decimal(ppsf_match.group(1)) if ppsf_match else "",
        "transaction_size_sqft": _extract_decimal(size_match.group(1)) if size_match else "",
        "bua_sqft": _extract_decimal(bua_matches[1]) if len(bua_matches) > 1 else "",
        "bedrooms_label": bed_match.group(1).strip() if bed_match else "",
        "transaction_date": _extract_date(date_match.group(1)) if date_match else "",
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
        extracted = _extract_sale_row(cells)
        rows.append(
            SaleTransactionRow(
                run_id=run_id,
                transaction_key=_transaction_key(
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
        duration_lines = _normalized_lines(duration_block)
        rent_lines = _normalized_lines(rent_block)
        bed_match = re.search(r"(Studio|\d+\s*Beds?|\d+\s*Bed)", specs, re.IGNORECASE)

        location_path = location.get_text(" ", strip=True) if location else ""
        annual_rent_aed = _extract_decimal(rent_block)
        lease_start_date = _extract_date(dates[0]) if dates else ""
        lease_end_date = _extract_date(dates[1]) if len(dates) > 1 else ""

        rows.append(
            RentalTransactionRow(
                run_id=run_id,
                transaction_key=_transaction_key(
                    source_page,
                    location_path,
                    lease_start_date,
                    annual_rent_aed,
                    _extract_decimal(specs),
                    _extract_decimal(purchase_block),
                ),
                source_page=source_page,
                scope_slug=scope_slug,
                listing_rank=index,
                location_path=location_path,
                status_text=status.get_text(" ", strip=True) if status else "",
                bedrooms_label=bed_match.group(1).strip() if bed_match else "",
                size_sqft=_extract_decimal(specs),
                annual_rent_aed=annual_rent_aed,
                rental_yield_pct=_extract_decimal(rent_lines[1]) if len(rent_lines) > 1 else "",
                lease_start_date=lease_start_date,
                lease_end_date=lease_end_date,
                duration_text=duration_lines[-1] if duration_lines else "",
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


def write_sales_transactions_csv(path: Path, rows: list[SaleTransactionRow]) -> Path:
    return _write_dataclass_csv(path, rows, SaleTransactionRow)


def write_rental_transactions_csv(path: Path, rows: list[RentalTransactionRow]) -> Path:
    return _write_dataclass_csv(path, rows, RentalTransactionRow)


def _load_page_urls(*, page_urls_text: str, page_urls_file: str) -> list[str]:
    urls: list[str] = []
    for raw_line in page_urls_text.splitlines():
        line = raw_line.strip()
        if line:
            urls.append(line)
    if page_urls_file.strip():
        for raw_line in Path(page_urls_file).read_text().splitlines():
            line = raw_line.strip()
            if line:
                urls.append(line)
    if not urls:
        urls = [DXBI_BASE_URL]

    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped


def _new_context(
    playwright: Playwright,
    *,
    chrome_path: str,
    storage_state_path: str,
) -> tuple[Browser, BrowserContext]:
    browser = playwright.chromium.launch(
        executable_path=_resolve_browser_executable(chrome_path),
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    kwargs = {
        "user_agent": DEFAULT_USER_AGENT,
        "viewport": {"width": 1440, "height": 900},
        "locale": "en-US",
        "timezone_id": "UTC",
    }
    if storage_state_path.strip():
        kwargs["storage_state"] = storage_state_path
    context = browser.new_context(**kwargs)
    return browser, context


def _fetch_page_html(
    *,
    context: BrowserContext,
    url: str,
) -> str:
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=120000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except TimeoutError:
            pass
        try:
            page.wait_for_selector(
                "#report_table_soldhistory, #report_table_rentHistory", timeout=15000
            )
        except TimeoutError:
            pass
        return page.content()
    finally:
        page.close()


def _extract_pagination_calls(html: str, *, table_index: int) -> list[dict[str, object]]:
    soup = BeautifulSoup(html, "html.parser")
    pagination_nodes = soup.select(".t-Report-paginationText")
    if table_index >= len(pagination_nodes):
        return []

    calls: list[dict[str, object]] = []
    seen_mins: set[int] = set()
    for anchor in pagination_nodes[table_index].select("a[href]"):
        href = str(anchor.get("href", "")).strip()
        match = _PAGINATE_LINK_PATTERN.search(href)
        if not match:
            continue
        min_value = int(match.group("min"))
        if min_value in seen_mins:
            continue
        seen_mins.add(min_value)
        calls.append(
            {
                "region_id": match.group("region_id"),
                "checksum": match.group("checksum"),
                "options": {
                    "min": min_value,
                    "max": int(match.group("max")),
                    "fetched": int(match.group("fetched")),
                },
            }
        )
    calls.sort(key=lambda call: int(call["options"]["min"]))  # type: ignore[index]
    return calls


def _paginate_report(
    *,
    page,
    table_selector: str,
    call: dict[str, object],
) -> str:
    tbody = page.locator(f"{table_selector} tbody")
    previous_html = tbody.inner_html()
    page.evaluate(
        """
        ({ regionId, checksum, options }) => {
            apex.widget.report.paginate(regionId, checksum, options);
        }
        """,
        {
            "regionId": call["region_id"],
            "checksum": call["checksum"],
            "options": call["options"],
        },
    )
    try:
        page.wait_for_function(
            """
            ({ selector, previousHtml }) => {
                const node = document.querySelector(selector);
                return !!node && node.innerHTML !== previousHtml;
            }
            """,
            arg={"selector": f"{table_selector} tbody", "previousHtml": previous_html},
            timeout=15000,
        )
    except TimeoutError:
        page.wait_for_timeout(2000)
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except TimeoutError:
        pass
    return page.content()


def _extract_root_page_rows(
    *,
    page,
    run_id: str,
    source_page: str,
) -> tuple[list[SaleTransactionRow], list[RentalTransactionRow]]:
    sales: list[SaleTransactionRow] = []
    rentals: list[RentalTransactionRow] = []
    scope_slug = _scope_slug_from_url(source_page)

    initial_html = page.content()
    sales.extend(
        parse_sales_transactions_html(
            initial_html,
            run_id=run_id,
            source_page=source_page,
            scope_slug=scope_slug,
        )
    )
    rentals.extend(
        parse_rental_transactions_html(
            initial_html,
            run_id=run_id,
            source_page=source_page,
            scope_slug=scope_slug,
        )
    )

    for call in _extract_pagination_calls(initial_html, table_index=0):
        html = _paginate_report(page=page, table_selector=SALE_TABLE_SELECTOR, call=call)
        sales.extend(
            parse_sales_transactions_html(
                html,
                run_id=run_id,
                source_page=source_page,
                scope_slug=scope_slug,
            )
        )

    page.goto(source_page, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(4000)
    reset_html = page.content()
    for call in _extract_pagination_calls(reset_html, table_index=1):
        html = _paginate_report(page=page, table_selector=RENTAL_TABLE_SELECTOR, call=call)
        rentals.extend(
            parse_rental_transactions_html(
                html,
                run_id=run_id,
                source_page=source_page,
                scope_slug=scope_slug,
            )
        )

    return sales, rentals


def _bootstrap_clearance(
    *,
    context: BrowserContext,
) -> None:
    page = context.new_page()
    try:
        page.goto(DXBI_BASE_URL, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(8000)
        cookies = {cookie["name"] for cookie in context.cookies()}
        if "cf_clearance" not in cookies:
            raise RuntimeError(
                "DXBI browser bootstrap did not obtain cf_clearance. "
                "Set chrome_path to a local Chrome/Chromium binary that clears Cloudflare, "
                "or provide a valid storage_state_path."
            )
    finally:
        page.close()


def download_all(
    *,
    dest_dir: Path,
    run_id: str,
    page_urls_text: str,
    page_urls_file: str,
    storage_state_path: str,
    chrome_path: str,
    max_pages: int | None,
    context,
) -> list[DownloadResult]:
    urls = _load_page_urls(page_urls_text=page_urls_text, page_urls_file=page_urls_file)
    if not urls:
        raise ValueError(
            "dxbi_transactions requires at least one DXBI page URL via page_urls or page_urls_file"
        )
    if max_pages is not None:
        urls = urls[: max(max_pages, 0)]

    if storage_state_path.strip() and not Path(storage_state_path).exists():
        raise FileNotFoundError(f"DXBI storage state not found: {storage_state_path}")

    sale_rows: list[SaleTransactionRow] = []
    rental_rows: list[RentalTransactionRow] = []

    with sync_playwright() as playwright:
        browser, browser_context = _new_context(
            playwright,
            chrome_path=chrome_path,
            storage_state_path=storage_state_path,
        )
        try:
            if not storage_state_path.strip():
                _bootstrap_clearance(context=browser_context)
            for index, url in enumerate(urls, start=1):
                page = browser_context.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=120000)
                    page.wait_for_timeout(4000)
                    html = page.content()
                    if "Just a moment..." in html:
                        raise RuntimeError(
                            "DXBI returned a Cloudflare challenge page. Supply a valid "
                            "storage_state_path captured after solving the challenge in a browser."
                        )
                    if url.rstrip("/") == DXBI_BASE_URL.rstrip("/"):
                        page_sales, page_rentals = _extract_root_page_rows(
                            page=page,
                            run_id=run_id,
                            source_page=url,
                        )
                    else:
                        scope_slug = _scope_slug_from_url(url)
                        page_sales = parse_sales_transactions_html(
                            html,
                            run_id=run_id,
                            source_page=url,
                            scope_slug=scope_slug,
                        )
                        page_rentals = parse_rental_transactions_html(
                            html,
                            run_id=run_id,
                            source_page=url,
                            scope_slug=scope_slug,
                        )
                finally:
                    page.close()
                sale_rows.extend(page_sales)
                rental_rows.extend(page_rentals)
                if context is not None:
                    context.log.info(
                        "dxbi_transactions: visited "
                        f"{index}/{len(urls)} pages; +{len(page_sales)} sales, "
                        f"+{len(page_rentals)} rentals from {url}"
                    )
        finally:
            browser.close()

    sales_path = dest_dir / "sales.csv"
    rentals_path = dest_dir / "rentals.csv"
    write_sales_transactions_csv(sales_path, sale_rows)
    write_rental_transactions_csv(rentals_path, rental_rows)
    return [
        DownloadResult(canonical_name="sales.csv", local_path=sales_path),
        DownloadResult(canonical_name="rentals.csv", local_path=rentals_path),
    ]
