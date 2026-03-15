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

from etl.lib.csv_utils import write_csv

log = logging.getLogger(__name__)

_BASE_URL = "https://gis.dda.gov.ae"
_PLOT_LAYER_URL = f"{_BASE_URL}/server/rest/services/DIS/MAIN_MAP/MapServer/13"
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


def _is_token_error(data: dict) -> bool:
    error = data.get("error") or {}
    return error.get("code") in {498, 499}


async def _fetch_all_plots(
    client: httpx.AsyncClient,
    token: str,
    limit: int | None = None,
) -> list[dict]:
    plots: list[dict] = []
    offset = 0
    current_token = token
    token_refreshes = 0
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
                "token": current_token,
            },
            headers=_HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
        if _is_token_error(data):
            token_refreshes += 1
            if token_refreshes > _MAX_RETRIES:
                raise RuntimeError(
                    f"ArcGIS token refresh failed {token_refreshes} times for plot layer"
                )
            log.info("Refreshing ArcGIS token for plot layer pagination")
            current_token = await _fetch_token(client)
            continue
        token_refreshes = 0
        if "error" in data:
            raise RuntimeError(f"ArcGIS error: {data['error']}")
        features = data.get("features", [])
        if not features:
            break
        plots.extend(f["attributes"] for f in features)
        if limit is not None and len(plots) >= limit:
            plots = plots[:limit]
            break
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
        html,
        re.IGNORECASE,
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
        html,
        re.DOTALL | re.IGNORECASE,
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
            html,
            re.IGNORECASE,
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
                await asyncio.sleep(2**attempt)

    return base  # unreachable


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def scrape(output: Path, concurrency: int = 15, max_plots: int | None = None) -> None:
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
        fetch_limit = None if max_plots is None else len(done_plots) + max_plots
        all_plots = await _fetch_all_plots(client, token, limit=fetch_limit)

        pending = [p for p in all_plots if p["PLOT_NUMBER"] not in done_plots]
        if max_plots is not None:
            pending = pending[:max_plots]
        total = len(all_plots)
        target_total = len(done_plots) + len(pending)
        log.info(
            f"{len(pending)} plots to fetch "
            f"({total - len(done_plots) - len(pending)} skipped by limit, "
            f"{len(done_plots)} already done)"
        )

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
                if completed % 100 == 0 or completed == target_total:
                    log.info(
                        f"Progress: {completed}/{target_total} ({100 * completed // target_total}%)"
                    )

    log.info(f"GIS scrape complete: {target_total} plots written → {output}")


# ---------------------------------------------------------------------------
# Project polygon scraper (layer 10 — "Project Limit Outline")
# ---------------------------------------------------------------------------

PROJECT_CSV_FIELDS = ["object_id", "project_name", "rings"]
SUBPROJECT_CSV_FIELDS = [
    "object_id",
    "project_id",
    "project_name",
    "entity_name",
    "developer_name",
    "master_project_name",
    "original_plot_number",
    "project_logo",
    "rings",
]
BUILDING_LIMIT_CSV_FIELDS = ["object_id", "plot_number", "rings"]
PODIUM_LIMIT_CSV_FIELDS = ["object_id", "plot_number", "max_height", "rings"]
PLOT_FEATURE_CSV_FIELDS = [
    "object_id",
    "plot_number",
    "feature_type_code",
    "feature_type_label",
    "feature_area_sqm",
    "feature_perimeter_m",
    "rings",
]
FROZEN_PLOT_CSV_FIELDS = [
    "object_id",
    "plot_number",
    "old_plot_numbers",
    "is_frozen",
    "plot_area_sqm",
    "plot_perimeter_m",
    "gfa_type",
    "gfa_sqm_t",
    "gfa_sqft_t",
    "rings",
]
LANDUSE_SYMBOL_CSV_FIELDS = [
    "object_id",
    "landuse",
    "landuse_character",
    "landuse_id",
    "lat",
    "lng",
]
PLOT_BUILT_TO_LINE_CSV_FIELDS = ["object_id", "plot_number", "paths"]
PLOT_ARCADE_CSV_FIELDS = ["object_id", "plot_number", "rings"]
PLOT_RETAIL_CSV_FIELDS = ["object_id", "plot_number", "rings"]

PLOT_FEATURE_LABELS = {
    1: "No Construction Allowed",
    2: "Affected Area",
    3: "Basement Limit",
    4: "Frozen Area",
    5: "Reserved Corridor",
    6: "Easement Limit",
    7: "Pedestrian Interface",
    8: "Walkway",
    9: "Loading Area",
    10: "Landscape",
    11: "Optional Podium",
    12: "Low Rise Zone",
    13: "Restricted Build Zone",
    14: "Parking Structure",
    15: "Parking Area",
    16: "Structure Limit",
    17: "Allocated Underground Parking",
}


async def _fetch_all_layer_features(
    client: httpx.AsyncClient,
    token: str,
    layer_id: int,
    *,
    out_fields: str = "*",
    out_sr: int | None = 4326,
    where: str = "1=1",
) -> list[dict]:
    features: list[dict] = []
    offset = 0
    current_token = token
    token_refreshes = 0

    while True:
        params = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true",
            "resultRecordCount": _PAGE_SIZE,
            "resultOffset": offset,
            "f": "json",
            "token": current_token,
        }
        if out_sr is not None:
            params["outSR"] = str(out_sr)

        resp = await client.get(
            f"{_BASE_URL}/server/rest/services/DIS/MAIN_MAP/MapServer/{layer_id}/query",
            params=params,
            headers=_HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
        if _is_token_error(data):
            token_refreshes += 1
            if token_refreshes > _MAX_RETRIES:
                raise RuntimeError(
                    f"ArcGIS token refresh failed {token_refreshes} times for layer {layer_id}"
                )
            log.info(f"Refreshing ArcGIS token for layer {layer_id}")
            current_token = await _fetch_token(client)
            continue
        token_refreshes = 0
        if "error" in data:
            raise RuntimeError(f"ArcGIS error for layer {layer_id}: {data['error']}")

        batch = data.get("features", [])
        if not batch:
            break

        features.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    return features


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


async def scrape_project_areas(output: Path) -> None:
    """Fetch project area polygons from layer 10 and write them to CSV."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        token = await _fetch_token(client)
        features = await _fetch_all_layer_features(
            client,
            token,
            10,
            out_fields="OBJECTID,ProjectName",
        )

    rows = [
        {
            "object_id": feat.get("attributes", {}).get("OBJECTID", ""),
            "project_name": feat.get("attributes", {}).get("ProjectName", ""),
            "rings": _json_dumps(feat.get("geometry", {}).get("rings", [])),
        }
        for feat in features
    ]
    write_csv(output, PROJECT_CSV_FIELDS, rows)
    log.info(f"Project area scrape complete: {len(rows)} rows → {output}")


async def scrape_subproject_areas(output: Path) -> None:
    """Fetch subproject polygons and attached metadata from layer 11."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        token = await _fetch_token(client)
        features = await _fetch_all_layer_features(client, token, 11)

    rows = []
    for feat in features:
        attrs = feat.get("attributes", {})
        rows.append(
            {
                "object_id": attrs.get("OBJECTID", ""),
                "project_id": attrs.get("ProjectID") or "",
                "project_name": attrs.get("ProjectName") or "",
                "entity_name": attrs.get("EntityName") or "",
                "developer_name": attrs.get("DeveloperName") or "",
                "master_project_name": attrs.get("MasterProjectName") or "",
                "original_plot_number": attrs.get("OriginalPlotNumber") or "",
                "project_logo": attrs.get("ProjectLogo") or "",
                "rings": _json_dumps(feat.get("geometry", {}).get("rings", [])),
            }
        )

    write_csv(output, SUBPROJECT_CSV_FIELDS, rows)
    log.info(f"Subproject area scrape complete: {len(rows)} rows → {output}")


async def scrape_building_limits(output: Path) -> None:
    """Fetch per-plot building envelopes from layer 8."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        token = await _fetch_token(client)
        features = await _fetch_all_layer_features(
            client,
            token,
            8,
            out_fields="OBJECTID,PlotNumber",
        )

    rows = [
        {
            "object_id": feat.get("attributes", {}).get("OBJECTID", ""),
            "plot_number": feat.get("attributes", {}).get("PlotNumber") or "",
            "rings": _json_dumps(feat.get("geometry", {}).get("rings", [])),
        }
        for feat in features
    ]
    write_csv(output, BUILDING_LIMIT_CSV_FIELDS, rows)
    log.info(f"Building limit scrape complete: {len(rows)} rows → {output}")


async def scrape_podium_limits(output: Path) -> None:
    """Fetch per-plot podium envelopes from layer 9."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        token = await _fetch_token(client)
        features = await _fetch_all_layer_features(
            client,
            token,
            9,
            out_fields="OBJECTID,PlotNumber,MaxHeight",
        )

    rows = []
    for feat in features:
        attrs = feat.get("attributes", {})
        rows.append(
            {
                "object_id": attrs.get("OBJECTID", ""),
                "plot_number": attrs.get("PlotNumber") or "",
                "max_height": attrs.get("MaxHeight") or "",
                "rings": _json_dumps(feat.get("geometry", {}).get("rings", [])),
            }
        )

    write_csv(output, PODIUM_LIMIT_CSV_FIELDS, rows)
    log.info(f"Podium limit scrape complete: {len(rows)} rows → {output}")


async def scrape_plot_features(output: Path) -> None:
    """Fetch plot feature overlays from layer 7 with decoded feature labels."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        token = await _fetch_token(client)
        features = await _fetch_all_layer_features(
            client,
            token,
            7,
            out_fields="OBJECTID,FeatureType,PlotNumber,SHAPE.STArea(),SHAPE.STLength()",
        )

    rows = []
    for feat in features:
        attrs = feat.get("attributes", {})
        feature_type = attrs.get("FeatureType")
        rows.append(
            {
                "object_id": attrs.get("OBJECTID", ""),
                "plot_number": attrs.get("PlotNumber") or "",
                "feature_type_code": feature_type if feature_type is not None else "",
                "feature_type_label": PLOT_FEATURE_LABELS.get(feature_type, ""),
                "feature_area_sqm": attrs.get("SHAPE.STArea()") or 0,
                "feature_perimeter_m": attrs.get("SHAPE.STLength()") or 0,
                "rings": _json_dumps(feat.get("geometry", {}).get("rings", [])),
            }
        )

    write_csv(output, PLOT_FEATURE_CSV_FIELDS, rows)
    log.info(f"Plot feature scrape complete: {len(rows)} rows → {output}")


async def scrape_frozen_plots(output: Path) -> None:
    """Fetch frozen-plot polygons from layer 16."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        token = await _fetch_token(client)
        features = await _fetch_all_layer_features(
            client,
            token,
            16,
            out_fields=(
                "OBJECTID,PLOT_NUMBER,OLD_PLOT_NUMBERS,IS_FROZEN,"
                "SHAPE.STArea(),SHAPE.STLength(),GFA_TYPE,GFA_SQM_T,GFA_SQFT_T"
            ),
        )

    rows = []
    for feat in features:
        attrs = feat.get("attributes", {})
        rows.append(
            {
                "object_id": attrs.get("OBJECTID", ""),
                "plot_number": attrs.get("PLOT_NUMBER") or "",
                "old_plot_numbers": attrs.get("OLD_PLOT_NUMBERS") or "",
                "is_frozen": attrs.get("IS_FROZEN") or 0,
                "plot_area_sqm": attrs.get("SHAPE.STArea()") or 0,
                "plot_perimeter_m": attrs.get("SHAPE.STLength()") or 0,
                "gfa_type": attrs.get("GFA_TYPE") or "",
                "gfa_sqm_t": attrs.get("GFA_SQM_T") or "",
                "gfa_sqft_t": attrs.get("GFA_SQFT_T") or "",
                "rings": _json_dumps(feat.get("geometry", {}).get("rings", [])),
            }
        )

    write_csv(output, FROZEN_PLOT_CSV_FIELDS, rows)
    log.info(f"Frozen plot scrape complete: {len(rows)} rows → {output}")


async def scrape_landuse_symbols(output: Path) -> None:
    """Fetch land-use symbol lookup points from layer 15."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        token = await _fetch_token(client)
        features = await _fetch_all_layer_features(
            client,
            token,
            15,
            out_fields="OBJECTID,LANDUSE,LANDUSE_CHARACTER,LANDUSE_ID",
        )

    rows = []
    for feat in features:
        attrs = feat.get("attributes", {})
        geom = feat.get("geometry", {})
        rows.append(
            {
                "object_id": attrs.get("OBJECTID", ""),
                "landuse": attrs.get("LANDUSE") or "",
                "landuse_character": attrs.get("LANDUSE_CHARACTER") or "",
                "landuse_id": attrs.get("LANDUSE_ID") or "",
                "lat": geom.get("y") or 0,
                "lng": geom.get("x") or 0,
            }
        )

    write_csv(output, LANDUSE_SYMBOL_CSV_FIELDS, rows)
    log.info(f"Land-use symbol scrape complete: {len(rows)} rows → {output}")


async def scrape_plot_built_to_lines(output: Path) -> None:
    """Fetch built-to-line guides from layer 4."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        token = await _fetch_token(client)
        features = await _fetch_all_layer_features(
            client,
            token,
            4,
            out_fields="OBJECTID,PlotNumber",
        )

    rows = [
        {
            "object_id": feat.get("attributes", {}).get("OBJECTID", ""),
            "plot_number": feat.get("attributes", {}).get("PlotNumber") or "",
            "paths": _json_dumps(feat.get("geometry", {}).get("paths", [])),
        }
        for feat in features
    ]

    write_csv(output, PLOT_BUILT_TO_LINE_CSV_FIELDS, rows)
    log.info(f"Built-to-line scrape complete: {len(rows)} rows → {output}")


async def scrape_plot_arcades(output: Path) -> None:
    """Fetch arcade polygons from layer 5."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        token = await _fetch_token(client)
        features = await _fetch_all_layer_features(
            client,
            token,
            5,
            out_fields="OBJECTID,PlotNumber",
        )

    rows = [
        {
            "object_id": feat.get("attributes", {}).get("OBJECTID", ""),
            "plot_number": feat.get("attributes", {}).get("PlotNumber") or "",
            "rings": _json_dumps(feat.get("geometry", {}).get("rings", [])),
        }
        for feat in features
    ]

    write_csv(output, PLOT_ARCADE_CSV_FIELDS, rows)
    log.info(f"Arcade scrape complete: {len(rows)} rows → {output}")


async def scrape_plot_retail(output: Path) -> None:
    """Fetch retail polygons from layer 6."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        token = await _fetch_token(client)
        features = await _fetch_all_layer_features(
            client,
            token,
            6,
            out_fields="OBJECTID,PlotNumber",
        )

    rows = [
        {
            "object_id": feat.get("attributes", {}).get("OBJECTID", ""),
            "plot_number": feat.get("attributes", {}).get("PlotNumber") or "",
            "rings": _json_dumps(feat.get("geometry", {}).get("rings", [])),
        }
        for feat in features
    ]

    write_csv(output, PLOT_RETAIL_CSV_FIELDS, rows)
    log.info(f"Retail scrape complete: {len(rows)} rows → {output}")
