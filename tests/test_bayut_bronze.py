import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from holocron.sources.bay_listings.bronze import (
    load_release_to_clickhouse as load_listings_release,
)
from holocron.sources.bay_locations.bronze import (
    load_release_to_clickhouse as load_locations_release,
)
from holocron.sources.bay_transactions.bronze import (
    load_release_to_clickhouse as load_transactions_release,
)


class _FakeS3:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self._objects = objects

    def download_file(self, *, key: str, path: str | Path) -> None:
        payload = self._objects[key]
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)


class _FakeClickHouse:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.insert_calls: list[dict[str, Any]] = []
        self.replace_calls: list[dict[str, Any]] = []

    def command(self, sql: str) -> None:
        self.commands.append(sql)

    def insert_rows(
        self, *, table: str, rows: list[tuple], column_names: tuple[str, ...] | list[str]
    ) -> None:
        self.insert_calls.append(
            {
                "table": table,
                "rows": rows,
                "column_names": tuple(column_names),
            }
        )

    def replace_table_rows(
        self,
        *,
        table: str,
        rows: list[tuple],
        column_names: tuple[str, ...] | list[str],
        staging_suffix: str,
    ) -> int:
        self.replace_calls.append(
            {
                "table": table,
                "rows": rows,
                "column_names": tuple(column_names),
                "staging_suffix": staging_suffix,
            }
        )
        return len(rows)


def _jsonl_payload(rows: list[dict[str, Any]]) -> bytes:
    return ("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n").encode("utf-8")


def test_load_bay_listings_release_to_clickhouse() -> None:
    raw_rows = [
        {
            "endpoint": "properties_search",
            "scraped_at": "2026-05-02T16:00:00+00:00",
            "purpose": "for-sale",
            "category": "residential",
            "location_id": 2,
            "page": 0,
            "raw": {
                "id": 15050992,
                "title": "Apartment for Sale",
                "reference_number": "REF-1",
                "purpose": "for-sale",
                "type": {"main": "Residential", "sub": "Apartments"},
                "price": 1250000,
                "area": {"built_up": 850, "plot": None},
                "details": {"bedrooms": 1, "bathrooms": 2, "completion_status": "completed"},
                "location": {
                    "city": {"id": 2, "name": "Dubai"},
                    "community": {"id": 59, "name": "Jumeirah Village Circle (JVC)"},
                    "sub_community": {"id": 2478, "name": "JVC District 10"},
                    "cluster": {"id": 87382, "name": "Example Tower"},
                    "coordinates": {"lat": 25.1, "lng": 55.2},
                },
                "agency": {"id": 10212, "name": "White & Co"},
                "agent": {"id": 2118760, "name": "Maybelle Teraza"},
                "legal": {"permit_number": "716", "dld_property_sk": "15050992"},
                "project": {"id": 3505, "title": "Binghatti Etherea"},
                "meta": {
                    "created_at": "2026-05-02 15:38:58",
                    "updated_at": "2026-05-02 15:39:05",
                    "url": "https://www.bayut.com/property/details-15050992.html",
                },
            },
        }
    ]
    payload = _jsonl_payload(raw_rows)
    s3 = _FakeS3({"raw/listings.jsonl": payload})
    clickhouse = _FakeClickHouse()

    result = load_listings_release(
        raw_release={
            "source": "bay_listings",
            "run_id": "run-1",
            "extract_date": "2026-05-02",
            "files": [
                {
                    "path": "bay_listings_for_sale_residential_location_2.jsonl",
                    "s3_key": "raw/listings.jsonl",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ],
        },
        s3=s3,  # type: ignore[arg-type]
        clickhouse=clickhouse,  # type: ignore[arg-type]
    )

    assert result["table_row_counts"] == {"bay_listings_bronze": 1}
    assert any(
        "CREATE TABLE IF NOT EXISTS bay_listings_bronze" in sql for sql in clickhouse.commands
    )
    assert any(
        "ALTER TABLE bay_listings_bronze DELETE WHERE extract_date" in sql
        for sql in clickhouse.commands
    )
    insert_call = clickhouse.insert_calls[0]
    assert insert_call["table"] == "bay_listings_bronze"
    assert insert_call["rows"][0][1] == 15050992
    assert insert_call["rows"][0][19] == "Dubai"


def test_load_bay_transactions_release_to_clickhouse() -> None:
    raw_rows = [
        {
            "endpoint": "transactions",
            "scraped_at": "2026-05-02T16:00:00+00:00",
            "purpose": "for-sale",
            "category": "residential",
            "locations_ids": [10, 36, 21741],
            "start_date": "2026-04-25",
            "end_date": "2026-05-02",
            "page": 0,
            "raw": {
                "amount": "875000.00",
                "category": "Sales",
                "date": "2026-05-01",
                "property": {
                    "floor": "5",
                    "beds": "1",
                    "type": "apartments",
                    "builtup_area": {"sqft": 589.0},
                    "plot_area": {"sqft": None},
                    "occupancy_status": "Vacant",
                },
                "location": {
                    "id": 980,
                    "location": "Marina Diamond 2",
                    "full_location": "Dubai Marina -> Marina Diamonds -> Marina Diamond 2",
                    "coordinates": {"latitude": 25.069448, "longitude": 55.134892},
                },
                "agent_id": 2347968,
                "status": "Approved",
                "contract": {
                    "monthly_amount": "",
                    "contract_type": "Unknown",
                    "duration_months": "",
                },
            },
        }
    ]
    payload = _jsonl_payload(raw_rows)
    s3 = _FakeS3({"raw/transactions.jsonl": payload})
    clickhouse = _FakeClickHouse()

    result = load_transactions_release(
        raw_release={
            "source": "bay_transactions",
            "run_id": "run-1",
            "files": [
                {
                    "path": "bay_transactions_for_sale_2026-04-25_2026-05-02.jsonl",
                    "s3_key": "raw/transactions.jsonl",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ],
        },
        s3=s3,  # type: ignore[arg-type]
        clickhouse=clickhouse,  # type: ignore[arg-type]
    )

    assert result["table_row_counts"] == {"bay_transactions_bronze": 1}
    assert any(
        "CREATE TABLE IF NOT EXISTS bay_transactions_bronze" in sql for sql in clickhouse.commands
    )
    delete_sql = next(
        sql
        for sql in clickhouse.commands
        if "ALTER TABLE bay_transactions_bronze DELETE WHERE" in sql
    )
    assert "transaction_date >= toDate('2026-04-25')" in delete_sql
    assert "transaction_date <= toDate('2026-05-02')" in delete_sql
    insert_call = clickhouse.insert_calls[0]
    assert insert_call["table"] == "bay_transactions_bronze"
    assert insert_call["rows"][0][8].isoformat() == "2026-05-01"
    assert insert_call["rows"][0][9] == 875000.0


def test_load_bay_locations_release_to_clickhouse() -> None:
    raw_rows = [
        {
            "endpoint": "locations_search",
            "scraped_at": "2026-05-02T16:00:00+00:00",
            "query": "dubai marina",
            "page": 0,
            "raw": {
                "id": 36,
                "name": "Dubai Marina",
                "level": "community",
                "full": {
                    "country": {"id": 1, "name": "UAE"},
                    "city": {"id": 2, "name": "Dubai"},
                    "community": {"id": 36, "name": "Dubai Marina"},
                },
                "coordinates": {"lat": 25.08, "lng": 55.14},
                "completion_status": "completed",
            },
        }
    ]
    payload = _jsonl_payload(raw_rows)
    s3 = _FakeS3({"raw/locations.jsonl": payload})
    clickhouse = _FakeClickHouse()

    result = load_locations_release(
        raw_release={
            "source": "bay_locations",
            "run_id": "run-1",
            "extract_date": "2026-05-02",
            "files": [
                {
                    "path": "bay_locations_dubai.jsonl",
                    "s3_key": "raw/locations.jsonl",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ],
        },
        s3=s3,  # type: ignore[arg-type]
        clickhouse=clickhouse,  # type: ignore[arg-type]
    )

    assert result["table_row_counts"] == {"bay_locations_bronze": 1}
    assert any(
        "CREATE TABLE IF NOT EXISTS bay_locations_bronze" in sql for sql in clickhouse.commands
    )
    assert "TRUNCATE TABLE bay_locations_bronze" not in clickhouse.commands
    assert not clickhouse.insert_calls
    replace_call = clickhouse.replace_calls[0]
    assert replace_call["table"] == "bay_locations_bronze"
    assert replace_call["rows"][0][0] == 36
    assert replace_call["rows"][0][11] == "Dubai"


def test_bay_locations_empty_release_does_not_replace_existing_data() -> None:
    payload = _jsonl_payload([])
    s3 = _FakeS3({"raw/locations.jsonl": payload})
    clickhouse = _FakeClickHouse()

    with pytest.raises(ValueError, match="parsed zero rows"):
        load_locations_release(
            raw_release={
                "source": "bay_locations",
                "run_id": "run-1",
                "extract_date": "2026-05-02",
                "files": [
                    {
                        "path": "bay_locations_dubai.jsonl",
                        "s3_key": "raw/locations.jsonl",
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "row_count": 0,
                    }
                ],
            },
            s3=s3,  # type: ignore[arg-type]
            clickhouse=clickhouse,  # type: ignore[arg-type]
        )

    assert not clickhouse.commands
    assert not clickhouse.insert_calls
    assert not clickhouse.replace_calls


def test_bay_locations_invalid_release_does_not_replace_existing_data() -> None:
    payload = _jsonl_payload([])
    s3 = _FakeS3({"raw/locations.jsonl": payload})
    clickhouse = _FakeClickHouse()

    with pytest.raises(ValueError, match="checksum mismatch"):
        load_locations_release(
            raw_release={
                "source": "bay_locations",
                "run_id": "run-1",
                "extract_date": "2026-05-02",
                "files": [
                    {
                        "path": "bay_locations_dubai.jsonl",
                        "s3_key": "raw/locations.jsonl",
                        "sha256": "bad",
                    }
                ],
            },
            s3=s3,  # type: ignore[arg-type]
            clickhouse=clickhouse,  # type: ignore[arg-type]
        )

    assert not clickhouse.commands
    assert not clickhouse.insert_calls
    assert not clickhouse.replace_calls


def test_bay_listings_loader_rejects_wrong_source() -> None:
    with pytest.raises(ValueError, match="Expected raw_release.source=bay_listings"):
        load_listings_release(
            raw_release={"source": "other", "run_id": "run-1", "files": []},
            s3=_FakeS3({}),  # type: ignore[arg-type]
            clickhouse=_FakeClickHouse(),  # type: ignore[arg-type]
        )
