from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import BrowserContext, Page, Playwright, TimeoutError, sync_playwright
from twocaptcha import TwoCaptcha

from holocron.contracts import RawFile, RawRelease
from holocron.platform.execution import build_raw_file, build_raw_release, new_run_id, utc_now
from holocron.platform.metadata import safe_config_metadata
from holocron.sources.dxbi.source import (
    DXBI_BASE_URL,
    DateSlice,
    DxbiConfig,
    SOURCE,
    build_date_slices,
)

SALE_REGION_SELECTOR = "#soldhistory"
RENTAL_REGION_SELECTOR = "#rentHistory"
SALE_TABLE_SELECTOR = "#report_table_soldhistory"
RENTAL_TABLE_SELECTOR = "#report_table_rentHistory"
PAGINATION_SELECTOR = ".t-Report-paginationText"
PAGINATION_CALL_PATTERN = re.compile(
    r"apex\.widget\.report\.paginate\('(?P<region_id>[^']+)',\s*'(?P<checksum>[^']+)',\s*\{"
    r"min:(?P<min>\d+),max:(?P<max>\d+),fetched:(?P<fetched>\d+)\}\);"
)


def load_page_urls(
    *, page_urls_text: str, page_urls_file: str, max_pages: int | None = None
) -> list[str]:
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
        urls.append(DXBI_BASE_URL)

    deduped = list(dict.fromkeys(urls))
    if max_pages is not None:
        return deduped[:max_pages]
    return deduped


def extract_release(
    output_dir: str | Path,
    *,
    config: DxbiConfig | dict,
    now: datetime | None = None,
    page_scraper: Callable[..., list[dict]] | None = None,
    playwright_factory: Callable[[], object] = sync_playwright,
) -> RawRelease:
    parsed_config = config if isinstance(config, DxbiConfig) else DxbiConfig.model_validate(config)
    if (
        parsed_config.storage_state_path.strip()
        and not Path(parsed_config.storage_state_path).exists()
    ):
        raise FileNotFoundError(f"DXBI storage state not found: {parsed_config.storage_state_path}")
    current_time = now or utc_now()
    run_id = new_run_id(current_time)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    slices = build_date_slices(parsed_config, today=current_time.date())
    urls = load_page_urls(
        page_urls_text=parsed_config.page_urls,
        page_urls_file=parsed_config.page_urls_file,
        max_pages=parsed_config.max_pages,
    )

    files = (
        _extract_with_scraper(
            output_path=output_path,
            run_id=run_id,
            current_time=current_time,
            urls=urls,
            date_slices=slices,
            page_scraper=page_scraper,
            config=parsed_config,
        )
        if page_scraper is not None
        else _extract_with_playwright(
            output_path=output_path,
            run_id=run_id,
            current_time=current_time,
            urls=urls,
            date_slices=slices,
            config=parsed_config,
            playwright_factory=playwright_factory,
        )
    )
    return build_raw_release(
        source=SOURCE,
        files=files,
        run_id=run_id,
        now=current_time,
        metadata={"config": safe_config_metadata(parsed_config), "slice_count": len(slices)},
    )


def _collect_all_slices(
    *,
    output_path: Path,
    urls: list[str],
    date_slices: Iterable[DateSlice],
    collect_rows: Callable[[str, DateSlice], list[dict]],
) -> tuple[RawFile, ...]:
    files = []
    for date_slice in date_slices:
        rows: list[dict] = []
        for url in urls:
            rows.extend(collect_rows(url, date_slice))
        files.append(_write_slice_file(output_path=output_path, date_slice=date_slice, rows=rows))
    return tuple(files)


def _extract_with_scraper(
    *,
    output_path: Path,
    run_id: str,
    current_time: datetime,
    urls: list[str],
    date_slices: Iterable[DateSlice],
    page_scraper: Callable[..., list[dict]],
    config: DxbiConfig,
) -> tuple[RawFile, ...]:
    scraped_at = current_time.isoformat()

    def collect(url: str, date_slice: DateSlice) -> list[dict]:
        return page_scraper(
            url=url, date_slice=date_slice, run_id=run_id, config=config, scraped_at=scraped_at
        )

    return _collect_all_slices(
        output_path=output_path, urls=urls, date_slices=date_slices, collect_rows=collect
    )


def _extract_with_playwright(
    *,
    output_path: Path,
    run_id: str,
    current_time: datetime,
    urls: list[str],
    date_slices: Iterable[DateSlice],
    config: DxbiConfig,
    playwright_factory: Callable[[], object],
) -> tuple[RawFile, ...]:
    scraped_at = current_time.isoformat()
    with playwright_factory() as playwright:
        browser_context = _new_context(playwright=playwright, config=config)
        try:

            def collect(url: str, date_slice: DateSlice) -> list[dict]:
                return _scrape_url_slice(
                    context=browser_context,
                    url=url,
                    date_slice=date_slice,
                    run_id=run_id,
                    scraped_at=scraped_at,
                    config=config,
                )

            return _collect_all_slices(
                output_path=output_path, urls=urls, date_slices=date_slices, collect_rows=collect
            )
        finally:
            browser_context.browser.close()


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
)
DEFAULT_CHROME_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
)


def _resolve_browser_executable(chrome_path: str) -> str | None:
    candidate = chrome_path.strip()
    if candidate:
        resolved = shutil.which(candidate) if "/" not in candidate else candidate
        if resolved and Path(resolved).exists():
            return resolved
        raise FileNotFoundError(f"DXBI browser executable not found: {chrome_path}")

    for name in DEFAULT_CHROME_CANDIDATES:
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


def _raise_if_blocked_ajax(*, statuses: Iterable[int], url: str) -> None:
    blocked = sorted({status for status in statuses if status >= 400})
    if not blocked:
        return
    statuses_text = ", ".join(str(status) for status in blocked)
    raise RuntimeError(
        "DXBI APEX requests were blocked while scraping "
        f"{url} (HTTP {statuses_text}). "
        "Use a real Chrome executable via chrome_path (or ensure one is installed), "
        "or provide a storage_state_path from a cleared browser session."
    )


def _new_context(*, playwright: Playwright, config: DxbiConfig) -> BrowserContext:
    launch_kwargs: dict = {
        "headless": config.headless,
        "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    }
    executable_path = _resolve_browser_executable(config.chrome_path)
    if executable_path:
        launch_kwargs["executable_path"] = executable_path
    browser = playwright.chromium.launch(**launch_kwargs)
    context_kwargs: dict = {"user_agent": _USER_AGENT}
    if config.storage_state_path.strip():
        context_kwargs["storage_state"] = config.storage_state_path
    return browser.new_context(**context_kwargs)


def _scrape_url_slice(
    *,
    context: BrowserContext,
    url: str,
    date_slice: DateSlice,
    run_id: str,
    scraped_at: str,
    config: DxbiConfig,
) -> list[dict]:
    page = context.new_page()
    blocked_ajax_statuses: list[int] = []
    ajax_request_count = 0

    def handle_response(response) -> None:
        nonlocal ajax_request_count
        if "wwv_flow.ajax" not in response.url:
            return
        ajax_request_count += 1
        if response.status >= 400:
            blocked_ajax_statuses.append(response.status)

    page.on("response", handle_response)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=120000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except TimeoutError:
            page.wait_for_timeout(3000)
        _maybe_solve_captcha(page=page, api_key=config.twocaptcha_api_key)
        _maybe_accept_terms(page)
        _apply_date_slice(page=page, date_slice=date_slice)
        _maybe_solve_captcha(page=page, api_key=config.twocaptcha_api_key)
        try:
            page.wait_for_selector(f"{SALE_TABLE_SELECTOR} tbody tr", timeout=15000)
        except TimeoutError:
            pass
        rows = []
        rows.extend(
            _collect_table_pages(
                page=page,
                url=url,
                run_id=run_id,
                scraped_at=scraped_at,
                date_slice=date_slice,
                table_selector=SALE_TABLE_SELECTOR,
                table_name="sales",
                region_selector=SALE_REGION_SELECTOR,
            )
        )
        rows.extend(
            _collect_table_pages(
                page=page,
                url=url,
                run_id=run_id,
                scraped_at=scraped_at,
                date_slice=date_slice,
                table_selector=RENTAL_TABLE_SELECTOR,
                table_name="rentals",
                region_selector=RENTAL_REGION_SELECTOR,
            )
        )
        _raise_if_blocked_ajax(statuses=blocked_ajax_statuses, url=url)
        if url.rstrip("/") == DXBI_BASE_URL.rstrip("/") and ajax_request_count == 0:
            raise RuntimeError(
                "DXBI root page did not emit any APEX ajax responses while scraping. "
                "The session may be blocked or page behavior has changed."
            )
        if url.rstrip("/") == DXBI_BASE_URL.rstrip("/") and not rows:
            raise RuntimeError(
                "DXBI root page returned zero rows after date refresh; this usually means "
                "Cloudflare blocked report ajax calls or the page contract changed."
            )
        return rows
    finally:
        page.close()


def _collect_table_pages(
    *,
    page: Page,
    url: str,
    run_id: str,
    scraped_at: str,
    date_slice: DateSlice,
    table_selector: str,
    table_name: str,
    region_selector: str,
) -> list[dict]:
    rows = _extract_table_rows(
        page=page,
        table_selector=table_selector,
        table_name=table_name,
        page_number=1,
        url=url,
        run_id=run_id,
        scraped_at=scraped_at,
        date_slice=date_slice,
    )
    for page_number, call in enumerate(
        _extract_pagination_calls(page=page, region_selector=region_selector), start=2
    ):
        _paginate_report(page=page, table_selector=table_selector, call=call)
        rows.extend(
            _extract_table_rows(
                page=page,
                table_selector=table_selector,
                table_name=table_name,
                page_number=page_number,
                url=url,
                run_id=run_id,
                scraped_at=scraped_at,
                date_slice=date_slice,
            )
        )
    return rows


def _extract_table_rows(
    *,
    page: Page,
    table_selector: str,
    table_name: str,
    page_number: int,
    url: str,
    run_id: str,
    scraped_at: str,
    date_slice: DateSlice,
) -> list[dict]:
    # Extract all cell text in one JS call to avoid per-element locator timeouts
    # when APEX re-renders the table mid-iteration.
    raw_rows: list[list[str]] = page.evaluate(
        """
        selector => {
            const tbody = document.querySelector(selector + ' tbody');
            if (!tbody) return [];
            return Array.from(tbody.querySelectorAll('tr')).map(tr =>
                Array.from(tr.querySelectorAll('td')).map(td => td.innerText ?? '')
            );
        }
        """,
        table_selector,
    )
    rows = []
    for row_index, cell_values in enumerate(raw_rows):
        normalized = [_normalize_cell_text(v) for v in cell_values]
        if not any(normalized):
            continue
        rows.append(
            {
                "table": table_name,
                "cells": normalized,
                "_run_id": run_id,
                "_scraped_at": scraped_at,
                "_slice_start_date": date_slice.start_date.isoformat(),
                "_slice_end_date": date_slice.end_date.isoformat(),
                "_source_url": url,
                "_page_number": page_number,
                "_row_number": row_index + 1,
            }
        )
    return rows


def _normalize_cell_text(value: str) -> str:
    return " ".join(part.strip() for part in value.splitlines() if part.strip())


def _apply_date_slice(*, page: Page, date_slice: DateSlice) -> None:
    start_str = date_slice.start_date.isoformat()
    end_str = date_slice.end_date.isoformat()
    result = page.evaluate(
        """
        ([startDate, endDate]) => {
            if (typeof window.$s !== 'function') return { status: 'no-$s' };
            if (!document.querySelector('#P74_START_DATE') || !document.querySelector('#P74_END_DATE')) {
                return { status: 'missing-date-items' };
            }

            const reportHtml = (regionSelector, tableSelector) => {
                const catchNode = document.querySelector(`${regionSelector} [id^="report_"][id$="_catch"]`);
                const bodyNode = document.querySelector(`${tableSelector} tbody`);
                return [
                    catchNode ? catchNode.innerHTML : '',
                    bodyNode ? bodyNode.innerHTML : '',
                ].join('\\n');
            };
            const token = `${startDate}:${endDate}:${Date.now()}`;
            const state = {
                token,
                soldBefore: reportHtml('#soldhistory', '#report_table_soldhistory'),
                rentBefore: reportHtml('#rentHistory', '#report_table_rentHistory'),
                soldPresent: !!document.querySelector('#soldhistory'),
                rentPresent: !!document.querySelector('#rentHistory'),
                soldDone: false,
                rentDone: false,
            };
            window.__holocronDxbiRefresh = state;

            const jq = window.apex?.jQuery || window.jQuery;
            if (typeof jq === 'function') {
                if (state.soldPresent) {
                    jq('#soldhistory').one('apexafterrefresh', () => { state.soldDone = true; });
                }
                if (state.rentPresent) {
                    jq('#rentHistory').one('apexafterrefresh', () => { state.rentDone = true; });
                }
            }

            $s('P74_START_DATE', startDate);
            $s('P74_END_DATE', endDate);

            try {
                if (window.apex?.region) {
                    apex.region('soldhistory').refresh();
                    apex.region('rentHistory').refresh();
                } else if (window.apex?.da?.refresh) {
                    apex.da.refresh('.refresh');
                } else {
                    return { status: 'no-refresh-api' };
                }
            } catch (error) {
                return { status: 'refresh-error', detail: String(error) };
            }

            return { status: 'ok', token };
        }
        """,
        [start_str, end_str],
    )
    if result.get("status") != "ok":
        detail = result.get("detail") or result.get("status")
        raise RuntimeError(f"DXBI date refresh not ready: {detail}")

    try:
        page.wait_for_function(
            """
            ({ token }) => {
                const state = window.__holocronDxbiRefresh;
                if (!state || state.token !== token) return false;

                const reportHtml = (regionSelector, tableSelector) => {
                    const catchNode = document.querySelector(`${regionSelector} [id^="report_"][id$="_catch"]`);
                    const bodyNode = document.querySelector(`${tableSelector} tbody`);
                    return [
                        catchNode ? catchNode.innerHTML : '',
                        bodyNode ? bodyNode.innerHTML : '',
                    ].join('\\n');
                };
                const soldChanged = reportHtml('#soldhistory', '#report_table_soldhistory') !== state.soldBefore;
                const rentChanged = reportHtml('#rentHistory', '#report_table_rentHistory') !== state.rentBefore;
                const soldReady = !state.soldPresent || state.soldDone || soldChanged;
                const rentReady = !state.rentPresent || state.rentDone || rentChanged;
                return soldReady && rentReady;
            }
            """,
            arg={
                "token": result.get("token", ""),
            },
            timeout=20000,
        )
    except TimeoutError:
        page.wait_for_timeout(3000)


def _extract_pagination_calls(*, page: Page, region_selector: str) -> list[dict]:
    links = page.locator(f"{region_selector} {PAGINATION_SELECTOR} a[href]")
    calls = []
    seen: set[int] = set()
    for link_index in range(links.count()):
        href = links.nth(link_index).get_attribute("href") or ""
        match = PAGINATION_CALL_PATTERN.search(href)
        if match is None:
            continue
        min_value = int(match.group("min"))
        if min_value in seen:
            continue
        seen.add(min_value)
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
    return sorted(calls, key=lambda call: call["options"]["min"])


def _paginate_report(*, page: Page, table_selector: str, call: dict) -> None:
    previous_html = page.evaluate(
        f"document.querySelector('{table_selector} tbody')?.innerHTML ?? ''"
    )
    page.evaluate(
        """
        ({ regionId, checksum, options }) => {
            apex.widget.report.paginate(regionId, checksum, options);
        }
        """,
        {"regionId": call["region_id"], "checksum": call["checksum"], "options": call["options"]},
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


def _maybe_solve_captcha(*, page: Page, api_key: str) -> None:
    challenge = _detect_captcha(page)
    if challenge is None:
        return
    resolved_api_key = api_key or os.environ.get("TWOCAPTCHA_API_KEY", "").strip()
    resolved_api_key = resolved_api_key or os.environ.get("CAPTCHA_API_KEY", "").strip()
    if not resolved_api_key:
        raise RuntimeError("DXBI captcha detected but twocaptcha_api_key is not configured")
    solver = TwoCaptcha(resolved_api_key)
    if challenge["kind"] == "turnstile":
        result = solver.turnstile(sitekey=challenge["sitekey"], url=page.url)
    else:
        result = solver.hcaptcha(sitekey=challenge["sitekey"], url=page.url)
    token = result["code"]
    _inject_captcha_token(page=page, token=token)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except TimeoutError:
        page.wait_for_timeout(3000)


def _maybe_accept_terms(page: Page) -> None:
    try:
        checkbox = page.locator(
            "dialog input[type='checkbox'], .a-Dialog input[type='checkbox']"
        ).first
        if checkbox.is_visible(timeout=3000):
            checkbox.check()
            page.locator(
                "dialog button:has-text('Submit'), .a-Dialog button:has-text('Submit')"
            ).first.click()
            page.wait_for_timeout(1000)
    except TimeoutError:
        pass


def _detect_captcha(page: Page) -> dict | None:
    turnstile = page.locator(
        "iframe[src*='challenges.cloudflare.com'], div.cf-turnstile[data-sitekey]"
    )
    if turnstile.count():
        sitekey = _sitekey_from_locator(
            page, "div.cf-turnstile[data-sitekey]"
        ) or _sitekey_from_iframe(turnstile.first.get_attribute("src") or "")
        if sitekey:
            return {"kind": "turnstile", "sitekey": sitekey}
    hcaptcha = page.locator("[data-sitekey], iframe[src*='hcaptcha']")
    if hcaptcha.count():
        sitekey = _sitekey_from_locator(page, "[data-sitekey]") or _sitekey_from_iframe(
            hcaptcha.first.get_attribute("src") or ""
        )
        if sitekey:
            return {"kind": "hcaptcha", "sitekey": sitekey}
    return None


def _sitekey_from_locator(page: Page, selector: str) -> str:
    locator = page.locator(selector)
    if not locator.count():
        return ""
    return locator.first.get_attribute("data-sitekey") or ""


def _sitekey_from_iframe(src: str) -> str:
    if not src:
        return ""
    return parse_qs(urlparse(src).query).get("sitekey", [""])[0]


def _inject_captcha_token(*, page: Page, token: str) -> None:
    page.evaluate(
        """
        value => {
            for (const selector of [
                'textarea[name="h-captcha-response"]',
                'textarea[name="g-recaptcha-response"]',
                'input[name="cf-turnstile-response"]',
                'textarea[name="cf-turnstile-response"]'
            ]) {
                for (const node of document.querySelectorAll(selector)) {
                    node.value = value;
                    node.innerHTML = value;
                    node.dispatchEvent(new Event('input', { bubbles: true }));
                    node.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }
            for (const form of document.forms) {
                const submit = form.querySelector('[type="submit"]');
                if (submit) {
                    submit.click();
                    return;
                }
            }
        }
        """,
        token,
    )


def _write_slice_file(*, output_path: Path, date_slice: DateSlice, rows: list[dict]) -> RawFile:
    path = output_path / f"slice_{date_slice.key}.jsonl"
    hasher = hashlib.sha256()
    size = 0
    with path.open("wb") as handle:
        for row in rows:
            line = (json.dumps(row, sort_keys=True) + "\n").encode()
            handle.write(line)
            hasher.update(line)
            size += len(line)
    return build_raw_file(
        path=path,
        sha256=hasher.hexdigest(),
        size_bytes=size,
        row_count=len(rows),
        content_type="application/x-ndjson",
        metadata={
            "slice_start_date": date_slice.start_date.isoformat(),
            "slice_end_date": date_slice.end_date.isoformat(),
        },
    )
