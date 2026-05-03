"""Bayut location discovery extraction logic."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from holocron.contracts import RawFile, RawRelease
from holocron.platform.execution import build_raw_file, build_raw_release, new_run_id, utc_now
from holocron.platform.metadata import safe_config_metadata
from holocron.sources.bay_locations.source import (
    BAYUT_DUBAI_LOCATION_ID,
    BayutLocationsConfig,
    SOURCE,
)


class BayutLocationsApi(Protocol):
    def search_locations(self, *, query: str, page: int, langs: str) -> dict[str, Any]: ...


class BayutLocationsApiClient:
    def __init__(self, *, client: httpx.Client, api_key: str, base_url: str) -> None:
        self._client = client
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def search_locations(self, *, query: str, page: int, langs: str) -> dict[str, Any]:
        response = self._client.get(
            f"{self._base_url}/locations_search",
            params={"query": query, "page": page, "langs": langs},
            headers=_headers(self._api_key),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Bayut locations_search response must be a JSON object")
        return payload


def extract_release(
    output_dir: str | Path,
    *,
    config: BayutLocationsConfig | dict,
    now: datetime | None = None,
    api_client: BayutLocationsApi | None = None,
) -> RawRelease:
    parsed_config = (
        config
        if isinstance(config, BayutLocationsConfig)
        else BayutLocationsConfig.model_validate(config)
    )
    current_time = now or utc_now()
    run_id = new_run_id(current_time)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if api_client is None:
        api_key = _resolve_api_key(parsed_config.api_key)
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            api_client = BayutLocationsApiClient(
                client=client,
                api_key=api_key,
                base_url=parsed_config.base_url,
            )
            files = _extract_files(
                output_path,
                config=parsed_config,
                api_client=api_client,
                scraped_at=current_time.isoformat(),
            )
    else:
        files = _extract_files(
            output_path,
            config=parsed_config,
            api_client=api_client,
            scraped_at=current_time.isoformat(),
        )

    if not files:
        raise RuntimeError("Bayut locations extraction produced no raw files")

    return build_raw_release(
        source=SOURCE,
        files=files,
        run_id=run_id,
        now=current_time,
        metadata={"config": safe_config_metadata(parsed_config)},
    )


def _extract_files(
    output_path: Path,
    *,
    config: BayutLocationsConfig,
    api_client: BayutLocationsApi,
    scraped_at: str,
) -> tuple[RawFile, ...]:
    rows = list(_location_rows(config=config, api_client=api_client, scraped_at=scraped_at))
    path = output_path / "bay_locations_dubai.jsonl"
    return (_write_jsonl_raw_file(path, rows),)


def _location_rows(
    *,
    config: BayutLocationsConfig,
    api_client: BayutLocationsApi,
    scraped_at: str,
) -> Iterable[dict[str, Any]]:
    seen: set[int] = set()
    queries = tuple(dict.fromkeys(query.strip() for query in config.queries if query.strip()))
    for query in queries:
        pages_without_new = 0
        for page in range(config.max_pages):
            payload = api_client.search_locations(query=query, page=page, langs=config.langs)
            results = _result_list(payload)
            new_ids_on_page = 0
            for item in results:
                if config.only_dubai and not _is_dubai_location(item):
                    continue
                for location in _locations_from_result(
                    item, include_ancestors=config.include_ancestors
                ):
                    location_id = location.get("id")
                    if isinstance(location_id, int) and location_id in seen:
                        continue
                    if isinstance(location_id, int):
                        seen.add(location_id)
                        new_ids_on_page += 1
                    yield {
                        "endpoint": "locations_search",
                        "scraped_at": scraped_at,
                        "query": query,
                        "page": page,
                        "raw": location,
                    }
            if len(results) == 0:
                break
            if new_ids_on_page == 0:
                pages_without_new += 1
            else:
                pages_without_new = 0
            if (
                config.stop_after_pages_without_new
                and pages_without_new >= config.stop_after_pages_without_new
            ):
                break
            if config.request_pause_seconds:
                time.sleep(config.request_pause_seconds)


def _result_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results")
    if results is None:
        return []
    if not isinstance(results, list):
        raise ValueError("Bayut locations_search response.results must be a list")
    if not all(isinstance(item, dict) for item in results):
        raise ValueError("Bayut locations_search response.results must contain objects")
    return results


def _is_dubai_location(item: dict[str, Any]) -> bool:
    if item.get("id") == BAYUT_DUBAI_LOCATION_ID and item.get("level") == "city":
        return True
    full = item.get("full")
    if not isinstance(full, dict):
        return False
    city = full.get("city")
    return isinstance(city, dict) and city.get("id") == BAYUT_DUBAI_LOCATION_ID


def _locations_from_result(
    item: dict[str, Any],
    *,
    include_ancestors: bool,
) -> Iterable[dict[str, Any]]:
    yield item
    if not include_ancestors:
        return

    full = item.get("full")
    if not isinstance(full, dict):
        return

    for level in ("city", "community", "sub_community", "cluster"):
        location = _ancestor_location(full, level=level, source_item=item)
        if location is not None:
            yield location


def _ancestor_location(
    full: dict[str, Any],
    *,
    level: str,
    source_item: dict[str, Any],
) -> dict[str, Any] | None:
    ancestor = full.get(level)
    if not isinstance(ancestor, dict):
        return None

    location_id = ancestor.get("id")
    if not isinstance(location_id, int):
        return None

    country = full.get("country") if isinstance(full.get("country"), dict) else {}
    city = full.get("city") if isinstance(full.get("city"), dict) else {}
    community = full.get("community") if isinstance(full.get("community"), dict) else {}
    sub_community = full.get("sub_community") if isinstance(full.get("sub_community"), dict) else {}
    cluster = full.get("cluster") if isinstance(full.get("cluster"), dict) else {}

    ancestor_full = {"country": country}
    if level in {"city", "community", "sub_community", "cluster"}:
        ancestor_full["city"] = city
    if level in {"community", "sub_community", "cluster"}:
        ancestor_full["community"] = community
    if level in {"sub_community", "cluster"}:
        ancestor_full["sub_community"] = sub_community
    if level == "cluster":
        ancestor_full["cluster"] = cluster

    return {
        "id": location_id,
        "name": ancestor.get("name", ""),
        "name_l1": ancestor.get("name_l1", ""),
        "level": level,
        "completion_status": source_item.get("completion_status", ""),
        "full": ancestor_full,
        "derived_from_location_id": source_item.get("id"),
        "derived_from_level": source_item.get("level"),
    }


def _headers(api_key: str) -> dict[str, str]:
    return {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "uae-real-estate2.p.rapidapi.com",
        "accept": "application/json",
    }


def _resolve_api_key(configured_api_key: str) -> str:
    api_key = configured_api_key.strip() or os.environ.get("BAYUT_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Bayut API key missing. Set BAYUT_API_KEY or pass api_key in config.")
    return api_key


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
