"""Dubai Land Department transaction extraction logic."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from holocron.contracts import RawFile, RawRelease
from holocron.platform.execution import build_raw_file, build_raw_release, new_run_id, utc_now
from holocron.platform.metadata import safe_config_metadata
from holocron.sources.dld.source import DldConfig, SOURCE, build_daily_slices

logger = logging.getLogger(__name__)

_GATEWAY_URL = "https://gateway.dubailand.gov.ae"
_DLD_URL = "https://dubailand.gov.ae/en/eservices/real-estate-transaction"
_TRANSACTION_TYPE_IDS = {"sales": 1, "mortgage": 2, "others": 3}
_HEADERS = {
    "Accept": "application/json",
    "Referer": _DLD_URL,
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


class DldApi(Protocol):
    def fetch_transactions(
        self,
        *,
        kind: str,
        start_date: date,
        end_date: date,
        data_mode: str,
    ) -> dict[str, Any]: ...

    def fetch_daily_totals(
        self,
        *,
        kind: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]: ...


class DldApiClient:
    def __init__(self, *, client: httpx.Client, consumer_id: str) -> None:
        self._client = client
        self._consumer_id = consumer_id
        self._token: str | None = None

    def fetch_transactions(
        self,
        *,
        kind: str,
        start_date: date,
        end_date: date,
        data_mode: str,
    ) -> dict[str, Any]:
        url = f"{_GATEWAY_URL}/communitywise/transaction/{kind}/details/"
        return self._get_json(
            url,
            params={
                "fromDate": start_date.isoformat(),
                "toDate": end_date.isoformat(),
                "data": data_mode,
            },
        )

    def fetch_daily_totals(
        self,
        *,
        kind: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        url = f"{_GATEWAY_URL}/areawise/transaction/daily/transactions/"
        return self._get_json(
            url,
            params={
                "fromDate": start_date.isoformat(),
                "toDate": end_date.isoformat(),
                "transactionType": str(_TRANSACTION_TYPE_IDS[kind]),
            },
        )

    def _get_json(self, url: str, *, params: dict[str, str]) -> dict[str, Any]:
        response = self._client.get(url, params=params, headers=self._authorized_headers())
        response.raise_for_status()
        payload = response.json()
        _raise_for_dld_errors(payload, url=response.url)
        return payload

    def _authorized_headers(self) -> dict[str, str]:
        return {**_HEADERS, "consumer-id": self._consumer_id, "TOKEN": self._get_token()}

    def _get_token(self) -> str:
        if self._token is None:
            self._token = self._authenticate()
        return self._token

    def _authenticate(self) -> str:
        response = self._client.post(
            f"{_GATEWAY_URL}/dldrest/authentication",
            json={"dateOfBirth": "01/01/01"},
            headers={
                **_HEADERS,
                "consumer-id": self._consumer_id,
                "Authorization": f"Basic {_guest_credential()}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        token = response.headers.get("token")
        if not token:
            raise RuntimeError("DLD authentication response did not include TOKEN header")
        payload = response.json()
        _raise_for_dld_errors(payload, url=response.url)
        return token


def extract_release(
    output_dir: str | Path,
    *,
    config: DldConfig | dict,
    now: datetime | None = None,
    api_client: DldApi | None = None,
) -> RawRelease:
    parsed_config = config if isinstance(config, DldConfig) else DldConfig.model_validate(config)
    current_time = now or utc_now()
    run_id = new_run_id(current_time)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if api_client is None:
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            api_client = DldApiClient(client=client, consumer_id=parsed_config.consumer_id)
            files = _extract_files(output_path, config=parsed_config, api_client=api_client)
    else:
        files = _extract_files(output_path, config=parsed_config, api_client=api_client)

    if not files:
        raise RuntimeError("DLD extraction produced no raw files")

    return build_raw_release(
        source=SOURCE,
        files=files,
        run_id=run_id,
        now=current_time,
        metadata={"config": safe_config_metadata(parsed_config)},
    )


def _extract_files(
    output_path: Path, *, config: DldConfig, api_client: DldApi
) -> tuple[RawFile, ...]:
    raw_files: list[RawFile] = []
    for date_slice in build_daily_slices(config):
        for kind in config.transaction_kinds:
            raw_response = api_client.fetch_transactions(
                kind=kind,
                start_date=date_slice.day,
                end_date=date_slice.day,
                data_mode=config.data_mode,
            )
            rows = _transaction_rows(
                raw_response,
                kind=kind,
                day=date_slice.day,
                data_mode=config.data_mode,
            )
            path = output_path / f"dld_transactions_{kind}_{date_slice.key}.jsonl"
            raw_files.append(_write_jsonl_raw_file(path, rows))

        if config.include_daily_totals:
            total_rows = []
            for kind in config.transaction_kinds:
                raw_response = api_client.fetch_daily_totals(
                    kind=kind,
                    start_date=date_slice.day,
                    end_date=date_slice.day,
                )
                total_rows.extend(_daily_total_rows(raw_response, kind=kind, day=date_slice.day))
            path = output_path / f"dld_transaction_daily_totals_{date_slice.key}.jsonl"
            raw_files.append(_write_jsonl_raw_file(path, total_rows))

    return tuple(raw_files)


def _transaction_rows(
    payload: dict[str, Any],
    *,
    kind: str,
    day: date,
    data_mode: str,
) -> Iterable[dict[str, Any]]:
    for group in _result_items(payload):
        property_type = {
            "id": group.get("propertyTypeId"),
            "name": group.get("propertyTypeName"),
        }
        for transaction in group.get("transactions") or []:
            yield {
                "endpoint": "communitywise_transaction_details",
                "transaction_kind": kind,
                "transaction_date": day.isoformat(),
                "data_mode": data_mode,
                "property_type": property_type,
                "raw": transaction,
            }


def _daily_total_rows(
    payload: dict[str, Any],
    *,
    kind: str,
    day: date,
) -> Iterable[dict[str, Any]]:
    for item in _result_items(payload):
        yield {
            "endpoint": "areawise_daily_transactions",
            "transaction_kind": kind,
            "transaction_type_id": _TRANSACTION_TYPE_IDS[kind],
            "requested_date": day.isoformat(),
            "raw": item,
        }


def _result_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    response = payload.get("response")
    if not isinstance(response, dict):
        raise ValueError("DLD payload missing response object")
    result = response.get("result")
    if result is None:
        return []
    if not isinstance(result, list):
        raise ValueError("DLD payload response.result must be a list")
    return result


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


def _guest_credential() -> str:
    credential = {
        "ApplicationKey": "MyBrowser",
        "MethodIdentity": "guest",
        "MethodPasscode": "123",
        "Platform": "DESKTOP",
        "Method": "ANONYMOUS",
        "DeviceKey": "MyPC",
    }
    raw = json.dumps(credential, separators=(",", ":")).encode()
    return base64.b64encode(raw).decode()


def _raise_for_dld_errors(payload: dict[str, Any], *, url: Any) -> None:
    errors = payload.get("validationErrorsList")
    if errors:
        raise RuntimeError(f"DLD API returned validation errors for {url}: {errors}")
    response_code = payload.get("responseCode")
    if response_code not in (None, 200):
        raise RuntimeError(f"DLD API returned responseCode={response_code} for {url}")
