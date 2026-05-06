"""Supply service for upcoming projects.

The supply catalogue helpers in this module intentionally target a demo-only local
Postgres import created by backend/scripts/supply/import_supply_catalogue_demo.py.
"""

import hashlib
import io
import logging
from pathlib import Path
from typing import Any, Dict, List

import aioboto3
from fastapi import HTTPException
from PIL import Image, ImageOps
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.clickhouse.client import query
from app.config import settings
from app.supply.models import (
    SupplyCatalogueAssetResponse,
    SupplyCatalogueBuildingResponse,
    SupplyCatalogueNearbyPointResponse,
    SupplyCataloguePaymentStepResponse,
    SupplyCatalogueProjectCardResponse,
    SupplyCatalogueProjectDetailResponse,
    SupplyCatalogueProjectsResponse,
    SupplyCatalogueUnitResponse,
)

logger = logging.getLogger(__name__)

SUPPLY_CATALOGUE_ASSET_CACHE_DIR = Path(".cache/supply-catalogue/assets")
SUPPLY_CATALOGUE_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
SUPPLY_CATALOGUE_GALLERY_ASSET_TYPES = (
    "building_image",
    "interior_image",
    "facility_image",
    "unit_image",
)
SUPPLY_CATALOGUE_IMAGE_CACHE_SIZE = (960, 720)
SUPPLY_CATALOGUE_LOGO_CACHE_SIZE = (220, 220)
SUPPLY_CATALOGUE_IMAGE_CACHE_QUALITY = 78


async def get_upcoming_projects_ch(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """
    Get all active/upcoming projects from ClickHouse.
    Active = has start_date AND no completion_date AND no cancellation_date
    """
    try:
        sql = """
            SELECT
                p.project_id,
                p.project_name,
                p.developer_id,
                d.developer_name_en as developer_name,
                p.area_name_en,
                p.project_start_date,
                p.project_end_date,
                p.percent_completed,
                p.no_of_buildings,
                p.no_of_units
            FROM ch_projects p
            LEFT JOIN ch_developers d ON p.developer_id = d.developer_id
            WHERE
                p.project_start_date IS NOT NULL
                AND p.completion_date IS NULL
                AND p.cancellation_date IS NULL
            ORDER BY
                p.project_end_date ASC NULLS LAST,
                p.project_name ASC
            LIMIT {limit:Int32}
            OFFSET {offset:Int32}
        """
        params = {"limit": limit, "offset": offset}

        result = await query(sql, params)
        return result

    except Exception as e:
        logger.error(f"Error fetching upcoming projects from ClickHouse: {str(e)}")
        return []


def _api_base_url() -> str:
    return str(settings.PUBLIC_API_BASE_URL).rstrip("/") if settings.PUBLIC_API_BASE_URL else ""


def _asset_url(asset_id: int) -> str:
    return f"{_api_base_url()}/api/v1/supply/catalogue/assets/{asset_id}"


def _asset_download_url(asset_id: int) -> str:
    return f"{_asset_url(asset_id)}?download=true"


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _card_from_row(row: Any) -> SupplyCatalogueProjectCardResponse:
    data = dict(row._mapping)
    cover_asset_id = data.get("cover_asset_id")
    developer_logo_asset_id = data.get("developer_logo_asset_id")

    return SupplyCatalogueProjectCardResponse(
        project_id=data["project_id"],
        project_name=data["project_name"],
        developer_name=data.get("developer_name") or "Unknown developer",
        developer_id=data.get("developer_id"),
        area_name=data.get("area_name"),
        region=data.get("region"),
        status=data.get("status"),
        sale_status=data.get("sale_status"),
        completion_date=data.get("completion_date"),
        min_price_aed=data.get("min_price_aed"),
        max_price_aed=data.get("max_price_aed"),
        units_in_sale=data.get("units_in_sale"),
        unit_types=_as_list(data.get("unit_types")),
        overview_excerpt=data.get("overview_excerpt"),
        cover_image_url=_asset_url(cover_asset_id) if cover_asset_id else None,
        developer_logo_url=_asset_url(developer_logo_asset_id) if developer_logo_asset_id else None,
        image_count=data.get("image_count") or 0,
        floorplan_count=data.get("floorplan_count") or 0,
        brochure_count=data.get("brochure_count") or 0,
    )


def _asset_from_row(row: Any) -> SupplyCatalogueAssetResponse:
    data = dict(row._mapping)
    asset_id = data["id"]
    asset_type = data["asset_type"]
    is_document = asset_type in {"brochure", "floorplan"}
    return SupplyCatalogueAssetResponse(
        id=asset_id,
        asset_type=asset_type,
        name=data.get("name"),
        url=_asset_url(asset_id),
        download_url=_asset_download_url(asset_id) if is_document else None,
        content_type=data.get("content_type"),
        size_bytes=data.get("size_bytes"),
    )


def _demo_table_missing(exc: Exception) -> bool:
    message = str(exc).lower()
    return "demo_supply_catalogue" in message and (
        "does not exist" in message or "undefinedtable" in message
    )


def _sql_filters(
    search: str | None, area: str | None, status: str | None
) -> tuple[str, dict[str, Any]]:
    clauses = []
    params: dict[str, Any] = {}
    if search:
        clauses.append(
            "(project_name ILIKE :search OR developer_name ILIKE :search OR area_name ILIKE :search)"
        )
        params["search"] = f"%{search}%"
    if area:
        clauses.append("area_name = :area")
        params["area"] = area
    if status:
        clauses.append("status = :status")
        params["status"] = status
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


async def list_supply_catalogue_projects(
    db: AsyncSession,
    limit: int = 48,
    offset: int = 0,
    search: str | None = None,
    area: str | None = None,
    status: str | None = None,
) -> SupplyCatalogueProjectsResponse:
    where, params = _sql_filters(search, area, status)
    params = {**params, "limit": limit, "offset": offset}

    try:
        rows_result = await db.execute(
            text(
                f"""
                SELECT
                    p.*,
                    (
                        SELECT a.id
                        FROM demo_supply_catalogue_assets a
                        WHERE a.project_id = p.project_id AND a.asset_type = 'cover_image'
                        ORDER BY a.sort_order ASC, a.id ASC
                        LIMIT 1
                    ) AS cover_asset_id,
                    (
                        SELECT a.id
                        FROM demo_supply_catalogue_assets a
                        WHERE a.project_id = p.project_id AND a.asset_type = 'developer_logo'
                        ORDER BY a.sort_order ASC, a.id ASC
                        LIMIT 1
                    ) AS developer_logo_asset_id,
                    (
                        SELECT COUNT(*)
                        FROM demo_supply_catalogue_assets a
                        WHERE a.project_id = p.project_id
                          AND a.asset_type IN ('building_image', 'interior_image', 'facility_image', 'unit_image')
                    ) AS image_count,
                    (
                        SELECT COUNT(*)
                        FROM demo_supply_catalogue_assets a
                        WHERE a.project_id = p.project_id AND a.asset_type = 'floorplan'
                    ) AS floorplan_count,
                    (
                        SELECT COUNT(*)
                        FROM demo_supply_catalogue_assets a
                        WHERE a.project_id = p.project_id AND a.asset_type = 'brochure'
                    ) AS brochure_count
                FROM demo_supply_catalogue_projects p
                {where}
                ORDER BY
                    CASE
                        WHEN p.region = 'Dubai' THEN 0
                        WHEN p.region IN (
                            'Abu Dhabi',
                            'Sharjah',
                            'Ras Al Khaimah',
                            'Ajman',
                            'Umm Al Quwain'
                        ) THEN 1
                        ELSE 2
                    END,
                    CASE WHEN p.sale_status = 'On sale' THEN 0 ELSE 1 END,
                    NULLIF(p.min_price_aed, 0) ASC NULLS LAST,
                    p.project_name ASC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM demo_supply_catalogue_projects p {where}"),
            {key: value for key, value in params.items() if key not in {"limit", "offset"}},
        )
        areas_result = await db.execute(
            text(
                """
                SELECT area_name
                FROM demo_supply_catalogue_projects
                WHERE area_name IS NOT NULL AND area_name <> ''
                GROUP BY area_name
                ORDER BY COUNT(*) DESC, area_name ASC
                LIMIT 40
                """
            )
        )
        statuses_result = await db.execute(
            text(
                """
                SELECT status
                FROM demo_supply_catalogue_projects
                WHERE status IS NOT NULL AND status <> ''
                GROUP BY status
                ORDER BY COUNT(*) DESC, status ASC
                """
            )
        )
    except ProgrammingError as exc:
        if _demo_table_missing(exc):
            await db.rollback()
            return SupplyCatalogueProjectsResponse(projects=[], total=0, limit=limit, offset=offset)
        raise

    projects = [_card_from_row(row) for row in rows_result.fetchall()]
    return SupplyCatalogueProjectsResponse(
        projects=projects,
        total=count_result.scalar_one(),
        limit=limit,
        offset=offset,
        areas=[row[0] for row in areas_result.fetchall()],
        statuses=[row[0] for row in statuses_result.fetchall()],
    )


async def get_supply_catalogue_project(
    db: AsyncSession, project_id: int
) -> SupplyCatalogueProjectDetailResponse:
    row_result = await db.execute(
        text(
            """
            SELECT
                p.*,
                (
                    SELECT a.id
                    FROM demo_supply_catalogue_assets a
                    WHERE a.project_id = p.project_id AND a.asset_type = 'cover_image'
                    ORDER BY a.sort_order ASC, a.id ASC
                    LIMIT 1
                ) AS cover_asset_id,
                (
                    SELECT a.id
                    FROM demo_supply_catalogue_assets a
                    WHERE a.project_id = p.project_id AND a.asset_type = 'developer_logo'
                    ORDER BY a.sort_order ASC, a.id ASC
                    LIMIT 1
                ) AS developer_logo_asset_id,
                (
                    SELECT COUNT(*)
                    FROM demo_supply_catalogue_assets a
                    WHERE a.project_id = p.project_id
                      AND a.asset_type IN ('building_image', 'interior_image', 'facility_image', 'unit_image')
                ) AS image_count,
                (
                    SELECT COUNT(*)
                    FROM demo_supply_catalogue_assets a
                    WHERE a.project_id = p.project_id AND a.asset_type = 'floorplan'
                ) AS floorplan_count,
                (
                    SELECT COUNT(*)
                    FROM demo_supply_catalogue_assets a
                    WHERE a.project_id = p.project_id AND a.asset_type = 'brochure'
                ) AS brochure_count
            FROM demo_supply_catalogue_projects p
            WHERE p.project_id = :project_id
            """
        ),
        {"project_id": project_id},
    )
    row = row_result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Supply catalogue demo project not found")

    card = _card_from_row(row)
    data = dict(row._mapping)
    asset_rows = await db.execute(
        text(
            """
            SELECT id, asset_type, name, content_type, size_bytes
            FROM demo_supply_catalogue_assets
            WHERE project_id = :project_id
            ORDER BY sort_order ASC, id ASC
            """
        ),
        {"project_id": project_id},
    )
    grouped: dict[str, list[SupplyCatalogueAssetResponse]] = {}
    for asset_row in asset_rows.fetchall():
        asset = _asset_from_row(asset_row)
        grouped.setdefault(asset.asset_type, []).append(asset)

    gallery = []
    for asset_type in SUPPLY_CATALOGUE_GALLERY_ASSET_TYPES:
        gallery.extend(grouped.get(asset_type, [])[:8])
    gallery = gallery[:18]

    coordinates = None
    if data.get("latitude") is not None and data.get("longitude") is not None:
        coordinates = {"latitude": float(data["latitude"]), "longitude": float(data["longitude"])}

    return SupplyCatalogueProjectDetailResponse(
        **card.model_dump(),
        overview=data.get("overview"),
        coordinates=coordinates,
        units=[
            SupplyCatalogueUnitResponse.model_validate(item) for item in _as_list(data.get("units"))
        ],
        payment_plan=[
            SupplyCataloguePaymentStepResponse.model_validate(item)
            for item in _as_list(data.get("payment_plan"))
        ],
        facilities=[str(item) for item in _as_list(data.get("facilities")) if item],
        buildings=[
            SupplyCatalogueBuildingResponse.model_validate(item)
            for item in _as_list(data.get("buildings"))
        ],
        nearby_points=[
            SupplyCatalogueNearbyPointResponse.model_validate(item)
            for item in _as_list(data.get("nearby_points"))
        ],
        gallery=gallery,
        floorplans=grouped.get("floorplan", [])[:12],
        brochures=grouped.get("brochure", [])[:6],
        master_plans=grouped.get("master_plan", [])[:4],
        demo_metadata={
            "source": "Supply catalogue R2 demo import",
            "source_run_id": data.get("source_run_id"),
            "scraped_at": data.get("scraped_at").isoformat()
            if data.get("scraped_at") is not None
            else None,
        },
    )


def _r2_client_kwargs() -> dict[str, str]:
    return {
        "endpoint_url": str(settings.S3_ENDPOINT_URL),
        "aws_access_key_id": settings.S3_ACCESS_KEY_ID,
        "aws_secret_access_key": settings.S3_SECRET_ACCESS_KEY,
        "region_name": settings.S3_REGION or "auto",
    }


def _asset_cache_dir() -> Path:
    path = SUPPLY_CATALOGUE_ASSET_CACHE_DIR
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _safe_asset_filename(asset_id: int, target_key: str, content_type: str | None) -> str:
    digest = hashlib.sha256(target_key.encode("utf-8")).hexdigest()[:16]
    if (content_type and content_type.startswith("image/")) or Path(target_key).suffix.lower() in {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    }:
        return f"asset-{asset_id}-{digest}.webp"
    suffix = Path(target_key).suffix or ".bin"
    return f"asset-{asset_id}-{digest}{suffix}"


def _looks_like_image(content_type: str | None, target_key: str) -> bool:
    normalized = (content_type or "").split(";", 1)[0].lower()
    if normalized in SUPPLY_CATALOGUE_IMAGE_CONTENT_TYPES:
        return True
    return Path(target_key).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}


async def _fetch_asset_row(db: AsyncSession, asset_id: int) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT id, asset_type, name, target_key, content_type, size_bytes
            FROM demo_supply_catalogue_assets
            WHERE id = :asset_id
            """
        ),
        {"asset_id": asset_id},
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Supply catalogue demo asset not found")
    return dict(row._mapping)


async def get_supply_catalogue_asset_file(
    db: AsyncSession, asset_id: int
) -> tuple[Path, str, str | None]:
    asset = await _fetch_asset_row(db, asset_id)
    target_key = asset.get("target_key")
    if not target_key:
        raise HTTPException(status_code=404, detail="Supply catalogue demo asset has no R2 object")

    source_content_type = asset.get("content_type")
    cache_path = _asset_cache_dir() / _safe_asset_filename(
        asset_id, target_key, source_content_type
    )
    if cache_path.exists():
        content_type = (
            "image/webp"
            if cache_path.suffix == ".webp"
            else (source_content_type or "application/octet-stream")
        )
        if asset.get("asset_type") in {"brochure", "floorplan"} and not _looks_like_image(
            content_type, target_key
        ):
            content_type = "application/pdf"
        return cache_path, content_type, asset.get("name")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    session = aioboto3.Session()
    try:
        async with session.client("s3", **_r2_client_kwargs()) as s3:
            response = await s3.get_object(Bucket=settings.S3_BUCKET_NAME, Key=target_key)
            data = await response["Body"].read()
            content_type = (
                response.get("ContentType") or source_content_type or "application/octet-stream"
            )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="Failed to fetch supply catalogue demo asset"
        ) from exc

    if asset.get("asset_type") in {"brochure", "floorplan"} and not _looks_like_image(
        content_type, target_key
    ):
        content_type = "application/pdf"

    if _looks_like_image(content_type, target_key):
        try:
            image = Image.open(io.BytesIO(data))
            image = ImageOps.exif_transpose(image).convert("RGB")
            size = (
                SUPPLY_CATALOGUE_LOGO_CACHE_SIZE
                if asset.get("asset_type") == "developer_logo"
                else SUPPLY_CATALOGUE_IMAGE_CACHE_SIZE
            )
            image.thumbnail(size)
            image.save(cache_path, "WEBP", quality=SUPPLY_CATALOGUE_IMAGE_CACHE_QUALITY, method=6)
            return cache_path, "image/webp", asset.get("name")
        except Exception:
            logger.warning(
                "Failed to optimise supply catalogue image asset %s; serving original", asset_id
            )

    cache_path.write_bytes(data)
    return cache_path, content_type, asset.get("name")


def supply_catalogue_download_filename(asset_id: int, name: str | None, content_type: str) -> str:
    if name:
        if content_type == "application/pdf" and not name.lower().endswith(".pdf"):
            return f"{name}.pdf"
        return name
    if content_type == "application/pdf":
        return f"supply-catalogue-asset-{asset_id}.pdf"
    return f"supply-catalogue-asset-{asset_id}"
