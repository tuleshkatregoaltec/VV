from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from holocron.sources import DLD_SOURCE, registry
from holocron.sources.dld.extract import extract_release
from holocron.sources.dld.source import DailySlice, DldConfig, build_daily_slices


class FakeDldApiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, date, date]] = []

    def fetch_transactions(
        self,
        *,
        kind: str,
        start_date: date,
        end_date: date,
        data_mode: str,
    ) -> dict:
        self.calls.append(("transactions", kind, start_date, end_date))
        assert data_mode == "Flat"
        return {
            "responseCode": 200,
            "validationErrorsList": [],
            "response": {
                "result": [
                    {
                        "propertyTypeId": 3,
                        "propertyTypeName": {"englishName": "Unit", "arabicName": "وحدة"},
                        "transactions": [
                            {
                                "community": {
                                    "id": "A-266",
                                    "name": {"englishName": "Al Satwa"},
                                },
                                "value": 1623250.0,
                                "projects": [],
                            }
                        ],
                    }
                ]
            },
        }

    def fetch_daily_totals(
        self,
        *,
        kind: str,
        start_date: date,
        end_date: date,
    ) -> dict:
        self.calls.append(("daily_totals", kind, start_date, end_date))
        return {
            "responseCode": 200,
            "validationErrorsList": [],
            "response": {
                "result": [
                    {
                        "date": f"{start_date.isoformat()}T00:00:00",
                        "value": 1623250.0,
                    }
                ]
            },
        }


def test_dld_source_is_registered() -> None:
    assert registry.get("dld_transactions") is DLD_SOURCE


def test_incremental_daily_slices_use_lookback_window() -> None:
    config = DldConfig(mode="incremental", lookback_days=2)

    slices = build_daily_slices(config, today=date(2026, 4, 30))

    assert slices == (
        DailySlice(day=date(2026, 4, 28)),
        DailySlice(day=date(2026, 4, 29)),
        DailySlice(day=date(2026, 4, 30)),
    )


def test_config_rejects_unknown_transaction_kind() -> None:
    with pytest.raises(ValueError, match="unsupported transaction kinds"):
        DldConfig(transaction_kinds=("sales", "leases"))


def test_extract_release_writes_transaction_and_total_jsonl_files(tmp_path: Path) -> None:
    api_client = FakeDldApiClient()

    release = extract_release(
        tmp_path,
        config=DldConfig(
            mode="backfill",
            start_date=date(2026, 4, 30),
            end_date=date(2026, 4, 30),
            transaction_kinds=("sales",),
        ),
        now=datetime(2026, 4, 30, 8, 0, tzinfo=UTC),
        api_client=api_client,
    )

    assert release.run_id == "2026-04-30T08-00-00Z"
    assert release.source == "dld_transactions"
    assert len(release.files) == 2
    assert {Path(file.path).name for file in release.files} == {
        "dld_transactions_sales_2026-04-30.jsonl",
        "dld_transaction_daily_totals_2026-04-30.jsonl",
    }
    assert [file.row_count for file in release.files] == [1, 1]
    assert all(file.content_type == "application/x-ndjson" for file in release.files)
    assert api_client.calls == [
        ("transactions", "sales", date(2026, 4, 30), date(2026, 4, 30)),
        ("daily_totals", "sales", date(2026, 4, 30), date(2026, 4, 30)),
    ]
