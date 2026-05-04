"""Reelly raw supply extraction logic."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import re
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from holocron.contracts import RawFile, RawRelease
from holocron.platform.execution import build_raw_file, build_raw_release, new_run_id, utc_now
from holocron.platform.metadata import safe_config_metadata
from holocron.sources.reelly_supply.source import ReellySupplyConfig, SOURCE

logger = logging.getLogger(__name__)

_DOCUMENT_HINTS = (
    "brochure",
    "document",
    "docs",
    "file",
    "files",
    "gallery",
    "image",
    "images",
    "layout",
    "link",
    "links",
    "master_plan",
    "material",
    "pdf",
    "photo",
    "plan",
    "units_layouts_pdf",
)
_DOCUMENT_URL_KEYS = (
    "download_url",
    "file",
    "href",
    "link",
    "path",
    "signed_url",
    "signedUrl",
    "src",
    "url",
)
_DOCUMENT_NAME_KEYS = (
    "file_name",
    "filename",
    "label",
    "name",
    "title",
)
_PROJECT_ID_KEYS = ("id", "project_id", "projects_id", "Project_id", "ID")
_PROJECT_NAME_KEYS = ("project_name", "Project_name", "name", "Name")
_MATRIX_SIGNAL_KEYS = ("units_in_sale", "project_api", "project_availability_id")


@dataclass(frozen=True, slots=True)
class DocumentDownload:
    content: bytes
    content_type: str | None
    final_url: str


class DocumentTooLargeError(RuntimeError):
    """Raised when a document download exceeds the configured byte limit."""


@dataclass(frozen=True, slots=True)
class DiscoveredDocument:
    project_id: Any
    source_endpoint: str
    field_path: str
    name: str
    url: str
    normalized_url: str
    raw: Any


class ReellySupplyApi(Protocol):
    def authenticate(self, *, email: str, password: str) -> dict[str, Any]: ...

    def current_user(self) -> dict[str, Any]: ...

    def fetch_project_list(
        self,
        *,
        page: int,
        region: str,
        sale_statuses: tuple[str, ...],
        user_id: Any | None,
    ) -> dict[str, Any] | list[Any]: ...

    def fetch_project_detail(
        self,
        *,
        project_id: Any,
        user_id: Any | None,
    ) -> dict[str, Any]: ...

    def fetch_project_documents(self, *, project_id: Any) -> dict[str, Any] | list[Any]: ...

    def fetch_matrix_availability(
        self,
        *,
        endpoint: str,
        identifier: Any,
    ) -> dict[str, Any] | list[Any]: ...

    def download_document(self, url: str, *, max_bytes: int) -> DocumentDownload: ...


class ReellySupplyApiClient:
    def __init__(
        self,
        *,
        client: httpx.Client,
        base_url: str,
        documents_base_url: str,
        availability_base_url: str,
        allowed_document_hosts: Sequence[str],
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._documents_base_url = documents_base_url.rstrip("/")
        self._availability_base_url = availability_base_url.rstrip("/")
        self._allowed_document_hosts = tuple(allowed_document_hosts)
        self._auth_token: str | None = None

    def authenticate(self, *, email: str, password: str) -> dict[str, Any]:
        response = self._client.post(
            f"{self._base_url}/auth/login0",
            json={"email": email, "password": password},
            headers={"accept": "application/json", "content-type": "application/json"},
        )
        response.raise_for_status()
        payload = _json_payload(response)
        token = _auth_token(payload)
        if not token:
            raise RuntimeError("Reelly authentication response did not include authToken")
        self._auth_token = token
        return payload

    def current_user(self) -> dict[str, Any]:
        payload = self._get_json(f"{self._base_url}/auth/me0")
        if not isinstance(payload, dict):
            raise ValueError("Reelly auth/me0 response must be a JSON object")
        return payload

    def fetch_project_list(
        self,
        *,
        page: int,
        region: str,
        sale_statuses: tuple[str, ...],
        user_id: Any | None,
    ) -> dict[str, Any] | list[Any]:
        params: dict[str, Any] = {
            "page": page,
            "external": _project_filter_json(),
            "region": region,
            "sales_status": ",".join(sale_statuses),
            "search_field": "",
        }
        if user_id is not None:
            params["user_id"] = user_id
        return self._get_json(f"{self._base_url}/projectsExternalSearch", params=params)

    def fetch_project_detail(
        self,
        *,
        project_id: Any,
        user_id: Any | None,
    ) -> dict[str, Any]:
        params = {"user_id": user_id} if user_id is not None else None
        payload = self._get_json(f"{self._base_url}/projects/{project_id}", params=params)
        if not isinstance(payload, dict):
            raise ValueError("Reelly project detail response must be a JSON object")
        return payload

    def fetch_project_documents(self, *, project_id: Any) -> dict[str, Any] | list[Any]:
        return self._get_json(
            f"{self._documents_base_url}/links_docs",
            params={"project_id": project_id},
        )

    def fetch_matrix_availability(
        self,
        *,
        endpoint: str,
        identifier: Any,
    ) -> dict[str, Any] | list[Any]:
        query_key = "unit_id" if endpoint == "unit" else "project_name"
        return self._get_json(
            f"{self._availability_base_url}/evolutions/availability/{endpoint}",
            params={query_key: identifier},
        )

    def download_document(self, url: str, *, max_bytes: int) -> DocumentDownload:
        safe_url = _validate_document_url(url, allowed_hosts=self._allowed_document_hosts)
        chunks: list[bytes] = []
        size = 0
        with self._client.stream("GET", safe_url) as response:
            response.raise_for_status()
            final_url = _validate_document_url(
                str(response.url), allowed_hosts=self._allowed_document_hosts
            )
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise DocumentTooLargeError(f"document exceeds max size of {max_bytes} bytes")
                chunks.append(chunk)
            return DocumentDownload(
                content=b"".join(chunks),
                content_type=response.headers.get("content-type"),
                final_url=final_url,
            )

    def _get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        response = self._client.get(url, params=params, headers=self._authorized_headers())
        response.raise_for_status()
        return _json_payload(response)

    def _authorized_headers(self) -> dict[str, str]:
        if not self._auth_token:
            raise RuntimeError("Reelly API client is not authenticated")
        return {"accept": "application/json", "authorization": f"Bearer {self._auth_token}"}


def extract_release(
    output_dir: str | Path,
    *,
    config: ReellySupplyConfig | dict,
    now: datetime | None = None,
    api_client: ReellySupplyApi | None = None,
    progress_log: Any | None = None,
) -> RawRelease:
    parsed_config = (
        config
        if isinstance(config, ReellySupplyConfig)
        else ReellySupplyConfig.model_validate(config)
    )
    current_time = now or utc_now()
    run_id = new_run_id(current_time)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    email, password = _resolve_credentials(parsed_config, required=api_client is None)
    log = progress_log or logger
    _log_info(
        log,
        (
            "reelly_supply: starting raw extraction run_id=%s start_page=%s "
            "pages_per_run=%s download_documents=%s try_matrix_availability=%s"
        ),
        run_id,
        parsed_config.resolved_start_page,
        parsed_config.pages_per_run,
        parsed_config.download_documents,
        parsed_config.try_matrix_availability,
    )

    if api_client is None:
        with httpx.Client(timeout=parsed_config.timeout_seconds, follow_redirects=True) as client:
            api_client = ReellySupplyApiClient(
                client=client,
                base_url=parsed_config.base_url,
                documents_base_url=parsed_config.documents_base_url,
                availability_base_url=parsed_config.availability_base_url,
                allowed_document_hosts=parsed_config.allowed_document_hosts,
            )
            files, metadata = _extract_files(
                output_path,
                config=parsed_config,
                api_client=api_client,
                scraped_at=current_time.isoformat(),
                email=email,
                password=password,
                progress_log=log,
            )
    else:
        files, metadata = _extract_files(
            output_path,
            config=parsed_config,
            api_client=api_client,
            scraped_at=current_time.isoformat(),
            email=email,
            password=password,
            progress_log=log,
        )

    if not files:
        raise RuntimeError("Reelly supply extraction produced no raw files")

    release = build_raw_release(
        source=SOURCE,
        files=files,
        run_id=run_id,
        now=current_time,
        metadata={"config": safe_config_metadata(parsed_config), **metadata},
    )
    _log_info(
        log,
        (
            "reelly_supply: completed raw extraction run_id=%s files=%s total_size=%s "
            "projects=%s documents=%s matrix_rows=%s"
        ),
        run_id,
        len(files),
        _format_bytes(sum(raw_file.size_bytes for raw_file in files)),
        metadata.get("project_detail_count"),
        metadata.get("document_count"),
        metadata.get("matrix_attempt_count"),
    )
    return release


def _extract_files(
    output_path: Path,
    *,
    config: ReellySupplyConfig,
    api_client: ReellySupplyApi,
    scraped_at: str,
    email: str,
    password: str,
    progress_log: Any,
) -> tuple[tuple[RawFile, ...], dict[str, Any]]:
    started_at = time.monotonic()
    _log_info(progress_log, "reelly_supply: authenticating")
    auth_payload = api_client.authenticate(email=email, password=password)
    _pause(config)
    user_payload = api_client.current_user()
    user_id = _extract_user_id(user_payload)
    _log_info(progress_log, "reelly_supply: authenticated user_id=%s", user_id)
    _pause(config)

    list_page_rows, project_items, batch_metadata = _fetch_project_batch(
        config=config,
        api_client=api_client,
        scraped_at=scraped_at,
        user_id=user_id,
        progress_log=progress_log,
    )
    project_details = _fetch_project_details(
        config=config,
        api_client=api_client,
        scraped_at=scraped_at,
        user_id=user_id,
        project_items=project_items,
        progress_log=progress_log,
    )
    document_rows, document_files = _collect_project_documents(
        output_path=output_path,
        config=config,
        api_client=api_client,
        scraped_at=scraped_at,
        project_details=project_details,
        progress_log=progress_log,
    )
    matrix_rows = _collect_matrix_availability(
        config=config,
        api_client=api_client,
        scraped_at=scraped_at,
        project_details=project_details,
        progress_log=progress_log,
    )

    raw_files = [
        _write_jsonl_raw_file(
            output_path / "reelly_supply_project_list_pages.jsonl", list_page_rows
        ),
        _write_jsonl_raw_file(
            output_path / "reelly_supply_project_details.jsonl",
            [detail["row"] for detail in project_details],
        ),
        _write_jsonl_raw_file(
            output_path / "reelly_supply_project_documents.jsonl",
            document_rows,
        ),
        _write_jsonl_raw_file(
            output_path / "reelly_supply_matrix_availability.jsonl",
            matrix_rows,
        ),
    ]
    raw_files.extend(document_files)
    jsonl_files = [raw_file for raw_file in raw_files if raw_file.row_count is not None]
    _log_info(
        progress_log,
        (
            "reelly_supply: wrote local raw files jsonl_files=%s document_files=%s "
            "total_size=%s elapsed=%.1fs"
        ),
        len(jsonl_files),
        len(document_files),
        _format_bytes(sum(raw_file.size_bytes for raw_file in raw_files)),
        time.monotonic() - started_at,
    )

    return tuple(raw_files), {
        **batch_metadata,
        "authenticated": bool(_auth_token(auth_payload)),
        "user_id": user_id,
        "project_count": len(project_items),
        "project_detail_count": len(project_details),
        "document_count": len(document_rows),
        "matrix_attempt_count": len(matrix_rows),
    }


def _fetch_project_batch(
    *,
    config: ReellySupplyConfig,
    api_client: ReellySupplyApi,
    scraped_at: str,
    user_id: Any | None,
    progress_log: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    started_at = time.monotonic()
    start_page = config.resolved_start_page
    if config.max_pages is not None and start_page > config.max_pages:
        start_page = 1
    _log_info(
        progress_log,
        "reelly_supply: fetching project list start_page=%s pages_per_run=%s max_pages=%s",
        start_page,
        config.pages_per_run,
        config.max_pages,
    )

    rows: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []
    page_total: int | None = None
    items_total: int | None = None
    end_page = start_page - 1

    for page in range(start_page, start_page + config.pages_per_run):
        effective_total = _effective_page_total(page_total, config.max_pages)
        if effective_total is not None and page > effective_total:
            break

        payload = api_client.fetch_project_list(
            page=page,
            region=config.region,
            sale_statuses=config.sale_statuses,
            user_id=user_id,
        )
        items = _project_items(payload)
        page_total = _first_int(
            payload,
            ("pageTotal", "page_total", "total_pages", "pages", "last_page"),
            default=page_total,
        )
        items_total = _first_int(
            payload,
            ("itemsTotal", "items_total", "total", "count", "recordsTotal"),
            default=items_total,
        )
        rows.append(
            {
                "endpoint": "projectsExternalSearch",
                "scraped_at": scraped_at,
                "page": page,
                "region": config.region,
                "sale_statuses": list(config.sale_statuses),
                "item_count": len(items),
                "page_total": page_total,
                "items_total": items_total,
                "raw": payload,
            }
        )
        projects.extend(items)
        end_page = page
        _log_info(
            progress_log,
            (
                "reelly_supply: fetched list page=%s items=%s page_total=%s "
                "items_total=%s accumulated_projects=%s"
            ),
            page,
            len(items),
            page_total,
            items_total,
            len(projects),
        )
        if not items and page_total is None:
            break
        _pause(config)

    effective_total = _effective_page_total(page_total, config.max_pages)
    next_page = end_page + 1 if rows else start_page
    completed = False
    if effective_total is not None:
        completed = bool(rows) and end_page >= effective_total
        if next_page > effective_total:
            next_page = 1
    elif rows and len(rows) < config.pages_per_run:
        completed = True

    metadata = {
        "start_page": start_page,
        "end_page": end_page if rows else None,
        "next_page": next_page,
        "page_total": page_total,
        "items_total": items_total,
        "pages_fetched": len(rows),
        "batch_completed_result_set": completed,
    }
    _log_info(
        progress_log,
        (
            "reelly_supply: completed project list pages=%s start_page=%s end_page=%s "
            "next_page=%s projects=%s elapsed=%.1fs"
        ),
        len(rows),
        start_page,
        end_page if rows else None,
        next_page,
        len(projects),
        time.monotonic() - started_at,
    )
    return rows, projects, metadata


def _fetch_project_details(
    *,
    config: ReellySupplyConfig,
    api_client: ReellySupplyApi,
    scraped_at: str,
    user_id: Any | None,
    project_items: Sequence[Mapping[str, Any]],
    progress_log: Any,
) -> list[dict[str, Any]]:
    started_at = time.monotonic()
    unique_projects = list(_unique_projects(project_items))
    total_projects = len(unique_projects)
    _log_info(
        progress_log,
        "reelly_supply: fetching project details unique_projects=%s",
        total_projects,
    )
    details: list[dict[str, Any]] = []
    for index, (project_id, list_item) in enumerate(unique_projects, start=1):
        payload = api_client.fetch_project_detail(project_id=project_id, user_id=user_id)
        row = {
            "endpoint": "projects",
            "scraped_at": scraped_at,
            "project_id": project_id,
            "list_item": list_item,
            "raw": payload,
        }
        details.append(
            {"project_id": project_id, "list_item": list_item, "raw": payload, "row": row}
        )
        if _should_log_progress(index, total_projects, interval=25):
            _log_info(
                progress_log,
                "reelly_supply: fetched project details progress=%s/%s project_id=%s",
                index,
                total_projects,
                project_id,
            )
        _pause(config)
    _log_info(
        progress_log,
        "reelly_supply: completed project details rows=%s elapsed=%.1fs",
        len(details),
        time.monotonic() - started_at,
    )
    return details


def _collect_project_documents(
    *,
    output_path: Path,
    config: ReellySupplyConfig,
    api_client: ReellySupplyApi,
    scraped_at: str,
    project_details: Sequence[dict[str, Any]],
    progress_log: Any,
) -> tuple[list[dict[str, Any]], list[RawFile]]:
    started_at = time.monotonic()
    rows: list[dict[str, Any]] = []
    raw_files: list[RawFile] = []
    max_bytes = config.max_document_mb * 1024 * 1024
    total_projects = len(project_details)
    downloaded_count = 0
    skipped_count = 0
    error_count = 0
    discovery_error_count = 0
    downloaded_bytes = 0
    _log_info(
        progress_log,
        (
            "reelly_supply: collecting project documents projects=%s "
            "download_documents=%s max_document_mb=%s"
        ),
        total_projects,
        config.download_documents,
        config.max_document_mb,
    )

    for project_index, detail in enumerate(project_details, start=1):
        project_id = detail["project_id"]
        documents = list(
            _discover_documents(
                detail["raw"],
                project_id=project_id,
                source_endpoint="projects",
                download_all_project_docs=config.download_all_project_docs,
                allowed_document_hosts=config.allowed_document_hosts,
            )
        )
        try:
            docs_payload = api_client.fetch_project_documents(project_id=project_id)
            documents.extend(
                _discover_documents(
                    docs_payload,
                    project_id=project_id,
                    source_endpoint="links_docs",
                    download_all_project_docs=True,
                    allowed_document_hosts=config.allowed_document_hosts,
                )
            )
            _pause(config)
        except Exception as exc:  # noqa: BLE001
            discovery_error_count += 1
            _log_warning(
                progress_log,
                "reelly_supply: document discovery failed project_id=%s error=%s",
                project_id,
                exc,
            )
            rows.append(
                {
                    "endpoint": "links_docs",
                    "scraped_at": scraped_at,
                    "project_id": project_id,
                    "status": "discovery_error",
                    "error": str(exc),
                }
            )

        for index, document in enumerate(_dedupe_documents(documents), start=1):
            row = _document_row(document=document, scraped_at=scraped_at)
            if not config.download_documents:
                row["status"] = "download_skipped"
                rows.append(row)
                skipped_count += 1
                continue
            try:
                document_started_at = time.monotonic()
                download = api_client.download_document(
                    document.normalized_url, max_bytes=max_bytes
                )
                final_url = _validate_document_url(
                    download.final_url, allowed_hosts=config.allowed_document_hosts
                )
                file_path = _document_path(output_path, document=document, index=index)
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_bytes(download.content)
                raw_file = _build_raw_file(
                    file_path,
                    row_count=None,
                    content_type=download.content_type,
                    metadata={
                        "project_id": project_id,
                        "source_url": document.url,
                        "final_url": final_url,
                    },
                )
                raw_files.append(raw_file)
                downloaded_count += 1
                downloaded_bytes += raw_file.size_bytes
                _log_info(
                    progress_log,
                    (
                        "reelly_supply: downloaded document project_id=%s index=%s "
                        "size=%s content_type=%s elapsed=%.1fs"
                    ),
                    project_id,
                    index,
                    _format_bytes(raw_file.size_bytes),
                    download.content_type,
                    time.monotonic() - document_started_at,
                )
                row.update(
                    {
                        "status": "downloaded",
                        "downloaded_path": str(file_path.relative_to(output_path)),
                        "final_url": final_url,
                        "content_type": download.content_type,
                        "sha256": raw_file.sha256,
                        "size_bytes": raw_file.size_bytes,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                error_count += 1
                _log_warning(
                    progress_log,
                    "reelly_supply: document download failed project_id=%s index=%s error=%s",
                    project_id,
                    index,
                    exc,
                )
                row.update({"status": "download_error", "error": str(exc)})
            rows.append(row)
        if _should_log_progress(project_index, total_projects, interval=25):
            _log_info(
                progress_log,
                (
                    "reelly_supply: document progress projects=%s/%s rows=%s "
                    "downloaded=%s skipped=%s errors=%s discovery_errors=%s bytes=%s"
                ),
                project_index,
                total_projects,
                len(rows),
                downloaded_count,
                skipped_count,
                error_count,
                discovery_error_count,
                _format_bytes(downloaded_bytes),
            )

    _log_info(
        progress_log,
        (
            "reelly_supply: completed documents rows=%s downloaded=%s skipped=%s "
            "errors=%s discovery_errors=%s bytes=%s elapsed=%.1fs"
        ),
        len(rows),
        downloaded_count,
        skipped_count,
        error_count,
        discovery_error_count,
        _format_bytes(downloaded_bytes),
        time.monotonic() - started_at,
    )
    return rows, raw_files


def _collect_matrix_availability(
    *,
    config: ReellySupplyConfig,
    api_client: ReellySupplyApi,
    scraped_at: str,
    project_details: Sequence[dict[str, Any]],
    progress_log: Any,
) -> list[dict[str, Any]]:
    if not config.try_matrix_availability:
        _log_info(progress_log, "reelly_supply: matrix availability disabled")
        return []

    started_at = time.monotonic()
    rows: list[dict[str, Any]] = []
    success_count = 0
    error_count = 0
    skipped_no_signal = 0
    total_projects = len(project_details)
    _log_info(
        progress_log,
        "reelly_supply: collecting matrix availability projects=%s endpoints=%s",
        total_projects,
        ",".join(config.matrix_endpoints),
    )
    for project_index, detail in enumerate(project_details, start=1):
        raw = detail["raw"]
        project_id = detail["project_id"]
        if not _has_matrix_signal(raw):
            skipped_no_signal += 1
            if _should_log_progress(project_index, total_projects, interval=25):
                _log_info(
                    progress_log,
                    (
                        "reelly_supply: matrix progress projects=%s/%s rows=%s "
                        "success=%s errors=%s skipped_no_signal=%s"
                    ),
                    project_index,
                    total_projects,
                    len(rows),
                    success_count,
                    error_count,
                    skipped_no_signal,
                )
            continue
        candidates = _matrix_candidates(project_id=project_id, project=raw)
        for endpoint in config.matrix_endpoints:
            for candidate in candidates:
                row = {
                    "endpoint": f"evolutions/availability/{endpoint}",
                    "scraped_at": scraped_at,
                    "project_id": project_id,
                    "candidate": candidate,
                }
                try:
                    payload = api_client.fetch_matrix_availability(
                        endpoint=endpoint,
                        identifier=candidate,
                    )
                    row.update({"status": "success", "raw": payload})
                    rows.append(row)
                    success_count += 1
                    _pause(config)
                    break
                except Exception as exc:  # noqa: BLE001
                    row.update({"status": "error", "error": str(exc)})
                    rows.append(row)
                    error_count += 1
                    _pause(config)
        if _should_log_progress(project_index, total_projects, interval=25):
            _log_info(
                progress_log,
                (
                    "reelly_supply: matrix progress projects=%s/%s rows=%s "
                    "success=%s errors=%s skipped_no_signal=%s"
                ),
                project_index,
                total_projects,
                len(rows),
                success_count,
                error_count,
                skipped_no_signal,
            )
    _log_info(
        progress_log,
        (
            "reelly_supply: completed matrix availability rows=%s success=%s "
            "errors=%s skipped_no_signal=%s elapsed=%.1fs"
        ),
        len(rows),
        success_count,
        error_count,
        skipped_no_signal,
        time.monotonic() - started_at,
    )
    return rows


def _discover_documents(
    value: Any,
    *,
    project_id: Any,
    source_endpoint: str,
    download_all_project_docs: bool,
    allowed_document_hosts: Sequence[str],
    path: tuple[str, ...] = (),
) -> Iterable[DiscoveredDocument]:
    if isinstance(value, str):
        if _is_url(value) and (download_all_project_docs or _has_document_context(path)):
            document = _document_from_url(
                project_id=project_id,
                source_endpoint=source_endpoint,
                field_path=_field_path(path),
                url=value,
                raw=value,
                allowed_document_hosts=allowed_document_hosts,
            )
            if document is not None:
                yield document
        return

    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _discover_documents(
                item,
                project_id=project_id,
                source_endpoint=source_endpoint,
                download_all_project_docs=download_all_project_docs,
                allowed_document_hosts=allowed_document_hosts,
                path=(*path, str(index)),
            )
        return

    if not isinstance(value, dict):
        return

    url = _document_url_from_mapping(value)
    if url and (download_all_project_docs or _has_document_context(path)):
        name = _document_name_from_mapping(value) or _field_path(path) or "document"
        normalized_url = _validate_document_url_or_none(url, allowed_hosts=allowed_document_hosts)
        if normalized_url is not None:
            yield DiscoveredDocument(
                project_id=project_id,
                source_endpoint=source_endpoint,
                field_path=_field_path(path),
                name=name,
                url=url,
                normalized_url=normalized_url,
                raw=value,
            )

    for key, item in value.items():
        yield from _discover_documents(
            item,
            project_id=project_id,
            source_endpoint=source_endpoint,
            download_all_project_docs=download_all_project_docs,
            allowed_document_hosts=allowed_document_hosts,
            path=(*path, str(key)),
        )


def _dedupe_documents(documents: Iterable[DiscoveredDocument]) -> list[DiscoveredDocument]:
    seen: set[tuple[str, str]] = set()
    deduped: list[DiscoveredDocument] = []
    for document in documents:
        key = (str(document.project_id), document.normalized_url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(document)
    return deduped


def _document_row(*, document: DiscoveredDocument, scraped_at: str) -> dict[str, Any]:
    return {
        "endpoint": document.source_endpoint,
        "scraped_at": scraped_at,
        "project_id": document.project_id,
        "field_path": document.field_path,
        "name": document.name,
        "url": document.url,
        "normalized_url": document.normalized_url,
        "raw": document.raw,
        "status": "discovered",
    }


def _document_from_url(
    *,
    project_id: Any,
    source_endpoint: str,
    field_path: str,
    url: str,
    raw: Any,
    allowed_document_hosts: Sequence[str],
) -> DiscoveredDocument | None:
    normalized_url = _validate_document_url_or_none(url, allowed_hosts=allowed_document_hosts)
    if normalized_url is None:
        return None
    return DiscoveredDocument(
        project_id=project_id,
        source_endpoint=source_endpoint,
        field_path=field_path,
        name=_name_from_url_or_path(url, field_path),
        url=url,
        normalized_url=normalized_url,
        raw=raw,
    )


def _project_items(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    else:
        items = None
        for key in ("items", "results", "result", "data", "records"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                items = candidate
                break
        if items is None:
            return []
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("Reelly project list response items must contain objects")
    return list(items)


def _unique_projects(
    project_items: Sequence[Mapping[str, Any]],
) -> Iterable[tuple[Any, Mapping[str, Any]]]:
    seen: set[str] = set()
    for item in project_items:
        project_id = _mapping_value(item, _PROJECT_ID_KEYS)
        if project_id in (None, ""):
            continue
        key = str(project_id)
        if key in seen:
            continue
        seen.add(key)
        yield project_id, item


def _matrix_candidates(*, project_id: Any, project: Mapping[str, Any]) -> list[Any]:
    candidates = [
        _mapping_value(project, ("project_availability_id",)),
        _mapping_value(project, ("project_api",)),
        project_id,
        _mapping_value(project, _PROJECT_NAME_KEYS),
    ]
    deduped: list[Any] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in (None, ""):
            continue
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _has_matrix_signal(project: Mapping[str, Any]) -> bool:
    return any(
        _mapping_value(project, (key,)) not in (None, "", 0, False) for key in _MATRIX_SIGNAL_KEYS
    )


def _extract_user_id(payload: Mapping[str, Any]) -> Any | None:
    user = payload.get("user")
    if isinstance(user, Mapping):
        return _mapping_value(user, ("id", "users_id", "user_id"))
    return _mapping_value(payload, ("id", "users_id", "user_id"))


def _json_payload(response: httpx.Response) -> dict[str, Any] | list[Any]:
    payload = response.json()
    if not isinstance(payload, (dict, list)):
        raise ValueError(f"Reelly response must be a JSON object or array: {response.url}")
    return payload


def _auth_token(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    if not isinstance(payload, Mapping):
        return ""
    token = _mapping_value(payload, ("authToken", "auth_token", "token"))
    return str(token).strip() if token else ""


def _resolve_credentials(
    config: ReellySupplyConfig,
    *,
    required: bool,
) -> tuple[str, str]:
    email = config.email.strip() or os.environ.get("REELLY_EMAIL", "").strip()
    password = config.password.strip() or os.environ.get("REELLY_PASSWORD", "").strip()
    if required and (not email or not password):
        raise RuntimeError(
            "Reelly credentials missing. Set REELLY_EMAIL and REELLY_PASSWORD or pass them in config."
        )
    return email, password


def _project_filter_json() -> str:
    return json.dumps({"expression": []}, separators=(",", ":"))


def _effective_page_total(page_total: int | None, max_pages: int | None) -> int | None:
    if page_total is None:
        return max_pages
    if max_pages is None:
        return page_total
    return min(page_total, max_pages)


def _first_int(
    payload: Any,
    keys: Sequence[str],
    *,
    default: int | None,
) -> int | None:
    if not isinstance(payload, Mapping):
        return default
    for key in keys:
        value = _mapping_value(payload, (key,))
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return default


def _mapping_value(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    lower_keys = {key.lower(): key for key in mapping}
    for key in keys:
        actual_key = lower_keys.get(key.lower())
        if actual_key is not None:
            return mapping[actual_key]
    return None


def _document_url_from_mapping(mapping: Mapping[str, Any]) -> str:
    for key in _DOCUMENT_URL_KEYS:
        value = _mapping_value(mapping, (key,))
        if isinstance(value, str) and _is_url(value):
            return value
    return ""


def _document_name_from_mapping(mapping: Mapping[str, Any]) -> str:
    for key in _DOCUMENT_NAME_KEYS:
        value = _mapping_value(mapping, (key,))
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _has_document_context(path: Sequence[str]) -> bool:
    normalized = "_".join(part.lower() for part in path)
    return any(hint in normalized for hint in _DOCUMENT_HINTS)


def _field_path(path: Sequence[str]) -> str:
    return ".".join(path)


def _is_url(value: str) -> bool:
    return value.startswith(("http://", "https://", "//"))


def _validate_document_url_or_none(url: str, *, allowed_hosts: Sequence[str]) -> str | None:
    try:
        return _validate_document_url(url, allowed_hosts=allowed_hosts)
    except ValueError:
        return None


def _validate_document_url(url: str, *, allowed_hosts: Sequence[str]) -> str:
    normalized = f"https:{url}" if url.startswith("//") else url
    parsed = urlparse(normalized)
    if parsed.scheme != "https":
        raise ValueError("document URL must use https")
    if parsed.username or parsed.password:
        raise ValueError("document URL must not include embedded credentials")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("document URL must include a host")
    _raise_if_unsafe_ip_host(host)
    if not _host_is_allowed(host, allowed_hosts):
        raise ValueError(f"document host is not allowlisted: {host}")
    return _normalize_document_url(normalized)


def _raise_if_unsafe_ip_host(host: str) -> None:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise ValueError(f"document URL targets an unsafe IP address: {host}")


def _host_is_allowed(host: str, allowed_hosts: Sequence[str]) -> bool:
    for allowed_host in allowed_hosts:
        normalized_allowed = allowed_host.strip().lower()
        if not normalized_allowed:
            continue
        if normalized_allowed.startswith("."):
            if host.endswith(normalized_allowed):
                return True
            continue
        if host == normalized_allowed:
            return True
    return False


def _normalize_document_url(url: str) -> str:
    normalized = f"https:{url}" if url.startswith("//") else url
    parsed = urlparse(normalized)
    if "drive.google.com" not in parsed.netloc:
        return normalized
    file_id = ""
    match = re.search(r"/file/d/([^/]+)", parsed.path)
    if match:
        file_id = match.group(1)
    else:
        file_id = parse_qs(parsed.query).get("id", [""])[0]
    if not file_id:
        return normalized
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def _document_path(output_path: Path, *, document: DiscoveredDocument, index: int) -> Path:
    project_segment = _safe_path_segment(str(document.project_id))
    file_name = _safe_document_file_name(document=document, index=index)
    return output_path / "documents" / project_segment / file_name


def _safe_document_file_name(*, document: DiscoveredDocument, index: int) -> str:
    name = document.name or _name_from_url_or_path(document.normalized_url, "")
    safe_name = _safe_path_segment(name)
    url_name = _name_from_url_or_path(document.normalized_url, "")
    url_suffix = Path(url_name).suffix
    if url_suffix and not Path(safe_name).suffix:
        safe_name = f"{safe_name}{url_suffix}"
    if not safe_name or safe_name == ".":
        safe_name = f"document_{index}"
    if len(safe_name) > 120:
        suffix = Path(safe_name).suffix
        stem = Path(safe_name).stem[: 120 - len(suffix) - 1]
        safe_name = f"{stem}{suffix}"
    return f"{index:03d}_{safe_name}"


def _name_from_url_or_path(url: str, field_path: str) -> str:
    parsed = urlparse(url)
    url_name = unquote(Path(parsed.path).name)
    if url_name:
        return url_name
    return field_path.rsplit(".", 1)[-1] if field_path else "document"


def _safe_path_segment(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._")
    return normalized or "unknown"


def _write_jsonl_raw_file(path: Path, rows: Iterable[dict[str, Any]]) -> RawFile:
    path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
            row_count += 1
    return _build_raw_file(path, row_count=row_count, content_type="application/x-ndjson")


def _build_raw_file(
    path: Path,
    *,
    row_count: int | None,
    content_type: str | None,
    metadata: Mapping[str, Any] | None = None,
) -> RawFile:
    content = path.read_bytes()
    return build_raw_file(
        path=path,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        row_count=row_count,
        content_type=content_type,
        metadata=metadata,
    )


def _pause(config: ReellySupplyConfig) -> None:
    if config.request_pause_seconds:
        time.sleep(config.request_pause_seconds)


def _should_log_progress(index: int, total: int, *, interval: int) -> bool:
    return index == 1 or index == total or index % interval == 0


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
