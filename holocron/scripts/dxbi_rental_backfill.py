#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import random
import re
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


DXBI_URL = "https://dxbinteract.com/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
)
RENTAL_REGION_SELECTOR = "#rentHistory"
RENTAL_MARKER = "47624226685649900817"
PAGE_SIZE = 300
CENT = Decimal("0.01")
RECOVERABLE_HTTP_STATUSES = {408, 429, 500, 502, 503, 504, 598}
FETCH_EVAL_TIMEOUT_MS = 120_000
PAGINATION_PATTERN = re.compile(
    r"apex\.widget\.report\.paginate\('([^']+)'\s*,\s*'([^']+)'\s*,"
    r"\s*\{min:(\d+),max:(\d+),fetched:(\d+)\}\)"
)
PRICE_BUCKETS = (
    (Decimal("0"), Decimal("24999.99")),
    (Decimal("25000"), Decimal("49999.99")),
    (Decimal("50000"), Decimal("74999.99")),
    (Decimal("75000"), Decimal("99999.99")),
    (Decimal("100000"), Decimal("124999.99")),
    (Decimal("125000"), Decimal("149999.99")),
    (Decimal("150000"), Decimal("199999.99")),
    (Decimal("200000"), Decimal("299999.99")),
    (Decimal("300000"), Decimal("499999.99")),
    (Decimal("500000"), Decimal("999999.99")),
    (Decimal("1000000"), None),
)
SIZE_BUCKETS = (
    (Decimal("0"), Decimal("249.99")),
    (Decimal("250"), Decimal("499.99")),
    (Decimal("500"), Decimal("749.99")),
    (Decimal("750"), Decimal("999.99")),
    (Decimal("1000"), Decimal("1499.99")),
    (Decimal("1500"), Decimal("1999.99")),
    (Decimal("2000"), Decimal("2999.99")),
    (Decimal("3000"), Decimal("4999.99")),
    (Decimal("5000"), Decimal("9999.99")),
    (Decimal("10000"), None),
)
DEFAULT_FILTER_OVERRIDES = {
    "P74_DEAL": "RENT",
    "P74_PROP_TYPE": "A",
    "P74_STATUS": "B",
    "P74_BEDS": "-1",
    "P74_SOLD_BY": "B",
    "P74_FLAG": "A",
    "P74_PROCEDURE": "B",
}
DEFAULT_LOCATION = {"id": "1", "text": "Dubai", "slug": "dubai"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value, "f")


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def dates_between(start: date, end: date, direction: str) -> Iterator[date]:
    if direction == "asc":
        current = start
        while current <= end:
            yield current
            current += timedelta(days=1)
        return
    current = end
    while current >= start:
        yield current
        current -= timedelta(days=1)


def shard_key(shard: dict[str, Any]) -> str:
    return "|".join(
        (
            shard["date"],
            decimal_text(shard["min_price"]),
            decimal_text(shard["max_price"]),
            decimal_text(shard["min_size"]),
            decimal_text(shard["max_size"]),
        )
    )


def initial_shards(day: date) -> list[dict[str, Any]]:
    return [
        {
            "date": day.isoformat(),
            "min_price": Decimal("0"),
            "max_price": None,
            "min_size": None,
            "max_size": None,
        }
    ]


def bisect_range(
    minimum: Decimal, maximum: Decimal | None
) -> tuple[tuple[Decimal, Decimal], tuple[Decimal, Decimal | None]]:
    if maximum is None:
        next_maximum = max(minimum * 2, minimum + Decimal("1000000"))
        return (minimum, next_maximum), (next_maximum + CENT, None)
    if maximum - minimum < CENT:
        raise ValueError("range cannot be split further")
    midpoint = ((minimum + maximum) / 2).quantize(CENT)
    if midpoint >= maximum:
        midpoint = maximum - CENT
    return (minimum, midpoint), (midpoint + CENT, maximum)


def split_capped_shard(shard: dict[str, Any]) -> list[dict[str, Any]]:
    min_price = shard["min_price"]
    max_price = shard["max_price"]
    min_size = shard["min_size"]
    max_size = shard["max_size"]

    if min_size is None:
        if min_price == 0 and max_price is None:
            return [
                {**shard, "min_price": minimum, "max_price": maximum}
                for minimum, maximum in PRICE_BUCKETS
            ]
        if max_price is None or max_price - min_price >= CENT:
            ranges = bisect_range(min_price, max_price)
            return [
                {**shard, "min_price": minimum, "max_price": maximum} for minimum, maximum in ranges
            ]
        return [
            {**shard, "min_size": minimum, "max_size": maximum} for minimum, maximum in SIZE_BUCKETS
        ]

    if max_size is None or max_size - min_size >= CENT:
        ranges = bisect_range(min_size, max_size)
        return [{**shard, "min_size": minimum, "max_size": maximum} for minimum, maximum in ranges]
    return []


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.chmod(0o600)
    os.replace(temporary, path)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "version": 1,
            "completed": {},
            "expanded": {},
            "failed": {},
            "requests": 0,
        }
    return json.loads(path.read_text())


def write_shard(path: Path, shard: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as raw_handle:
        temporary = Path(raw_handle.name)
    try:
        with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=6) as handle:
            for index, row in enumerate(rows, start=1):
                record = {
                    "transaction_type": "rentals",
                    "shard": {
                        key: decimal_text(value) if isinstance(value, Decimal) else value
                        for key, value in shard.items()
                    },
                    "row_index_in_response": index,
                    "columns": row["columns"],
                    "scraped_at": utc_now(),
                }
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def virtual_display() -> Iterator[None]:
    process: subprocess.Popen[bytes] | None = None
    display = ""
    for display_number in range(90, 120):
        if Path(f"/tmp/.X{display_number}-lock").exists():
            continue
        candidate = f":{display_number}"
        process = subprocess.Popen(
            ["Xvfb", candidate, "-screen", "0", "1366x768x24"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)
        if process.poll() is None:
            display = candidate
            break
        process = None
    if process is None or not display:
        raise RuntimeError("could not start an isolated Xvfb display")

    previous_display = os.environ.get("DISPLAY")
    os.environ["DISPLAY"] = display
    try:
        yield
    finally:
        if previous_display is None:
            os.environ.pop("DISPLAY", None)
        else:
            os.environ["DISPLAY"] = previous_display
        process.terminate()
        process.wait(timeout=5)


def maybe_accept_terms(page: Page) -> None:
    checkbox = page.locator("dialog input[type='checkbox'], .a-Dialog input[type='checkbox']").first
    try:
        if checkbox.is_visible(timeout=3_000):
            checkbox.check()
            page.locator(
                "dialog button:has-text('Submit'), .a-Dialog button:has-text('Submit')"
            ).first.click()
            page.wait_for_timeout(1_000)
    except PlaywrightTimeoutError:
        pass


def login(page: Page, credentials: dict[str, str]) -> None:
    page.goto(DXBI_URL, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(3_000)
    maybe_accept_terms(page)
    if page.locator(RENTAL_REGION_SELECTOR).count():
        return

    sign_in = page.get_by_text("Sign In", exact=True).first
    if not sign_in.count():
        raise RuntimeError("DXB Sign In control not found")
    sign_in.click()
    page.wait_for_timeout(2_000)
    scope: Any = page
    for frame in page.frames:
        if frame.locator("input[type='password']").count():
            scope = frame
            break

    username = scope.locator(
        "#P9999_USERNAME, input[name='P9999_USERNAME'], input[type='email']"
    ).first
    password = scope.locator(
        "#P9999_PASSWORD, input[name='P9999_PASSWORD'], input[type='password']"
    ).first
    if not username.count() or not password.count():
        raise RuntimeError("DXB modal login fields not found")
    username.fill(credentials["email"])
    password.fill(credentials["password"])
    submit = scope.get_by_role("button", name="Continue", exact=True).first
    if not submit.count():
        raise RuntimeError("DXB modal Continue button not found")
    submit.click()
    page.wait_for_timeout(5_000)
    page.goto(DXBI_URL, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(3_000)
    if not page.locator(RENTAL_REGION_SELECTOR).count():
        raise RuntimeError("DXB login did not expose the rental region")


def apply_filters_and_refresh(
    page: Page,
    shard: dict[str, Any],
    filter_overrides: dict[str, str],
    location: dict[str, str],
) -> None:
    payload = {
        "date": shard["date"],
        "minPrice": decimal_text(shard["min_price"]),
        "maxPrice": decimal_text(shard["max_price"]),
        "minSize": decimal_text(shard["min_size"]),
        "maxSize": decimal_text(shard["max_size"]),
        "filterOverrides": filter_overrides,
        "location": location,
    }
    refresh = page.evaluate(
        """filters => {
            const set = (id, value) => {
                if (document.querySelector(`#${id}`)) window.$s(id, value, null, true);
            };
            if (typeof window.$s !== 'function' || !window.apex?.region) {
                throw new Error('APEX filter API is unavailable');
            }
            set('P74_DLD_LOCATION_ID', filters.location.id);
            set('P74_DLD_LOCATION_TEXT', filters.location.text);
            set('P74_DLD_LOCATION', filters.location.slug);
            for (const [id, value] of Object.entries(filters.filterOverrides)) {
                set(id, value);
            }
            set('P74_START_DATE', filters.date);
            set('P74_END_DATE', filters.date);
            set('P74_MIN_PRICE', filters.minPrice);
            set('P74_MAX_PRICE', filters.maxPrice);
            set('P74_MIN_SIZE', filters.minSize);
            set('P74_MAX_SIZE', filters.maxSize);
            set('P74_PROJECT', '');
            set('P74_PROJECT_A', '');
            set('P74_PROJECT_A_HIDDENVALUE', '');
            set('P74_PROJECT_B', '');
            set('P74_PROJECT_B_HIDDENVALUE', '');
            set('P74_MY_PROJECT', '');
            set('P74_MY_PROJECT_HIDDENVALUE', '');
            const token = String(Date.now());
            const state = {token, soldDone: false, rentDone: false};
            window.__dxbiBackfillRefresh = state;
            const jq = window.apex?.jQuery || window.jQuery;
            if (typeof jq === 'function') {
                jq('#soldhistory').one(
                    'apexafterrefresh', () => { state.soldDone = true; }
                );
                jq('#rentHistory').one(
                    'apexafterrefresh', () => { state.rentDone = true; }
                );
            }
            window.apex.region('soldhistory').refresh();
            window.apex.region('rentHistory').refresh();
            return {token};
        }""",
        payload,
    )
    try:
        page.wait_for_function(
            """token => {
                const state = window.__dxbiBackfillRefresh;
                return state?.token === token && state.soldDone && state.rentDone;
            }""",
            arg=refresh["token"],
            timeout=20_000,
        )
    except PlaywrightTimeoutError:
        page.wait_for_timeout(3_000)


def capture_template(
    page: Page, template_date: str, filter_overrides: dict[str, str]
) -> dict[str, str]:
    shard = {
        "date": template_date,
        "min_price": Decimal("0"),
        "max_price": None,
        "min_size": None,
        "max_size": None,
    }
    apply_filters_and_refresh(page, shard, filter_overrides, DEFAULT_LOCATION)
    link = page.locator(f'{RENTAL_REGION_SELECTOR} a[href*="apex.widget.report.paginate"]').first
    if not link.count():
        raise RuntimeError("dense template date produced no rental pagination link")
    href = link.get_attribute("href") or ""
    match = PAGINATION_PATTERN.search(href)
    if not match:
        raise RuntimeError("could not parse rental pagination link")

    with page.expect_request(
        lambda request: (
            request.method == "POST"
            and "wwv_flow.ajax?p_context=litedxb/transactions/" in request.url
            and RENTAL_MARKER in (request.post_data or "")
        ),
        timeout=10_000,
    ) as request_info:
        page.evaluate(
            """selector => {
                document.querySelector(
                    `${selector} a[href*="apex.widget.report.paginate"]`
                ).click();
            }""",
            RENTAL_REGION_SELECTOR,
        )
    request = request_info.value
    return {
        "url": request.url,
        "post_data": request.post_data or "",
        "region_id": match.group(1),
    }


def fetch_rows(
    page: Page,
    template: dict[str, str],
    shard: dict[str, Any],
    filter_overrides: dict[str, str],
    location: dict[str, str],
) -> dict[str, Any]:
    payload = {
        "template": template,
        "date": shard["date"],
        "minPrice": decimal_text(shard["min_price"]),
        "maxPrice": decimal_text(shard["max_price"]),
        "minSize": decimal_text(shard["min_size"]),
        "maxSize": decimal_text(shard["max_size"]),
        "filterOverrides": filter_overrides,
        "location": location,
    }
    return page.evaluate(
        """async input => {
            const params = new URLSearchParams(input.template.post_data);
            params.set('p_pg_min_row', '1');
            params.set('p_pg_max_rows', '300');
            params.set('p_pg_rows_fetched', '300');
            params.set('x01', input.template.region_id);
            const payload = JSON.parse(params.get('p_json'));
            for (const item of payload.pageItems?.itemsToSubmit || []) {
                if (item.n === 'P74_DLD_LOCATION_ID') item.v = input.location.id;
                if (item.n === 'P74_DLD_LOCATION_TEXT') item.v = input.location.text;
                if (item.n === 'P74_DLD_LOCATION') item.v = input.location.slug;
                if (Object.hasOwn(input.filterOverrides, item.n)) {
                    item.v = input.filterOverrides[item.n];
                }
                if (item.n === 'P74_START_DATE') item.v = input.date;
                if (item.n === 'P74_END_DATE') item.v = input.date;
                if (item.n === 'P74_MIN_PRICE') item.v = input.minPrice;
                if (item.n === 'P74_MAX_PRICE') item.v = input.maxPrice;
                if (item.n === 'P74_MIN_SIZE') item.v = input.minSize;
                if (item.n === 'P74_MAX_SIZE') item.v = input.maxSize;
            }
            params.set('p_json', JSON.stringify(payload));
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 90000);
            let response;
            try {
                response = await fetch(input.template.url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'X-Requested-With': 'XMLHttpRequest',
                        Accept: 'text/html, */*; q=0.01'
                    },
                    body: params.toString(),
                    signal: controller.signal
                });
            } catch (error) {
                return {
                    status: 598,
                    login_redirect: false,
                    rows: [],
                    error: String(error)
                };
            } finally {
                clearTimeout(timeout);
            }
            const html = await response.text();
            const document_ = new DOMParser().parseFromString(html, 'text/html');
            const table = document_.querySelector('#report_table_rentHistory');
            const headers = {};
            table?.querySelectorAll('thead th').forEach(header => {
                if (header.id) {
                    headers[header.id] = (
                        header.innerText || header.textContent || ''
                    ).replace(/\\s+/g, ' ').trim();
                }
            });
            const rows = table ? Array.from(table.querySelectorAll('tbody tr')).map(row => ({
                columns: Array.from(row.querySelectorAll('td')).map(cell => {
                    const id = cell.getAttribute('headers') || '';
                    return {
                        id,
                        label: headers[id] || '',
                        text: (cell.innerText || cell.textContent || '')
                            .replace(/\\s+/g, ' ').trim(),
                        html: cell.innerHTML || '',
                        links: Array.from(cell.querySelectorAll('a[href]')).map(link => ({
                            text: (link.innerText || link.textContent || '')
                                .replace(/\\s+/g, ' ').trim(),
                            href: link.href || link.getAttribute('href') || '',
                            class: link.getAttribute('class') || ''
                        }))
                    };
                })
            })).filter(row => row.columns.some(column => column.text)) : [];
            return {
                status: response.status,
                login_redirect: /P9999_USERNAME|apex_authentication/i.test(html),
                rows
            };
        }""",
        payload,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", required=True)
    parser.add_argument("--storage-state", required=True)
    parser.add_argument("--browser", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--direction", choices=("asc", "desc"), required=True)
    parser.add_argument("--template-date", default="2025-07-01")
    parser.add_argument("--delay-min", type=float, default=3.0)
    parser.add_argument("--delay-max", type=float, default=6.0)
    parser.add_argument("--max-requests", type=int, default=0)
    parser.add_argument(
        "--filter-overrides-json",
        default="{}",
        help="JSON map of P74 filter IDs to values; merged with the existing rental profile.",
    )
    parser.add_argument("--inspect-filter-items", action="store_true")
    parser.add_argument("--page-url", default=DXBI_URL)
    parser.add_argument("--area-slug", default="")
    parser.add_argument("--location-id", default=DEFAULT_LOCATION["id"])
    parser.add_argument("--location-text", default=DEFAULT_LOCATION["text"])
    parser.add_argument("--location-slug", default=DEFAULT_LOCATION["slug"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    start = parse_date(args.start_date)
    end = parse_date(args.end_date)
    if start > end:
        raise ValueError("start date must be on or before end date")
    supplied_overrides = json.loads(args.filter_overrides_json)
    if not isinstance(supplied_overrides, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in supplied_overrides.items()
    ):
        raise ValueError("--filter-overrides-json must be a JSON object of string values")
    filter_overrides = {**DEFAULT_FILTER_OVERRIDES, **supplied_overrides}
    location = {
        "id": args.location_id,
        "text": args.location_text,
        "slug": args.location_slug,
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_dir.chmod(0o700)
    shard_dir = output_dir / "shards"
    state_path = output_dir / "checkpoint.json"
    state = load_state(state_path)
    credentials = json.loads(Path(args.credentials).read_text())
    if not credentials.get("email") or not credentials.get("password"):
        raise RuntimeError("credentials contain a blank email or password")

    started_requests = int(state.get("requests", 0))
    current_run_requests = 0
    with virtual_display(), sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=args.browser,
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context_kwargs: dict[str, Any] = {"user_agent": USER_AGENT}
        storage_path = Path(args.storage_state)
        if storage_path.exists():
            context_kwargs["storage_state"] = str(storage_path)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.set_default_timeout(FETCH_EVAL_TIMEOUT_MS)
        page.set_default_navigation_timeout(FETCH_EVAL_TIMEOUT_MS)
        try:
            login(page, credentials)
            if args.page_url != DXBI_URL:
                page.goto(args.page_url, wait_until="domcontentloaded", timeout=120_000)
                page.wait_for_timeout(3_000)
            if args.area_slug:
                page.locator(
                    f'a[href*="/dubai-house-prices/{args.area_slug}"]'
                ).first.click(timeout=20_000)
                page.wait_for_timeout(4_000)
            context.storage_state(path=storage_path)
            storage_path.chmod(0o600)
            if args.inspect_filter_items:
                initial_page_location = page.evaluate(
                    """() => ({
                        slug: document.querySelector('#P74_DLD_LOCATION')?.value || '',
                        id: document.querySelector('#P74_DLD_LOCATION_ID')?.value || '',
                        text: document.querySelector('#P74_DLD_LOCATION_TEXT')?.value || ''
                    })"""
                )
                apply_filters_and_refresh(
                    page,
                    {
                        "date": args.template_date,
                        "min_price": Decimal("0"),
                        "max_price": None,
                        "min_size": None,
                        "max_size": None,
                    },
                    DEFAULT_FILTER_OVERRIDES,
                    DEFAULT_LOCATION,
                )
                print(
                    json.dumps(
                        page.evaluate(
                            """input => ({
                                url: location.href,
                                initial_page_location: input.initial_page_location,
                                page_text: document.body.innerText,
                                controls: [...document.querySelectorAll(
                                    '.inline-popup[data-id], .search-choose-btns[data-id], .more-filters[data-id]'
                                )].map(element => element.outerHTML.slice(0, 6000)),
                                scripts: [...document.scripts]
                                    .map(script => script.src)
                                    .filter(Boolean),
                                area_links: [...document.links]
                                    .filter(link => /Business Bay|Downtown Dubai|Dubai Marina/i.test(link.textContent || ''))
                                    .map(link => ({
                                        text: (link.textContent || '').trim(), href: link.href
                                    })),
                                items: [...document.querySelectorAll('[id*="P74_PROP_TYPE"], [id*="P74_STATUS"], [id*="P74_SOLD_BY"], [id*="P74_FLAG"], [id*="P74_PROCEDURE"], [for*="P74_PROP_TYPE"], [for*="P74_STATUS"], [for*="P74_SOLD_BY"], [for*="P74_FLAG"], [for*="P74_PROCEDURE"]')]
                                .map(element => ({
                                    id: element.id,
                                    value: element.value || '',
                                    tag: element.tagName,
                                    attributes: Object.fromEntries(
                                        [...element.attributes].map(a => [a.name, a.value])
                                    ),
                                    options: element.tagName === 'SELECT'
                                        ? [...element.options].map(o => ({
                                            value: o.value, text: o.text, selected: o.selected
                                        }))
                                        : [],
                                    html: element.outerHTML.slice(0, 1500),
                                }))
                            })""",
                            {"initial_page_location": initial_page_location},
                        ),
                        indent=2,
                    )
                )
                return 0
            # Capture the authenticated APEX request shape using the known-dense
            # profile. The requested profile is injected into each fetch below;
            # sparse valid profiles do not necessarily expose a pagination link.
            template = capture_template(
                page, args.template_date, DEFAULT_FILTER_OVERRIDES
            )

            for day in dates_between(start, end, args.direction):
                queue = initial_shards(day)
                while queue:
                    shard = queue.pop(0)
                    key = shard_key(shard)
                    if key in state["completed"] or key in state["failed"]:
                        continue
                    if key in state["expanded"]:
                        queue = split_capped_shard(shard) + queue
                        continue
                    if args.max_requests and current_run_requests >= args.max_requests:
                        print(
                            json.dumps(
                                {
                                    "status": "max_requests_reached",
                                    "run_requests": current_run_requests,
                                    "total_requests": state["requests"],
                                }
                            )
                        )
                        return 0

                    response: dict[str, Any] | None = None
                    for attempt in range(1, 4):
                        try:
                            response = fetch_rows(
                                page, template, shard, filter_overrides, location
                            )
                        except PlaywrightTimeoutError as error:
                            response = {
                                "status": 598,
                                "login_redirect": False,
                                "rows": [],
                                "error": f"PLAYWRIGHT_TIMEOUT: {error}",
                            }
                        except Exception as error:
                            response = {
                                "status": 598,
                                "login_redirect": False,
                                "rows": [],
                                "error": f"{type(error).__name__}: {error}",
                            }

                        current_run_requests += 1
                        state["requests"] = started_requests + current_run_requests
                        if response["login_redirect"]:
                            login(page, credentials)
                            context.storage_state(path=storage_path)
                            template = capture_template(
                                page, args.template_date, DEFAULT_FILTER_OVERRIDES
                            )
                            if attempt < 3:
                                continue
                        if response["status"] < 400:
                            break
                        if response["status"] in RECOVERABLE_HTTP_STATUSES and attempt < 3:
                            retry_delay = random.uniform(10 * attempt, 20 * attempt)
                            if response.get("error"):
                                print(
                                    f"RETRY {key} status={response['status']} "
                                    f"attempt={attempt} error={response['error']} "
                                    f"delay={retry_delay:.1f}s",
                                    flush=True,
                                )
                            else:
                                print(
                                    f"RETRY {key} status={response['status']} "
                                    f"attempt={attempt} delay={retry_delay:.1f}s",
                                    flush=True,
                                )
                            time.sleep(retry_delay)
                            continue
                        break
                    if response is None:
                        raise RuntimeError(f"{key}: request loop produced no response")
                    if response["status"] >= 400:
                        raise RuntimeError(f"{key}: HTTP {response['status']}")

                    rows = response["rows"]
                    if len(rows) < PAGE_SIZE:
                        digest = hashlib.sha256(key.encode()).hexdigest()[:20]
                        relative_path = ""
                        if rows:
                            path = shard_dir / shard["date"] / f"{digest}.jsonl.gz"
                            write_shard(path, shard, rows)
                            relative_path = str(path.relative_to(output_dir))
                        state["completed"][key] = {
                            "rows": len(rows),
                            "path": relative_path,
                            "completed_at": utc_now(),
                        }
                        print(f"COMPLETE {key} rows={len(rows)}", flush=True)
                    else:
                        children = split_capped_shard(shard)
                        if children:
                            state["expanded"][key] = {
                                "children": [shard_key(child) for child in children],
                                "expanded_at": utc_now(),
                            }
                            queue = children + queue
                            print(f"EXPAND {key} rows={len(rows)}", flush=True)
                        else:
                            state["failed"][key] = {
                                "reason": "300-row cap remains at minimum price and size spans",
                                "failed_at": utc_now(),
                            }
                            print(f"FAILED {key} rows={len(rows)}", flush=True)
                    atomic_json(state_path, state)
                    time.sleep(random.uniform(args.delay_min, args.delay_max))
        finally:
            context.close()
            browser.close()

    print(
        json.dumps(
            {
                "status": "completed_range",
                "run_requests": current_run_requests,
                "total_requests": state["requests"],
                "completed_shards": len(state["completed"]),
                "failed_shards": len(state["failed"]),
            }
        )
    )
    return 1 if state["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
