"""Bayut extraction logic local to the Bayut source."""

from __future__ import annotations

from dataclasses import asdict, fields
from datetime import date
from pathlib import Path
import re
import time
from typing import Any

from playwright.sync_api import APIRequestContext, Playwright, sync_playwright
from twocaptcha import TwoCaptcha

from holocron.framework.csv_utils import write_csv
from holocron.framework.models import DownloadResult, utc_now_sql
from holocron.scrape.browser import browser_context_kwargs, resolve_browser_executable
from holocron.sources.bayut.parse import (
    RentalTransactionRow,
    SaleTransactionRow,
    format_bayut_range,
    parse_date,
    rental_row,
    sale_row,
)

HUMBUCKER_GENERATE_SCRIPT_URL = "https://www.bayut.com/.humbucker/challenge/js/generate/script"
TRANSACTIONS_API_URL = "https://www.bayut.com/api/transactions"
SALE_TARGET_URL = "https://www.bayut.com/property-market-analysis/transactions/sale/property/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
)
TRANSIENT_BAYUT_STATUSES = (401, 403, 429)
BOOTSTRAP_RETRY_ATTEMPTS = 3
BOOTSTRAP_RETRY_DELAY_SECONDS = 2.0
HCAPTCHA_RENDER_WAIT_MILLISECONDS = 5000
TWOCAPTCHA_TIMEOUT_SECONDS = 180
TWOCAPTCHA_POLL_INTERVAL_SECONDS = 5.0
HCAPTCHA_SITEKEY_PATTERN = re.compile(r'data-sitekey=["\']([^"\']+)["\']', re.IGNORECASE)
HCAPTCHA_IFRAME_SITEKEY_PATTERN = re.compile(r"[?#&]sitekey=([^&#\"']+)", re.IGNORECASE)

_utc_now_sql = utc_now_sql


def _build_target_url() -> str:
    return (
        "https://www.bayut.com/captchaChallenge?externalRedirectPath="
        "https%3A%2F%2Fwww.bayut.com%2Fproperty-market-analysis%2Ftransactions%2Fsale%2Fproperty%2F"
    )


def _wait_for_hb_session(
    browser_context,
    *,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.5,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if any(cookie["name"] == "hb-session-id" for cookie in browser_context.cookies()):
            return
        time.sleep(poll_interval_seconds)
    raise RuntimeError("Bayut browser bootstrap did not produce hb-session-id")


def _storage_state_input_path(storage_state_path: str) -> str:
    path = Path(storage_state_path).expanduser()
    if storage_state_path.strip() and path.exists():
        return str(path)
    return ""


def _persist_storage_state(browser_context, storage_state_path: str) -> None:
    path = Path(storage_state_path).expanduser()
    if not storage_state_path.strip():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    browser_context.storage_state(path=str(path))


def _extract_hcaptcha_sitekey(html: str) -> str:
    match = HCAPTCHA_SITEKEY_PATTERN.search(html)
    if match is not None:
        return match.group(1)

    iframe_match = HCAPTCHA_IFRAME_SITEKEY_PATTERN.search(html)
    if iframe_match is not None:
        return iframe_match.group(1)

    raise RuntimeError("Bayut hCaptcha challenge did not expose a sitekey")


def _extract_hcaptcha_sitekey_from_page(page) -> str:
    widget = page.locator("[data-sitekey]").first
    if widget.count() > 0:
        widget_sitekey = widget.get_attribute("data-sitekey", timeout=1000)
        if isinstance(widget_sitekey, str) and widget_sitekey.strip():
            return widget_sitekey

    iframe = page.locator('iframe[src*="hcaptcha"]').first
    if iframe.count() > 0:
        iframe_src = iframe.get_attribute("src", timeout=1000)
        if isinstance(iframe_src, str) and iframe_src.strip():
            iframe_match = HCAPTCHA_IFRAME_SITEKEY_PATTERN.search(iframe_src)
            if iframe_match is not None:
                return iframe_match.group(1)

    return _extract_hcaptcha_sitekey(page.content())


def _is_hcaptcha_challenge_html(html: str) -> bool:
    lower_html = html.lower()
    return (
        ("hcaptcha" in lower_html or "h-captcha" in lower_html)
        and "verify your identity" in lower_html
    )


def _solve_hcaptcha_via_2captcha(
    *,
    api_key: str,
    page_url: str,
    site_key: str,
    timeout_seconds: int,
    poll_interval_seconds: float,
) -> str:
    solver = TwoCaptcha(
        api_key,
        defaultTimeout=timeout_seconds,
        pollingInterval=max(int(poll_interval_seconds), 5),
    )
    try:
        result = solver.hcaptcha(
            sitekey=site_key,
            url=page_url,
            domain="hcaptcha.com",
        )
    except Exception as exc:  # pragma: no cover - library exceptions vary by code path
        raise RuntimeError(f"2captcha hcaptcha solve failed: {exc}") from exc

    token = result.get("code") if isinstance(result, dict) else result
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError(f"2captcha hcaptcha solve returned invalid token payload: {result}")
    return token


def _inject_hcaptcha_token(page, token: str) -> None:
    page.evaluate(
        """(captchaToken) => {
            const ensureResponseField = (name) => {
                let element = document.querySelector(`[name="${name}"]`);
                if (!element) {
                    element = document.createElement("textarea");
                    element.name = name;
                    element.style.display = "none";
                    document.body.appendChild(element);
                }
                element.value = captchaToken;
                element.innerHTML = captchaToken;
                element.dispatchEvent(new Event("input", { bubbles: true }));
                element.dispatchEvent(new Event("change", { bubbles: true }));
            };

            ensureResponseField("h-captcha-response");
            ensureResponseField("g-recaptcha-response");

            const widget = document.querySelector("[data-sitekey]");
            const callbackName = widget?.getAttribute("data-callback");
            if (callbackName && typeof window[callbackName] === "function") {
                window[callbackName](captchaToken);
            }

            const forms = Array.from(document.forms);
            if (forms.length === 1) {
                forms[0].submit();
            }
        }""",
        token,
    )


def _solve_bayut_hcaptcha(
    *,
    page,
    browser_context,
    twocaptcha_api_key: str,
    twocaptcha_timeout_seconds: int,
    twocaptcha_poll_interval_seconds: float,
) -> None:
    html = page.content()
    has_hcaptcha_iframe = page.locator('iframe[src*="hcaptcha"]').count() > 0
    if not _is_hcaptcha_challenge_html(html) and not has_hcaptcha_iframe:
        return
    if not twocaptcha_api_key.strip():
        raise RuntimeError(
            "Bayut presented an hCaptcha challenge but twocaptcha_api_key is not configured"
        )

    token = _solve_hcaptcha_via_2captcha(
        api_key=twocaptcha_api_key,
        page_url=page.url,
        site_key=_extract_hcaptcha_sitekey_from_page(page),
        timeout_seconds=twocaptcha_timeout_seconds,
        poll_interval_seconds=twocaptcha_poll_interval_seconds,
    )
    _inject_hcaptcha_token(page, token)
    _wait_for_hb_session(browser_context, timeout_seconds=twocaptcha_timeout_seconds)


def _bootstrap_api(
    *,
    playwright: Playwright,
    chrome_path: str,
    storage_state_path: str,
    twocaptcha_api_key: str,
    twocaptcha_timeout_seconds: int,
    twocaptcha_poll_interval_seconds: float,
) -> tuple[Any, APIRequestContext]:
    executable_path = resolve_browser_executable(chrome_path, source_name="Bayut")
    browser = playwright.chromium.launch(
        executable_path=executable_path,
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        **browser_context_kwargs(
            user_agent=DEFAULT_USER_AGENT,
            storage_state_path=_storage_state_input_path(storage_state_path),
        )
    )
    if not any(cookie["name"] == "hb-session-id" for cookie in context.cookies()):
        page = context.new_page()
        try:
            page.goto(_build_target_url(), wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(HCAPTCHA_RENDER_WAIT_MILLISECONDS)
            _solve_bayut_hcaptcha(
                page=page,
                browser_context=context,
                twocaptcha_api_key=twocaptcha_api_key,
                twocaptcha_timeout_seconds=twocaptcha_timeout_seconds,
                twocaptcha_poll_interval_seconds=twocaptcha_poll_interval_seconds,
            )
            if not any(cookie["name"] == "hb-session-id" for cookie in context.cookies()):
                page.add_script_tag(url=HUMBUCKER_GENERATE_SCRIPT_URL)
            _wait_for_hb_session(context)
            _persist_storage_state(context, storage_state_path)
        except RuntimeError:
            browser.close()
            raise
        finally:
            page.close()

    api = playwright.request.new_context(
        storage_state=context.storage_state(),
        user_agent=DEFAULT_USER_AGENT,
        extra_http_headers={
            "accept": "application/json",
            "content-type": "application/json",
            "origin": "https://www.bayut.com",
            "referer": SALE_TARGET_URL,
        },
    )
    return browser, api


def _fetch_transactions_page(
    api: APIRequestContext,
    *,
    purpose: str,
    page: int,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    response = api.post(
        TRANSACTIONS_API_URL,
        data={
            "purpose": purpose,
            "page": page,
            "timeSinceCreation": format_bayut_range(start_date, end_date),
            "v": "20",
        },
    )
    if response.status != 200:
        raise RuntimeError(
            f"Bayut transactions request failed for {purpose} page={page}: {response.status}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected Bayut payload type for {purpose} page={page}")
    return payload


def _is_retryable_bayut_error(exc: Exception) -> bool:
    if not isinstance(exc, RuntimeError):
        return False
    message = str(exc)
    return any(f": {status}" in message for status in TRANSIENT_BAYUT_STATUSES)


def _fetch_all_hits(
    api: APIRequestContext,
    *,
    purpose: str,
    start_date: date,
    end_date: date,
    max_pages: int | None,
) -> list[tuple[int, dict[str, Any]]]:
    first_page = _fetch_transactions_page(
        api,
        purpose=purpose,
        page=1,
        start_date=start_date,
        end_date=end_date,
    )
    total_pages = int(first_page.get("nbPages") or 0)
    if total_pages <= 0:
        return []
    capped_pages = min(total_pages, max_pages) if max_pages else total_pages
    results: list[tuple[int, dict[str, Any]]] = [(1, first_page)]
    if capped_pages == 1:
        return results

    for page_number in range(2, capped_pages + 1):
        results.append(
            (
                page_number,
                _fetch_transactions_page(
                    api,
                    purpose=purpose,
                    page=page_number,
                    start_date=start_date,
                    end_date=end_date,
                ),
            )
        )
    results.sort(key=lambda item: item[0])
    return results


def _fieldnames(row_type: type[Any]) -> list[str]:
    return [field.name for field in fields(row_type)]


def _write_rows(path: Path, *, fieldnames: list[str], rows: list[Any]) -> None:
    write_csv(path, fieldnames=fieldnames, rows=[asdict(row) for row in rows])


def _download_payloads(
    *,
    playwright: Playwright,
    chrome_path: str,
    storage_state_path: str,
    twocaptcha_api_key: str,
    twocaptcha_timeout_seconds: int,
    twocaptcha_poll_interval_seconds: float,
    parsed_start: date,
    parsed_end: date,
    max_pages: int | None,
) -> tuple[list[tuple[int, dict[str, Any]]], list[tuple[int, dict[str, Any]]]]:
    last_error: Exception | None = None
    for attempt in range(1, BOOTSTRAP_RETRY_ATTEMPTS + 1):
        browser, api = _bootstrap_api(
            playwright=playwright,
            chrome_path=chrome_path,
            storage_state_path=storage_state_path,
            twocaptcha_api_key=twocaptcha_api_key,
            twocaptcha_timeout_seconds=twocaptcha_timeout_seconds,
            twocaptcha_poll_interval_seconds=twocaptcha_poll_interval_seconds,
        )
        try:
            sale_pages = _fetch_all_hits(
                api,
                purpose="for-sale",
                start_date=parsed_start,
                end_date=parsed_end,
                max_pages=max_pages,
            )
            rent_pages = _fetch_all_hits(
                api,
                purpose="for-rent",
                start_date=parsed_start,
                end_date=parsed_end,
                max_pages=max_pages,
            )
            return sale_pages, rent_pages
        except Exception as exc:
            last_error = exc
            if attempt >= BOOTSTRAP_RETRY_ATTEMPTS or not _is_retryable_bayut_error(exc):
                raise
            time.sleep(BOOTSTRAP_RETRY_DELAY_SECONDS * attempt)
        finally:
            api.dispose()
            browser.close()

    if last_error is not None:
        raise RuntimeError(
            "Bayut transactions bootstrap exhausted retries without a successful API session"
        ) from last_error
    raise RuntimeError("Bayut transactions bootstrap exhausted retries without an error")


def download_all(
    *,
    dest_dir: Path,
    run_id: str,
    start_date: str,
    end_date: str,
    max_pages: int | None = None,
    chrome_path: str = "",
    storage_state_path: str = "",
    twocaptcha_api_key: str = "",
    twocaptcha_timeout_seconds: int = TWOCAPTCHA_TIMEOUT_SECONDS,
    twocaptcha_poll_interval_seconds: float = TWOCAPTCHA_POLL_INTERVAL_SECONDS,
) -> list[DownloadResult]:
    parsed_start = parse_date(start_date)
    parsed_end = parse_date(end_date)
    if parsed_start > parsed_end:
        raise ValueError(f"Bayut start_date {start_date} is after end_date {end_date}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    scraped_at = _utc_now_sql()

    with sync_playwright() as playwright:
        sale_pages, rent_pages = _download_payloads(
            playwright=playwright,
            chrome_path=chrome_path,
            storage_state_path=storage_state_path,
            twocaptcha_api_key=twocaptcha_api_key,
            twocaptcha_timeout_seconds=twocaptcha_timeout_seconds,
            twocaptcha_poll_interval_seconds=twocaptcha_poll_interval_seconds,
            parsed_start=parsed_start,
            parsed_end=parsed_end,
            max_pages=max_pages,
        )

    sale_rows: list[SaleTransactionRow] = []
    for page_number, payload in sale_pages:
        for hit in payload.get("hits", []):
            sale_rows.append(
                sale_row(
                    release_id=run_id,
                    scraped_at=scraped_at,
                    start_date=parsed_start,
                    end_date=parsed_end,
                    page=page_number,
                    hit=hit,
                )
            )

    rental_rows: list[RentalTransactionRow] = []
    for page_number, payload in rent_pages:
        for hit in payload.get("hits", []):
            rental_rows.append(
                rental_row(
                    release_id=run_id,
                    scraped_at=scraped_at,
                    start_date=parsed_start,
                    end_date=parsed_end,
                    page=page_number,
                    hit=hit,
                )
            )

    results: list[DownloadResult] = []
    sale_path = dest_dir / "sales.csv"
    _write_rows(sale_path, fieldnames=_fieldnames(SaleTransactionRow), rows=sale_rows)
    results.append(DownloadResult(canonical_name="sales.csv", local_path=sale_path))

    rental_path = dest_dir / "rentals.csv"
    _write_rows(rental_path, fieldnames=_fieldnames(RentalTransactionRow), rows=rental_rows)
    results.append(DownloadResult(canonical_name="rentals.csv", local_path=rental_path))
    return results
