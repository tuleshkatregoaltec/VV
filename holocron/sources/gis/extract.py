"""DDA planning map extraction logic."""

from __future__ import annotations

import csv
import html as html_lib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from dagster import get_dagster_logger

from holocron.framework.csv_utils import write_csv

_BASE_URL = "https://gis.dda.gov.ae"
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


def _log(message: str) -> None:
    get_dagster_logger().info(message)
    print(message, flush=True)


def _fetch_token(client: httpx.Client) -> str:
    _log("dda: fetching planning map token")
    response = client.get(f"{_BASE_URL}/DIS", headers=_HEADERS)
    response.raise_for_status()
    match = re.search(r'"AGSToken"\s*:\s*"([^"]+)"', response.text)
    if not match:
        raise RuntimeError("Could not extract AGSToken from DIS page HTML")
    _log("dda: fetched planning map token")
    return match.group(1)


def _is_token_error(data: dict) -> bool:
    error = data.get("error") or {}
    return error.get("code") in {498, 499}


def _strip_tags(text: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _parse_area(text: str) -> tuple[str, str]:
    sqm_match = re.search(r"([\d,]+\.?\d*)\s*M", text)
    sqm = sqm_match.group(1).replace(",", "") if sqm_match else ""
    sqft_match = re.search(r"\(([\d,]+\.?\d*)\s*Ft", text)
    sqft = sqft_match.group(1).replace(",", "") if sqft_match else ""
    return sqm, sqft


def _parse_plot_info(html: str, plot_number: str) -> dict:
    row: dict = {"plot_number": plot_number}
    for match in re.finditer(
        r"<label[^>]*>([^<]+)</label>\s*<div[^>]*form-info-dda[^>]*>(.*?)</div>",
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        label = match.group(1).strip()
        value = _strip_tags(match.group(2)).replace("\xa0", " ")

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

    for match in re.finditer(
        r"<td[^>]*>Side (\d+)</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>",
        html,
        re.IGNORECASE,
    ):
        side = match.group(1)
        row[f"side{side}_building"] = match.group(2).strip()
        row[f"side{side}_podium"] = match.group(3).strip()

    land_use = [
        {"type": land_type.strip(), "use": land_use.strip()}
        for land_type, land_use in re.findall(
            r"<li>\s*<b>([^<]+)</b>:\s*([^<]+)</li>", html, re.IGNORECASE
        )
    ]
    row["land_use"] = json.dumps(land_use)

    notes_match = re.search(
        r"General Notes</div>(.*?)(?:<div class=\"section-header|<div class=\"w-100 overflow-auto)",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if notes_match:
        row["general_notes"] = " | ".join(
            note.strip() for note in re.findall(r"<li[^>]*>([^<]+)</li>", notes_match.group(1))
        )
    else:
        row["general_notes"] = ""

    coords = [
        [float(east), float(north)]
        for east, north in re.findall(
            r"<td[^>]*>\d+</td>\s*<td[^>]*>([\d.]+)</td>\s*<td[^>]*>([\d.]+)</td>",
            html,
            re.IGNORECASE,
        )
    ]
    row["coordinates"] = json.dumps(coords)
    return row


def _fetch_plot_info(client: httpx.Client, plot: dict) -> dict:
    plot_number = plot["PLOT_NUMBER"]
    base = {
        "plot_number": plot_number,
        "old_numbers": plot.get("OLD_PLOT_NUMBERS") or "",
        "landuse_symbols": plot.get("LANDUSE_SYMBOLS") or "",
        "gfa_type": plot.get("GFA_TYPE") or "",
        "is_verified": str(plot.get("IS_VERIFIED") or ""),
        "verify_comments": plot.get("VERIFY_COMMENTS") or "",
    }

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.get(
                f"{_BASE_URL}/DIS",
                params={"handler": "PlotInfo", "plotNumber": plot_number},
                headers=_HEADERS,
                timeout=30,
            )
            response.raise_for_status()
            if "form-info-dda" not in response.text:
                raise ValueError("Unexpected response (possible WAF block)")
            return {**base, **_parse_plot_info(response.text, plot_number)}
        except Exception as exc:
            if attempt == _MAX_RETRIES:
                _log(f"dda: plot {plot_number} failed after {_MAX_RETRIES} attempts: {exc}")
                return base
            time.sleep(2**attempt)

    return base


def scrape(output: Path, concurrency: int = 20, max_plots: int | None = None) -> None:
    done_plots: set[str] = set()
    if output.exists():
        with output.open(encoding="utf-8") as handle:
            done_plots = {
                row["plot_number"] for row in csv.DictReader(handle) if row.get("plot_number")
            }
        if done_plots:
            _log(f"dda: resuming plot scrape with {len(done_plots)} plots already in {output}")

    with httpx.Client(timeout=60, follow_redirects=True) as client:
        token = _fetch_token(client)
        fetch_limit = None if max_plots is None else len(done_plots) + max_plots
        _log(
            "dda: fetching plot layer 13 features"
            + (f" with max_plots={max_plots}" if max_plots is not None else "")
        )
        raw = _fetch_all_layer_features(
            client,
            token,
            13,
            out_fields=(
                "PLOT_NUMBER,OLD_PLOT_NUMBERS,LANDUSE_SYMBOLS,GFA_TYPE,IS_VERIFIED,VERIFY_COMMENTS"
            ),
            out_sr=None,
            return_geometry=False,
            limit=fetch_limit,
            layer_name="plots",
        )
        all_plots = [f["attributes"] for f in raw]
        _log(f"dda: fetched {len(all_plots)} plot records from ArcGIS layer 13")

        pending = [plot for plot in all_plots if plot["PLOT_NUMBER"] not in done_plots]
        if max_plots is not None:
            pending = pending[:max_plots]
        target_total = len(done_plots) + len(pending)
        worker_count = max(1, concurrency)
        _log(
            f"dda: starting plot detail fetch for {len(pending)} pending plots "
            f"with workers={worker_count}"
        )

        write_mode = "a" if done_plots else "w"
        with output.open(write_mode, newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
            if not done_plots:
                writer.writeheader()

            completed = len(done_plots)
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [executor.submit(_fetch_plot_info, client, plot) for plot in pending]
                for future in as_completed(futures):
                    row = future.result()
                    writer.writerow(row)
                    handle.flush()
                    completed += 1
                    if (
                        completed % 100 == 0
                        or completed == target_total
                        or completed == len(done_plots) + 1
                    ):
                        _log(f"dda: plot detail progress {completed}/{target_total}")

        _log(f"dda: wrote plot details to {output}")


def _fetch_all_layer_features(
    client: httpx.Client,
    token: str,
    layer_id: int,
    *,
    out_fields: str = "*",
    out_sr: int | None = 4326,
    where: str = "1=1",
    return_geometry: bool = True,
    limit: int | None = None,
    layer_name: str | None = None,
) -> list[dict]:
    features: list[dict] = []
    offset = 0
    current_token = token
    token_refreshes = 0
    label = layer_name or f"layer {layer_id}"
    _log(f"dda: starting {label} fetch (layer_id={layer_id})")

    while True:
        params = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true" if return_geometry else "false",
            "resultRecordCount": _PAGE_SIZE,
            "resultOffset": offset,
            "f": "json",
            "token": current_token,
        }
        if out_sr is not None:
            params["outSR"] = str(out_sr)

        response = client.get(
            f"{_BASE_URL}/server/rest/services/DIS/MAIN_MAP/MapServer/{layer_id}/query",
            params=params,
            headers=_HEADERS,
        )
        response.raise_for_status()
        data = response.json()
        if _is_token_error(data):
            token_refreshes += 1
            if token_refreshes > _MAX_RETRIES:
                raise RuntimeError(
                    f"ArcGIS token refresh failed {token_refreshes} times for layer {layer_id}"
                )
            _log(
                f"dda: token expired while fetching {label}; refreshing token "
                f"({token_refreshes}/{_MAX_RETRIES})"
            )
            current_token = _fetch_token(client)
            continue
        token_refreshes = 0
        if "error" in data:
            raise RuntimeError(f"ArcGIS error for layer {layer_id}: {data['error']}")

        batch = data.get("features", [])
        if not batch:
            break
        features.extend(batch)
        _log(
            f"dda: {label} fetched batch offset={offset} batch_size={len(batch)} total={len(features)}"
        )
        if limit is not None and len(features) >= limit:
            features = features[:limit]
            break
        if len(batch) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    _log(f"dda: completed {label} fetch with {len(features)} features")
    return features


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def scrape_project_areas(client: httpx.Client, token: str, output: Path) -> None:
    features = _fetch_all_layer_features(
        client,
        token,
        10,
        out_fields="OBJECTID,ProjectName",
        layer_name="project_areas",
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
    _log(f"dda: wrote {len(rows)} project areas to {output}")


def scrape_subproject_areas(client: httpx.Client, token: str, output: Path) -> None:
    features = _fetch_all_layer_features(client, token, 11, layer_name="subproject_areas")
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
    _log(f"dda: wrote {len(rows)} subproject areas to {output}")


def scrape_building_limits(client: httpx.Client, token: str, output: Path) -> None:
    features = _fetch_all_layer_features(
        client,
        token,
        8,
        out_fields="OBJECTID,PlotNumber",
        layer_name="plot_building_limits",
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
    _log(f"dda: wrote {len(rows)} building limits to {output}")


def scrape_podium_limits(client: httpx.Client, token: str, output: Path) -> None:
    features = _fetch_all_layer_features(
        client,
        token,
        9,
        out_fields="OBJECTID,PlotNumber,MaxHeight",
        layer_name="plot_podium_limits",
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
    _log(f"dda: wrote {len(rows)} podium limits to {output}")


def scrape_plot_features(client: httpx.Client, token: str, output: Path) -> None:
    features = _fetch_all_layer_features(
        client,
        token,
        7,
        out_fields="OBJECTID,FeatureType,PlotNumber,SHAPE.STArea(),SHAPE.STLength()",
        layer_name="plot_features",
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
    _log(f"dda: wrote {len(rows)} plot features to {output}")


def scrape_frozen_plots(client: httpx.Client, token: str, output: Path) -> None:
    features = _fetch_all_layer_features(
        client,
        token,
        16,
        out_fields=(
            "OBJECTID,PLOT_NUMBER,OLD_PLOT_NUMBERS,IS_FROZEN,"
            "SHAPE.STArea(),SHAPE.STLength(),GFA_TYPE,GFA_SQM_T,GFA_SQFT_T"
        ),
        layer_name="frozen_plots",
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
    _log(f"dda: wrote {len(rows)} frozen plots to {output}")


def scrape_landuse_symbols(client: httpx.Client, token: str, output: Path) -> None:
    features = _fetch_all_layer_features(
        client,
        token,
        15,
        out_fields="OBJECTID,LANDUSE,LANDUSE_CHARACTER,LANDUSE_ID",
        layer_name="landuse_symbols",
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
    _log(f"dda: wrote {len(rows)} landuse symbols to {output}")


def scrape_plot_built_to_lines(client: httpx.Client, token: str, output: Path) -> None:
    features = _fetch_all_layer_features(
        client,
        token,
        4,
        out_fields="OBJECTID,PlotNumber",
        layer_name="plot_built_to_lines",
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
    _log(f"dda: wrote {len(rows)} built-to-line records to {output}")


def scrape_plot_arcades(client: httpx.Client, token: str, output: Path) -> None:
    features = _fetch_all_layer_features(
        client,
        token,
        5,
        out_fields="OBJECTID,PlotNumber",
        layer_name="plot_arcades",
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
    _log(f"dda: wrote {len(rows)} arcade records to {output}")


def scrape_plot_retail(client: httpx.Client, token: str, output: Path) -> None:
    features = _fetch_all_layer_features(
        client,
        token,
        6,
        out_fields="OBJECTID,PlotNumber",
        layer_name="plot_retail",
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
    _log(f"dda: wrote {len(rows)} plot retail records to {output}")


def _skip_if_done(output: Path, label: str) -> bool:
    if output.exists() and output.stat().st_size > 0:
        _log(f"dda: skipping {label} (already complete at {output})")
        return True
    return False


def scrape_all_layers(output_dir: Path, concurrency: int, max_plots: int | None) -> None:
    _log(f"dda: starting full scrape into {output_dir}")
    scrape(
        output=output_dir / "dda_plots.csv",
        concurrency=concurrency,
        max_plots=max_plots,
    )
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        token = _fetch_token(client)
        layers = [
            ("dda_project_areas.csv", scrape_project_areas, "project_areas"),
            ("dda_subproject_areas.csv", scrape_subproject_areas, "subproject_areas"),
            ("dda_plot_building_limits.csv", scrape_building_limits, "plot_building_limits"),
            ("dda_plot_podium_limits.csv", scrape_podium_limits, "plot_podium_limits"),
            ("dda_plot_features.csv", scrape_plot_features, "plot_features"),
            ("dda_frozen_plots.csv", scrape_frozen_plots, "frozen_plots"),
            ("dda_landuse_symbols.csv", scrape_landuse_symbols, "landuse_symbols"),
            ("dda_plot_built_to_lines.csv", scrape_plot_built_to_lines, "plot_built_to_lines"),
            ("dda_plot_arcades.csv", scrape_plot_arcades, "plot_arcades"),
            ("dda_plot_retail.csv", scrape_plot_retail, "plot_retail"),
        ]
        for filename, fn, label in layers:
            output = output_dir / filename
            if not _skip_if_done(output, label):
                fn(client, token, output)
    _log("dda: completed full scrape")
