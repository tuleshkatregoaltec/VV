"""DLD extraction logic local to the DLD source."""

from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

_PORTAL_API_BASE = "https://www.dubaipulse.gov.ae/api/3/action"

DLD_SOURCES: list[tuple[str, str]] = [
    (
        "https://www.dubaipulse.gov.ae/data/dld-transactions/dld_transactions-open",
        "transactions.csv",
    ),
    (
        "https://www.dubaipulse.gov.ae/data/dld-registration/dld_rent_contracts-open",
        "rent_contracts.csv",
    ),
    ("https://www.dubaipulse.gov.ae/data/dld-registration/dld_buildings-open", "buildings.csv"),
    ("https://www.dubaipulse.gov.ae/data/dld-registration/dld_units-open", "units.csv"),
    ("https://www.dubaipulse.gov.ae/data/dld-registration/dld_projects-open", "projects.csv"),
    ("https://www.dubaipulse.gov.ae/data/dld-registration/dld_developers-open", "developers.csv"),
    (
        "https://www.dubaipulse.gov.ae/data/dld-registration/dld_land_registry-open",
        "land_registry.csv",
    ),
]

_DIAG_LOCK = threading.Lock()


@dataclass
class DownloadResult:
    source_url: str
    canonical_name: str
    local_path: Path | None
    blocked: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.local_path is not None


def _new_session(cookie_file: str | None = None) -> requests.Session:
    retry = Retry(
        total=4,
        read=4,
        connect=4,
        status=4,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    if cookie_file:
        try:
            jar = MozillaCookieJar(cookie_file)
            jar.load(ignore_discard=True, ignore_expires=True)
            session.cookies.update(jar)
        except Exception as exc:
            log.warning(f"Could not load cookie file {cookie_file}: {exc}")
    return session


def _random_ua() -> str:
    os_token = random.choice(
        [
            "Windows NT 10.0; Win64; x64",
            "X11; Linux x86_64",
            "Macintosh; Intel Mac OS X 10_15_7",
        ]
    )
    family = random.choice(["chrome", "edge", "firefox"])
    if family == "chrome":
        m, b, p = random.randint(124, 133), random.randint(6200, 6999), random.randint(40, 180)
        return (
            f"Mozilla/5.0 ({os_token}) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{m}.0.{b}.{p} Safari/537.36"
        )
    if family == "edge":
        m, b, p = random.randint(124, 133), random.randint(2500, 3200), random.randint(30, 130)
        return (
            f"Mozilla/5.0 ({os_token}) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{m}.0.{b}.{p} Safari/537.36 Edg/{m}.0.{b}.{p}"
        )
    version = random.randint(124, 136)
    return f"Mozilla/5.0 ({os_token}; rv:{version}.0) Gecko/20100101 Firefox/{version}.0"


def _headers(referer: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {
        "User-Agent": _random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": random.choice(["en-US,en;q=0.9", "en-GB,en;q=0.9"]),
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": random.choice(["max-age=0", "no-cache"]),
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _is_waf_block(html: str) -> bool:
    lower = html.lower()
    return any(
        token in lower for token in ("request rejected", "support id", "access denied", "forbidden")
    )


def _extract_support_id(html: str) -> str | None:
    match = re.search(r"support id is:\s*([0-9]+)", html, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _write_diagnostic(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _DIAG_LOCK:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def _resolve_url_from_html(source_url: str, html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    anchor = soup.find("a", class_="action-icon-anchor", href=True)
    if anchor:
        return urljoin(source_url, str(anchor["href"]))

    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if any(
            token in href.lower() for token in ("download", "resource", ".csv", ".xlsx", ".zip")
        ):
            return urljoin(source_url, href)

    for key in ("download_url", "downloadurl", "resource_url", "file_url"):
        match = re.search(rf'"{key}"\s*:\s*"([^"]+)"', html, flags=re.IGNORECASE)
        if match:
            return urljoin(source_url, match.group(1))

    match = re.search(
        r'href=["\']([^"\']+(?:\.csv|\.xlsx|\.zip)(?:\?[^"\']*)?)["\']',
        html,
        flags=re.IGNORECASE,
    )
    if match:
        return urljoin(source_url, match.group(1))

    return None


def _resolve_url_from_api(
    source_url: str,
    session: requests.Session,
    api_base: str = _PORTAL_API_BASE,
) -> str | None:
    dataset_id = source_url.rstrip("/").split("/")[-1].removesuffix("-open")
    try:
        response = session.get(
            f"{api_base.rstrip('/')}/package_show",
            params={"id": dataset_id},
            headers=_headers(referer=source_url),
            timeout=45,
        )
        response.raise_for_status()
        resources = response.json().get("result", {}).get("resources", [])
        preferred, others = [], []
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            url = resource.get("url", "")
            if not url:
                continue
            fmt = str(resource.get("format", "")).lower()
            (preferred if fmt in {"csv", "xlsx", "xls", "zip", "json"} else others).append(url)
        for url in preferred + others:
            if url:
                log.info(f"Resolved via API: {dataset_id} -> {url}")
                return url
    except Exception as exc:
        log.warning(f"API fallback failed for {dataset_id}: {exc}")
    return None


def _download_one(
    source_url: str,
    canonical_name: str,
    dest_dir: Path,
    cookie_file: str | None,
    api_base: str,
    diagnostics_file: str | None,
) -> DownloadResult:
    session = _new_session(cookie_file)
    try:
        time.sleep(random.uniform(0.15, 0.9))
        page = session.get(source_url, headers=_headers(), timeout=45)
        page.raise_for_status()

        if _is_waf_block(page.text):
            support_id = _extract_support_id(page.text)
            log.warning(
                f"WAF block on source page for {canonical_name} (support_id={support_id}), trying API"
            )
            if diagnostics_file:
                _write_diagnostic(
                    diagnostics_file,
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "phase": "source_page",
                        "source_url": source_url,
                        "status_code": page.status_code,
                        "support_id": support_id,
                        "blocked": True,
                    },
                )
            download_url = _resolve_url_from_api(source_url, session, api_base)
            if not download_url:
                return DownloadResult(
                    source_url, canonical_name, None, blocked=True, error="waf_blocked"
                )
        else:
            download_url = _resolve_url_from_html(source_url, page.text)
            if not download_url:
                log.warning(f"HTML parse found no URL for {canonical_name}, trying API")
                download_url = _resolve_url_from_api(source_url, session, api_base)
            if not download_url:
                return DownloadResult(source_url, canonical_name, None, error="link_not_found")

        response = session.get(
            download_url,
            headers=_headers(referer=source_url),
            stream=True,
            timeout=300,
        )
        response.raise_for_status()

        if "text/html" in response.headers.get("Content-Type", "").lower():
            head = response.text[:2000]
            if _is_waf_block(head):
                support_id = _extract_support_id(head)
                log.error(f"WAF block on file fetch for {canonical_name} (support_id={support_id})")
                if diagnostics_file:
                    _write_diagnostic(
                        diagnostics_file,
                        {
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "phase": "file_fetch",
                            "source_url": source_url,
                            "status_code": response.status_code,
                            "support_id": support_id,
                            "blocked": True,
                        },
                    )
                return DownloadResult(
                    source_url, canonical_name, None, blocked=True, error="waf_blocked_file"
                )

        destination = dest_dir / canonical_name
        size = 0
        with open(destination, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
                    size += len(chunk)

        log.info(f"Downloaded {canonical_name} ({size:,} bytes)")
        return DownloadResult(source_url, canonical_name, destination)
    except Exception as exc:
        log.error(f"Download failed for {canonical_name}: {exc}")
        return DownloadResult(source_url, canonical_name, None, error=str(exc))
    finally:
        session.close()


def preflight_check(
    cookie_file: str | None = None,
    diagnostics_file: str | None = None,
) -> bool:
    session = _new_session(cookie_file)
    try:
        source_url, _ = DLD_SOURCES[0]
        response = session.get(source_url, headers=_headers(), timeout=30)
        if _is_waf_block(response.text):
            support_id = _extract_support_id(response.text)
            log.error(f"Preflight WAF block (support_id={support_id})")
            if diagnostics_file:
                _write_diagnostic(
                    diagnostics_file,
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "phase": "preflight",
                        "source_url": source_url,
                        "status_code": response.status_code,
                        "support_id": support_id,
                        "blocked": True,
                    },
                )
            return False
        return True
    except Exception as exc:
        log.warning(f"Preflight request failed: {exc}")
        return True
    finally:
        session.close()


def download_all(
    dest_dir: Path,
    workers: int = 4,
    api_base: str = _PORTAL_API_BASE,
    cookie_file: str | None = None,
    diagnostics_file: str | None = None,
    skip_preflight: bool = False,
) -> list[DownloadResult]:
    dest_dir.mkdir(parents=True, exist_ok=True)

    if not skip_preflight and not preflight_check(cookie_file, diagnostics_file):
        raise RuntimeError(
            "Dubai Pulse portal is WAF-blocked from this network. "
            "Run from an allowed IP or pass skip_preflight=True."
        )

    results: list[DownloadResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _download_one,
                source_url,
                canonical_name,
                dest_dir,
                cookie_file,
                api_base,
                diagnostics_file,
            ): canonical_name
            for source_url, canonical_name in DLD_SOURCES
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                name = futures[future]
                log.error(f"Worker error for {name}: {exc}")
                results.append(DownloadResult("", name, None, error=str(exc)))

    failed = [result for result in results if not result.ok]
    if failed:
        names = ", ".join(result.canonical_name for result in failed)
        raise RuntimeError(f"Download failed for: {names}")

    return results
