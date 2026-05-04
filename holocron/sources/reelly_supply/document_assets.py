"""Reelly document asset hydration from previously uploaded raw manifests."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from holocron.platform.execution import new_run_id, utc_now
from holocron.sources.reelly_supply.extract import (
    DocumentDownload,
    DocumentTooLargeError,
    ReellySupplyApiClient,
    _dedupe_documents,
    _discover_documents,
    _name_from_url_or_path,
    _safe_path_segment,
    _validate_document_url,
)
from holocron.sources.reelly_supply.source import REELLY_DEFAULT_ALLOWED_DOCUMENT_HOSTS

logger = logging.getLogger(__name__)

_DOCUMENTS_FILE_NAME = "reelly_supply_project_documents.jsonl"
_PROJECT_DETAILS_FILE_NAME = "reelly_supply_project_details.jsonl"
_INVENTORY_FILE_NAME = "reelly_supply_document_assets.jsonl"


class ReellyDocumentAssetHydrationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_prefix: str = "raw/source=reelly_supply/manifests/"
    target_prefix: str = "media/reelly_supply/documents"
    inventory_prefix: str = "raw/source=reelly_supply/document_asset_manifests"
    max_assets_per_run: int = Field(default=500, ge=1)
    overwrite_existing: bool = False
    allowed_document_hosts: tuple[str, ...] = REELLY_DEFAULT_ALLOWED_DOCUMENT_HOSTS
    max_document_mb: int = Field(default=100, ge=1)
    request_pause_seconds: float = Field(default=0, ge=0)
    timeout_seconds: float = Field(default=60, ge=1)
    max_concurrent_downloads: int = Field(default=1, ge=1, le=32)
    include_project_documents: bool = True
    include_project_detail_media: bool = False
    structured_target_keys: bool = False
    asset_type_allowlist: tuple[str, ...] = ()
    inventory_file_name: str = _INVENTORY_FILE_NAME

    @field_validator("allowed_document_hosts", mode="before")
    @classmethod
    def coerce_allowed_document_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(host.strip() for host in value.split(",") if host.strip())
        return value

    @field_validator("asset_type_allowlist", mode="before")
    @classmethod
    def coerce_asset_type_allowlist(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(
                asset_type.strip() for asset_type in value.split(",") if asset_type.strip()
            )
        return value

    @model_validator(mode="after")
    def validate_config(self) -> "ReellyDocumentAssetHydrationConfig":
        if not self.manifest_prefix.strip():
            raise ValueError("manifest_prefix must not be blank")
        if not self.target_prefix.strip():
            raise ValueError("target_prefix must not be blank")
        if not self.inventory_prefix.strip():
            raise ValueError("inventory_prefix must not be blank")
        if not self.allowed_document_hosts:
            raise ValueError("allowed_document_hosts must include at least one host")
        if any(not host.strip() for host in self.allowed_document_hosts):
            raise ValueError("allowed_document_hosts must not include blank hosts")
        if not self.include_project_documents and not self.include_project_detail_media:
            raise ValueError(
                "at least one of include_project_documents or include_project_detail_media "
                "must be true"
            )
        if not self.inventory_file_name.strip():
            raise ValueError("inventory_file_name must not be blank")
        if any(not asset_type.strip() for asset_type in self.asset_type_allowlist):
            raise ValueError("asset_type_allowlist must not include blank asset types")
        return self


@dataclass(frozen=True, slots=True)
class ManifestDocumentRow:
    source_manifest_key: str
    source_document_key: str
    source_file_name: str
    source_manifest_run_id: str
    line_number: int
    row: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PlannedDocumentAsset:
    source_row: ManifestDocumentRow
    project_id: str
    name: str
    source_url: str
    normalized_url: str
    target_key: str
    asset_type: str
    field_path: str
    status: str | None = None
    error: str | None = None


class DocumentDownloader(Protocol):
    def download_document(self, url: str, *, max_bytes: int) -> DocumentDownload: ...


def hydrate_reelly_document_assets(
    *,
    s3: Any,
    config: ReellyDocumentAssetHydrationConfig | Mapping[str, Any] | None = None,
    now: datetime | None = None,
    download_client: DocumentDownloader | None = None,
    progress_log: Any | None = None,
) -> dict[str, Any]:
    parsed_config = (
        config
        if isinstance(config, ReellyDocumentAssetHydrationConfig)
        else ReellyDocumentAssetHydrationConfig.model_validate(config or {})
    )
    current_time = now or utc_now()
    run_id = new_run_id(current_time)
    log = progress_log or logger

    source_rows = _load_manifest_asset_rows(s3=s3, config=parsed_config)
    planned_assets = _plan_document_assets(source_rows, config=parsed_config)
    selected_assets = planned_assets[: parsed_config.max_assets_per_run]
    _log_info(
        log,
        (
            "reelly_supply: hydrating document assets manifests=%s discovered=%s "
            "selected=%s max_assets_per_run=%s overwrite_existing=%s "
            "max_concurrent_downloads=%s"
        ),
        len({row.source_manifest_key for row in source_rows}),
        len(planned_assets),
        len(selected_assets),
        parsed_config.max_assets_per_run,
        parsed_config.overwrite_existing,
        parsed_config.max_concurrent_downloads,
    )

    if download_client is None:
        with httpx.Client(
            timeout=parsed_config.timeout_seconds,
            follow_redirects=True,
        ) as client:
            download_client = ReellySupplyApiClient(
                client=client,
                base_url="",
                documents_base_url="",
                availability_base_url="",
                allowed_document_hosts=parsed_config.allowed_document_hosts,
            )
            inventory_rows = _hydrate_planned_assets(
                s3=s3,
                planned_assets=selected_assets,
                config=parsed_config,
                download_client=download_client,
                run_id=run_id,
                created_at=current_time.isoformat(),
                progress_log=log,
            )
    else:
        inventory_rows = _hydrate_planned_assets(
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
        "source_document_row_count": len(source_rows),
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
            "reelly_supply: completed document asset hydration run_id=%s attempted=%s "
            "downloaded=%s already_existing=%s errors=%s bytes=%s inventory_key=%s"
        ),
        run_id,
        result["attempted"],
        result["downloaded"],
        result["already_existing"],
        result["errors"],
        total_bytes,
        inventory_key,
    )
    return result


def _load_manifest_document_rows(*, s3: Any, manifest_prefix: str) -> list[ManifestDocumentRow]:
    config = ReellyDocumentAssetHydrationConfig(
        manifest_prefix=manifest_prefix,
        include_project_documents=True,
        include_project_detail_media=False,
    )
    return _load_manifest_asset_rows(s3=s3, config=config)


def _load_manifest_asset_rows(
    *,
    s3: Any,
    config: ReellyDocumentAssetHydrationConfig,
) -> list[ManifestDocumentRow]:
    rows: list[ManifestDocumentRow] = []
    for manifest_key in sorted(s3.list_keys(prefix=config.manifest_prefix)):
        manifest = json.loads(s3.read_text(key=manifest_key))
        if not isinstance(manifest, dict):
            raise ValueError(f"Reelly raw manifest must be an object: {manifest_key}")
        run_id = _string_value(manifest.get("run_id"))
        if config.include_project_documents:
            rows.extend(
                _load_manifest_jsonl_rows(
                    s3=s3,
                    manifest=manifest,
                    manifest_key=manifest_key,
                    run_id=run_id,
                    file_name=_DOCUMENTS_FILE_NAME,
                    strict=True,
                )
            )
        if config.include_project_detail_media:
            detail_rows = _load_manifest_jsonl_rows(
                s3=s3,
                manifest=manifest,
                manifest_key=manifest_key,
                run_id=run_id,
                file_name=_PROJECT_DETAILS_FILE_NAME,
                strict=False,
            )
            rows.extend(
                _project_detail_media_rows(
                    detail_rows,
                    allowed_document_hosts=config.allowed_document_hosts,
                )
            )
    return rows


def _load_manifest_jsonl_rows(
    *,
    s3: Any,
    manifest: Mapping[str, Any],
    manifest_key: str,
    run_id: str,
    file_name: str,
    strict: bool,
) -> list[ManifestDocumentRow]:
    file_entry = _manifest_file_entry(manifest, file_name)
    if file_entry is None:
        return []
    source_document_key = _string_value(file_entry.get("s3_key"))
    if not source_document_key:
        raise ValueError(f"Reelly file entry is missing s3_key: {manifest_key} {file_name}")
    parsed_rows = _read_jsonl_rows(
        text=s3.read_text(key=source_document_key),
        source_key=source_document_key,
        strict=strict,
    )
    expected_count = file_entry.get("row_count")
    if strict and expected_count is not None and int(expected_count) != len(parsed_rows):
        raise ValueError(
            f"Reelly row_count mismatch for {source_document_key}: "
            f"manifest={expected_count} actual={len(parsed_rows)}"
        )
    rows: list[ManifestDocumentRow] = []
    for line_number, row in parsed_rows:
        rows.append(
            ManifestDocumentRow(
                source_manifest_key=manifest_key,
                source_document_key=source_document_key,
                source_file_name=file_name,
                source_manifest_run_id=run_id,
                line_number=line_number,
                row=row,
            )
        )
    return rows


def _project_detail_media_rows(
    detail_rows: Sequence[ManifestDocumentRow],
    *,
    allowed_document_hosts: Sequence[str],
) -> list[ManifestDocumentRow]:
    rows: list[ManifestDocumentRow] = []
    for detail_row in detail_rows:
        project_id = detail_row.row.get("project_id")
        documents = _dedupe_documents(
            _discover_documents(
                detail_row.row.get("raw"),
                project_id=project_id,
                source_endpoint="projects",
                download_all_project_docs=True,
                allowed_document_hosts=allowed_document_hosts,
            )
        )
        for index, document in enumerate(documents, start=1):
            rows.append(
                ManifestDocumentRow(
                    source_manifest_key=detail_row.source_manifest_key,
                    source_document_key=detail_row.source_document_key,
                    source_file_name=detail_row.source_file_name,
                    source_manifest_run_id=detail_row.source_manifest_run_id,
                    line_number=detail_row.line_number,
                    row={
                        "endpoint": document.source_endpoint,
                        "project_id": document.project_id,
                        "field_path": document.field_path,
                        "name": document.name,
                        "url": document.url,
                        "normalized_url": document.normalized_url,
                        "raw": document.raw,
                        "status": "discovered",
                        "source_row_type": "project_details",
                        "source_detail_line": detail_row.line_number,
                        "source_detail_media_index": index,
                    },
                )
            )
    return rows


def _plan_document_assets(
    source_rows: Sequence[ManifestDocumentRow],
    *,
    config: ReellyDocumentAssetHydrationConfig,
) -> list[PlannedDocumentAsset]:
    planned_assets: list[PlannedDocumentAsset] = []
    seen: set[tuple[str, str]] = set()
    asset_type_allowlist = set(config.asset_type_allowlist)
    for source_row in source_rows:
        row = source_row.row
        project_id = _string_value(row.get("project_id"))
        name = _string_value(row.get("name"))
        field_path = _string_value(row.get("field_path"))
        asset_type = _asset_type_for_row(row)
        if asset_type_allowlist and asset_type not in asset_type_allowlist:
            continue
        source_url = _string_value(row.get("url"))
        candidate_url = _string_value(row.get("normalized_url")) or source_url

        if not candidate_url:
            planned_assets.append(
                PlannedDocumentAsset(
                    source_row=source_row,
                    project_id=project_id,
                    name=name,
                    source_url=source_url,
                    normalized_url="",
                    target_key="",
                    asset_type=asset_type,
                    field_path=field_path,
                    status="missing_url",
                    error="document row does not include url or normalized_url",
                )
            )
            continue
        if not source_url:
            source_url = candidate_url
        if not project_id:
            planned_assets.append(
                PlannedDocumentAsset(
                    source_row=source_row,
                    project_id=project_id,
                    name=name,
                    source_url=source_url,
                    normalized_url="",
                    target_key="",
                    asset_type=asset_type,
                    field_path=field_path,
                    status="validation_error",
                    error="document row does not include project_id",
                )
            )
            continue

        try:
            normalized_url = _validate_document_url(
                candidate_url,
                allowed_hosts=config.allowed_document_hosts,
            )
        except ValueError as exc:
            planned_assets.append(
                PlannedDocumentAsset(
                    source_row=source_row,
                    project_id=project_id,
                    name=name,
                    source_url=source_url,
                    normalized_url="",
                    target_key="",
                    asset_type=asset_type,
                    field_path=field_path,
                    status="validation_error",
                    error=str(exc),
                )
            )
            continue

        dedupe_key = (project_id, normalized_url)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        planned_assets.append(
            PlannedDocumentAsset(
                source_row=source_row,
                project_id=project_id,
                name=name,
                source_url=source_url,
                normalized_url=normalized_url,
                target_key=_target_key(
                    target_prefix=config.target_prefix,
                    project_id=project_id,
                    normalized_url=normalized_url,
                    name=name,
                    asset_type=asset_type,
                    field_path=field_path,
                    structured=config.structured_target_keys,
                ),
                asset_type=asset_type,
                field_path=field_path,
            )
        )
    return planned_assets


def _hydrate_planned_assets(
    *,
    s3: Any,
    planned_assets: Sequence[PlannedDocumentAsset],
    config: ReellyDocumentAssetHydrationConfig,
    download_client: DocumentDownloader,
    run_id: str,
    created_at: str,
    progress_log: Any,
) -> list[dict[str, Any]]:
    status_counts: Counter[str] = Counter()
    max_bytes = config.max_document_mb * 1024 * 1024
    total_assets = len(planned_assets)
    downloaded_bytes = 0
    if total_assets == 0:
        return []

    worker_count = min(config.max_concurrent_downloads, total_assets)
    if worker_count > 1:
        _log_info(
            progress_log,
            "reelly_supply: document asset hydration using parallel workers=%s total_assets=%s",
            worker_count,
            total_assets,
        )

    if worker_count == 1:
        inventory_rows: list[dict[str, Any]] = []
        for index, planned_asset in enumerate(planned_assets, start=1):
            inventory_row = _hydrate_single_planned_asset(
                s3=s3,
                planned_asset=planned_asset,
                config=config,
                download_client=download_client,
                max_bytes=max_bytes,
                run_id=run_id,
                created_at=created_at,
                progress_log=progress_log,
                index=index,
                total=total_assets,
            )
            inventory_rows.append(inventory_row)
            downloaded_bytes += _inventory_row_downloaded_bytes(inventory_row)
            status_counts[str(inventory_row["status"])] += 1
            _log_hydration_progress(
                progress_log,
                index=index,
                total=total_assets,
                status_counts=status_counts,
                downloaded_bytes=downloaded_bytes,
            )
        return inventory_rows

    rows_by_index: dict[int, dict[str, Any]] = {}
    assets_by_index = dict(enumerate(planned_assets, start=1))
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="reelly-document-assets",
    ) as executor:
        future_to_index = {
            executor.submit(
                _hydrate_single_planned_asset,
                s3=s3,
                planned_asset=planned_asset,
                config=config,
                download_client=download_client,
                max_bytes=max_bytes,
                run_id=run_id,
                created_at=created_at,
                progress_log=progress_log,
                index=index,
                total=total_assets,
            ): index
            for index, planned_asset in assets_by_index.items()
        }
        for completed_count, future in enumerate(as_completed(future_to_index), start=1):
            index = future_to_index[future]
            try:
                inventory_row = future.result()
            except Exception as exc:  # noqa: BLE001
                planned_asset = assets_by_index[index]
                inventory_row = _base_inventory_row(
                    planned_asset=planned_asset,
                    run_id=run_id,
                    created_at=created_at,
                    s3=s3,
                )
                inventory_row.update({"status": "download_error", "error": str(exc)})
                _log_warning(
                    progress_log,
                    (
                        "reelly_supply: document asset worker failed completed=%s/%s "
                        "asset_index=%s project_id=%s target_key=%s error=%s"
                    ),
                    completed_count,
                    total_assets,
                    index,
                    planned_asset.project_id,
                    planned_asset.target_key,
                    exc,
                )
            rows_by_index[index] = inventory_row
            downloaded_bytes += _inventory_row_downloaded_bytes(inventory_row)
            status_counts[str(inventory_row["status"])] += 1
            _log_hydration_progress(
                progress_log,
                index=completed_count,
                total=total_assets,
                status_counts=status_counts,
                downloaded_bytes=downloaded_bytes,
            )

    return [rows_by_index[index] for index in range(1, total_assets + 1)]


def _hydrate_single_planned_asset(
    *,
    s3: Any,
    planned_asset: PlannedDocumentAsset,
    config: ReellyDocumentAssetHydrationConfig,
    download_client: DocumentDownloader,
    max_bytes: int,
    run_id: str,
    created_at: str,
    progress_log: Any,
    index: int,
    total: int,
) -> dict[str, Any]:
    inventory_row = _base_inventory_row(
        planned_asset=planned_asset,
        run_id=run_id,
        created_at=created_at,
        s3=s3,
    )
    if planned_asset.status is not None:
        inventory_row["status"] = planned_asset.status
        inventory_row["error"] = planned_asset.error
        _log_warning(
            progress_log,
            (
                "reelly_supply: skipped document asset asset_index=%s/%s status=%s "
                "project_id=%s field_path=%s source_line=%s error=%s"
            ),
            index,
            total,
            planned_asset.status,
            planned_asset.project_id,
            planned_asset.source_row.row.get("field_path"),
            planned_asset.source_row.line_number,
            planned_asset.error,
        )
        return inventory_row

    attempted_download = False
    try:
        if not config.overwrite_existing and s3.object_exists(key=planned_asset.target_key):
            inventory_row["status"] = "already_exists"
            _log_info(
                progress_log,
                (
                    "reelly_supply: skipped existing document asset asset_index=%s/%s "
                    "project_id=%s target_key=%s"
                ),
                index,
                total,
                planned_asset.project_id,
                planned_asset.target_key,
            )
            return inventory_row

        attempted_download = True
        download = download_client.download_document(
            planned_asset.normalized_url,
            max_bytes=max_bytes,
        )
        final_url = _validate_document_url(
            download.final_url,
            allowed_hosts=config.allowed_document_hosts,
        )
        if len(download.content) > max_bytes:
            raise DocumentTooLargeError(f"document exceeds max size of {max_bytes} bytes")
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
        _log_info(
            progress_log,
            (
                "reelly_supply: hydrated document asset asset_index=%s/%s "
                "project_id=%s target_key=%s size=%s"
            ),
            index,
            total,
            planned_asset.project_id,
            planned_asset.target_key,
            len(download.content),
        )
    except ValueError as exc:
        inventory_row.update({"status": "validation_error", "error": str(exc)})
        _log_warning(
            progress_log,
            (
                "reelly_supply: document asset validation failed asset_index=%s/%s "
                "project_id=%s target_key=%s error=%s"
            ),
            index,
            total,
            planned_asset.project_id,
            planned_asset.target_key,
            exc,
        )
    except Exception as exc:  # noqa: BLE001
        status = "too_large" if _is_too_large_error(exc) else "download_error"
        inventory_row.update(
            {
                "status": status,
                "error": str(exc),
            }
        )
        _log_warning(
            progress_log,
            (
                "reelly_supply: document asset download failed asset_index=%s/%s "
                "status=%s project_id=%s target_key=%s error=%s"
            ),
            index,
            total,
            status,
            planned_asset.project_id,
            planned_asset.target_key,
            exc,
        )
    finally:
        if attempted_download and config.request_pause_seconds:
            time.sleep(config.request_pause_seconds)
    return inventory_row


def _inventory_row_downloaded_bytes(inventory_row: Mapping[str, Any]) -> int:
    if inventory_row.get("status") != "downloaded":
        return 0
    return int(inventory_row.get("size_bytes") or 0)


def _document_file_entry(manifest: Mapping[str, Any]) -> dict[str, Any] | None:
    return _manifest_file_entry(manifest, _DOCUMENTS_FILE_NAME)


def _manifest_file_entry(manifest: Mapping[str, Any], file_name: str) -> dict[str, Any] | None:
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("Reelly raw manifest files must be a list")
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("Reelly raw manifest files must contain objects")
        if Path(_string_value(item.get("path"))).name == file_name:
            return item
    return None


def _read_jsonl_rows(
    *,
    text: str,
    source_key: str,
    strict: bool = True,
) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            if strict:
                raise
            continue
        if not isinstance(payload, dict):
            raise ValueError(f"Reelly document row must be an object: {source_key}:{line_number}")
        rows.append((line_number, payload))
    return rows


def _base_inventory_row(
    *,
    planned_asset: PlannedDocumentAsset,
    run_id: str,
    created_at: str,
    s3: Any,
) -> dict[str, Any]:
    source_row = planned_asset.source_row
    inventory_row: dict[str, Any] = {
        "run_id": run_id,
        "created_at": created_at,
        "source_manifest": source_row.source_manifest_key,
        "source_manifest_run_id": source_row.source_manifest_run_id,
        "source_document_key": source_row.source_document_key,
        "source_file_name": source_row.source_file_name,
        "source_document_line": source_row.line_number,
        "source_document_row": source_row.row,
        "asset_type": planned_asset.asset_type,
    }
    if planned_asset.field_path:
        inventory_row["field_path"] = planned_asset.field_path
    if planned_asset.project_id:
        inventory_row["project_id"] = planned_asset.project_id
    if planned_asset.name:
        inventory_row["name"] = planned_asset.name
    if planned_asset.source_url:
        inventory_row["source_url"] = planned_asset.source_url
    if planned_asset.normalized_url:
        inventory_row["normalized_url"] = planned_asset.normalized_url
    if planned_asset.target_key:
        inventory_row["target_key"] = planned_asset.target_key
        public_url = s3.public_url(key=planned_asset.target_key)
        if public_url:
            inventory_row["public_url"] = public_url
    return inventory_row


def _target_key(
    *,
    target_prefix: str,
    project_id: str,
    normalized_url: str,
    name: str,
    asset_type: str = "",
    field_path: str = "",
    structured: bool = False,
) -> str:
    project_segment = _safe_path_segment(project_id)
    url_sha256 = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()
    file_name = _safe_target_file_name(name=name, normalized_url=normalized_url)
    if structured:
        asset_segment = _safe_path_segment(asset_type or "other")
        field_segment = _safe_path_segment(field_path or "unknown")
        return (
            f"{target_prefix.rstrip('/')}/project_id={project_segment}/"
            f"asset_type={asset_segment}/field_path={field_segment}/"
            f"{url_sha256}/{file_name}"
        )
    return f"{target_prefix.rstrip('/')}/project_id={project_segment}/{url_sha256}/{file_name}"


def _asset_type_for_row(row: Mapping[str, Any]) -> str:
    field_path = _string_value(row.get("field_path")).lower()
    name = _string_value(row.get("name")).lower()
    combined = f"{field_path} {name}"
    if "brochure" in combined:
        return "brochure"
    if (
        "units_layouts_pdf" in field_path
        or "layouts_preview" in field_path
        or "floor" in combined
        or "layout" in combined
    ):
        return "floorplan"
    if "master_plan" in field_path or "master plan" in combined:
        return "master_plan"
    if "cover" in field_path:
        return "cover_image"
    if "logo" in field_path:
        return "developer_logo"
    if "building_image" in field_path or "architecture" in field_path:
        return "building_image"
    if "interior" in field_path or "lobby" in field_path:
        return "interior_image"
    if "facilities" in field_path or "facility" in combined:
        return "facility_image"
    if "typical_unit_jpg" in field_path:
        return "unit_image"
    if (
        "profile_photo" in field_path
        or "profileimage" in field_path
        or "user_image" in field_path
        or "executive_sales" in field_path
    ):
        return "profile_image"
    suffix = Path(_name_from_url_or_path(_string_value(row.get("normalized_url")), "")).suffix
    if suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".jfif"}:
        return "project_image"
    if suffix.lower() == ".pdf":
        return "document"
    return "other"


def _safe_target_file_name(*, name: str, normalized_url: str) -> str:
    url_name = _name_from_url_or_path(normalized_url, "")
    raw_name = name or url_name or "document"
    safe_name = _safe_path_segment(raw_name)
    url_suffix = Path(url_name).suffix
    safe_suffix = Path(safe_name).suffix
    if url_suffix and (not safe_suffix or safe_suffix.lstrip(".").isdigit()):
        safe_name = f"{safe_name}{url_suffix}"
    if safe_name == ".":
        safe_name = "document"
    if len(safe_name) > 120:
        suffix = Path(safe_name).suffix
        stem = Path(safe_name).stem[: 120 - len(suffix) - 1]
        safe_name = f"{stem}{suffix}"
    return safe_name


def _inventory_key(*, prefix: str, run_id: str, file_name: str) -> str:
    return f"{prefix.rstrip('/')}/run_id={run_id}/{file_name}"


def _jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    lines = [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows]
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_too_large_error(exc: BaseException) -> bool:
    return isinstance(exc, DocumentTooLargeError) or "exceeds max size" in str(exc).lower()


def _log_hydration_progress(
    progress_log: Any,
    *,
    index: int,
    total: int,
    status_counts: Counter[str],
    downloaded_bytes: int,
) -> None:
    if not _should_log_hydration_progress(index=index, total=total):
        return
    _log_info(
        progress_log,
        (
            "reelly_supply: document asset progress=%s/%s downloaded=%s "
            "already_exists=%s missing_url=%s validation_error=%s download_error=%s "
            "too_large=%s bytes=%s"
        ),
        index,
        total,
        status_counts["downloaded"],
        status_counts["already_exists"],
        status_counts["missing_url"],
        status_counts["validation_error"],
        status_counts["download_error"],
        status_counts["too_large"],
        _format_bytes(downloaded_bytes),
    )


def _should_log_hydration_progress(*, index: int, total: int) -> bool:
    return index == 1 or index == total or index % 25 == 0


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


def _log_warning(progress_log: Any, message: str, *args: Any) -> None:
    progress_log.warning(message, *args)
