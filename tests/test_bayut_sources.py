from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from holocron.sources import (
    BAY_LISTINGS_SOURCE,
    BAY_LOCATIONS_SOURCE,
    BAY_TRANSACTIONS_SOURCE,
    registry,
)
from holocron.sources.bay_locations.extract import extract_release as extract_locations_release
from holocron.sources.bay_locations.source import BayutLocationsConfig
from holocron.sources.bay_listings.extract import extract_release as extract_listings_release
from holocron.sources.bay_listings.source import BayutListingsConfig
from holocron.sources.bay_transactions.extract import (
    extract_release as extract_transactions_release,
)
from holocron.sources.bay_transactions.source import (
    BayutTransactionsConfig,
    DateWindow,
    resolve_date_window,
    transaction_request_body,
)


class FakeBayutListingsApi:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str, dict]] = []

    def search_properties(self, *, page: int, langs: str, body: dict) -> dict:
        self.calls.append((page, langs, body))
        return {
            "results": [
                {
                    "id": 15050992 + page,
                    "purpose": body["purpose"],
                    "type": {"main": "Residential", "sub": "Apartments"},
                    "meta": {"created_at": "2026-05-02 15:38:58"},
                }
            ],
            "count": 1,
            "page": page,
        }


class FakeBayutTransactionsApi:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict]] = []

    def fetch_transactions(self, *, page: int, body: dict) -> dict:
        self.calls.append((page, body))
        return {
            "results": [
                {
                    "amount": "875000.00",
                    "date": body["end_date"],
                    "category": "Sales",
                    "location": {"full_location": "Dubai Marina"},
                }
            ],
            "count": 1,
            "page": page,
        }


class FakeBayutLocationsApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []

    def search_locations(self, *, query: str, page: int, langs: str) -> dict:
        self.calls.append((query, page, langs))
        return {
            "results": [
                {
                    "id": 2,
                    "name": "Dubai",
                    "level": "city",
                    "full": {"city": {"id": 2, "name": "Dubai"}},
                    "coordinates": {"lat": 25.2, "lng": 55.3},
                },
                {
                    "id": 3,
                    "name": "Abu Dhabi",
                    "level": "city",
                    "full": {"city": {"id": 3, "name": "Abu Dhabi"}},
                    "coordinates": {"lat": 24.4, "lng": 54.4},
                },
            ],
            "count": 2,
            "page": page,
        }


class FakeBayutAncestorLocationsApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []

    def search_locations(self, *, query: str, page: int, langs: str) -> dict:
        self.calls.append((query, page, langs))
        return {
            "results": [
                {
                    "id": 9001,
                    "name": "Example Tower",
                    "level": "building",
                    "full": {
                        "country": {"id": 1, "name": "UAE"},
                        "city": {"id": 2, "name": "Dubai"},
                        "community": {"id": 10, "name": "Dubai Marina"},
                        "sub_community": {"id": 36, "name": "Marina Gate"},
                    },
                }
            ],
            "count": 1,
            "page": page,
        }


def test_bayut_sources_are_registered() -> None:
    assert registry.get("bay_locations") is BAY_LOCATIONS_SOURCE
    assert registry.get("bay_listings") is BAY_LISTINGS_SOURCE
    assert registry.get("bay_transactions") is BAY_TRANSACTIONS_SOURCE


def test_bayut_listings_config_rejects_unknown_purpose() -> None:
    with pytest.raises(ValueError, match="unsupported listing purposes"):
        BayutListingsConfig(purposes=("daily-rent",))


def test_bayut_listings_default_scope_is_dubai_only() -> None:
    assert BayutListingsConfig().locations_ids == (2,)


def test_bayut_listings_extract_writes_one_file_per_query(tmp_path: Path) -> None:
    api_client = FakeBayutListingsApi()

    release = extract_listings_release(
        tmp_path,
        config=BayutListingsConfig(
            locations_ids=(2,),
            purposes=("for-sale",),
            categories=("residential",),
            max_pages=2,
        ),
        now=datetime(2026, 5, 2, 16, 0, tzinfo=UTC),
        api_client=api_client,
    )

    assert release.source == "bay_listings"
    assert release.run_id == "2026-05-02T16-00-00Z"
    assert len(release.files) == 1
    assert release.files[0].row_count == 2
    assert Path(release.files[0].path).name == "bay_listings_for_sale_residential_location_2.jsonl"
    assert api_client.calls == [
        (
            0,
            "en,ar",
            {
                "purpose": "for-sale",
                "categories": ["residential"],
                "locations_ids": [2],
                "index": "latest",
            },
        ),
        (
            1,
            "en,ar",
            {
                "purpose": "for-sale",
                "categories": ["residential"],
                "locations_ids": [2],
                "index": "latest",
            },
        ),
    ]


def test_bayut_transactions_incremental_window_uses_lookback() -> None:
    config = BayutTransactionsConfig(lookback_days=3)

    window = resolve_date_window(config, today=date(2026, 5, 2))

    assert window == DateWindow(start_date=date(2026, 4, 29), end_date=date(2026, 5, 2))


def test_bayut_transactions_request_body_omits_empty_locations() -> None:
    config = BayutTransactionsConfig(locations_ids=())
    window = DateWindow(start_date=date(2026, 5, 1), end_date=date(2026, 5, 2))

    body = transaction_request_body(config, purpose="for-sale", window=window)

    assert body["start_date"] == "2026-05-01"
    assert body["end_date"] == "2026-05-02"
    assert "locations_ids" not in body


def test_bayut_transactions_default_scope_is_dubai_communities() -> None:
    config = BayutTransactionsConfig()

    assert config.purposes == ("for-sale", "for-rent")
    assert config.max_pages == 1
    assert 36 in config.locations_ids
    assert 54 in config.locations_ids
    assert config.location_batch_size == 1


def test_bayut_transactions_extract_writes_daily_window_file(tmp_path: Path) -> None:
    api_client = FakeBayutTransactionsApi()

    release = extract_transactions_release(
        tmp_path,
        config=BayutTransactionsConfig(
            mode="backfill",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 2),
            purposes=("for-sale",),
            locations_ids=(10, 36, 21741),
            max_pages=1,
        ),
        now=datetime(2026, 5, 2, 16, 0, tzinfo=UTC),
        api_client=api_client,
    )

    assert release.source == "bay_transactions"
    assert release.run_id == "2026-05-02T16-00-00Z"
    assert len(release.files) == 1
    assert release.files[0].row_count == 3
    assert (
        Path(release.files[0].path).name == "bay_transactions_for_sale_2026-05-01_2026-05-02.jsonl"
    )
    assert [call[1]["locations_ids"] for call in api_client.calls] == [[10], [36], [21741]]


def test_bayut_locations_extract_filters_to_dubai(tmp_path: Path) -> None:
    api_client = FakeBayutLocationsApi()

    release = extract_locations_release(
        tmp_path,
        config=BayutLocationsConfig(queries=("dubai",), max_pages=1),
        now=datetime(2026, 5, 2, 16, 0, tzinfo=UTC),
        api_client=api_client,
    )

    assert release.source == "bay_locations"
    assert len(release.files) == 1
    assert release.files[0].row_count == 1
    assert Path(release.files[0].path).name == "bay_locations_dubai.jsonl"
    assert api_client.calls == [("dubai", 0, "en,ar")]


def test_bayut_locations_extract_keeps_embedded_parent_locations(tmp_path: Path) -> None:
    api_client = FakeBayutAncestorLocationsApi()

    release = extract_locations_release(
        tmp_path,
        config=BayutLocationsConfig(queries=("marina gate",), max_pages=1),
        now=datetime(2026, 5, 2, 16, 0, tzinfo=UTC),
        api_client=api_client,
    )

    rows = [
        line
        for line in Path(release.files[0].path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert release.files[0].row_count == 4
    assert any('"id":10' in row and '"level":"community"' in row for row in rows)
    assert any('"id":36' in row and '"level":"sub_community"' in row for row in rows)
    assert any('"id":9001' in row and '"level":"building"' in row for row in rows)
