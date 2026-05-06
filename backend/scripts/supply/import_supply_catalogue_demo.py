"""Import upcoming supply catalogue data from R2 into local demo tables.

This is intentionally a demo shortcut. It creates local tables named
demo_supply_catalogue_projects and demo_supply_catalogue_assets, then fills them from
the latest raw catalogue export and asset manifests in R2.
"""

import argparse
import asyncio
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import aioboto3
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.postgres import close_postgres, get_postgres_engine
from app.supply.service import get_supply_catalogue_asset_file

JSON_DECODER = json.JSONDecoder()
SUPPLY_SOURCE_EXPORT_SLUG = "".join(("ree", "lly", "_supply"))
SUPPLY_RAW_MANIFEST_PREFIX = f"raw/source={SUPPLY_SOURCE_EXPORT_SLUG}/manifests/"
SUPPLY_DOCUMENT_ASSET_MANIFEST_PREFIX = (
    f"raw/source={SUPPLY_SOURCE_EXPORT_SLUG}/document_asset_manifests/"
)
SUPPLY_PROJECT_MEDIA_ASSET_MANIFEST_PREFIX = (
    f"raw/source={SUPPLY_SOURCE_EXPORT_SLUG}/project_media_asset_manifests/"
)


def iter_json_objects(text_value: str):
    """Read R2's newline-ish JSON streams, tolerating embedded newlines in strings."""
    index = 0
    length = len(text_value)
    while index < length:
        while index < length and text_value[index].isspace():
            index += 1
        if index >= length:
            break
        obj, end = JSON_DECODER.raw_decode(text_value, index)
        yield obj
        index = end


def flatten_records(value: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return records
    for item in value:
        if isinstance(item, dict):
            records.append(item)
        elif isinstance(item, list):
            records.extend(inner for inner in item if isinstance(inner, dict))
    return records


def clean_text(value: str | None) -> str | None:
    if not value:
        return None
    text_value = re.sub(r"#+\s*", "", value)
    text_value = re.sub(r"[*_`>]+", "", text_value)
    text_value = re.sub(r"\s+", " ", text_value).strip()
    return text_value or None


def excerpt(value: str | None, limit: int = 280) -> str | None:
    cleaned = clean_text(value)
    if not cleaned:
        return None
    return cleaned if len(cleaned) <= limit else f"{cleaned[: limit - 1].rstrip()}..."


def parse_coordinates(value: str | None) -> tuple[float | None, float | None]:
    if not value or "," not in value:
        return None, None
    try:
        lat_text, lon_text = value.split(",", 1)
        return float(lat_text.strip()), float(lon_text.strip())
    except ValueError:
        return None, None


def parse_int(value: Any) -> int | None:
    if value in (None, "", []):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_price(value: Any) -> int | None:
    parsed = parse_int(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def parse_float(value: Any) -> float | None:
    if value in (None, "", []):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_scraped_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def extract_unit_types(starting_prices: list[Any]) -> list[str]:
    seen: set[str] = set()
    labels: list[str] = []
    for row in starting_prices:
        if not isinstance(row, dict):
            continue
        label = " ".join(
            part
            for part in [
                str(row.get("unit_bedrooms") or "").strip(),
                str(row.get("unit_type") or row.get("Unit_type") or "").strip(),
            ]
            if part
        )
        if label and label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def extract_units(starting_prices: list[Any]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for row in starting_prices:
        if not isinstance(row, dict):
            continue
        bedrooms = row.get("unit_bedrooms")
        unit_type = row.get("unit_type") or row.get("Unit_type")
        label = " ".join(str(part).strip() for part in [bedrooms, unit_type] if part) or "Unit"
        units.append(
            {
                "label": label,
                "unit_type": unit_type,
                "bedrooms": bedrooms,
                "price_from_aed": parse_price(row.get("Price_from_AED")),
                "price_to_aed": parse_price(row.get("Price_to_AED")),
                "area_from_sqft": parse_float(row.get("Area_from_sqft")),
                "area_to_sqft": parse_float(row.get("Area_to_sqft")),
                "units_amount": parse_int(row.get("units_amount")),
            }
        )
    return units


def extract_payment_plan(raw: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for row in flatten_records(raw.get("Payment_plans")):
        label = row.get("Payment_time") or row.get("Name") or "Payment"
        steps.append(
            {
                "label": str(label),
                "percent": None
                if row.get("Percent_of_payment") is None
                else str(row.get("Percent_of_payment")),
                "order": parse_int(row.get("Order")),
            }
        )
    return sorted(steps, key=lambda item: item.get("order") or 999)


def extract_facilities(raw: dict[str, Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for row in flatten_records(raw.get("Facilities")):
        name = str(row.get("Name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def extract_buildings(raw: dict[str, Any]) -> list[dict[str, Any]]:
    buildings: list[dict[str, Any]] = []
    for row in flatten_records(raw.get("Buildings")):
        name = str(row.get("Name") or "Building").strip()
        buildings.append({"name": name, "description": clean_text(row.get("Description"))})
    return buildings


def extract_nearby_points(raw: dict[str, Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for row in flatten_records(raw.get("Map_points")):
        name = str(row.get("Point_name") or "").strip()
        if not name:
            continue
        points.append(
            {
                "name": name,
                "distance_km": parse_float(row.get("Distance_km")),
                "time_min": parse_float(row.get("Time_min")),
            }
        )
    return points[:12]


def project_record(row: dict[str, Any], source_manifest_key: str) -> dict[str, Any]:
    raw = row.get("raw") or {}
    developer = flatten_records(raw.get("Developer"))
    developer_id = raw.get("Developer", [{}])[0].get("id") if developer else None
    starting_prices = (
        raw.get("Starting_price") if isinstance(raw.get("Starting_price"), list) else []
    )
    latitude, longitude = parse_coordinates(
        raw.get("Coordinates") or raw.get("Place_ID_Coordinates")
    )

    return {
        "project_id": row["project_id"],
        "project_name": raw.get("Project_name")
        or row.get("list_item", {}).get("Project_name")
        or "Unknown",
        "developer_name": raw.get("Developers_name") or "Unknown developer",
        "developer_id": parse_int(developer_id),
        "area_name": raw.get("Area_name"),
        "region": raw.get("Region"),
        "status": raw.get("Status"),
        "sale_status": raw.get("sale_status"),
        "completion_date": raw.get("Completion_date"),
        "completion_time_ms": parse_int(raw.get("Completion_time")),
        "min_price_aed": parse_price(raw.get("min_price")),
        "max_price_aed": parse_price(raw.get("max_price")),
        "units_in_sale": parse_int(raw.get("units_in_sale")),
        "unit_types": extract_unit_types(starting_prices),
        "units": extract_units(starting_prices),
        "payment_plan": extract_payment_plan(raw),
        "facilities": extract_facilities(raw),
        "buildings": extract_buildings(raw),
        "nearby_points": extract_nearby_points(raw),
        "overview": raw.get("Overview"),
        "overview_excerpt": excerpt(raw.get("Overview")),
        "latitude": latitude,
        "longitude": longitude,
        "source_run_id": source_manifest_key.rsplit("/", 1)[-1].removesuffix(".json"),
        "scraped_at": parse_scraped_at(row.get("scraped_at")) or datetime.now(timezone.utc),
        "raw": raw,
    }


def source_content_type(row: dict[str, Any]) -> str | None:
    if row.get("content_type"):
        return row["content_type"]
    source = row.get("source_document_row") or {}
    raw = source.get("raw") if isinstance(source, dict) else {}
    if isinstance(raw, dict):
        return raw.get("mime")
    return None


def source_size(row: dict[str, Any]) -> int | None:
    if row.get("size_bytes"):
        return parse_int(row.get("size_bytes"))
    source = row.get("source_document_row") or {}
    raw = source.get("raw") if isinstance(source, dict) else {}
    if isinstance(raw, dict):
        return parse_int(raw.get("size"))
    return None


def asset_record(row: dict[str, Any], asset_type: str, sort_order: int) -> dict[str, Any] | None:
    target_key = row.get("target_key")
    project_id = parse_int(row.get("project_id"))
    if not target_key or not project_id:
        return None
    name = row.get("name")
    if asset_type == "brochure" and (not name or name == "view"):
        name = "Brochure"
    return {
        "project_id": project_id,
        "asset_type": asset_type,
        "field_path": row.get("field_path")
        or (row.get("source_document_row") or {}).get("field_path"),
        "name": name,
        "target_key": target_key,
        "source_url": row.get("source_url") or row.get("normalized_url"),
        "content_type": source_content_type(row),
        "size_bytes": source_size(row),
        "status": row.get("status"),
        "sort_order": sort_order,
        "raw": {
            "run_id": row.get("run_id"),
            "status": row.get("status"),
            "source_manifest": row.get("source_manifest"),
        },
    }


async def list_objects(s3, prefix: str) -> list[dict[str, Any]]:
    paginator = s3.get_paginator("list_objects_v2")
    objects: list[dict[str, Any]] = []
    async for page in paginator.paginate(
        Bucket=settings.S3_BUCKET_NAME,
        Prefix=prefix,
        PaginationConfig={"PageSize": 1000},
    ):
        objects.extend(page.get("Contents", []))
    return objects


async def read_text_object(s3, key: str) -> str:
    response = await s3.get_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
    return (await response["Body"].read()).decode("utf-8", errors="replace")


async def load_raw_manifests(s3) -> list[dict[str, Any]]:
    manifests = []
    for obj in await list_objects(s3, SUPPLY_RAW_MANIFEST_PREFIX):
        if obj["Key"].endswith(".json"):
            manifest = json.loads(await read_text_object(s3, obj["Key"]))
            manifest["s3_key"] = obj["Key"]
            manifests.append(manifest)
    return sorted(manifests, key=lambda item: item["created_at"])


async def latest_manifest_object(s3, prefix: str, *, largest: bool = False) -> dict[str, Any]:
    roots = await list_objects(s3, prefix)
    jsonl_objects = [obj for obj in roots if obj["Key"].endswith(".jsonl") and obj["Size"] > 0]
    if not jsonl_objects:
        raise RuntimeError(f"No supply catalogue manifest objects found under {prefix}")
    if largest:
        return max(jsonl_objects, key=lambda item: item["Size"])
    return max(jsonl_objects, key=lambda item: item["LastModified"])


async def create_demo_tables(db: AsyncSession, reset: bool) -> None:
    await db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS demo_supply_catalogue_projects (
                project_id INTEGER PRIMARY KEY,
                project_name TEXT NOT NULL,
                developer_name TEXT,
                developer_id INTEGER,
                area_name TEXT,
                region TEXT,
                status TEXT,
                sale_status TEXT,
                completion_date TEXT,
                completion_time_ms BIGINT,
                min_price_aed INTEGER,
                max_price_aed INTEGER,
                units_in_sale INTEGER,
                unit_types JSONB NOT NULL DEFAULT '[]'::jsonb,
                units JSONB NOT NULL DEFAULT '[]'::jsonb,
                payment_plan JSONB NOT NULL DEFAULT '[]'::jsonb,
                facilities JSONB NOT NULL DEFAULT '[]'::jsonb,
                buildings JSONB NOT NULL DEFAULT '[]'::jsonb,
                nearby_points JSONB NOT NULL DEFAULT '[]'::jsonb,
                overview TEXT,
                overview_excerpt TEXT,
                latitude DOUBLE PRECISION,
                longitude DOUBLE PRECISION,
                source_run_id TEXT,
                scraped_at TIMESTAMPTZ,
                raw JSONB NOT NULL DEFAULT '{}'::jsonb,
                imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    await db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS demo_supply_catalogue_assets (
                id BIGSERIAL PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES demo_supply_catalogue_projects(project_id)
                    ON DELETE CASCADE,
                asset_type TEXT NOT NULL,
                field_path TEXT,
                name TEXT,
                target_key TEXT NOT NULL UNIQUE,
                source_url TEXT,
                content_type TEXT,
                size_bytes BIGINT,
                status TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                raw JSONB NOT NULL DEFAULT '{}'::jsonb,
                imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    await db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_demo_supply_catalogue_projects_area
                ON demo_supply_catalogue_projects(area_name)
            """
        )
    )
    await db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_demo_supply_catalogue_projects_status
                ON demo_supply_catalogue_projects(status)
            """
        )
    )
    await db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_demo_supply_catalogue_assets_project_type
                ON demo_supply_catalogue_assets(project_id, asset_type, sort_order)
            """
        )
    )
    if reset:
        await db.execute(text("TRUNCATE demo_supply_catalogue_assets RESTART IDENTITY CASCADE"))
        await db.execute(text("TRUNCATE demo_supply_catalogue_projects CASCADE"))
    await db.commit()


async def upsert_projects(db: AsyncSession, projects: dict[int, dict[str, Any]]) -> None:
    sql = text(
        """
        INSERT INTO demo_supply_catalogue_projects (
            project_id, project_name, developer_name, developer_id, area_name, region, status,
            sale_status, completion_date, completion_time_ms, min_price_aed, max_price_aed,
            units_in_sale, unit_types, units, payment_plan, facilities, buildings,
            nearby_points, overview, overview_excerpt, latitude, longitude, source_run_id,
            scraped_at, raw
        ) VALUES (
            :project_id, :project_name, :developer_name, :developer_id, :area_name, :region,
            :status, :sale_status, :completion_date, :completion_time_ms, :min_price_aed,
            :max_price_aed, :units_in_sale, CAST(:unit_types AS jsonb), CAST(:units AS jsonb),
            CAST(:payment_plan AS jsonb), CAST(:facilities AS jsonb), CAST(:buildings AS jsonb),
            CAST(:nearby_points AS jsonb), :overview, :overview_excerpt, :latitude, :longitude,
            :source_run_id, :scraped_at, CAST(:raw AS jsonb)
        )
        ON CONFLICT (project_id) DO UPDATE SET
            project_name = EXCLUDED.project_name,
            developer_name = EXCLUDED.developer_name,
            developer_id = EXCLUDED.developer_id,
            area_name = EXCLUDED.area_name,
            region = EXCLUDED.region,
            status = EXCLUDED.status,
            sale_status = EXCLUDED.sale_status,
            completion_date = EXCLUDED.completion_date,
            completion_time_ms = EXCLUDED.completion_time_ms,
            min_price_aed = EXCLUDED.min_price_aed,
            max_price_aed = EXCLUDED.max_price_aed,
            units_in_sale = EXCLUDED.units_in_sale,
            unit_types = EXCLUDED.unit_types,
            units = EXCLUDED.units,
            payment_plan = EXCLUDED.payment_plan,
            facilities = EXCLUDED.facilities,
            buildings = EXCLUDED.buildings,
            nearby_points = EXCLUDED.nearby_points,
            overview = EXCLUDED.overview,
            overview_excerpt = EXCLUDED.overview_excerpt,
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            source_run_id = EXCLUDED.source_run_id,
            scraped_at = EXCLUDED.scraped_at,
            raw = EXCLUDED.raw,
            imported_at = now()
        """
    )
    rows = []
    for record in projects.values():
        row = record.copy()
        for json_field in [
            "unit_types",
            "units",
            "payment_plan",
            "facilities",
            "buildings",
            "nearby_points",
            "raw",
        ]:
            row[json_field] = json.dumps(row[json_field], ensure_ascii=False)
        rows.append(row)

    for index in range(0, len(rows), 250):
        await db.execute(sql, rows[index : index + 250])
    await db.commit()


async def insert_assets(db: AsyncSession, records: list[dict[str, Any]]) -> None:
    sql = text(
        """
        INSERT INTO demo_supply_catalogue_assets (
            project_id, asset_type, field_path, name, target_key, source_url, content_type,
            size_bytes, status, sort_order, raw
        ) VALUES (
            :project_id, :asset_type, :field_path, :name, :target_key, :source_url,
            :content_type, :size_bytes, :status, :sort_order, CAST(:raw AS jsonb)
        )
        ON CONFLICT (target_key) DO UPDATE SET
            project_id = EXCLUDED.project_id,
            asset_type = EXCLUDED.asset_type,
            field_path = EXCLUDED.field_path,
            name = EXCLUDED.name,
            source_url = EXCLUDED.source_url,
            content_type = EXCLUDED.content_type,
            size_bytes = EXCLUDED.size_bytes,
            status = EXCLUDED.status,
            sort_order = EXCLUDED.sort_order,
            raw = EXCLUDED.raw,
            imported_at = now()
        """
    )
    prepared = []
    for record in records:
        row = record.copy()
        row["raw"] = json.dumps(row["raw"], ensure_ascii=False)
        prepared.append(row)
    for index in range(0, len(prepared), 1000):
        await db.execute(sql, prepared[index : index + 1000])
    await db.commit()


async def cache_priority_assets(db: AsyncSession, project_limit: int) -> None:
    if project_limit <= 0:
        return
    result = await db.execute(
        text(
            """
            WITH priority_projects AS (
                SELECT project_id
                FROM demo_supply_catalogue_projects
                ORDER BY
                    CASE WHEN sale_status = 'On sale' THEN 0 ELSE 1 END,
                    min_price_aed ASC NULLS LAST,
                    project_name ASC
                LIMIT :project_limit
            ),
            ranked_assets AS (
                SELECT
                    a.id,
                    ROW_NUMBER() OVER (
                        PARTITION BY a.project_id, a.asset_type
                        ORDER BY a.sort_order ASC, a.id ASC
                    ) AS rank
                FROM demo_supply_catalogue_assets a
                JOIN priority_projects p ON p.project_id = a.project_id
                WHERE a.asset_type IN ('cover_image', 'developer_logo')
            )
            SELECT id
            FROM ranked_assets
            WHERE rank = 1
            ORDER BY id ASC
            """
        ),
        {"project_limit": project_limit},
    )
    asset_ids = [row[0] for row in result.fetchall()]
    for index, asset_id in enumerate(asset_ids, start=1):
        try:
            await get_supply_catalogue_asset_file(db, asset_id)
        except Exception as exc:
            print(f"asset cache miss id={asset_id}: {exc}")
        if index % 25 == 0 or index == len(asset_ids):
            print(f"cached {index}/{len(asset_ids)} priority cover/logo assets")


async def import_supply_catalogue_demo(reset: bool, cache_projects: int) -> None:
    session = aioboto3.Session()
    s3_kwargs = {
        "endpoint_url": str(settings.S3_ENDPOINT_URL),
        "aws_access_key_id": settings.S3_ACCESS_KEY_ID,
        "aws_secret_access_key": settings.S3_SECRET_ACCESS_KEY,
        "region_name": settings.S3_REGION or "auto",
    }

    async with session.client("s3", **s3_kwargs) as s3:
        manifests = await load_raw_manifests(s3)
        projects: dict[int, dict[str, Any]] = {}
        for manifest in manifests:
            files = {
                file["path"]: file for file in manifest["files"] if file["path"].endswith(".jsonl")
            }
            details_key = files[f"{SUPPLY_SOURCE_EXPORT_SLUG}_project_details.jsonl"]["s3_key"]
            details_text = await read_text_object(s3, details_key)
            for row in iter_json_objects(details_text):
                if row.get("project_id"):
                    projects[row["project_id"]] = project_record(row, manifest["s3_key"])

        media_manifest = await latest_manifest_object(
            s3, SUPPLY_PROJECT_MEDIA_ASSET_MANIFEST_PREFIX, largest=True
        )
        media_rows_text = await read_text_object(s3, media_manifest["Key"])

        document_manifest = await latest_manifest_object(s3, SUPPLY_DOCUMENT_ASSET_MANIFEST_PREFIX)
        document_rows_text = await read_text_object(s3, document_manifest["Key"])

    asset_records: list[dict[str, Any]] = []
    sort_counters: dict[tuple[int, str], int] = defaultdict(int)
    for row in iter_json_objects(media_rows_text):
        project_id = parse_int(row.get("project_id"))
        asset_type = row.get("asset_type")
        if not project_id or not asset_type:
            continue
        sort_counters[(project_id, asset_type)] += 1
        record = asset_record(row, asset_type, sort_counters[(project_id, asset_type)])
        if record:
            asset_records.append(record)
    for row in iter_json_objects(document_rows_text):
        project_id = parse_int(row.get("project_id"))
        if not project_id:
            continue
        sort_counters[(project_id, "brochure")] += 1
        record = asset_record(row, "brochure", sort_counters[(project_id, "brochure")])
        if record:
            asset_records.append(record)

    session_factory = async_sessionmaker(
        get_postgres_engine(), class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as db:
        await create_demo_tables(db, reset=reset)
        await upsert_projects(db, projects)
        await insert_assets(db, asset_records)
        project_count = len(projects)
        asset_count = len(asset_records)
        print(f"imported {project_count} supply catalogue projects and {asset_count} asset records")
        await cache_priority_assets(db, cache_projects)
    await close_postgres()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-reset", action="store_true", help="Do not truncate demo tables first")
    parser.add_argument(
        "--cache-projects",
        type=int,
        default=120,
        help="Pre-cache cover/logo images for this many priority projects",
    )
    args = parser.parse_args()
    asyncio.run(
        import_supply_catalogue_demo(reset=not args.no_reset, cache_projects=args.cache_projects)
    )


if __name__ == "__main__":
    main()
