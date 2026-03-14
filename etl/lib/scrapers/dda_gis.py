"""Scrape DDA GIS land plot data from https://gis.dda.gov.ae/DIS.

Usage from assets:
    import asyncio
    from etl.lib.scrapers.dda_gis import scrape
    asyncio.run(scrape(output=Path("/tmp/dda_plots.csv")))

The scraper:
  1. Loads the DIS page to extract the short-lived ArcGIS token
  2. Paginates layer 13 (Plot) to collect all plot numbers + basic fields
  3. Fetches /DIS?handler=PlotInfo for each plot to get full zoning details
  4. Writes one row per plot to CSV

CSV primary key: plot_number
"""

from __future__ import annotations

import asyncio
import csv
import html as html_lib
import json
import logging
import re
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

_BASE_URL = "https://gis.dda.gov.ae"
_PLOT_LAYER_URL = f"{_BASE_URL}/server/rest/services/DIS/MAIN_MAP/MapServer/13"
_PROJECT_LAYER_URL = f"{_BASE_URL}/server/rest/services/DIS/MAIN_MAP/MapServer/10"
_PAGE_SIZE = 2000
_MAX_RETRIES = 3

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": f"{_BASE_URL}/DIS",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CSV_FIELDS = [
    "plot_number",
    "old_numbers",
    "project_name",
    "community_name",
    "master_developer",
    "plot_area_sqm",
    "plot_area_sqft",
    "max_gfa_sqm",
    "max_gfa_sqft",
    "max_height",
    "max_coverage",
    "site_plan_issue_date",
    "site_plan_expiry_date",
    "side1_building",
    "side1_podium",
    "side2_building",
    "side2_podium",
    "side3_building",
    "side3_podium",
    "side4_building",
    "side4_podium",
    "land_use",
    "general_notes",
    "coordinates",
    "landuse_symbols",
    "gfa_type",
    "is_verified",
    "verify_comments",
]


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

async def _fetch_token(client: httpx.AsyncClient) -> str:
    resp = await client.get(f"{_BASE_URL}/DIS", headers=_HEADERS)
    resp.raise_for_status()
    m = re.search(r'"AGSToken"\s*:\s*"([^"]+)"', resp.text)
    if not m:
        raise RuntimeError("Could not extract AGSToken from DIS page HTML")
    return m.group(1)


async def _fetch_all_plots(client: httpx.AsyncClient, token: str) -> list[dict]:
    plots: list[dict] = []
    offset = 0
    while True:
        resp = await client.get(
            f"{_PLOT_LAYER_URL}/query",
            params={
                "where": "1=1",
                "outFields": (
                    "PLOT_NUMBER,OLD_PLOT_NUMBERS,"
                    "LANDUSE_SYMBOLS,GFA_TYPE,IS_VERIFIED,VERIFY_COMMENTS"
                ),
                "returnGeometry": "false",
                "resultRecordCount": _PAGE_SIZE,
                "resultOffset": offset,
                "f": "json",
                "token": token,
            },
            headers=_HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"ArcGIS error: {data['error']}")
        features = data.get("features", [])
        if not features:
            break
        plots.extend(f["attributes"] for f in features)
        log.debug(f"Paginated: {len(plots)} plots so far (offset={offset})")
        if len(features) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    log.info(f"Fetched {len(plots)} plot records from ArcGIS layer")
    return plots


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

def _strip_tags(text: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _parse_area(text: str) -> tuple[str, str]:
    """'18,994.94 M2 (204,459.83 Ft2)' → ('18994.94', '204459.83')"""
    m = re.search(r"([\d,]+\.?\d*)\s*M", text)
    sqm = m.group(1).replace(",", "") if m else ""
    m2 = re.search(r"\(([\d,]+\.?\d*)\s*Ft", text)
    sqft = m2.group(1).replace(",", "") if m2 else ""
    return sqm, sqft


def _parse_plot_info(html: str, plot_number: str) -> dict:
    row: dict = {"plot_number": plot_number}

    for m in re.finditer(
        r"<label[^>]*>([^<]+)</label>\s*<div[^>]*form-info-dda[^>]*>(.*?)</div>",
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        label = m.group(1).strip()
        value = _strip_tags(m.group(2)).replace("\xa0", " ")

        if label == "Old Numbers":
            row["old_numbers"] = value
        elif label == "Project Name":
            row["project_name"] = value
        elif label == "Community Name":
            row["community_name"] = value
        elif label == "Master Developer":
            row["master_developer"] = value
        elif label == "Plot Area":
            row["plot_area_sqm"], row["plot_area_sqft"] = _parse_area(value)
        elif label == "Maximum GFA":
            row["max_gfa_sqm"], row["max_gfa_sqft"] = _parse_area(value)
        elif label == "Maximum Height":
            row["max_height"] = value
        elif label == "Maximum Coverage":
            row["max_coverage"] = value
        elif label == "Site Plan Issue Date":
            row["site_plan_issue_date"] = value
        elif label == "Site Plan Expiry Date":
            row["site_plan_expiry_date"] = value

    for m in re.finditer(
        r"<td[^>]*>Side (\d+)</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>",
        html, re.IGNORECASE,
    ):
        n = m.group(1)
        row[f"side{n}_building"] = m.group(2).strip()
        row[f"side{n}_podium"] = m.group(3).strip()

    land_use = [
        {"type": t.strip(), "use": u.strip()}
        for t, u in re.findall(r"<li>\s*<b>([^<]+)</b>:\s*([^<]+)</li>", html, re.IGNORECASE)
    ]
    row["land_use"] = json.dumps(land_use)

    notes_m = re.search(
        r"General Notes</div>(.*?)(?:<div class=\"section-header|<div class=\"w-100 overflow-auto)",
        html, re.DOTALL | re.IGNORECASE,
    )
    if notes_m:
        row["general_notes"] = " | ".join(
            n.strip() for n in re.findall(r"<li[^>]*>([^<]+)</li>", notes_m.group(1))
        )
    else:
        row["general_notes"] = ""

    coords = [
        [float(e), float(n)]
        for e, n in re.findall(
            r"<td[^>]*>\d+</td>\s*<td[^>]*>([\d.]+)</td>\s*<td[^>]*>([\d.]+)</td>",
            html, re.IGNORECASE,
        )
    ]
    row["coordinates"] = json.dumps(coords)

    return row


# ---------------------------------------------------------------------------
# Plot info fetch with retry
# ---------------------------------------------------------------------------

async def _fetch_plot_info(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    plot: dict,
) -> dict:
    plot_number = plot["PLOT_NUMBER"]
    base = {
        "plot_number": plot_number,
        "old_numbers": plot.get("OLD_PLOT_NUMBERS") or "",
        "landuse_symbols": plot.get("LANDUSE_SYMBOLS") or "",
        "gfa_type": plot.get("GFA_TYPE") or "",
        "is_verified": str(plot.get("IS_VERIFIED") or ""),
        "verify_comments": plot.get("VERIFY_COMMENTS") or "",
    }

    async with sem:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = await client.get(
                    f"{_BASE_URL}/DIS",
                    params={"handler": "PlotInfo", "plotNumber": plot_number},
                    headers=_HEADERS,
                    timeout=30,
                )
                resp.raise_for_status()
                if "form-info-dda" not in resp.text:
                    raise ValueError("Unexpected response (possible WAF block)")
                return {**base, **_parse_plot_info(resp.text, plot_number)}
            except Exception as e:
                if attempt == _MAX_RETRIES:
                    log.warning(f"{plot_number} failed after {_MAX_RETRIES} attempts: {e}")
                    return base
                await asyncio.sleep(2 ** attempt)

    return base  # unreachable


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def scrape(output: Path, concurrency: int = 15) -> None:
    """
    Scrape all DDA GIS plots and write to output CSV.
    Resumes automatically if output already exists with partial data.
    """
    done_plots: set[str] = set()
    if output.exists():
        with output.open(encoding="utf-8") as f:
            done_plots = {r["plot_number"] for r in csv.DictReader(f) if r.get("plot_number")}
        if done_plots:
            log.info(f"Resuming: {len(done_plots)} plots already in {output}")

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        log.info("Fetching ArcGIS token from DIS page")
        token = await _fetch_token(client)

        log.info("Fetching plot list from ArcGIS layer 13")
        all_plots = await _fetch_all_plots(client, token)

        pending = [p for p in all_plots if p["PLOT_NUMBER"] not in done_plots]
        total = len(all_plots)
        log.info(f"{len(pending)} plots to fetch ({total - len(pending)} already done)")

        sem = asyncio.Semaphore(concurrency)
        tasks = [_fetch_plot_info(client, sem, p) for p in pending]

        write_mode = "a" if done_plots else "w"
        with output.open(write_mode, newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
            if not done_plots:
                writer.writeheader()

            completed = len(done_plots)
            for coro in asyncio.as_completed(tasks):
                row = await coro
                writer.writerow(row)
                f.flush()
                completed += 1
                if completed % 100 == 0 or completed == total:
                    log.info(f"Progress: {completed}/{total} ({100 * completed // total}%)")

    log.info(f"GIS scrape complete: {total} plots → {output}")


# ---------------------------------------------------------------------------
# Project polygon scraper (layer 10 — "Project Limit Outline")
# ---------------------------------------------------------------------------

PROJECT_CSV_FIELDS = ["object_id", "project_name", "rings"]


async def scrape_projects(output: Path) -> None:
    """
    Fetch all 208 DDA project polygons from layer 10 and write to output CSV.

    CSV columns:
      object_id    — ArcGIS OBJECTID
      project_name — e.g. "JUMEIRAH BEACH RESIDENCE"
      rings        — JSON array of rings (each ring is [[lon, lat], ...]) in WGS84
    """
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        log.info("Fetching ArcGIS token for project layer")
        token = await _fetch_token(client)

        log.info("Querying project layer 10")
        resp = await client.get(
            f"{_PROJECT_LAYER_URL}/query",
            params={
                "where": "1=1",
                "outFields": "OBJECTID,ProjectName",
                "returnGeometry": "true",
                "outSR": "4326",
                "resultRecordCount": 2000,
                "f": "json",
                "token": token,
            },
            headers=_HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"ArcGIS error: {data['error']}")

        features = data.get("features", [])
        log.info(f"Received {len(features)} project features")

        with output.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=PROJECT_CSV_FIELDS)
            writer.writeheader()
            for feat in features:
                attrs = feat.get("attributes", {})
                geom = feat.get("geometry", {})
                rings = geom.get("rings", [])
                writer.writerow({
                    "object_id": attrs.get("OBJECTID", ""),
                    "project_name": attrs.get("ProjectName", ""),
                    "rings": json.dumps(rings),
                })

    log.info(f"Project scrape complete: {len(features)} projects → {output}")
