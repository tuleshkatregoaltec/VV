"""Property Finder location hierarchy extraction logic."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, fields
import json
import re
from pathlib import Path
from typing import Any

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

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

NEXT_DATA_PATTERN = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)

SITEMAP_LOC_PATTERN = re.compile(r"<loc>(.*?)</loc>")


@dataclass(frozen=True)
class RawLocationRecord:
    purpose: str
    source_url: str
    pf_location_id: str
    location_name: str
    alternate_name: str
    path_ids: str
    path_names_en: str
    level_type: str
    slug: str
    city_slug: str
    is_transaction_visible: int
    is_community_visible: int
    is_subcommunity_visible: int
    is_in_cms: int
    breadcrumbs_json: str


@dataclass(frozen=True)
class PfLocationRow:
    release_id: str
    scraped_at: str
    pf_location_id: str
    parent_pf_location_id: str
    city_pf_location_id: str
    path_ids: str
    path_depth: int
    level_type: str
    location_name: str
    alternate_name: str
    slug: str
    city_slug: str
    parent_path_name_en: str
    full_path_name_en: str
    breadcrumbs_json: str
    is_transaction_visible: int
    is_community_visible: int
    is_subcommunity_visible: int
    is_in_cms: int
    seen_in_buy: int
    seen_in_rent: int
    buy_listing_url: str
    rent_listing_url: str


_utc_now_sql = utc_now_sql


def _slug_from_url(url: str, marker: str) -> str:
    return url.split(marker, 1)[1].removesuffix(".html")


def _extract_next_data(html: str) -> dict[str, Any]:
    match = NEXT_DATA_PATTERN.search(html)
    if match is None:
        raise ValueError("Property Finder page missing __NEXT_DATA__ payload")
    return json.loads(match.group(1))


def _fetch_text(http, url: str) -> str:
    response = http.get(url, headers=DEFAULT_HEADERS)
    return response.text


def _parse_generic_location_urls(xml_text: str, *, purpose: str) -> list[str]:
    marker = GENERIC_PAGE_MARKERS[purpose]
    urls: list[str] = []
    seen: set[str] = set()
    for url in SITEMAP_LOC_PATTERN.findall(xml_text):
        if marker not in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _extract_location_record(*, purpose: str, source_url: str, html: str) -> RawLocationRecord:
    payload = _extract_next_data(html)
    page_props = payload["props"]["pageProps"]
    location = page_props["filtersValueFromQuery"]["filter[locations_ids]"][0]
    breadcrumbs = page_props.get("breadCrumbs", [])
    return RawLocationRecord(
        purpose=purpose,
        source_url=source_url,
        pf_location_id=str(location.get("id", "")).strip(),
        location_name=str(location.get("n", "")).strip(),
        alternate_name=str(location.get("a", "")).strip(),
        path_ids=str(location.get("p", "")).strip(),
        path_names_en=str(location.get("en_p_n", "")).strip(),
        level_type=str(location.get("l_t", "")).strip(),
        slug=str(location.get("en_s") or location.get("s") or "").strip(),
        city_slug=str(location.get("en_c_s", "")).strip(),
        is_transaction_visible=1 if bool(location.get("i_t_v")) else 0,
        is_community_visible=1 if bool(location.get("i_c_v")) else 0,
        is_subcommunity_visible=1 if bool(location.get("i_sc_v")) else 0,
        is_in_cms=1 if bool(location.get("is_in_cms")) else 0,
        breadcrumbs_json=json.dumps(breadcrumbs, ensure_ascii=False, separators=(",", ":")),
    )


def _fetch_record(http, *, purpose: str, url: str) -> RawLocationRecord:
    html = _fetch_text(http, url)
    return _extract_location_record(purpose=purpose, source_url=url, html=html)


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


def _path_depth(path_ids: str) -> int:
    return len([part for part in path_ids.split(".") if part])


def _full_path_name(record: RawLocationRecord) -> str:
    parent_names = record.path_names_en.strip()
    if not parent_names:
        return record.location_name
    return f"{parent_names}, {record.location_name}"


def _merge_records(run_id: str, records: list[RawLocationRecord]) -> list[PfLocationRow]:
    by_id: dict[str, list[RawLocationRecord]] = {}
    for record in records:
        by_id.setdefault(record.pf_location_id, []).append(record)

    scraped_at = _utc_now_sql()
    rows: list[PfLocationRow] = []
    for pf_location_id in sorted(by_id, key=lambda value: (len(value), value)):
        grouped = by_id[pf_location_id]
        primary = sorted(
            grouped,
            key=lambda item: (
                _path_depth(item.path_ids),
                item.purpose != "buy",
                len(item.breadcrumbs_json),
            ),
        )[0]
        breadcrumbs = []
        for item in grouped:
            if item.breadcrumbs_json and item.breadcrumbs_json != "[]":
                breadcrumbs = json.loads(item.breadcrumbs_json)
                break
        buy_url = next((item.source_url for item in grouped if item.purpose == "buy"), "")
        rent_url = next((item.source_url for item in grouped if item.purpose == "rent"), "")
        rows.append(
            PfLocationRow(
                release_id=run_id,
                scraped_at=scraped_at,
                pf_location_id=pf_location_id,
                parent_pf_location_id=_parent_id(primary.path_ids),
                city_pf_location_id=_city_id(primary.path_ids),
                path_ids=primary.path_ids,
                path_depth=_path_depth(primary.path_ids),
                level_type=primary.level_type,
                location_name=primary.location_name,
                alternate_name=primary.alternate_name,
                slug=primary.slug,
                city_slug=primary.city_slug,
                parent_path_name_en=primary.path_names_en,
                full_path_name_en=_full_path_name(primary),
                breadcrumbs_json=json.dumps(breadcrumbs, ensure_ascii=False, separators=(",", ":")),
                is_transaction_visible=max(item.is_transaction_visible for item in grouped),
                is_community_visible=max(item.is_community_visible for item in grouped),
                is_subcommunity_visible=max(item.is_subcommunity_visible for item in grouped),
                is_in_cms=max(item.is_in_cms for item in grouped),
                seen_in_buy=1 if any(item.purpose == "buy" for item in grouped) else 0,
                seen_in_rent=1 if any(item.purpose == "rent" for item in grouped) else 0,
                buy_listing_url=buy_url,
                rent_listing_url=rent_url,
            )
        )
    return rows


def _collect_location_urls(http, *, purpose: str, max_pages_per_purpose: int | None) -> list[str]:
    sitemap_xml = _fetch_text(http, SITEMAP_URLS[purpose])
    urls = _parse_generic_location_urls(sitemap_xml, purpose=purpose)
    if max_pages_per_purpose is not None:
        return urls[:max_pages_per_purpose]
    return urls


def download_all(
    *,
    dest_dir: Path,
    run_id: str,
    http,
    max_pages_per_purpose: int | None = None,
    worker_count: int = 8,
    context=None,
) -> list[DownloadResult]:
    urls_by_purpose = {
        purpose: _collect_location_urls(
            http,
            purpose=purpose,
            max_pages_per_purpose=max_pages_per_purpose,
        )
        for purpose in ("buy", "rent")
    }
    if context is not None:
        for purpose, urls in urls_by_purpose.items():
            context.log.info(f"pf_locations: queued {len(urls)} {purpose} listing location pages")

    tasks = [(purpose, url) for purpose in ("buy", "rent") for url in urls_by_purpose[purpose]]
    records: list[RawLocationRecord] = []
    with ThreadPoolExecutor(max_workers=max(1, worker_count)) as executor:
        future_map = {
            executor.submit(_fetch_record, http, purpose=purpose, url=url): (purpose, url)
            for purpose, url in tasks
        }
        for index, future in enumerate(as_completed(future_map), start=1):
            purpose, url = future_map[future]
            record = future.result()
            records.append(record)
            if context is not None and (index <= 5 or index % 250 == 0):
                context.log.info(
                    f"pf_locations: fetched {index}/{len(tasks)} location pages; "
                    f"latest={purpose}:{record.slug}"
                )

    rows = _merge_records(run_id, records)
    csv_path = dest_dir / "pf_locations.csv"
    fieldnames = [field.name for field in fields(PfLocationRow)]
    write_csv(csv_path, fieldnames, (asdict(row) for row in rows))
    if context is not None:
        context.log.info(f"pf_locations: wrote {len(rows):,} unique locations to {csv_path.name}")
    return [DownloadResult(canonical_name=csv_path.name, local_path=csv_path)]
