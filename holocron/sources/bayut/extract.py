"""Bayut extraction logic local to the Bayut source."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import Path
import shutil
import time
from typing import Any

from playwright.sync_api import APIRequestContext, Playwright, sync_playwright

from holocron.framework.csv_utils import write_csv
from holocron.framework.models import DownloadResult, utc_now_sql

HUMBUCKER_GENERATE_SCRIPT_URL = "https://www.bayut.com/.humbucker/challenge/js/generate/script"
TRANSACTIONS_API_URL = "https://www.bayut.com/api/transactions"
SALE_TARGET_URL = "https://www.bayut.com/property-market-analysis/transactions/sale/property/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
)
BROWSER_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
)


@dataclass(frozen=True)
class SaleTransactionRow:
    release_id: str
    scraped_at: str
    window_start_date: str
    window_end_date: str
    purpose: str
    page: int
    transaction_hash_id: str
    transaction_date: str
    transaction_amount: str
    transaction_per_sqm_amount: str
    builtup_area_sqm: str
    plot_area_sqm: str
    balcony_area_sqm: str
    beds: str
    floor: str
    latitude: str
    longitude: str
    bayut_latitude: str
    bayut_longitude: str
    bayut_property_type_id: str
    bayut_leaf_location_id: str
    bayut_leaf_location_name_en: str
    bayut_leaf_location_name_ar: str
    bayut_location_l3_name_en: str
    bayut_location_l3_name_ar: str
    bayut_location_l4_name_en: str
    bayut_location_l4_name_ar: str
    bayut_location_l5_name_en: str
    bayut_location_l5_name_ar: str
    bayut_location_l6_name_en: str
    bayut_location_l6_name_ar: str
    occupancy_status_name: str
    claimed_transaction_status: str
    property_completion_status_sk: str
    sale_market_name: str
    seller_type: str
    transaction_payment_method: str
    unit_number: str
    has_kpi_value: int
    previous_sale_transaction_date: str


@dataclass(frozen=True)
class RentalTransactionRow:
    release_id: str
    scraped_at: str
    window_start_date: str
    window_end_date: str
    purpose: str
    page: int
    transaction_hash_id: str
    transaction_date: str
    contract_start_date: str
    contract_end_date: str
    transaction_amount: str
    contract_monthly_amount: str
    transaction_per_sqm_amount: str
    builtup_area_sqm: str
    plot_area_sqm: str
    balcony_area_sqm: str
    beds: str
    floor: str
    latitude: str
    longitude: str
    bayut_latitude: str
    bayut_longitude: str
    bayut_property_type_id: str
    bayut_leaf_location_id: str
    bayut_leaf_location_name_en: str
    bayut_leaf_location_name_ar: str
    bayut_location_l3_name_en: str
    bayut_location_l3_name_ar: str
    bayut_location_l4_name_en: str
    bayut_location_l4_name_ar: str
    bayut_location_l5_name_en: str
    bayut_location_l5_name_ar: str
    bayut_location_l6_name_en: str
    bayut_location_l6_name_ar: str
    occupancy_status_name: str
    claimed_transaction_status: str
    property_completion_status_sk: str
    rent_contract_duration_months: str
    rent_contract_renewal_status_name: str
    has_kpi_value: int
    previous_sale_transaction_date: str


_utc_now_sql = utc_now_sql


def _format_bayut_range(start_date: date, end_date: date) -> str:
    return f"{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}"


def _parse_date(raw: str) -> date:
    return date.fromisoformat(raw)


def _string(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _bool_int(value: Any) -> int:
    return 1 if bool(value) else 0


def _build_target_url() -> str:
    return (
        "https://www.bayut.com/captchaChallenge?externalRedirectPath="
        "https%3A%2F%2Fwww.bayut.com%2Fproperty-market-analysis%2Ftransactions%2Fsale%2Fproperty%2F"
    )


def _resolve_browser_executable(chrome_path: str) -> str | None:
    candidate = chrome_path.strip()
    if candidate:
        resolved = shutil.which(candidate) if "/" not in candidate else candidate
        if resolved and Path(resolved).exists():
            return resolved
        raise FileNotFoundError(f"Bayut browser executable not found: {chrome_path}")

    for name in BROWSER_CANDIDATES:
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


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


def _bootstrap_api(
    *,
    playwright: Playwright,
    chrome_path: str,
) -> tuple[Any, APIRequestContext]:
    executable_path = _resolve_browser_executable(chrome_path)
    browser = playwright.chromium.launch(
        executable_path=executable_path,
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        user_agent=DEFAULT_USER_AGENT,
        viewport={"width": 1440, "height": 900},
        locale="en-US",
        timezone_id="UTC",
    )
    page = context.new_page()
    page.goto(_build_target_url(), wait_until="domcontentloaded", timeout=120000)
    page.add_script_tag(url=HUMBUCKER_GENERATE_SCRIPT_URL)
    try:
        _wait_for_hb_session(context)
    except RuntimeError:
        browser.close()
        raise

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
            "timeSinceCreation": _format_bayut_range(start_date, end_date),
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


def _sale_row(
    *,
    release_id: str,
    scraped_at: str,
    start_date: date,
    end_date: date,
    page: int,
    hit: dict[str, Any],
) -> SaleTransactionRow:
    return SaleTransactionRow(
        release_id=release_id,
        scraped_at=scraped_at,
        window_start_date=start_date.isoformat(),
        window_end_date=end_date.isoformat(),
        purpose="for-sale",
        page=page,
        transaction_hash_id=_string(hit.get("transaction_hash_id")),
        transaction_date=_string(hit.get("date_transaction_nk")),
        transaction_amount=_string(hit.get("transaction_amount")),
        transaction_per_sqm_amount=_string(hit.get("transaction_per_sqm_amount")),
        builtup_area_sqm=_string(hit.get("builtup_area_sqm")),
        plot_area_sqm=_string(hit.get("plot_area_sqm")),
        balcony_area_sqm=_string(hit.get("balcony_area_sqm")),
        beds=_string(hit.get("beds")),
        floor=_string(hit.get("floor")),
        latitude=_string(hit.get("latitude")),
        longitude=_string(hit.get("longitude")),
        bayut_latitude=_string(hit.get("bayut_latitude")),
        bayut_longitude=_string(hit.get("bayut_longitude")),
        bayut_property_type_id=_string(hit.get("bayut_property_type_id")),
        bayut_leaf_location_id=_string(hit.get("bayut_leaf_location_id")),
        bayut_leaf_location_name_en=_string(hit.get("bayut_leaf_location_name_en")),
        bayut_leaf_location_name_ar=_string(hit.get("bayut_leaf_location_name_ar")),
        bayut_location_l3_name_en=_string(hit.get("bayut_location_l3_name_en")),
        bayut_location_l3_name_ar=_string(hit.get("bayut_location_l3_name_ar")),
        bayut_location_l4_name_en=_string(hit.get("bayut_location_l4_name_en")),
        bayut_location_l4_name_ar=_string(hit.get("bayut_location_l4_name_ar")),
        bayut_location_l5_name_en=_string(hit.get("bayut_location_l5_name_en")),
        bayut_location_l5_name_ar=_string(hit.get("bayut_location_l5_name_ar")),
        bayut_location_l6_name_en=_string(hit.get("bayut_location_l6_name_en")),
        bayut_location_l6_name_ar=_string(hit.get("bayut_location_l6_name_ar")),
        occupancy_status_name=_string(hit.get("occupancy_status_name")),
        claimed_transaction_status=_string(hit.get("claimed_transaction_status")),
        property_completion_status_sk=_string(hit.get("property_completion_status_sk")),
        sale_market_name=_string(hit.get("sale_market_name")),
        seller_type=_string(hit.get("seller_type")),
        transaction_payment_method=_string(hit.get("transaction_payment_method")),
        unit_number=_string(hit.get("unit_number")),
        has_kpi_value=_bool_int(hit.get("has_kpi_value")),
        previous_sale_transaction_date=_string(hit.get("date_previous_sale_transaction_nk")),
    )


def _rental_row(
    *,
    release_id: str,
    scraped_at: str,
    start_date: date,
    end_date: date,
    page: int,
    hit: dict[str, Any],
) -> RentalTransactionRow:
    return RentalTransactionRow(
        release_id=release_id,
        scraped_at=scraped_at,
        window_start_date=start_date.isoformat(),
        window_end_date=end_date.isoformat(),
        purpose="for-rent",
        page=page,
        transaction_hash_id=_string(hit.get("transaction_hash_id")),
        transaction_date=_string(hit.get("date_transaction_nk")),
        contract_start_date=_string(hit.get("date_start_nk")),
        contract_end_date=_string(hit.get("date_end_nk")),
        transaction_amount=_string(hit.get("transaction_amount")),
        contract_monthly_amount=_string(hit.get("contract_monthly_amount")),
        transaction_per_sqm_amount=_string(hit.get("transaction_per_sqm_amount")),
        builtup_area_sqm=_string(hit.get("builtup_area_sqm")),
        plot_area_sqm=_string(hit.get("plot_area_sqm")),
        balcony_area_sqm=_string(hit.get("balcony_area_sqm")),
        beds=_string(hit.get("beds")),
        floor=_string(hit.get("floor")),
        latitude=_string(hit.get("latitude")),
        longitude=_string(hit.get("longitude")),
        bayut_latitude=_string(hit.get("bayut_latitude")),
        bayut_longitude=_string(hit.get("bayut_longitude")),
        bayut_property_type_id=_string(hit.get("bayut_property_type_id")),
        bayut_leaf_location_id=_string(hit.get("bayut_leaf_location_id")),
        bayut_leaf_location_name_en=_string(hit.get("bayut_leaf_location_name_en")),
        bayut_leaf_location_name_ar=_string(hit.get("bayut_leaf_location_name_ar")),
        bayut_location_l3_name_en=_string(hit.get("bayut_location_l3_name_en")),
        bayut_location_l3_name_ar=_string(hit.get("bayut_location_l3_name_ar")),
        bayut_location_l4_name_en=_string(hit.get("bayut_location_l4_name_en")),
        bayut_location_l4_name_ar=_string(hit.get("bayut_location_l4_name_ar")),
        bayut_location_l5_name_en=_string(hit.get("bayut_location_l5_name_en")),
        bayut_location_l5_name_ar=_string(hit.get("bayut_location_l5_name_ar")),
        bayut_location_l6_name_en=_string(hit.get("bayut_location_l6_name_en")),
        bayut_location_l6_name_ar=_string(hit.get("bayut_location_l6_name_ar")),
        occupancy_status_name=_string(hit.get("occupancy_status_name")),
        claimed_transaction_status=_string(hit.get("claimed_transaction_status")),
        property_completion_status_sk=_string(hit.get("property_completion_status_sk")),
        rent_contract_duration_months=_string(hit.get("rent_contract_duration_months")),
        rent_contract_renewal_status_name=_string(hit.get("rent_contract_renewal_status_name")),
        has_kpi_value=_bool_int(hit.get("has_kpi_value")),
        previous_sale_transaction_date=_string(hit.get("date_previous_sale_transaction_nk")),
    )


def _fieldnames(row_type: type[Any]) -> list[str]:
    return [field.name for field in fields(row_type)]


def _write_rows(path: Path, *, fieldnames: list[str], rows: list[Any]) -> None:
    write_csv(path, fieldnames=fieldnames, rows=[asdict(row) for row in rows])


def download_all(
    *,
    dest_dir: Path,
    run_id: str,
    start_date: str,
    end_date: str,
    max_pages: int | None = None,
    chrome_path: str = "",
) -> list[DownloadResult]:
    parsed_start = _parse_date(start_date)
    parsed_end = _parse_date(end_date)
    if parsed_start > parsed_end:
        raise ValueError(f"Bayut start_date {start_date} is after end_date {end_date}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    scraped_at = _utc_now_sql()

    with sync_playwright() as playwright:
        browser, api = _bootstrap_api(playwright=playwright, chrome_path=chrome_path)
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
        finally:
            api.dispose()
            browser.close()

    sale_rows: list[SaleTransactionRow] = []
    for page_number, payload in sale_pages:
        for hit in payload.get("hits", []):
            sale_rows.append(
                _sale_row(
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
                _rental_row(
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
