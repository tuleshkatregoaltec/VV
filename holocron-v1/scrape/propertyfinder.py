"""Shared Property Finder scraping helpers."""

from __future__ import annotations

import json
import re
from typing import Any

from holocron.scrape.diagnostics import DiagnosticsCollector

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

JSON_HEADERS = {**DEFAULT_HEADERS, "Accept": "application/json", "x-nextjs-data": "1"}

NEXT_DATA_PATTERN = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
SITEMAP_LOC_PATTERN = re.compile(r"<loc>(.*?)</loc>")


def fetch_text(
    http,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    proxy: str = "",
    diagnostics: DiagnosticsCollector | None = None,
    failure_label: str = "",
) -> str:
    response = http.get(
        url,
        headers=headers or DEFAULT_HEADERS,
        proxy=proxy,
        diagnostics=diagnostics,
        failure_label=failure_label or "propertyfinder_html",
    )
    return response.text


def fetch_json(
    http,
    url: str,
    *,
    proxy: str = "",
    diagnostics: DiagnosticsCollector | None = None,
    failure_label: str = "",
) -> dict[str, Any]:
    response = http.get(
        url,
        headers=JSON_HEADERS,
        proxy=proxy,
        diagnostics=diagnostics,
        failure_label=failure_label or "propertyfinder_json",
    )
    return response.json()


def extract_next_data(html: str) -> dict[str, Any]:
    match = NEXT_DATA_PATTERN.search(html)
    if match is None:
        raise ValueError("Property Finder page missing __NEXT_DATA__ payload")
    return json.loads(match.group(1))


def parse_generic_location_urls(xml_text: str, *, purpose: str) -> list[str]:
    marker = GENERIC_PAGE_MARKERS[purpose]
    urls: list[str] = []
    seen: set[str] = set()
    for url in SITEMAP_LOC_PATTERN.findall(xml_text):
        if marker not in url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def collect_location_urls(
    http,
    *,
    purpose: str,
    max_pages_per_purpose: int | None,
    proxy: str = "",
    diagnostics: DiagnosticsCollector | None = None,
) -> list[str]:
    sitemap_xml = fetch_text(
        http,
        SITEMAP_URLS[purpose],
        proxy=proxy,
        diagnostics=diagnostics,
        failure_label=f"propertyfinder_sitemap_{purpose}",
    )
    urls = parse_generic_location_urls(sitemap_xml, purpose=purpose)
    if max_pages_per_purpose is not None:
        return urls[:max_pages_per_purpose]
    return urls
