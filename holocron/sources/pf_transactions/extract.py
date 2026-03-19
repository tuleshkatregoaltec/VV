"""Property Finder transaction extraction logic."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, fields
import json
import math
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from tenacity import RetryError

from holocron.framework.csv_utils import write_csv
from holocron.framework.models import DownloadResult, utc_now_sql

SITEMAP_URLS = {
    "buy": "https://www.propertyfinder.ae/sitemaps/dubai-buy-0.xml",
    "rent": "https://www.propertyfinder.ae/sitemaps/dubai-rent-0.xml",
}

GENERIC_PAGE_MARKERS = {
    "buy": "/en/buy/dubai/properties-for-sale-",
    "rent": "/en/rent/dubai/properties-for-rent-",
}

TRANSACTION_ROOT_URLS = {
    "buy": "https://www.propertyfinder.ae/en/transactions/buy/dubai",
    "rent": "https://www.propertyfinder.ae/en/transactions/rent/dubai",
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

JSON_HEADERS = {**DEFAULT_HEADERS, "Accept": "application/json", "x-nextjs-data": "1"}

NEXT_DATA_PATTERN = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
SITEMAP_LOC_PATTERN = re.compile(r"<loc>(.*?)</loc>")
BUILD_ID_PATTERN = re.compile(r'"buildId":"([^"]+)"')
TRANSACTION_URL_PATH_PATTERN = re.compile(r"^/en/transactions/(?P<purpose>buy|rent)/(?P<path>.+)$")

ROWS_PER_PAGE = 10
MAX_PAGES_PER_SORT = 50
MAX_ROWS_PER_SORT = ROWS_PER_PAGE * MAX_PAGES_PER_SORT
DUAL_SORT_COMPLETE_THRESHOLD = MAX_ROWS_PER_SORT * 2


@dataclass(frozen=True)
class RawLocationRecord:
    purpose: str
    pf_location_id: str
    location_name: str
    path_ids: str
    level_type: str
    slug: str
    city_slug: str
    is_transaction_visible: int


@dataclass(frozen=True)
class LocationNode:
    purpose: str
    pf_location_id: str
    parent_pf_location_id: str
    city_pf_location_id: str
    path_ids: str
    path_depth: int
    level_type: str
    location_name: str
    slug: str
    city_slug: str


@dataclass(frozen=True)
class TransactionRow:
    release_id: str
    scraped_at: str
    pf_transaction_id: str
    transaction_date: str
    contract_start_date: str
    contract_end_date: str
    price: float
    price_per_sqft: float
    property_size_sqft: float
    bedrooms: int
    property_number: str
    property_type: str
    status: str
    high_level_location_name: str
    location_name: str
    location_url: str
    propertyfinder_location_id: str
    captured_from_pf_location_id: str
    captured_from_slug: str
    captured_from_level_type: str
    captured_from_path_ids: str
    capture_strategy: str
    captured_sort: str
    captured_page_no: int


@dataclass(frozen=True)
class CoverageRow:
    release_id: str
    scraped_at: str
    purpose: str
    period: str
    build_id: str
    pf_location_id: str
    parent_pf_location_id: str
    city_pf_location_id: str
    path_ids: str
    path_depth: int
    level_type: str
    location_name: str
    slug: str
    city_slug: str
    transaction_url: str
    total_transaction_count: int
    child_count: int
    request_count: int
    unique_rows_captured: int
    strategy: str
    is_self_complete: int


@dataclass(frozen=True)
class CapturedTransaction:
    row: TransactionRow
    key: str


def _fetch_text(http, url: str, *, headers: dict[str, str] | None = None) -> str:
    response = http.get(url, headers=headers or DEFAULT_HEADERS)
    return response.text


def _fetch_json(http, url: str) -> dict[str, Any]:
    response = http.get(url, headers=JSON_HEADERS)
    return response.json()


def _extract_next_data(html: str) -> dict[str, Any]:
    match = NEXT_DATA_PATTERN.search(html)
    if match is None:
        raise ValueError("Property Finder page missing __NEXT_DATA__ payload")
    return json.loads(match.group(1))


def _parse_generic_location_urls(xml_text: str, *, purpose: str) -> list[str]:
    marker = GENERIC_PAGE_MARKERS[purpose]
    urls: list[str] = []
    seen: set[str] = set()
    for url in SITEMAP_LOC_PATTERN.findall(xml_text):
        if marker not in url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _path_depth(path_ids: str) -> int:
    return len([part for part in path_ids.split(".") if part])


def _parent_id(path_ids: str) -> str:
    parts = [part for part in path_ids.split(".") if part]
    if len(parts) <= 1:
        return ""
    return parts[-2]


def _city_id(path_ids: str) -> str:
    parts = [part for part in path_ids.split(".") if part]
    if not parts:
        return ""
    return parts[0]


def _extract_listing_location(*, purpose: str, html: str) -> RawLocationRecord:
    payload = _extract_next_data(html)
    page_props = payload["props"]["pageProps"]
    location = page_props["filtersValueFromQuery"]["filter[locations_ids]"][0]
    return RawLocationRecord(
        purpose=purpose,
        pf_location_id=str(location.get("id", "")).strip(),
        location_name=str(location.get("n", "")).strip(),
        path_ids=str(location.get("p", "")).strip(),
        level_type=str(location.get("l_t", "")).strip(),
        slug=str(location.get("en_s") or location.get("s") or "").strip(),
        city_slug=str(location.get("en_c_s", "")).strip(),
        is_transaction_visible=1 if bool(location.get("i_t_v")) else 0,
    )


def _fetch_listing_location(http, *, purpose: str, url: str) -> RawLocationRecord:
    html = _fetch_text(http, url)
    return _extract_listing_location(purpose=purpose, html=html)


def _collect_location_urls(http, *, purpose: str, max_pages_per_purpose: int | None) -> list[str]:
    sitemap_xml = _fetch_text(http, SITEMAP_URLS[purpose])
    urls = _parse_generic_location_urls(sitemap_xml, purpose=purpose)
    if max_pages_per_purpose is not None:
        return urls[:max_pages_per_purpose]
    return urls


def _discover_transaction_nodes(
    http,
    *,
    purpose: str,
    max_listing_pages_per_purpose: int | None,
    worker_count: int,
    context=None,
) -> dict[str, LocationNode]:
    urls = _collect_location_urls(
        http,
        purpose=purpose,
        max_pages_per_purpose=max_listing_pages_per_purpose,
    )
    if context is not None:
        context.log.info(
            f"pf_transactions: queued {len(urls)} listing pages for transaction discovery "
            f"({purpose})"
        )

    records: dict[str, RawLocationRecord] = {}
    with ThreadPoolExecutor(max_workers=max(1, worker_count)) as executor:
        future_map = {
            executor.submit(_fetch_listing_location, http, purpose=purpose, url=url): url for url in urls
        }
        for index, future in enumerate(as_completed(future_map), start=1):
            record = future.result()
            if record.is_transaction_visible and record.pf_location_id:
                existing = records.get(record.pf_location_id)
                if existing is None or _path_depth(record.path_ids) < _path_depth(existing.path_ids):
                    records[record.pf_location_id] = record
            if context is not None and (index <= 5 or index % 250 == 0):
                context.log.info(
                    f"pf_transactions: scanned {index}/{len(urls)} listing pages "
                    f"for {purpose}; visible_nodes={len(records):,}"
                )

    nodes = {
        pf_location_id: LocationNode(
            purpose=record.purpose,
            pf_location_id=pf_location_id,
            parent_pf_location_id=_parent_id(record.path_ids),
            city_pf_location_id=_city_id(record.path_ids),
            path_ids=record.path_ids,
            path_depth=_path_depth(record.path_ids),
            level_type=record.level_type,
            location_name=record.location_name,
            slug=record.slug,
            city_slug=record.city_slug,
        )
        for pf_location_id, record in records.items()
    }
    if context is not None:
        context.log.info(
            f"pf_transactions: discovered {len(nodes):,} transaction-visible nodes for {purpose}"
        )
    return nodes


def _resolve_build_id(http, *, purpose: str) -> str:
    html = _fetch_text(http, TRANSACTION_ROOT_URLS[purpose])
    match = BUILD_ID_PATTERN.search(html)
    if match is None:
        raise ValueError("Could not resolve Property Finder Next.js build id")
    return match.group(1)


def _transaction_path(node: LocationNode) -> str:
    if node.path_depth <= 1 or node.slug == node.city_slug:
        return node.city_slug or node.slug
    return f"{node.city_slug}/{node.slug}"


def _resolved_transaction_path(
    node: LocationNode,
    *,
    path_overrides: dict[str, str] | None = None,
) -> str:
    if path_overrides:
        override = path_overrides.get(node.pf_location_id, "").strip("/")
        if override:
            return override
    return _transaction_path(node)


def _transaction_json_url(
    *,
    build_id: str,
    purpose: str,
    node: LocationNode,
    period: str,
    sort: str,
    page: int,
    path_overrides: dict[str, str] | None = None,
) -> str:
    query = urlencode({"period": period, "sort": sort, "page": page})
    return (
        f"https://www.propertyfinder.ae/dataguru/_next/data/{build_id}/en/transactions/"
        f"{purpose}/{_resolved_transaction_path(node, path_overrides=path_overrides)}.json?{query}"
    )


def _transaction_page_url(
    *,
    purpose: str,
    node: LocationNode,
    path_overrides: dict[str, str] | None = None,
) -> str:
    path = _resolved_transaction_path(node, path_overrides=path_overrides)
    return f"https://www.propertyfinder.ae/en/transactions/{purpose}/{path}"


def _fetch_transaction_page(
    http,
    *,
    build_id: str,
    purpose: str,
    node: LocationNode,
    period: str,
    sort: str,
    page: int,
    path_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = _fetch_json(
        http,
        _transaction_json_url(
            build_id=build_id,
            purpose=purpose,
            node=node,
            period=period,
            sort=sort,
            page=page,
            path_overrides=path_overrides,
        ),
    )
    return payload["pageProps"]


def _is_not_found_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 404
    if isinstance(exc, RetryError):
        last_exc = exc.last_attempt.exception()
        return isinstance(last_exc, Exception) and _is_not_found_error(last_exc)
    return False


def _as_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _as_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    return int(value)


def _transaction_row(
    *,
    run_id: str,
    scraped_at: str,
    transaction: dict[str, Any],
    node: LocationNode,
    strategy: str,
    sort: str,
    page_no: int,
) -> TransactionRow:
    return TransactionRow(
        release_id=run_id,
        scraped_at=scraped_at,
        pf_transaction_id=str(transaction.get("id", "")).strip(),
        transaction_date=str(transaction.get("transactionDate", "")).strip(),
        contract_start_date=str(transaction.get("contractStartDate", "")).strip(),
        contract_end_date=str(transaction.get("contractEndDate", "")).strip(),
        price=_as_float(transaction.get("price")),
        price_per_sqft=_as_float(transaction.get("pricePerSqft")),
        property_size_sqft=_as_float(transaction.get("propertySize")),
        bedrooms=_as_int(transaction.get("bedrooms")),
        property_number=str(transaction.get("propertyNumber", "")).strip(),
        property_type=str(transaction.get("propertyType", "")).strip(),
        status=str(transaction.get("status", "")).strip(),
        high_level_location_name=str(transaction.get("highLevelLocationName", "")).strip(),
        location_name=str(transaction.get("locationName", "")).strip(),
        location_url=str(transaction.get("locationUrl", "")).strip(),
        propertyfinder_location_id=str(transaction.get("locationId", "")).strip(),
        captured_from_pf_location_id=node.pf_location_id,
        captured_from_slug=node.slug,
        captured_from_level_type=node.level_type,
        captured_from_path_ids=node.path_ids,
        capture_strategy=strategy,
        captured_sort=sort,
        captured_page_no=page_no,
    )


def _path_override_from_transaction_url(url: str, *, purpose: str) -> str:
    match = TRANSACTION_URL_PATH_PATTERN.match(url.strip())
    if match is None or match.group("purpose") != purpose:
        return ""
    return match.group("path").strip("/")


def _ingest_transactions(
    *,
    store: dict[str, CapturedTransaction],
    run_id: str,
    scraped_at: str,
    node: LocationNode,
    strategy: str,
    sort: str,
    page_no: int,
    transactions: list[dict[str, Any]],
    purpose: str,
    path_overrides: dict[str, str] | None = None,
) -> None:
    for transaction in transactions:
        key = str(transaction.get("id", "")).strip()
        location_id = str(transaction.get("locationId", "")).strip()
        if path_overrides is not None and location_id:
            override = _path_override_from_transaction_url(
                str(transaction.get("locationUrl", "")).strip(),
                purpose=purpose,
            )
            if override:
                path_overrides.setdefault(location_id, override)
        if not key or key in store:
            continue
        store[key] = CapturedTransaction(
            key=key,
            row=_transaction_row(
                run_id=run_id,
                scraped_at=scraped_at,
                transaction=transaction,
                node=node,
                strategy=strategy,
                sort=sort,
                page_no=page_no,
            ),
        )


def _collect_all_pages(
    http,
    *,
    build_id: str,
    purpose: str,
    node: LocationNode,
    period: str,
    run_id: str,
    scraped_at: str,
    first_page_props: dict[str, Any],
    path_overrides: dict[str, str] | None = None,
) -> tuple[list[TransactionRow], int]:
    store: dict[str, CapturedTransaction] = {}
    _ingest_transactions(
        store=store,
        run_id=run_id,
        scraped_at=scraped_at,
        node=node,
        strategy="all_pages",
        sort="td",
        page_no=1,
        transactions=first_page_props["list"]["transactionList"],
        purpose=purpose,
        path_overrides=path_overrides,
    )
    total_count = int(first_page_props["list"].get("totalTransactionCount") or 0)
    page_count = min(MAX_PAGES_PER_SORT, max(1, math.ceil(total_count / ROWS_PER_PAGE)))
    request_count = 1
    for page_no in range(2, page_count + 1):
        props = _fetch_transaction_page(
            http,
            build_id=build_id,
            purpose=purpose,
            node=node,
            period=period,
            sort="td",
            page=page_no,
            path_overrides=path_overrides,
        )
        request_count += 1
        _ingest_transactions(
            store=store,
            run_id=run_id,
            scraped_at=scraped_at,
            node=node,
            strategy="all_pages",
            sort="td",
            page_no=page_no,
            transactions=props["list"]["transactionList"],
            purpose=purpose,
            path_overrides=path_overrides,
        )
    return [captured.row for captured in store.values()], request_count


def _collect_dual_sort_pages(
    http,
    *,
    build_id: str,
    purpose: str,
    node: LocationNode,
    period: str,
    run_id: str,
    scraped_at: str,
    first_page_props: dict[str, Any],
    path_overrides: dict[str, str] | None = None,
) -> tuple[list[TransactionRow], int, bool]:
    store: dict[str, CapturedTransaction] = {}
    total_count = int(first_page_props["list"].get("totalTransactionCount") or 0)
    request_count = 1
    _ingest_transactions(
        store=store,
        run_id=run_id,
        scraped_at=scraped_at,
        node=node,
        strategy="dual_sort",
        sort="td",
        page_no=1,
        transactions=first_page_props["list"]["transactionList"],
        purpose=purpose,
        path_overrides=path_overrides,
    )
    for page_no in range(1, MAX_PAGES_PER_SORT + 1):
        if page_no > 1:
            props = _fetch_transaction_page(
                http,
                build_id=build_id,
                purpose=purpose,
                node=node,
                period=period,
                sort="td",
                page=page_no,
                path_overrides=path_overrides,
            )
            request_count += 1
            _ingest_transactions(
                store=store,
                run_id=run_id,
                scraped_at=scraped_at,
                node=node,
                strategy="dual_sort",
                sort="td",
                page_no=page_no,
                transactions=props["list"]["transactionList"],
                purpose=purpose,
                path_overrides=path_overrides,
            )
        if len(store) >= total_count:
            break
        props = _fetch_transaction_page(
            http,
            build_id=build_id,
            purpose=purpose,
            node=node,
            period=period,
            sort="ta",
            page=page_no,
            path_overrides=path_overrides,
        )
        request_count += 1
        _ingest_transactions(
            store=store,
            run_id=run_id,
            scraped_at=scraped_at,
            node=node,
            strategy="dual_sort",
            sort="ta",
            page_no=page_no,
            transactions=props["list"]["transactionList"],
            purpose=purpose,
            path_overrides=path_overrides,
        )
        if len(store) >= total_count:
            break
    rows = [captured.row for captured in store.values()]
    return rows, request_count, len(rows) >= total_count


def _sorted_children(nodes: dict[str, LocationNode]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = {}
    for node in nodes.values():
        parent_id = node.parent_pf_location_id
        if not parent_id:
            continue
        children.setdefault(parent_id, []).append(node.pf_location_id)
    for child_ids in children.values():
        child_ids.sort(key=lambda node_id: (nodes[node_id].path_depth, nodes[node_id].slug, node_id))
    return children


def _root_node_ids(nodes: dict[str, LocationNode]) -> list[str]:
    city_nodes = [node.pf_location_id for node in nodes.values() if node.path_depth == 1]
    if city_nodes:
        return sorted(city_nodes)
    community_nodes = [node.pf_location_id for node in nodes.values() if node.path_depth == 2]
    if community_nodes:
        return sorted(community_nodes)
    return sorted(nodes)


def _crawl_transactions_for_purpose(
    http,
    *,
    purpose: str,
    period: str,
    build_id: str,
    nodes: dict[str, LocationNode],
    max_nodes_per_purpose: int | None,
    run_id: str,
    scraped_at: str,
    context=None,
) -> tuple[list[TransactionRow], list[CoverageRow]]:
    children_by_parent = _sorted_children(nodes)
    transaction_rows: dict[str, TransactionRow] = {}
    coverage_rows: list[CoverageRow] = []
    visited_count = 0
    path_overrides: dict[str, str] = {}

    def visit(node_id: str) -> None:
        nonlocal visited_count
        if max_nodes_per_purpose is not None and visited_count >= max_nodes_per_purpose:
            return
        node = nodes[node_id]
        visited_count += 1
        child_ids = children_by_parent.get(node_id, [])
        transaction_url = _transaction_page_url(
            purpose=purpose,
            node=node,
            path_overrides=path_overrides,
        )
        strategy = "skip_zero"
        request_count = 1
        captured_rows: list[TransactionRow] = []
        is_self_complete = 0
        total_count = 0

        try:
            first_page = _fetch_transaction_page(
                http,
                build_id=build_id,
                purpose=purpose,
                node=node,
                period=period,
                sort="td",
                page=1,
                path_overrides=path_overrides,
            )
        except Exception as exc:
            if not _is_not_found_error(exc):
                raise
            strategy = "route_not_found"
            if child_ids:
                strategy = "route_not_found_descend"
                for child_id in child_ids:
                    visit(child_id)
            coverage_rows.append(
                CoverageRow(
                    release_id=run_id,
                    scraped_at=scraped_at,
                    purpose=purpose,
                    period=period,
                    build_id=build_id,
                    pf_location_id=node.pf_location_id,
                    parent_pf_location_id=node.parent_pf_location_id,
                    city_pf_location_id=node.city_pf_location_id,
                    path_ids=node.path_ids,
                    path_depth=node.path_depth,
                    level_type=node.level_type,
                    location_name=node.location_name,
                    slug=node.slug,
                    city_slug=node.city_slug,
                    transaction_url=transaction_url,
                    total_transaction_count=0,
                    child_count=len(child_ids),
                    request_count=request_count,
                    unique_rows_captured=0,
                    strategy=strategy,
                    is_self_complete=0,
                )
            )
            if context is not None and (visited_count <= 10 or visited_count % 100 == 0):
                context.log.info(
                    f"pf_transactions: {purpose} visited {visited_count:,} nodes; "
                    f"node={node.slug} strategy={strategy}"
                )
            return

        total_count = int(first_page["list"].get("totalTransactionCount") or 0)

        if total_count <= 0:
            strategy = "skip_zero"
        elif total_count > DUAL_SORT_COMPLETE_THRESHOLD and child_ids:
            strategy = "descend_children"
            for child_id in child_ids:
                visit(child_id)
        elif total_count <= MAX_ROWS_PER_SORT:
            strategy = "all_pages"
            captured_rows, request_count = _collect_all_pages(
                http,
                build_id=build_id,
                purpose=purpose,
                node=node,
                period=period,
                run_id=run_id,
                scraped_at=scraped_at,
                first_page_props=first_page,
                path_overrides=path_overrides,
            )
            is_self_complete = 1 if len(captured_rows) >= total_count else 0
        else:
            strategy = "dual_sort"
            captured_rows, request_count, complete = _collect_dual_sort_pages(
                http,
                build_id=build_id,
                purpose=purpose,
                node=node,
                period=period,
                run_id=run_id,
                scraped_at=scraped_at,
                first_page_props=first_page,
                path_overrides=path_overrides,
            )
            is_self_complete = 1 if complete else 0

        added_rows = 0
        for row in captured_rows:
            if row.pf_transaction_id and row.pf_transaction_id not in transaction_rows:
                transaction_rows[row.pf_transaction_id] = row
                added_rows += 1

        coverage_rows.append(
            CoverageRow(
                release_id=run_id,
                scraped_at=scraped_at,
                purpose=purpose,
                period=period,
                build_id=build_id,
                pf_location_id=node.pf_location_id,
                parent_pf_location_id=node.parent_pf_location_id,
                city_pf_location_id=node.city_pf_location_id,
                path_ids=node.path_ids,
                path_depth=node.path_depth,
                level_type=node.level_type,
                location_name=node.location_name,
                slug=node.slug,
                city_slug=node.city_slug,
                transaction_url=transaction_url,
                total_transaction_count=total_count,
                child_count=len(child_ids),
                request_count=request_count,
                unique_rows_captured=added_rows,
                strategy=strategy,
                is_self_complete=is_self_complete,
            )
        )
        if context is not None and (visited_count <= 10 or visited_count % 100 == 0):
            context.log.info(
                f"pf_transactions: {purpose} visited {visited_count:,} nodes; "
                f"node={node.slug} count={total_count:,} strategy={strategy} "
                f"captured={added_rows:,}"
            )

    for root_id in _root_node_ids(nodes):
        visit(root_id)
        if max_nodes_per_purpose is not None and visited_count >= max_nodes_per_purpose:
            break

    return list(transaction_rows.values()), coverage_rows


def download_all(
    *,
    dest_dir: Path,
    run_id: str,
    http,
    period: str = "3y",
    max_listing_pages_per_purpose: int | None = None,
    max_nodes_per_purpose: int | None = None,
    worker_count: int = 8,
    context=None,
) -> list[DownloadResult]:
    scraped_at = utc_now_sql()
    sales: list[TransactionRow] = []
    rentals: list[TransactionRow] = []
    coverage: list[CoverageRow] = []

    for purpose in ("buy", "rent"):
        nodes = _discover_transaction_nodes(
            http,
            purpose=purpose,
            max_listing_pages_per_purpose=max_listing_pages_per_purpose,
            worker_count=worker_count,
            context=context,
        )
        build_id = _resolve_build_id(http, purpose=purpose)
        if context is not None:
            context.log.info(
                f"pf_transactions: resolved build_id={build_id} for {purpose}; "
                f"starting crawl across {len(nodes):,} visible nodes"
            )
        purpose_rows, purpose_coverage = _crawl_transactions_for_purpose(
            http,
            purpose=purpose,
            period=period,
            build_id=build_id,
            nodes=nodes,
            max_nodes_per_purpose=max_nodes_per_purpose,
            run_id=run_id,
            scraped_at=scraped_at,
            context=context,
        )
        purpose_rows.sort(key=lambda row: (row.transaction_date, row.pf_transaction_id))
        purpose_coverage.sort(key=lambda row: (row.purpose, row.path_depth, row.pf_location_id))
        coverage.extend(purpose_coverage)
        if purpose == "buy":
            sales.extend(purpose_rows)
        else:
            rentals.extend(purpose_rows)

    outputs = [
        ("sales.csv", [field.name for field in fields(TransactionRow)], (asdict(row) for row in sales)),
        (
            "rentals.csv",
            [field.name for field in fields(TransactionRow)],
            (asdict(row) for row in rentals),
        ),
        (
            "coverage.csv",
            [field.name for field in fields(CoverageRow)],
            (asdict(row) for row in coverage),
        ),
    ]

    results: list[DownloadResult] = []
    for filename, fieldnames, rows in outputs:
        path = dest_dir / filename
        write_csv(path, fieldnames, rows)
        if context is not None:
            context.log.info(f"pf_transactions: wrote {filename}")
        results.append(DownloadResult(canonical_name=filename, local_path=path))
    return results
