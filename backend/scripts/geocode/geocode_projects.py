"""Batch geocode ch_projects using Nominatim and insert into ch_geo_projects."""

import argparse
import json
import os
import time
import urllib.parse
import urllib.request

from clickhouse_driver import Client

CLICKHOUSE_HOST = os.environ.get("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DB = os.environ.get("CLICKHOUSE_DB", "default")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "ViteVue Real Estate Analytics/1.0"
RATE_LIMIT_SLEEP = 1.1  # Nominatim requires >= 1 req/sec


def nominatim_search(query: str) -> dict | None:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "json",
            "limit": 3,
            "polygon_geojson": 1,
            "countrycodes": "ae",
            "addressdetails": 1,
        }
    )
    req = urllib.request.Request(
        f"{NOMINATIM_URL}?{params}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    return data[0] if data else None


def extract_polygon(geojson: dict | None) -> list:
    if not geojson:
        return []
    coords = geojson.get("coordinates", [])
    t = geojson.get("type", "")
    if t == "Polygon":
        return [[float(p[0]), float(p[1])] for p in coords[0]]
    if t == "MultiPolygon":
        ring = max((r for poly in coords for r in poly), key=len)
        return [[float(p[0]), float(p[1])] for p in ring]
    return []


def main():
    parser = argparse.ArgumentParser(description="Geocode ch_projects via Nominatim")
    parser.add_argument(
        "--limit", type=int, default=None, help="Max projects to geocode"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print without inserting"
    )
    args = parser.parse_args()

    client = Client(
        host=CLICKHOUSE_HOST,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        database=CLICKHOUSE_DB,
    )

    rows = client.execute("""
        SELECT p.project_id, p.project_name_en, p.area_name_en
        FROM ch_projects p
        WHERE p.project_name_en != ''
          AND NOT match(p.project_name_en, '^Project [0-9]')
          AND p.project_id NOT IN (SELECT project_id FROM ch_geo_projects)
        ORDER BY p.project_id
    """)

    if args.limit:
        rows = rows[: args.limit]

    total = len(rows)
    print(f"Projects to geocode: {total}")

    for i, (project_id, name, area) in enumerate(rows):
        result = nominatim_search(f"{name}, {area}, Dubai, UAE")
        if not result:
            result = nominatim_search(f"{name}, Dubai, UAE")
            time.sleep(RATE_LIMIT_SLEEP)
        if not result:
            print(f"[{i + 1}/{total}] {name} → NOT FOUND")
            time.sleep(RATE_LIMIT_SLEEP)
            continue

        lat = float(result["lat"])
        lng = float(result["lon"])
        polygon = extract_polygon(result.get("geojson"))
        importance = float(result.get("importance", 0))

        if not args.dry_run:
            client.execute(
                "INSERT INTO ch_geo_projects "
                "(project_id, centroid_lat, centroid_lng, polygon, importance) VALUES",
                [(project_id, lat, lng, polygon, importance)],
            )

        poly_str = "yes" if polygon else "no"
        print(
            f"[{i + 1}/{total}] {name} → {lat:.4f}, {lng:.4f} "
            f"imp={importance:.3f} (polygon: {poly_str})"
        )
        time.sleep(RATE_LIMIT_SLEEP)

    print("Done.")


if __name__ == "__main__":
    main()
