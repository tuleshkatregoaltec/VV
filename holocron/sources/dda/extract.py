"""DDA planning map extraction logic."""

from __future__ import annotations

import csv
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from dagster import get_dagster_logger

from holocron.framework.csv_utils import write_csv
from holocron.sources.dda.parse import (
    BUILDING_LIMIT_CSV_FIELDS,
    CSV_FIELDS,
    FROZEN_PLOT_CSV_FIELDS,
    LANDUSE_SYMBOL_CSV_FIELDS,
    PLOT_ARCADE_CSV_FIELDS,
    PLOT_BUILT_TO_LINE_CSV_FIELDS,
    PLOT_FEATURE_CSV_FIELDS,
    PLOT_RETAIL_CSV_FIELDS,
    PODIUM_LIMIT_CSV_FIELDS,
    PROJECT_CSV_FIELDS,
    SUBPROJECT_CSV_FIELDS,
    arcade_row,
    building_limit_row,
    built_to_line_row,
    frozen_plot_row,
    landuse_symbol_row,
    parse_plot_info,
    plot_feature_row,
    podium_limit_row,
    project_area_row,
    retail_row,
    subproject_area_row,
)

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
            return {**base, **parse_plot_info(response.text, plot_number)}
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

def scrape_project_areas(client: httpx.Client, token: str, output: Path) -> None:
    features = _fetch_all_layer_features(
        client,
        token,
        10,
        out_fields="OBJECTID,ProjectName",
        layer_name="project_areas",
    )
    rows = [project_area_row(feature) for feature in features]
    write_csv(output, PROJECT_CSV_FIELDS, rows)
    _log(f"dda: wrote {len(rows)} project areas to {output}")


def scrape_subproject_areas(client: httpx.Client, token: str, output: Path) -> None:
    features = _fetch_all_layer_features(client, token, 11, layer_name="subproject_areas")
    rows = [subproject_area_row(feature) for feature in features]
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
    rows = [building_limit_row(feature) for feature in features]
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
    rows = [podium_limit_row(feature) for feature in features]
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
    rows = [plot_feature_row(feature) for feature in features]
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
    rows = [frozen_plot_row(feature) for feature in features]
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
    rows = [landuse_symbol_row(feature) for feature in features]
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
    rows = [built_to_line_row(feature) for feature in features]
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
    rows = [arcade_row(feature) for feature in features]
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
    rows = [retail_row(feature) for feature in features]
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
