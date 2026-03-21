"""DXBI transaction extraction logic local to the DXBI transactions source."""

from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import Browser, BrowserContext, Playwright, TimeoutError, sync_playwright

from holocron.framework.csv_utils import write_csv
from holocron.framework.models import DownloadResult
from holocron.scrape.browser import browser_context_kwargs, resolve_browser_executable
from holocron.sources.dxbi_transactions.parse import (
    RentalTransactionRow,
    SaleTransactionRow,
    parse_rental_transactions_html,
    parse_sales_transactions_html,
    scope_slug_from_url,
)

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
        executable_path=resolve_browser_executable(chrome_path, source_name="DXBI"),
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    kwargs = browser_context_kwargs(
        user_agent=DEFAULT_USER_AGENT,
        storage_state_path=storage_state_path,
    )
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
    scope_slug = scope_slug_from_url(source_page)

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
                        scope_slug = scope_slug_from_url(url)
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
