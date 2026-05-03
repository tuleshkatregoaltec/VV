"""Bayut transaction extraction logic."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from holocron.contracts import RawFile, RawRelease
from holocron.platform.execution import build_raw_file, build_raw_release, new_run_id, utc_now
from holocron.platform.metadata import safe_config_metadata
from holocron.sources.bay_transactions.source import (
    BayutTransactionsConfig,
    DateWindow,
    SOURCE,
    resolve_date_window,
    transaction_request_body,
)


class BayutTransactionsApi(Protocol):
    def fetch_transactions(
        self,
        *,
        page: int,
        body: Mapping[str, Any],
    ) -> dict[str, Any]: ...


class BayutTransactionsApiClient:
    def __init__(self, *, client: httpx.Client, api_key: str, base_url: str) -> None:
        self._client = client
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def fetch_transactions(
        self,
        *,
        page: int,
        body: Mapping[str, Any],
    ) -> dict[str, Any]:
        response = self._client.post(
            f"{self._base_url}/transactions",
            params={"page": page},
            json=dict(body),
            headers=_headers(self._api_key),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Bayut transactions response must be a JSON object")
        return payload


def extract_release(
    output_dir: str | Path,
    *,
    config: BayutTransactionsConfig | dict,
    now: datetime | None = None,
    api_client: BayutTransactionsApi | None = None,
) -> RawRelease:
    parsed_config = (
        config
        if isinstance(config, BayutTransactionsConfig)
        else BayutTransactionsConfig.model_validate(config)
    )
    current_time = now or utc_now()
    run_id = new_run_id(current_time)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    window = resolve_date_window(parsed_config, today=current_time.date())

    if api_client is None:
        api_key = _resolve_api_key(parsed_config.api_key)
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            api_client = BayutTransactionsApiClient(
                client=client,
                api_key=api_key,
                base_url=parsed_config.base_url,
            )
            files = _extract_files(
                output_path,
                config=parsed_config,
                api_client=api_client,
                window=window,
                scraped_at=current_time.isoformat(),
            )
    else:
        files = _extract_files(
            output_path,
            config=parsed_config,
            api_client=api_client,
            window=window,
            scraped_at=current_time.isoformat(),
        )

    if not files:
        raise RuntimeError("Bayut transactions extraction produced no raw files")

    return build_raw_release(
        source=SOURCE,
        files=files,
        run_id=run_id,
        now=current_time,
        metadata={
            "config": safe_config_metadata(parsed_config),
            "date_window": {
                "start_date": window.start_date.isoformat(),
                "end_date": window.end_date.isoformat(),
            },
        },
    )


def _extract_files(
    output_path: Path,
    *,
    config: BayutTransactionsConfig,
    api_client: BayutTransactionsApi,
    window: DateWindow,
    scraped_at: str,
) -> tuple[RawFile, ...]:
    files: list[RawFile] = []
    for purpose in config.purposes:
        rows = list(
            _transaction_rows(
                config=config,
                api_client=api_client,
                window=window,
                scraped_at=scraped_at,
                purpose=purpose,
            )
        )
        path = output_path / _transaction_file_name(purpose=purpose, window=window)
        files.append(_write_jsonl_raw_file(path, rows))
    return tuple(files)


def _transaction_rows(
    *,
    config: BayutTransactionsConfig,
    api_client: BayutTransactionsApi,
    window: DateWindow,
    scraped_at: str,
    purpose: str,
) -> Iterable[dict[str, Any]]:
    for locations_ids in _location_id_batches(
        config.locations_ids,
        batch_size=config.location_batch_size,
    ):
        body = transaction_request_body(
            config,
            purpose=purpose,
            window=window,
            locations_ids=locations_ids,
        )
        for page in range(config.max_pages):
            payload = api_client.fetch_transactions(page=page, body=body)
            results = _result_list(payload)
            for item in results:
                yield {
                    "endpoint": "transactions",
                    "scraped_at": scraped_at,
                    "purpose": purpose,
                    "category": config.category,
                    "locations_ids": list(locations_ids),
                    "start_date": window.start_date.isoformat(),
                    "end_date": window.end_date.isoformat(),
                    "page": page,
                    "raw": item,
                }
            if len(results) == 0:
                break
            if config.request_pause_seconds:
                time.sleep(config.request_pause_seconds)


def _location_id_batches(
    locations_ids: tuple[int, ...],
    *,
    batch_size: int,
) -> Iterable[tuple[int, ...]]:
    if not locations_ids:
        yield ()
        return
    for start in range(0, len(locations_ids), batch_size):
        yield locations_ids[start : start + batch_size]


def _result_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results")
    if results is None:
        return []
    if not isinstance(results, list):
        raise ValueError("Bayut transactions response.results must be a list")
    if not all(isinstance(item, dict) for item in results):
        raise ValueError("Bayut transactions response.results must contain objects")
    return results


def _headers(api_key: str) -> dict[str, str]:
    return {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "uae-real-estate2.p.rapidapi.com",
        "accept": "application/json",
        "content-type": "application/json",
    }


def _resolve_api_key(configured_api_key: str) -> str:
    api_key = configured_api_key.strip() or os.environ.get("BAYUT_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Bayut API key missing. Set BAYUT_API_KEY or pass api_key in config.")
    return api_key


def _transaction_file_name(*, purpose: str, window: DateWindow) -> str:
    safe_purpose = purpose.replace("-", "_")
    return f"bay_transactions_{safe_purpose}_{window.key}.jsonl"


def _write_jsonl_raw_file(path: Path, rows: Iterable[dict[str, Any]]) -> RawFile:
    path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
            row_count += 1
    return _build_raw_file(path, row_count=row_count)


def _build_raw_file(path: Path, *, row_count: int) -> RawFile:
    content = path.read_bytes()
    return build_raw_file(
        path=path,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        row_count=row_count,
        content_type="application/x-ndjson",
    )
