"""Download Dubai Pulse DLD datasets to local files.

Usage from assets:
    from etl.lib.scrapers.dld import download_all
    results = download_all(dest_dir=Path("/tmp/dld"))
"""

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

# (portal_page_url, canonical_filename)
# Order preserved for reproducible output.
DLD_SOURCES: list[tuple[str, str]] = [
    ("https://www.dubaipulse.gov.ae/data/dld-transactions/dld_transactions-open", "transactions.csv"),
    ("https://www.dubaipulse.gov.ae/data/dld-registration/dld_rent_contracts-open", "rent_contracts.csv"),
    ("https://www.dubaipulse.gov.ae/data/dld-registration/dld_buildings-open", "buildings.csv"),
    ("https://www.dubaipulse.gov.ae/data/dld-registration/dld_units-open", "units.csv"),
    ("https://www.dubaipulse.gov.ae/data/dld-registration/dld_projects-open", "projects.csv"),
    ("https://www.dubaipulse.gov.ae/data/dld-registration/dld_developers-open", "developers.csv"),
    ("https://www.dubaipulse.gov.ae/data/dld-registration/dld_land_registry-open", "land_registry.csv"),
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


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

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
    s = requests.Session()
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    if cookie_file:
        try:
            jar = MozillaCookieJar(cookie_file)
            jar.load(ignore_discard=True, ignore_expires=True)
            s.cookies.update(jar)
        except Exception as e:
            log.warning(f"Could not load cookie file {cookie_file}: {e}")
    return s


def _random_ua() -> str:
    os_token = random.choice([
        "Windows NT 10.0; Win64; x64",
        "X11; Linux x86_64",
        "Macintosh; Intel Mac OS X 10_15_7",
    ])
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
    v = random.randint(124, 136)
    return f"Mozilla/5.0 ({os_token}; rv:{v}.0) Gecko/20100101 Firefox/{v}.0"


def _headers(referer: str | None = None) -> dict[str, str]:
    h: dict[str, str] = {
        "User-Agent": _random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": random.choice(["en-US,en;q=0.9", "en-GB,en;q=0.9"]),
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": random.choice(["max-age=0", "no-cache"]),
    }
    if referer:
        h["Referer"] = referer
    return h


def _is_waf_block(html: str) -> bool:
    lower = html.lower()
    return any(k in lower for k in ("request rejected", "support id", "access denied", "forbidden"))


def _extract_support_id(html: str) -> str | None:
    m = re.search(r"support id is:\s*([0-9]+)", html, flags=re.IGNORECASE)
    return m.group(1) if m else None


def _write_diagnostic(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _DIAG_LOCK:
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")


# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------

def _resolve_url_from_html(source_url: str, html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    anchor = soup.find("a", class_="action-icon-anchor", href=True)
    if anchor:
        return urljoin(source_url, str(anchor["href"]))

    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if any(k in href.lower() for k in ("download", "resource", ".csv", ".xlsx", ".zip")):
            return urljoin(source_url, href)

    for key in ("download_url", "downloadurl", "resource_url", "file_url"):
        m = re.search(rf'"{key}"\s*:\s*"([^"]+)"', html, flags=re.IGNORECASE)
        if m:
            return urljoin(source_url, m.group(1))

    m = re.search(
        r'href=["\']([^"\']+(?:\.csv|\.xlsx|\.zip)(?:\?[^"\']*)?)["\']',
        html, flags=re.IGNORECASE,
    )
    if m:
        return urljoin(source_url, m.group(1))

    return None


def _resolve_url_from_api(
    source_url: str,
    session: requests.Session,
    api_base: str = _PORTAL_API_BASE,
) -> str | None:
    dataset_id = source_url.rstrip("/").split("/")[-1].removesuffix("-open")
    try:
        r = session.get(
            f"{api_base.rstrip('/')}/package_show",
            params={"id": dataset_id},
            headers=_headers(referer=source_url),
            timeout=45,
        )
        r.raise_for_status()
        resources = r.json().get("result", {}).get("resources", [])
        preferred, others = [], []
        for res in resources:
            if not isinstance(res, dict):
                continue
            url = res.get("url", "")
            if not url:
                continue
            fmt = str(res.get("format", "")).lower()
            (preferred if fmt in {"csv", "xlsx", "xls", "zip", "json"} else others).append(url)
        for url in preferred + others:
            if url:
                log.info(f"Resolved via API: {dataset_id} → {url}")
                return url
    except Exception as e:
        log.warning(f"API fallback failed for {dataset_id}: {e}")
    return None


# ---------------------------------------------------------------------------
# Core download
# ---------------------------------------------------------------------------

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
            log.warning(f"WAF block on source page for {canonical_name} (support_id={support_id}), trying API")
            if diagnostics_file:
                _write_diagnostic(diagnostics_file, {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "phase": "source_page", "source_url": source_url,
                    "status_code": page.status_code, "support_id": support_id, "blocked": True,
                })
            dl_url = _resolve_url_from_api(source_url, session, api_base)
            if not dl_url:
                return DownloadResult(source_url, canonical_name, None, blocked=True, error="waf_blocked")
        else:
            dl_url = _resolve_url_from_html(source_url, page.text)
            if not dl_url:
                log.warning(f"HTML parse found no URL for {canonical_name}, trying API")
                dl_url = _resolve_url_from_api(source_url, session, api_base)
            if not dl_url:
                return DownloadResult(source_url, canonical_name, None, error="link_not_found")

        r = session.get(dl_url, headers=_headers(referer=source_url), stream=True, timeout=300)
        r.raise_for_status()

        if "text/html" in r.headers.get("Content-Type", "").lower():
            head = r.text[:2000]
            if _is_waf_block(head):
                support_id = _extract_support_id(head)
                log.error(f"WAF block on file fetch for {canonical_name} (support_id={support_id})")
                if diagnostics_file:
                    _write_diagnostic(diagnostics_file, {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "phase": "file_fetch", "source_url": source_url,
                        "status_code": r.status_code, "support_id": support_id, "blocked": True,
                    })
                return DownloadResult(source_url, canonical_name, None, blocked=True, error="waf_blocked_file")

        dest = dest_dir / canonical_name
        size = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    size += len(chunk)

        log.info(f"Downloaded {canonical_name} ({size:,} bytes)")
        return DownloadResult(source_url, canonical_name, dest)

    except Exception as e:
        log.error(f"Download failed for {canonical_name}: {e}")
        return DownloadResult(source_url, canonical_name, None, error=str(e))
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def preflight_check(
    cookie_file: str | None = None,
    diagnostics_file: str | None = None,
) -> bool:
    """Return True if the portal is reachable and not WAF-blocked."""
    session = _new_session(cookie_file)
    try:
        source_url, _ = DLD_SOURCES[0]
        r = session.get(source_url, headers=_headers(), timeout=30)
        if _is_waf_block(r.text):
            support_id = _extract_support_id(r.text)
            log.error(f"Preflight WAF block (support_id={support_id})")
            if diagnostics_file:
                _write_diagnostic(diagnostics_file, {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "phase": "preflight", "source_url": source_url,
                    "status_code": r.status_code, "support_id": support_id, "blocked": True,
                })
            return False
        return True
    except Exception as e:
        log.warning(f"Preflight request failed: {e}")
        return True  # network error ≠ WAF block; let individual downloads fail
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
    """
    Download all DLD source files to dest_dir.
    Each file is saved under its canonical_name (e.g. 'transactions.csv').
    Returns one DownloadResult per source; check result.ok to detect failures.
    """
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
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                name = futures[fut]
                log.error(f"Worker error for {name}: {e}")
                results.append(DownloadResult("", name, None, error=str(e)))

    failed = [r for r in results if not r.ok]
    if failed:
        names = ", ".join(r.canonical_name for r in failed)
        raise RuntimeError(f"Download failed for: {names}")

    return results
