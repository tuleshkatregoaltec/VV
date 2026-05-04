"""News feed thumbnail hydration and platform publishing from raw manifests."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import mimetypes
import re
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from holocron.platform.execution import new_run_id, utc_now
from holocron.platform.settings import Settings
from holocron.sources.news_feeds.extract import ARTICLES_FILE_NAME, clean_text

logger = logging.getLogger(__name__)

NEWS_THUMBNAIL_INVENTORY_FILE_NAME = "news_thumbnail_assets.jsonl"
_THUMBNAIL_LOG_INTERVAL = 25
_PUBLIC_NEWS_URL_SCHEMES = {"http", "https"}


class NewsThumbnailHydrationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_prefix: str = "raw/source=news_feeds/manifests/"
    target_prefix: str = "media/news/thumbnails"
    inventory_prefix: str = "raw/source=news_feeds/thumbnail_asset_manifests"
    inventory_file_name: str = NEWS_THUMBNAIL_INVENTORY_FILE_NAME
    lookback_days: int = Field(default=3, ge=0)
    max_assets_per_run: int = Field(default=1000, ge=1)
    overwrite_existing: bool = False
    allowed_thumbnail_hosts: tuple[str, ...] = ()
    max_thumbnail_mb: int = Field(default=5, ge=1)
    request_pause_seconds: float = Field(default=0, ge=0)
    timeout_seconds: float = Field(default=30, ge=1)
    max_concurrent_downloads: int = Field(default=8, ge=1, le=32)

    @field_validator("allowed_thumbnail_hosts", mode="before")
    @classmethod
    def coerce_allowed_thumbnail_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(host.strip() for host in value.split(",") if host.strip())
        return value

    @model_validator(mode="after")
    def validate_config(self) -> "NewsThumbnailHydrationConfig":
        if not self.manifest_prefix.strip():
            raise ValueError("manifest_prefix must not be blank")
        if not self.target_prefix.strip():
            raise ValueError("target_prefix must not be blank")
        if not self.inventory_prefix.strip():
            raise ValueError("inventory_prefix must not be blank")
        if not self.inventory_file_name.strip():
            raise ValueError("inventory_file_name must not be blank")
        if any(not host.strip() for host in self.allowed_thumbnail_hosts):
            raise ValueError("allowed_thumbnail_hosts must not include blank hosts")
        return self


class NewsPublishConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_prefix: str = "raw/source=news_feeds/manifests/"
    thumbnail_inventory_prefix: str = "raw/source=news_feeds/thumbnail_asset_manifests"
    lookback_days: int = Field(default=3, ge=0)
    max_articles_per_run: int = Field(default=1000, ge=1)
    platform_postgres_url: str = ""
    ensure_schema: bool = False
    dry_run: bool = False

    @model_validator(mode="after")
    def validate_config(self) -> "NewsPublishConfig":
        if not self.manifest_prefix.strip():
            raise ValueError("manifest_prefix must not be blank")
        if not self.thumbnail_inventory_prefix.strip():
            raise ValueError("thumbnail_inventory_prefix must not be blank")
        return self


@dataclass(frozen=True, slots=True)
class ManifestArticleRow:
    source_manifest_key: str
    source_article_key: str
    source_file_name: str
    source_manifest_run_id: str
    line_number: int
    row: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ThumbnailDownload:
    content: bytes
    content_type: str | None
    final_url: str


class ThumbnailTooLargeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PlannedThumbnailAsset:
    source_row: ManifestArticleRow
    article_key: str
    source_url: str
    normalized_url: str
    target_key: str
    status: str | None = None
    error: str | None = None


class ThumbnailDownloader(Protocol):
    def download_thumbnail(self, url: str, *, max_bytes: int) -> ThumbnailDownload: ...


class NewsArticleWriter(Protocol):
    def upsert_articles(
        self,
        articles: Sequence[Mapping[str, Any]],
        *,
        ensure_schema: bool,
        dry_run: bool,
    ) -> Mapping[str, Any]: ...


class NewsThumbnailDownloadClient:
    def __init__(self, *, client: httpx.Client, allowed_thumbnail_hosts: Sequence[str]) -> None:
        self._client = client
        self._allowed_thumbnail_hosts = tuple(allowed_thumbnail_hosts)

    def download_thumbnail(self, url: str, *, max_bytes: int) -> ThumbnailDownload:
        normalized_url = _validate_thumbnail_url(
            url,
            allowed_hosts=self._allowed_thumbnail_hosts,
        )
        with self._client.stream("GET", normalized_url, headers=_thumbnail_headers()) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise ThumbnailTooLargeError(f"thumbnail exceeds max size of {max_bytes} bytes")
            return ThumbnailDownload(
                content=bytes(content),
                content_type=response.headers.get("content-type"),
                final_url=str(response.url),
            )


def hydrate_news_thumbnail_assets(
    *,
    s3: Any,
    config: NewsThumbnailHydrationConfig | Mapping[str, Any] | None = None,
    now: datetime | None = None,
    download_client: ThumbnailDownloader | None = None,
    progress_log: Any | None = None,
) -> dict[str, Any]:
    parsed_config = (
        config
        if isinstance(config, NewsThumbnailHydrationConfig)
        else NewsThumbnailHydrationConfig.model_validate(config or {})
    )
    current_time = now or utc_now()
    run_id = new_run_id(current_time)
    log = progress_log or logger

    source_rows = _load_manifest_article_rows(
        s3=s3,
        manifest_prefix=parsed_config.manifest_prefix,
        lookback_days=parsed_config.lookback_days,
        now=current_time,
    )
    planned_assets = _plan_thumbnail_assets(source_rows, config=parsed_config)
    selected_assets = planned_assets[: parsed_config.max_assets_per_run]
    _log_info(
        log,
        (
            "news_feeds: hydrating thumbnails manifests=%s source_rows=%s discovered=%s "
            "selected=%s lookback_days=%s workers=%s"
        ),
        len({row.source_manifest_key for row in source_rows}),
        len(source_rows),
        len(planned_assets),
        len(selected_assets),
        parsed_config.lookback_days,
        parsed_config.max_concurrent_downloads,
    )

    if download_client is None:
        with httpx.Client(timeout=parsed_config.timeout_seconds, follow_redirects=True) as client:
            download_client = NewsThumbnailDownloadClient(
                client=client,
                allowed_thumbnail_hosts=parsed_config.allowed_thumbnail_hosts,
            )
            inventory_rows = _hydrate_planned_thumbnail_assets(
                s3=s3,
                planned_assets=selected_assets,
                config=parsed_config,
                download_client=download_client,
                run_id=run_id,
                created_at=current_time.isoformat(),
                progress_log=log,
            )
    else:
        inventory_rows = _hydrate_planned_thumbnail_assets(
            s3=s3,
            planned_assets=selected_assets,
            config=parsed_config,
            download_client=download_client,
            run_id=run_id,
            created_at=current_time.isoformat(),
            progress_log=log,
        )

    inventory_key = _inventory_key(
        prefix=parsed_config.inventory_prefix,
        run_id=run_id,
        file_name=parsed_config.inventory_file_name,
    )
    s3.put_bytes(
        key=inventory_key,
        payload=_jsonl_bytes(inventory_rows),
        content_type="application/x-ndjson",
    )

    status_counts = Counter(str(row.get("status")) for row in inventory_rows)
    error_count = sum(
        status_counts[status]
        for status in ("download_error", "validation_error", "too_large", "missing_url")
    )
    total_bytes = sum(
        int(row.get("size_bytes") or 0)
        for row in inventory_rows
        if row.get("status") == "downloaded"
    )
    result = {
        "run_id": run_id,
        "created_at": current_time.isoformat(),
        "manifest_prefix": parsed_config.manifest_prefix,
        "target_prefix": parsed_config.target_prefix,
        "inventory_prefix": parsed_config.inventory_prefix,
        "inventory_manifest_key": inventory_key,
        "source_manifest_count": len({row.source_manifest_key for row in source_rows}),
        "source_row_count": len(source_rows),
        "discovered": len(planned_assets),
        "attempted": len(inventory_rows),
        "downloaded": status_counts["downloaded"],
        "already_exists": status_counts["already_exists"],
        "already_existing": status_counts["already_exists"],
        "errors": error_count,
        "total_bytes": total_bytes,
        "status_counts": dict(status_counts),
        "max_concurrent_downloads": parsed_config.max_concurrent_downloads,
    }
    _log_info(
        log,
        (
            "news_feeds: completed thumbnail hydration run_id=%s attempted=%s "
            "downloaded=%s already_existing=%s errors=%s bytes=%s inventory_key=%s"
        ),
        run_id,
        result["attempted"],
        result["downloaded"],
        result["already_existing"],
        result["errors"],
        _format_bytes(total_bytes),
        inventory_key,
    )
    return result


def publish_news_to_platform(
    *,
    s3: Any,
    config: NewsPublishConfig | Mapping[str, Any] | None = None,
    writer: NewsArticleWriter | None = None,
    now: datetime | None = None,
    progress_log: Any | None = None,
) -> dict[str, Any]:
    parsed_config = (
        config
        if isinstance(config, NewsPublishConfig)
        else NewsPublishConfig.model_validate(config or {})
    )
    current_time = now or utc_now()
    log = progress_log or logger
    source_rows = _load_manifest_article_rows(
        s3=s3,
        manifest_prefix=parsed_config.manifest_prefix,
        lookback_days=parsed_config.lookback_days,
        now=current_time,
    )
    deduped_rows = _dedupe_article_rows(source_rows)[: parsed_config.max_articles_per_run]
    thumbnail_map = _load_thumbnail_inventory_map(
        s3=s3,
        inventory_prefix=parsed_config.thumbnail_inventory_prefix,
    )
    articles = [
        _article_payload(
            source_row=source_row,
            thumbnail_map=thumbnail_map,
            updated_at=current_time,
        )
        for source_row in deduped_rows
    ]
    selected_articles = [article for article in articles if article["url"] and article["headline"]]
    skipped = len(articles) - len(selected_articles)
    _log_info(
        log,
        (
            "news_feeds: publishing articles manifests=%s source_rows=%s selected=%s "
            "skipped=%s lookback_days=%s dry_run=%s"
        ),
        len({row.source_manifest_key for row in source_rows}),
        len(source_rows),
        len(selected_articles),
        skipped,
        parsed_config.lookback_days,
        parsed_config.dry_run,
    )

    if writer is None:
        postgres_url = (
            parsed_config.platform_postgres_url.strip() or Settings().platform_postgres_url
        )
        writer = PlatformNewsArticleWriter(postgres_url)

    writer_result = dict(
        writer.upsert_articles(
            selected_articles,
            ensure_schema=parsed_config.ensure_schema,
            dry_run=parsed_config.dry_run,
        )
    )
    result = {
        "source_manifest_count": len({row.source_manifest_key for row in source_rows}),
        "source_row_count": len(source_rows),
        "selected": len(selected_articles),
        "skipped": skipped,
        "published": int(writer_result.get("published") or 0),
        "created": int(writer_result.get("created") or 0),
        "updated": int(writer_result.get("updated") or 0),
        "failed": int(writer_result.get("failed") or 0),
        "dry_run": bool(parsed_config.dry_run),
        "writer_result": writer_result,
    }
    _log_info(
        log,
        (
            "news_feeds: completed platform publish selected=%s published=%s "
            "created=%s updated=%s failed=%s dry_run=%s"
        ),
        result["selected"],
        result["published"],
        result["created"],
        result["updated"],
        result["failed"],
        result["dry_run"],
    )
    return result


class PlatformNewsArticleWriter:
    def __init__(self, postgres_url: str) -> None:
        self._postgres_url = postgres_url.strip()
        if not self._postgres_url:
            raise ValueError("PLATFORM_POSTGRES_URL is required for news publish")

    def upsert_articles(
        self,
        articles: Sequence[Mapping[str, Any]],
        *,
        ensure_schema: bool,
        dry_run: bool,
    ) -> Mapping[str, Any]:
        if dry_run:
            return {
                "published": len(articles),
                "created": 0,
                "updated": 0,
                "failed": 0,
                "dry_run": True,
            }

        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "psycopg is required for platform news writes. Run `uv sync`."
            ) from exc

        created = 0
        updated = 0
        failed = 0
        with psycopg.connect(self._postgres_url) as connection:
            with connection.cursor() as cursor:
                if ensure_schema:
                    _ensure_news_articles_schema(cursor)
                for article in articles:
                    try:
                        cursor.execute(
                            """
                            UPDATE news_articles
                            SET
                                url = %s,
                                canonical_url = %s,
                                headline = %s,
                                summary = %s,
                                source_name = %s,
                                source_feed_url = %s,
                                thumbnail_url = %s,
                                thumbnail_base64 = %s,
                                publish_date = %s,
                                discovered_at = %s,
                                topic_tags = %s,
                                raw_manifest_key = %s,
                                raw_run_id = %s,
                                is_active = %s,
                                updated_at = %s
                            WHERE article_key = %s OR url = %s
                            """,
                            _article_update_params(article),
                        )
                        if cursor.rowcount:
                            updated += cursor.rowcount
                            continue
                        cursor.execute(
                            """
                            INSERT INTO news_articles (
                                article_key,
                                url,
                                canonical_url,
                                headline,
                                summary,
                                source_name,
                                source_feed_url,
                                thumbnail_url,
                                thumbnail_base64,
                                publish_date,
                                discovered_at,
                                topic_tags,
                                raw_manifest_key,
                                raw_run_id,
                                is_active,
                                updated_at
                            )
                            VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s
                            )
                            """,
                            _article_insert_params(article),
                        )
                        created += 1
                    except Exception:
                        failed += 1
                        logger.exception(
                            "news_feeds: failed to upsert article url=%s",
                            article.get("url"),
                        )
                connection.commit()
        return {
            "published": created + updated,
            "created": created,
            "updated": updated,
            "failed": failed,
            "dry_run": False,
        }


def _ensure_news_articles_schema(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS news_articles (
            id bigserial PRIMARY KEY,
            article_key text,
            url text NOT NULL,
            canonical_url text,
            headline text NOT NULL,
            summary text,
            source_name text,
            source_feed_url text,
            thumbnail_url text,
            thumbnail_base64 text,
            publish_date timestamptz,
            discovered_at timestamptz,
            topic_tags text[],
            raw_manifest_key text,
            raw_run_id text,
            is_active boolean NOT NULL DEFAULT true,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    for statement in (
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS url text",
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS headline text",
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS thumbnail_url text",
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS thumbnail_base64 text",
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS publish_date timestamptz",
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS article_key text",
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS canonical_url text",
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS summary text",
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS source_name text",
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS source_feed_url text",
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS discovered_at timestamptz",
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS topic_tags text[]",
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS raw_manifest_key text",
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS raw_run_id text",
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true",
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now()",
        "ALTER TABLE news_articles ALTER COLUMN url TYPE text",
        "ALTER TABLE news_articles ALTER COLUMN headline TYPE text",
        "ALTER TABLE news_articles ALTER COLUMN thumbnail_url TYPE text",
        "CREATE INDEX IF NOT EXISTS news_articles_article_key_lookup_idx ON news_articles(article_key)",
        "CREATE INDEX IF NOT EXISTS news_articles_url_lookup_idx ON news_articles(url)",
        "CREATE INDEX IF NOT EXISTS news_articles_publish_date_idx ON news_articles(publish_date)",
    ):
        cursor.execute(statement)


def _load_manifest_article_rows(
    *,
    s3: Any,
    manifest_prefix: str,
    lookback_days: int,
    now: datetime,
) -> list[ManifestArticleRow]:
    cutoff = _lookback_cutoff(now=now, lookback_days=lookback_days)
    rows: list[ManifestArticleRow] = []
    for manifest_key in sorted(s3.list_keys(prefix=manifest_prefix)):
        manifest = json.loads(s3.read_text(key=manifest_key))
        if not isinstance(manifest, dict):
            raise ValueError(f"News raw manifest must be an object: {manifest_key}")
        run_id = _string_value(manifest.get("run_id"))
        file_entry = _manifest_file_entry(manifest, ARTICLES_FILE_NAME)
        if file_entry is None:
            continue
        source_article_key = _string_value(file_entry.get("s3_key"))
        if not source_article_key:
            raise ValueError(
                f"News file entry is missing s3_key: {manifest_key} {ARTICLES_FILE_NAME}"
            )
        parsed_rows = _read_jsonl_rows(
            text=s3.read_text(key=source_article_key), source_key=source_article_key
        )
        expected_count = file_entry.get("row_count")
        if expected_count is not None and int(expected_count) != len(parsed_rows):
            raise ValueError(
                f"News row_count mismatch for {source_article_key}: "
                f"manifest={expected_count} actual={len(parsed_rows)}"
            )
        for line_number, row in parsed_rows:
            if cutoff is not None and not _row_within_lookback(row, cutoff=cutoff):
                continue
            rows.append(
                ManifestArticleRow(
                    source_manifest_key=manifest_key,
                    source_article_key=source_article_key,
                    source_file_name=ARTICLES_FILE_NAME,
                    source_manifest_run_id=run_id,
                    line_number=line_number,
                    row=row,
                )
            )
    return rows


def _plan_thumbnail_assets(
    source_rows: Sequence[ManifestArticleRow],
    *,
    config: NewsThumbnailHydrationConfig,
) -> list[PlannedThumbnailAsset]:
    planned_assets: list[PlannedThumbnailAsset] = []
    seen: set[str] = set()
    for source_row in source_rows:
        article_key = _article_key(source_row.row)
        source_url = _string_value(source_row.row.get("thumbnail_source_url"))
        if not source_url:
            planned_assets.append(
                PlannedThumbnailAsset(
                    source_row=source_row,
                    article_key=article_key,
                    source_url="",
                    normalized_url="",
                    target_key="",
                    status="missing_url",
                    error="article row does not include thumbnail_source_url",
                )
            )
            continue
        try:
            normalized_url = _validate_thumbnail_url(
                source_url,
                allowed_hosts=config.allowed_thumbnail_hosts,
            )
        except ValueError as exc:
            planned_assets.append(
                PlannedThumbnailAsset(
                    source_row=source_row,
                    article_key=article_key,
                    source_url=source_url,
                    normalized_url="",
                    target_key="",
                    status="validation_error",
                    error=str(exc),
                )
            )
            continue
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        planned_assets.append(
            PlannedThumbnailAsset(
                source_row=source_row,
                article_key=article_key,
                source_url=source_url,
                normalized_url=normalized_url,
                target_key=_thumbnail_target_key(
                    target_prefix=config.target_prefix,
                    normalized_url=normalized_url,
                    name=_name_from_url_or_path(normalized_url),
                ),
            )
        )
    return planned_assets


def _hydrate_planned_thumbnail_assets(
    *,
    s3: Any,
    planned_assets: Sequence[PlannedThumbnailAsset],
    config: NewsThumbnailHydrationConfig,
    download_client: ThumbnailDownloader,
    run_id: str,
    created_at: str,
    progress_log: Any,
) -> list[dict[str, Any]]:
    if not planned_assets:
        return []
    max_bytes = config.max_thumbnail_mb * 1024 * 1024
    worker_count = min(config.max_concurrent_downloads, len(planned_assets))
    if worker_count == 1:
        rows: list[dict[str, Any]] = []
        status_counts: Counter[str] = Counter()
        downloaded_bytes = 0
        for index, planned_asset in enumerate(planned_assets, start=1):
            row = _hydrate_single_thumbnail_asset(
                s3=s3,
                planned_asset=planned_asset,
                config=config,
                download_client=download_client,
                max_bytes=max_bytes,
                run_id=run_id,
                created_at=created_at,
                progress_log=progress_log,
                index=index,
                total=len(planned_assets),
            )
            rows.append(row)
            status_counts[str(row.get("status"))] += 1
            downloaded_bytes += _inventory_row_downloaded_bytes(row)
            _log_thumbnail_progress(
                progress_log,
                completed=index,
                total=len(planned_assets),
                status_counts=status_counts,
                downloaded_bytes=downloaded_bytes,
            )
        return rows

    rows_by_index: dict[int, dict[str, Any]] = {}
    assets_by_index = dict(enumerate(planned_assets, start=1))
    status_counts: Counter[str] = Counter()
    downloaded_bytes = 0
    _log_info(
        progress_log,
        "news_feeds: thumbnail hydration starting assets=%s workers=%s overwrite_existing=%s",
        len(planned_assets),
        worker_count,
        config.overwrite_existing,
    )
    with ThreadPoolExecutor(
        max_workers=worker_count, thread_name_prefix="news-thumbnails"
    ) as executor:
        future_to_index = {
            executor.submit(
                _hydrate_single_thumbnail_asset,
                s3=s3,
                planned_asset=planned_asset,
                config=config,
                download_client=download_client,
                max_bytes=max_bytes,
                run_id=run_id,
                created_at=created_at,
                progress_log=progress_log,
                index=index,
                total=len(planned_assets),
            ): index
            for index, planned_asset in assets_by_index.items()
        }
        for completed_count, future in enumerate(as_completed(future_to_index), start=1):
            index = future_to_index[future]
            try:
                rows_by_index[index] = future.result()
            except Exception as exc:  # noqa: BLE001
                planned_asset = assets_by_index[index]
                row = _base_thumbnail_inventory_row(
                    planned_asset=planned_asset,
                    run_id=run_id,
                    created_at=created_at,
                    s3=s3,
                )
                row.update({"status": "download_error", "error": str(exc)})
                rows_by_index[index] = row
            status_counts[str(rows_by_index[index].get("status"))] += 1
            downloaded_bytes += _inventory_row_downloaded_bytes(rows_by_index[index])
            _log_thumbnail_progress(
                progress_log,
                completed=completed_count,
                total=len(planned_assets),
                status_counts=status_counts,
                downloaded_bytes=downloaded_bytes,
            )
    return [rows_by_index[index] for index in range(1, len(planned_assets) + 1)]


def _hydrate_single_thumbnail_asset(
    *,
    s3: Any,
    planned_asset: PlannedThumbnailAsset,
    config: NewsThumbnailHydrationConfig,
    download_client: ThumbnailDownloader,
    max_bytes: int,
    run_id: str,
    created_at: str,
    progress_log: Any,
    index: int,
    total: int,
) -> dict[str, Any]:
    inventory_row = _base_thumbnail_inventory_row(
        planned_asset=planned_asset,
        run_id=run_id,
        created_at=created_at,
        s3=s3,
    )
    if planned_asset.status is not None:
        inventory_row.update({"status": planned_asset.status, "error": planned_asset.error})
        return inventory_row

    attempted_download = False
    try:
        if not config.overwrite_existing and s3.object_exists(key=planned_asset.target_key):
            inventory_row["status"] = "already_exists"
            return inventory_row

        attempted_download = True
        download = download_client.download_thumbnail(
            planned_asset.normalized_url, max_bytes=max_bytes
        )
        final_url = _validate_thumbnail_url(
            download.final_url,
            allowed_hosts=config.allowed_thumbnail_hosts,
        )
        if len(download.content) > max_bytes:
            raise ThumbnailTooLargeError(f"thumbnail exceeds max size of {max_bytes} bytes")
        sha256 = hashlib.sha256(download.content).hexdigest()
        s3.put_bytes(
            key=planned_asset.target_key,
            payload=download.content,
            content_type=download.content_type,
        )
        inventory_row.update(
            {
                "status": "downloaded",
                "sha256": sha256,
                "size_bytes": len(download.content),
                "content_type": download.content_type,
                "final_url": final_url,
            }
        )
        if index <= 5 or index % _THUMBNAIL_LOG_INTERVAL == 0 or index == total:
            _log_info(
                progress_log,
                "news_feeds: hydrated thumbnail %s/%s article_key=%s key=%s size=%s",
                index,
                total,
                planned_asset.article_key,
                planned_asset.target_key,
                len(download.content),
            )
    except ValueError as exc:
        inventory_row.update({"status": "validation_error", "error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        status = "too_large" if isinstance(exc, ThumbnailTooLargeError) else "download_error"
        inventory_row.update({"status": status, "error": str(exc)})
    finally:
        if attempted_download and config.request_pause_seconds:
            time.sleep(config.request_pause_seconds)
    return inventory_row


def _base_thumbnail_inventory_row(
    *,
    planned_asset: PlannedThumbnailAsset,
    run_id: str,
    created_at: str,
    s3: Any,
) -> dict[str, Any]:
    source_row = planned_asset.source_row
    row: dict[str, Any] = {
        "run_id": run_id,
        "created_at": created_at,
        "source_manifest": source_row.source_manifest_key,
        "source_manifest_run_id": source_row.source_manifest_run_id,
        "source_article_key": source_row.source_article_key,
        "source_file_name": source_row.source_file_name,
        "source_article_line": source_row.line_number,
        "source_article_row": source_row.row,
        "article_key": planned_asset.article_key,
        "url": _string_value(source_row.row.get("url")),
        "canonical_url": _string_value(source_row.row.get("canonical_url")),
        "headline": _string_value(source_row.row.get("headline")),
        "source_feed_url": _string_value(source_row.row.get("source_feed_url")),
        "source_name": _string_value(source_row.row.get("source_name")),
    }
    if planned_asset.source_url:
        row["thumbnail_source_url"] = planned_asset.source_url
    if planned_asset.normalized_url:
        row["normalized_url"] = planned_asset.normalized_url
    if planned_asset.target_key:
        row["target_key"] = planned_asset.target_key
        public_url = (
            s3.public_url(key=planned_asset.target_key) if hasattr(s3, "public_url") else None
        )
        if public_url:
            row["public_url"] = public_url
    return row


def _load_thumbnail_inventory_map(*, s3: Any, inventory_prefix: str) -> dict[str, dict[str, Any]]:
    inventory_rows: dict[str, dict[str, Any]] = {}
    for inventory_key in sorted(s3.list_keys(prefix=inventory_prefix)):
        if not inventory_key.endswith(".jsonl"):
            continue
        for _, row in _read_jsonl_rows(
            text=s3.read_text(key=inventory_key), source_key=inventory_key
        ):
            normalized_url = _string_value(row.get("normalized_url"))
            if not normalized_url:
                continue
            status = _string_value(row.get("status"))
            if status not in {"downloaded", "already_exists"}:
                continue
            inventory_rows[normalized_url] = row
    return inventory_rows


def _dedupe_article_rows(source_rows: Sequence[ManifestArticleRow]) -> list[ManifestArticleRow]:
    by_key: dict[str, ManifestArticleRow] = {}
    for source_row in source_rows:
        key = _article_key(source_row.row)
        existing = by_key.get(key)
        if existing is None or _row_sort_datetime(source_row.row) >= _row_sort_datetime(
            existing.row
        ):
            by_key[key] = source_row
    return sorted(by_key.values(), key=lambda row: _row_sort_datetime(row.row), reverse=True)


def _article_payload(
    *,
    source_row: ManifestArticleRow,
    thumbnail_map: Mapping[str, Mapping[str, Any]],
    updated_at: datetime,
) -> dict[str, Any]:
    row = source_row.row
    thumbnail_source_url = _string_value(row.get("thumbnail_source_url"))
    normalized_thumbnail_url = ""
    if thumbnail_source_url:
        try:
            normalized_thumbnail_url = _validate_thumbnail_url(
                thumbnail_source_url,
                allowed_hosts=(),
            )
        except ValueError:
            normalized_thumbnail_url = ""
    thumbnail_inventory = (
        thumbnail_map.get(normalized_thumbnail_url) if normalized_thumbnail_url else None
    )
    thumbnail_url = (
        _string_value(thumbnail_inventory.get("public_url")) if thumbnail_inventory else ""
    )
    if not thumbnail_url:
        thumbnail_url = thumbnail_source_url
    headline = clean_text(_string_value(row.get("headline")))
    summary = clean_text(_string_value(row.get("summary")))
    return {
        "article_key": _article_key(row),
        "url": _string_value(row.get("url")),
        "canonical_url": _string_value(row.get("canonical_url")),
        "headline": headline,
        "summary": summary,
        "source_name": _string_value(row.get("source_name")),
        "source_feed_url": _string_value(row.get("source_feed_url")),
        "thumbnail_url": thumbnail_url or None,
        "thumbnail_asset_key": (
            _string_value(thumbnail_inventory.get("target_key")) if thumbnail_inventory else None
        ),
        "thumbnail_source_url": thumbnail_source_url or None,
        "publish_date": _parse_datetime(row.get("publish_date")),
        "discovered_at": _parse_datetime(row.get("discovered_at") or row.get("_scraped_at")),
        "topic_tags": _infer_topic_tags(headline=headline, summary=summary, row=row),
        "raw_manifest_key": source_row.source_manifest_key,
        "raw_run_id": source_row.source_manifest_run_id,
        "is_active": True,
        "updated_at": updated_at,
    }


def _article_update_params(article: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        article["url"],
        article["canonical_url"] or None,
        _trim_text(article["headline"], 1000),
        _trim_text(article["summary"], 4000) or None,
        article["source_name"] or None,
        article["source_feed_url"] or None,
        article["thumbnail_url"],
        None,
        article["publish_date"],
        article["discovered_at"],
        article["topic_tags"],
        article["raw_manifest_key"],
        article["raw_run_id"],
        article["is_active"],
        article["updated_at"],
        article["article_key"],
        article["url"],
    )


def _article_insert_params(article: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        article["article_key"],
        article["url"],
        article["canonical_url"] or None,
        _trim_text(article["headline"], 1000),
        _trim_text(article["summary"], 4000) or None,
        article["source_name"] or None,
        article["source_feed_url"] or None,
        article["thumbnail_url"],
        None,
        article["publish_date"],
        article["discovered_at"],
        article["topic_tags"],
        article["raw_manifest_key"],
        article["raw_run_id"],
        article["is_active"],
        article["updated_at"],
    )


def _infer_topic_tags(*, headline: str, summary: str, row: Mapping[str, Any]) -> list[str]:
    text = " ".join(
        (
            headline,
            summary,
            _string_value(row.get("source_name")),
            _string_value(row.get("source_feed_url")),
        )
    ).lower()
    rules = {
        "dubai": ("dubai", "dxb"),
        "abu_dhabi": ("abu dhabi",),
        "uae": ("uae", "emirates"),
        "offplan": ("off-plan", "off plan", "new launch", "launches"),
        "rentals": ("rent", "rental", "tenant", "lease"),
        "sales": ("sale", "sales", "sold", "transaction"),
        "mortgages": ("mortgage", "interest rate"),
        "developers": ("developer", "aldar", "emaar", "nakheel", "damac", "sobha"),
        "market": ("market", "price", "prices", "yield", "demand"),
        "policy": ("law", "regulation", "policy", "visa", "tax"),
        "infrastructure": ("metro", "airport", "road", "transport", "infrastructure"),
        "commercial": ("office", "retail", "commercial"),
        "luxury": ("luxury", "prime", "branded residence"),
    }
    tags = [tag for tag, needles in rules.items() if any(needle in text for needle in needles)]
    return sorted(set(tags))


def _manifest_file_entry(manifest: Mapping[str, Any], file_name: str) -> dict[str, Any] | None:
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("News raw manifest files must be a list")
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("News raw manifest files must contain objects")
        if Path(_string_value(item.get("path"))).name == file_name:
            return item
    return None


def _read_jsonl_rows(*, text: str, source_key: str) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError(f"News row must be an object: {source_key}:{line_number}")
        rows.append((line_number, payload))
    return rows


def _validate_thumbnail_url(url: str, *, allowed_hosts: Sequence[str]) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in _PUBLIC_NEWS_URL_SCHEMES:
        raise ValueError("thumbnail URL must use http or https")
    if parsed.username or parsed.password:
        raise ValueError("thumbnail URL must not include credentials")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("thumbnail URL must include a host")
    if _is_private_or_local_host(host):
        raise ValueError(f"thumbnail URL host is private or local: {host}")
    allowed = tuple(item.lower().strip() for item in allowed_hosts)
    if allowed and not any(host == item or host.endswith(f".{item}") for item in allowed):
        raise ValueError(f"thumbnail URL host is not allowlisted: {host}")
    return parsed._replace(fragment="").geturl()


def _is_private_or_local_host(host: str) -> bool:
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _thumbnail_target_key(*, target_prefix: str, normalized_url: str, name: str) -> str:
    url_sha256 = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()
    return f"{target_prefix.rstrip('/')}/{url_sha256}/{_safe_target_file_name(name=name, normalized_url=normalized_url)}"


def _name_from_url_or_path(value: str) -> str:
    parsed = urlparse(value)
    candidate = Path(parsed.path).name
    return candidate or hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _safe_target_file_name(*, name: str, normalized_url: str) -> str:
    parsed_suffix = Path(urlparse(normalized_url).path).suffix
    content_suffix = mimetypes.guess_extension(mimetypes.guess_type(normalized_url)[0] or "")
    suffix = (
        parsed_suffix if parsed_suffix and len(parsed_suffix) <= 12 else content_suffix or ".bin"
    )
    stem = Path(name).stem or "thumbnail"
    safe_stem = _safe_path_segment(stem) or "thumbnail"
    if len(safe_stem) > 120:
        safe_stem = safe_stem[:120]
    return f"{safe_stem}{suffix}"


def _safe_path_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._=-]+", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("._")
    return cleaned or "unknown"


def _inventory_key(*, prefix: str, run_id: str, file_name: str) -> str:
    return f"{prefix.rstrip('/')}/run_id={_safe_path_segment(run_id)}/{file_name}"


def _jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    row_list = list(rows)
    if not row_list:
        return b""
    return (
        "\n".join(
            json.dumps(row, ensure_ascii=False, default=str, separators=(",", ":"))
            for row in row_list
        )
        + "\n"
    ).encode("utf-8")


def _lookback_cutoff(*, now: datetime, lookback_days: int) -> datetime | None:
    if lookback_days <= 0:
        return None
    current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return current.astimezone(UTC) - timedelta(days=lookback_days)


def _row_within_lookback(row: Mapping[str, Any], *, cutoff: datetime) -> bool:
    candidates = (
        _parse_datetime(row.get("publish_date")),
        _parse_datetime(row.get("discovered_at")),
        _parse_datetime(row.get("_scraped_at")),
    )
    parsed_candidates = [candidate for candidate in candidates if candidate is not None]
    if not parsed_candidates:
        return True
    return any(candidate >= cutoff for candidate in parsed_candidates)


def _row_sort_datetime(row: Mapping[str, Any]) -> datetime:
    return (
        _parse_datetime(row.get("publish_date"))
        or _parse_datetime(row.get("discovered_at"))
        or _parse_datetime(row.get("_scraped_at"))
        or datetime.min.replace(tzinfo=UTC)
    )


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _article_key(row: Mapping[str, Any]) -> str:
    key = _string_value(row.get("article_key"))
    if key:
        return key
    basis = _string_value(row.get("canonical_url")) or _string_value(row.get("url"))
    if not basis:
        basis = "|".join(
            (
                _string_value(row.get("source_feed_url")),
                _string_value(row.get("guid")),
                _string_value(row.get("headline")),
            )
        )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _inventory_row_downloaded_bytes(inventory_row: Mapping[str, Any]) -> int:
    if inventory_row.get("status") != "downloaded":
        return 0
    return int(inventory_row.get("size_bytes") or 0)


def _thumbnail_headers() -> dict[str, str]:
    return {
        "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        ),
    }


def _trim_text(value: Any, limit: int) -> str:
    text = _string_value(value)
    return text[:limit]


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _log_thumbnail_progress(
    progress_log: Any,
    *,
    completed: int,
    total: int,
    status_counts: Counter[str],
    downloaded_bytes: int,
) -> None:
    if completed <= 5 or completed % _THUMBNAIL_LOG_INTERVAL == 0 or completed == total:
        _log_info(
            progress_log,
            (
                "news_feeds: thumbnail progress completed=%s/%s downloaded=%s "
                "already_exists=%s missing_url=%s validation_error=%s download_error=%s "
                "too_large=%s bytes=%s"
            ),
            completed,
            total,
            status_counts["downloaded"],
            status_counts["already_exists"],
            status_counts["missing_url"],
            status_counts["validation_error"],
            status_counts["download_error"],
            status_counts["too_large"],
            _format_bytes(downloaded_bytes),
        )


def _format_bytes(size_bytes: float | int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def _log_info(progress_log: Any, message: str, *args: Any) -> None:
    progress_log.info(message, *args)
