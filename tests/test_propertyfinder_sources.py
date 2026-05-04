from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from holocron.contracts import RawRelease
from holocron.orchestration.factory import (
    _resolve_pf_listings_config,
    _write_pf_listings_checkpoint,
)
from holocron.platform.checkpoints import checkpoint_s3_key
from holocron.sources import PF_LISTINGS_SOURCE, PF_LOCATIONS_SOURCE, registry
from holocron.sources.pf_listings.extract import extract_release as extract_listings_release
from holocron.sources.pf_listings.media_assets import (
    MediaDownload,
    PropertyFinderListingMediaHydrationConfig,
    hydrate_pf_listing_media_assets,
)
from holocron.sources.pf_listings.source import PropertyFinderListingsConfig
from holocron.sources.pf_locations.extract import extract_release as extract_locations_release
from holocron.sources.pf_locations.source import PropertyFinderLocationsConfig


class FakePropertyFinderLocationsApi:
    def __init__(self) -> None:
        self.location_calls: list[tuple[int, int, str]] = []
        self.filter_calls: list[tuple[int, str]] = []

    def fetch_locations(self, *, page: int, limit: int, locale: str) -> dict[str, Any]:
        self.location_calls.append((page, limit, locale))
        return {
            "data": {
                "attributes": [
                    {
                        "id": 1,
                        "name": "Dubai",
                        "path": "1",
                        "path_name": "",
                        "level": 0,
                        "location_type": "CITY",
                        "coordinates": {"lat": 25.2, "lon": 55.3},
                    },
                    {
                        "id": 14,
                        "name": "Al Furjan",
                        "path": "1.14",
                        "path_name": "Dubai",
                        "level": 1,
                        "location_type": "COMMUNITY",
                        "coordinates": {"lat": 25.0, "lon": 55.1},
                    },
                    {
                        "id": 900,
                        "name": "Abu Dhabi Marina",
                        "path": "2.900",
                        "path_name": "Abu Dhabi",
                        "level": 1,
                        "location_type": "COMMUNITY",
                    },
                ],
                "meta": {"total_count": 3, "total_pages": 1},
            }
        }

    def fetch_filter_settings(self, *, category: int, locale: str) -> dict[str, Any]:
        self.filter_calls.append((category, locale))
        return _filter_settings(property_types=(("1", "Apartment"), ("5", "Land")))


class FakePropertyFinderListingsClient:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, str]] = []
        self.detail_calls: list[str] = []

    def fetch_filter_settings(self, *, category: int, locale: str) -> dict[str, Any]:
        assert category == 1
        assert locale == "en"
        return _filter_settings(property_types=(("1", "Apartment"), ("5", "Land")))

    def fetch_locations(self, *, page: int, limit: int, locale: str) -> dict[str, Any]:
        assert page == 1
        assert limit == 500
        assert locale == "en"
        return _locations_payload(
            [
                {"id": 1, "name": "Dubai", "path": "1", "level": 0, "location_type": "CITY"},
                {
                    "id": 14,
                    "name": "Al Furjan",
                    "path": "1.14",
                    "level": 1,
                    "location_type": "COMMUNITY",
                },
                {
                    "id": 250,
                    "name": "Example Tower",
                    "path": "1.14.250",
                    "level": 2,
                    "location_type": "TOWER",
                },
            ]
        )

    def fetch_search_page(self, *, params) -> dict[str, Any]:
        query = dict(params)
        self.search_calls.append(query)
        property_type_id = query.get("t")
        if property_type_id is None:
            return _search_payload(total_count=5, page_count=1, listings=[])
        if property_type_id == "1":
            return _search_payload(
                total_count=1,
                page_count=1,
                listings=[
                    _listing_wrapper(
                        listing_id="apt-1",
                        property_type="Apartment",
                        location_tree=[
                            {"id": 1, "name": "Dubai", "type": "CITY"},
                            {"id": 14, "name": "Al Furjan", "type": "COMMUNITY"},
                            {"id": 250, "name": "Example Tower", "type": "TOWER"},
                        ],
                        details_path="/en/plp/buy/apartment-for-sale-dubai-example-apt-1.html",
                    )
                ],
            )
        if property_type_id == "5":
            return _search_payload(
                total_count=1,
                page_count=1,
                listings=[
                    _listing_wrapper(
                        listing_id="land-1",
                        property_type="Land",
                        location_tree=[
                            {"id": 1, "name": "Dubai", "type": "CITY"},
                            {"id": 14, "name": "Al Furjan", "type": "COMMUNITY"},
                        ],
                        details_path="/en/plp/buy/land-for-sale-dubai-example-land-1.html",
                    )
                ],
            )
        raise AssertionError(f"Unexpected property type: {property_type_id}")

    def fetch_detail(self, *, details_path: str) -> dict[str, Any]:
        self.detail_calls.append(details_path)
        return {
            "pageProps": {
                "propertyResult": {
                    "property": {
                        "id": "apt-1",
                        "listing_id": "apt-1",
                        "images": {
                            "property": [
                                {
                                    "full": "https://static.shared.propertyfinder.ae/listings/apt-1/full.jpg",
                                    "medium": (
                                        "https://static.shared.propertyfinder.ae/listings/"
                                        "apt-1/medium.jpg"
                                    ),
                                }
                            ],
                            "tower": ["https://graph-images.propertyfinder.ae/towers/example.jpg"],
                        },
                        "floor_plans": [
                            {
                                "url": (
                                    "https://static.shared.propertyfinder.ae/listings/"
                                    "apt-1/floorplan.jpg"
                                )
                            }
                        ],
                    }
                }
            }
        }


class FakePropertyFinderLocationSplitListingsClient:
    def fetch_filter_settings(self, *, category: int, locale: str) -> dict[str, Any]:
        assert category == 1
        assert locale == "en"
        return _filter_settings(property_types=(("1", "Apartment"),))

    def fetch_locations(self, *, page: int, limit: int, locale: str) -> dict[str, Any]:
        assert page == 1
        assert limit == 500
        assert locale == "en"
        return _locations_payload(
            [
                {"id": 1, "name": "Dubai", "path": "1", "level": 0, "location_type": "CITY"},
                {
                    "id": 14,
                    "name": "Al Furjan",
                    "path": "1.14",
                    "level": 1,
                    "location_type": "COMMUNITY",
                },
                {
                    "id": 15,
                    "name": "Dubai Marina",
                    "path": "1.15",
                    "level": 1,
                    "location_type": "COMMUNITY",
                },
            ]
        )

    def fetch_search_page(self, *, params) -> dict[str, Any]:
        query = dict(params)
        if query.get("t") is None:
            return _search_payload(total_count=5, page_count=1, listings=[])
        if query.get("l") == "1":
            return _search_payload(total_count=5, page_count=1, listings=[])
        return _search_payload(
            total_count=1,
            page_count=1,
            listings=[
                _listing_wrapper(
                    listing_id=f"apt-{query['l']}",
                    property_type="Apartment",
                    location_tree=[
                        {"id": 1, "name": "Dubai", "type": "CITY"},
                        {"id": int(query["l"]), "name": "Community", "type": "COMMUNITY"},
                    ],
                    details_path=f"/en/plp/buy/apartment-for-sale-dubai-{query['l']}.html",
                )
            ],
        )

    def fetch_detail(self, *, details_path: str) -> dict[str, Any]:
        raise AssertionError("details should not be fetched")


class FakePropertyFinderSearchErrorListingsClient:
    def fetch_filter_settings(self, *, category: int, locale: str) -> dict[str, Any]:
        assert category == 1
        assert locale == "en"
        return _filter_settings(property_types=(("1", "Apartment"),))

    def fetch_locations(self, *, page: int, limit: int, locale: str) -> dict[str, Any]:
        assert page == 1
        assert limit == 500
        assert locale == "en"
        return _locations_payload(
            [{"id": 1, "name": "Dubai", "path": "1", "level": 0, "location_type": "CITY"}]
        )

    def fetch_search_page(self, *, params) -> dict[str, Any]:
        query = dict(params)
        if query.get("page") == "2":
            raise RuntimeError("Property Finder fetch returned non-JSON after retries")
        if query.get("t") is None:
            return _search_payload(total_count=2_000, page_count=1, listings=[])
        return _search_payload(
            total_count=31,
            page_count=2,
            listings=[
                _listing_wrapper(
                    listing_id="apt-with-page-error",
                    property_type="Apartment",
                    location_tree=[{"id": 1, "name": "Dubai", "type": "CITY"}],
                    details_path="/en/plp/buy/apartment-for-sale-dubai-page-error.html",
                )
            ],
        )

    def fetch_detail(self, *, details_path: str) -> dict[str, Any]:
        raise AssertionError("details should not be fetched")


class FakePropertyFinderChunkListingsClient:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, str]] = []
        self.detail_calls: list[str] = []

    def fetch_search_page(self, *, params) -> dict[str, Any]:
        query = dict(params)
        self.search_calls.append(query)
        page = int(query["page"])
        listing_id = f"chunk-{query['l']}-{page}"
        return _search_payload(
            total_count=2 if query["l"] == "14" else 1,
            page_count=2 if query["l"] == "14" else 1,
            listings=[
                _listing_wrapper(
                    listing_id=listing_id,
                    property_type="Apartment",
                    location_tree=[
                        {"id": 1, "name": "Dubai", "type": "CITY"},
                        {"id": int(query["l"]), "name": "Community", "type": "COMMUNITY"},
                    ],
                    details_path=f"/en/plp/buy/apartment-for-sale-dubai-{listing_id}.html",
                )
            ],
        )

    def fetch_detail(self, *, details_path: str) -> dict[str, Any]:
        self.detail_calls.append(details_path)
        return {
            "pageProps": {
                "propertyResult": {
                    "property": {
                        "listing_id": details_path.rsplit("-", 1)[-1].replace(".html", ""),
                        "images": {"property": []},
                    }
                }
            }
        }


class FakeS3:
    def __init__(self, *, public_url_base: str = "https://cdn.example.test") -> None:
        self.objects: dict[str, bytes] = {}
        self.json_objects: dict[str, dict[str, Any]] = {}
        self.content_types: dict[str, str | None] = {}
        self.public_url_base = public_url_base

    def list_keys(self, *, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))

    def read_text(self, *, key: str, encoding: str = "utf-8") -> str:
        return self.objects[key].decode(encoding)

    def put_bytes(self, *, key: str, payload: bytes, content_type: str | None = None) -> None:
        self.objects[key] = payload
        self.content_types[key] = content_type

    def get_json(self, *, key: str) -> dict[str, Any] | None:
        return self.json_objects.get(key)

    def put_json(self, *, key: str, payload: dict[str, Any]) -> None:
        self.json_objects[key] = payload

    def object_exists(self, *, key: str) -> bool:
        return key in self.objects

    def public_url(self, *, key: str) -> str | None:
        return f"{self.public_url_base.rstrip('/')}/{key}" if self.public_url_base else None


class FakeMediaDownloader:
    def __init__(self, downloads: dict[str, bytes]) -> None:
        self.downloads = downloads
        self.calls: list[str] = []

    def download_media(self, url: str, *, max_bytes: int) -> MediaDownload:
        self.calls.append(url)
        payload = self.downloads[url]
        assert len(payload) <= max_bytes
        return MediaDownload(content=payload, content_type="image/jpeg", final_url=url)


def test_propertyfinder_sources_are_registered() -> None:
    assert registry.get("pf_locations") is PF_LOCATIONS_SOURCE
    assert registry.get("pf_listings") is PF_LISTINGS_SOURCE


def test_pf_locations_extract_writes_dubai_hierarchy_and_filter_context(tmp_path: Path) -> None:
    api_client = FakePropertyFinderLocationsApi()

    release = extract_locations_release(
        tmp_path,
        config=PropertyFinderLocationsConfig(categories=(1,), max_location_pages=1),
        now=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        api_client=api_client,
    )

    files_by_name = {Path(raw_file.path).name: raw_file for raw_file in release.files}
    assert release.source == "pf_locations"
    assert files_by_name["pf_locations_pages.jsonl"].row_count == 1
    assert files_by_name["pf_locations.jsonl"].row_count == 2
    assert files_by_name["pf_filter_settings.jsonl"].row_count == 1
    assert api_client.location_calls == [(1, 500, "en")]
    assert api_client.filter_calls == [(1, "en")]

    location_rows = _read_jsonl(Path(files_by_name["pf_locations.jsonl"].path))
    assert {row["location_id"] for row in location_rows} == {"1", "14"}
    assert {tuple(row["path_ids"]) for row in location_rows} == {("1",), ("1", "14")}

    filter_rows = _read_jsonl(Path(files_by_name["pf_filter_settings.jsonl"].path))
    assert {"value": "5", "label": "Land"} in filter_rows[0]["property_type_choices"]


def test_pf_listings_extract_partitions_by_property_type_and_keeps_land(
    tmp_path: Path,
) -> None:
    listing_client = FakePropertyFinderListingsClient()

    release = extract_listings_release(
        tmp_path,
        config=PropertyFinderListingsConfig(
            categories=(1,),
            max_results_per_query=2,
            max_planned_queries=5,
            max_search_pages_per_run=5,
            fetch_details=True,
            max_details_per_run=1,
        ),
        now=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        listing_client=listing_client,
    )

    files_by_name = {Path(raw_file.path).name: raw_file for raw_file in release.files}
    assert release.source == "pf_listings"
    assert files_by_name["pf_listing_query_plan.jsonl"].row_count == 3
    assert files_by_name["pf_listing_properties.jsonl"].row_count == 2
    assert files_by_name["pf_listing_details.jsonl"].row_count == 1

    plan_rows = _read_jsonl(Path(files_by_name["pf_listing_query_plan.jsonl"].path))
    assert plan_rows[0]["status"] == "split"
    assert plan_rows[0]["split_reason"] == "property_type"
    assert {row["query"]["property_type_id"] for row in plan_rows[1:]} == {1, 5}

    property_rows = _read_jsonl(Path(files_by_name["pf_listing_properties.jsonl"].path))
    rows_by_listing_id = {row["listing_id"]: row for row in property_rows}
    assert set(rows_by_listing_id) == {"apt-1", "land-1"}
    assert rows_by_listing_id["land-1"]["raw_property"]["type"] == "Land"
    assert rows_by_listing_id["apt-1"]["listing_location_ids"] == ["1", "14", "250"]
    assert rows_by_listing_id["apt-1"]["community_location_id"] == "14"
    assert rows_by_listing_id["apt-1"]["building_location_id"] == "250"
    assert listing_client.detail_calls == [
        "/en/plp/buy/apartment-for-sale-dubai-example-apt-1.html"
    ]


def test_pf_listings_extract_uses_location_hierarchy_for_broad_queries(
    tmp_path: Path,
) -> None:
    listing_client = FakePropertyFinderLocationSplitListingsClient()

    release = extract_listings_release(
        tmp_path,
        config=PropertyFinderListingsConfig(
            categories=(1,),
            max_results_per_query=2,
            max_planned_queries=4,
            max_search_pages_per_run=5,
            fetch_details=False,
        ),
        now=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        listing_client=listing_client,
    )

    files_by_name = {Path(raw_file.path).name: raw_file for raw_file in release.files}
    assert files_by_name["pf_listing_location_partitions.jsonl"].row_count == 3
    assert files_by_name["pf_listing_query_plan.jsonl"].row_count == 4
    assert files_by_name["pf_listing_properties.jsonl"].row_count == 2

    plan_rows = _read_jsonl(Path(files_by_name["pf_listing_query_plan.jsonl"].path))
    assert [row["split_reason"] for row in plan_rows[:2]] == ["property_type", "location"]
    assert {row["query"]["location_id"] for row in plan_rows[2:]} == {"14", "15"}


def test_pf_listings_extract_records_search_page_errors_and_continues(tmp_path: Path) -> None:
    listing_client = FakePropertyFinderSearchErrorListingsClient()

    release = extract_listings_release(
        tmp_path,
        config=PropertyFinderListingsConfig(
            categories=(1,),
            max_planned_queries=5,
            max_search_pages_per_run=5,
            fetch_details=False,
        ),
        now=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        listing_client=listing_client,
    )

    files_by_name = {Path(raw_file.path).name: raw_file for raw_file in release.files}
    assert files_by_name["pf_listing_properties.jsonl"].row_count == 1
    assert files_by_name["pf_listing_search_pages.jsonl"].row_count == 2

    search_page_rows = _read_jsonl(Path(files_by_name["pf_listing_search_pages.jsonl"].path))
    assert [row["status"] for row in search_page_rows] == ["ok", "search_error"]
    assert search_page_rows[1]["page"] == 2
    assert "non-JSON" in search_page_rows[1]["error"]


def test_pf_listings_plan_mode_writes_durable_plan_only(tmp_path: Path) -> None:
    listing_client = FakePropertyFinderListingsClient()

    release = extract_listings_release(
        tmp_path,
        config=PropertyFinderListingsConfig(
            mode="plan",
            categories=(1,),
            max_results_per_query=2,
            max_planned_queries=5,
            fetch_details=False,
        ),
        now=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        listing_client=listing_client,
    )

    files_by_name = {Path(raw_file.path).name: raw_file for raw_file in release.files}
    assert set(files_by_name) == {
        "pf_listing_filter_settings.jsonl",
        "pf_listing_location_partitions.jsonl",
        "pf_listing_query_plan.jsonl",
    }
    assert release.metadata["stage"] == "plan"
    assert release.metadata["terminal_query_count"] == 2


def test_pf_listings_search_mode_resumes_from_plan_manifest(tmp_path: Path) -> None:
    s3 = FakeS3()
    plan_manifest_key = _put_pf_plan_manifest(
        s3,
        run_id="plan-1",
        terminal_queries=[
            {"category_id": 1, "location_id": "14", "property_type_id": 1},
            {"category_id": 1, "location_id": "15", "property_type_id": 1},
        ],
    )
    listing_client = FakePropertyFinderChunkListingsClient()

    release = extract_listings_release(
        tmp_path,
        config=PropertyFinderListingsConfig(
            mode="search",
            categories=(1,),
            plan_manifest_s3_key=plan_manifest_key,
            search_query_cursor=0,
            search_page_cursor=2,
            max_search_pages_per_run=1,
            fetch_details=False,
        ),
        now=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        listing_client=listing_client,
        state_store=s3,
    )

    files_by_name = {Path(raw_file.path).name: raw_file for raw_file in release.files}
    search_rows = _read_jsonl(Path(files_by_name["pf_listing_search_pages.jsonl"].path))
    property_rows = _read_jsonl(Path(files_by_name["pf_listing_properties.jsonl"].path))

    assert release.metadata["stage"] == "search"
    assert release.metadata["next_query_index"] == 1
    assert release.metadata["next_page"] == 1
    assert release.metadata["search_completed_result_set"] is False
    assert search_rows[0]["query_index"] == 0
    assert search_rows[0]["page"] == 2
    assert property_rows[0]["listing_id"] == "chunk-14-2"


def test_pf_listings_detail_mode_resumes_through_property_manifests(tmp_path: Path) -> None:
    s3 = FakeS3()
    _put_pf_manifest(
        s3,
        run_id="search-1",
        details=[],
        properties=[
            {
                "listing_id": "apt-1",
                "property_key": "listing_id:apt-1",
                "details_path": "/en/plp/buy/apartment-for-sale-dubai-apt-1.html",
                "category_id": 1,
                "location_id": "14",
            },
            {
                "listing_id": "apt-2",
                "property_key": "listing_id:apt-2",
                "details_path": "/en/plp/buy/apartment-for-sale-dubai-apt-2.html",
                "category_id": 1,
                "location_id": "14",
            },
        ],
    )
    listing_client = FakePropertyFinderChunkListingsClient()

    release = extract_listings_release(
        tmp_path,
        config=PropertyFinderListingsConfig(
            mode="details",
            categories=(1,),
            detail_manifest_cursor=0,
            detail_row_cursor=1,
            max_details_per_run=1,
        ),
        now=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        listing_client=listing_client,
        state_store=s3,
    )

    detail_rows = _read_jsonl(Path(release.files[0].path))
    assert release.metadata["stage"] == "details"
    assert release.metadata["next_manifest_index"] == 1
    assert release.metadata["next_row_index"] == 0
    assert release.metadata["detail_completed_result_set"] is True
    assert detail_rows[0]["listing_id"] == "apt-2"
    assert detail_rows[0]["source_manifest_index"] == 0
    assert detail_rows[0]["source_row_index"] == 1


def test_pf_listings_search_checkpoint_resolves_plan_and_cursor() -> None:
    s3 = FakeS3()
    s3.json_objects[checkpoint_s3_key(source="pf_listings", operation="plan_snapshot")] = {
        "last_manifest_s3_key": "raw/source=pf_listings/manifests/plan-1.json",
        "completed": True,
    }
    s3.json_objects[checkpoint_s3_key(source="pf_listings", operation="search_chunk")] = {
        "plan_manifest_s3_key": "raw/source=pf_listings/manifests/plan-1.json",
        "next_query_index": 12,
        "next_page": 3,
        "completed": False,
    }

    config = _resolve_pf_listings_config(
        source_config={"mode": "search"},
        s3_client=s3,
    )

    assert config["plan_manifest_s3_key"] == "raw/source=pf_listings/manifests/plan-1.json"
    assert config["search_query_cursor"] == 12
    assert config["search_page_cursor"] == 3


def test_pf_listings_checkpoint_write_records_stage_specific_cursor() -> None:
    s3 = FakeS3()

    _write_pf_listings_checkpoint(
        raw_release=_raw_pf_release(
            run_id="search-1",
            metadata={
                "stage": "search",
                "plan_manifest_s3_key": "raw/source=pf_listings/manifests/plan-1.json",
                "search_completed_result_set": False,
                "next_query_index": 4,
                "next_page": 9,
                "search_page_count": 100,
                "property_row_count": 2000,
                "search_error_count": 1,
            },
        ),
        manifest_key="raw/source=pf_listings/manifests/search-1.json",
        s3_client=s3,
    )

    checkpoint = s3.json_objects[checkpoint_s3_key(source="pf_listings", operation="search_chunk")]
    assert checkpoint["completed"] is False
    assert checkpoint["next_query_index"] == 4
    assert checkpoint["next_page"] == 9
    assert checkpoint["last_manifest_s3_key"] == "raw/source=pf_listings/manifests/search-1.json"


def test_pf_listing_media_asset_hydrates_detail_images() -> None:
    s3 = FakeS3()
    image_url = "https://static.shared.propertyfinder.ae/listings/apt-1/full.jpg"
    agent_url = "https://static.shared.propertyfinder.ae/agents/agent-1.jpg"
    _put_pf_manifest(
        s3,
        run_id="run-1",
        details=[
            {
                "listing_id": "apt-1",
                "property_key": "listing_id:apt-1",
                "detail_property": {
                    "listing_id": "apt-1",
                    "images": {"property": [{"full": image_url}]},
                    "agent": {"image": {"url": agent_url}},
                },
            }
        ],
        properties=[],
    )
    downloader = FakeMediaDownloader({image_url: b"image", agent_url: b"agent"})

    result = hydrate_pf_listing_media_assets(
        s3=s3,
        config=PropertyFinderListingMediaHydrationConfig(
            include_search_listing_media=False,
            include_detail_media=True,
            max_concurrent_downloads=1,
        ),
        now=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        download_client=downloader,
    )
    inventory_rows = _inventory_rows(s3, result["inventory_manifest_key"])
    rows_by_type = {row["asset_type"]: row for row in inventory_rows}

    assert result["downloaded"] == 2
    assert set(rows_by_type) == {"listing_image", "agent_image"}
    assert rows_by_type["listing_image"]["status"] == "downloaded"
    assert rows_by_type["listing_image"]["sha256"] == hashlib.sha256(b"image").hexdigest()
    assert rows_by_type["listing_image"]["target_key"].startswith(
        "media/pf_listings/listing_media/listing_id=apt-1/"
        "asset_type=listing_image/field_path=images.property.0/"
    )
    assert rows_by_type["agent_image"]["field_path"] == "agent.image"
    assert s3.objects[rows_by_type["agent_image"]["target_key"]] == b"agent"


def _filter_settings(*, property_types: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    return {
        "filterChoices": {
            "filter[property_type_id]": [
                {"value": value, "label": label} for value, label in property_types
            ],
            "filter[number_of_bedrooms]": [
                {"value": "0", "label": "Studio"},
                {"value": "1", "label": "1 Bedroom"},
            ],
            "sort": [{"value": "nd", "label": "Newest"}],
        }
    }


def _search_payload(*, total_count: int, page_count: int, listings: list[dict[str, Any]]) -> dict:
    return {
        "pageProps": {
            "searchResult": {
                "listings": listings,
                "meta": {
                    "total_count": total_count,
                    "page_count": page_count,
                    "page": 1,
                },
            }
        }
    }


def _locations_payload(locations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "data": {
            "attributes": locations,
            "meta": {"total_count": len(locations), "total_pages": 1},
        }
    }


def _listing_wrapper(
    *,
    listing_id: str,
    property_type: str,
    location_tree: list[dict[str, Any]],
    details_path: str,
) -> dict[str, Any]:
    return {
        "listing_type": "property",
        "property": {
            "id": listing_id,
            "listing_id": listing_id,
            "reference": f"PF-{listing_id}",
            "title": f"{property_type} listing",
            "type": property_type,
            "price": {"value": 1_000_000, "currency": "AED"},
            "size": {"value": 1200, "unit": "sqft"},
            "location": {"id": location_tree[-1]["id"], "lat": 25.1, "lon": 55.2},
            "location_tree": location_tree,
            "share_url": details_path,
            "images": [
                {
                    "medium": (
                        f"https://static.shared.propertyfinder.ae/listings/{listing_id}/medium.jpg"
                    )
                }
            ],
        },
    }


def _put_pf_manifest(
    s3: FakeS3,
    *,
    run_id: str,
    details: list[dict[str, Any]],
    properties: list[dict[str, Any]],
) -> tuple[str, str, str]:
    manifest_key = f"raw/source=pf_listings/manifests/{run_id}.json"
    detail_key = (
        f"raw/source=pf_listings/extract_date=2026-05-04/run_id={run_id}/pf_listing_details.jsonl"
    )
    properties_key = (
        f"raw/source=pf_listings/extract_date=2026-05-04/"
        f"run_id={run_id}/pf_listing_properties.jsonl"
    )
    s3.objects[detail_key] = _jsonl_bytes(details)
    s3.objects[properties_key] = _jsonl_bytes(properties)
    s3.objects[manifest_key] = json.dumps(
        {
            "source": "pf_listings",
            "run_id": run_id,
            "files": [
                {
                    "path": "pf_listing_details.jsonl",
                    "s3_key": detail_key,
                    "row_count": len(details),
                },
                {
                    "path": "pf_listing_properties.jsonl",
                    "s3_key": properties_key,
                    "row_count": len(properties),
                },
            ],
        }
    ).encode("utf-8")
    return manifest_key, detail_key, properties_key


def _put_pf_plan_manifest(
    s3: FakeS3,
    *,
    run_id: str,
    terminal_queries: list[dict[str, Any]],
) -> str:
    manifest_key = f"raw/source=pf_listings/manifests/{run_id}.json"
    plan_key = (
        f"raw/source=pf_listings/extract_date=2026-05-04/run_id={run_id}/"
        "pf_listing_query_plan.jsonl"
    )
    plan_rows = [
        {
            "endpoint": "search_plan",
            "query_signature": f"query-{index}",
            "terminal": True,
            "status": "terminal",
            "query": query,
        }
        for index, query in enumerate(terminal_queries)
    ]
    s3.objects[plan_key] = _jsonl_bytes(plan_rows)
    s3.objects[manifest_key] = json.dumps(
        {
            "source": "pf_listings",
            "run_id": run_id,
            "files": [
                {
                    "path": "pf_listing_query_plan.jsonl",
                    "s3_key": plan_key,
                    "row_count": len(plan_rows),
                }
            ],
        }
    ).encode("utf-8")
    return manifest_key


def _raw_pf_release(*, run_id: str, metadata: dict[str, Any]) -> RawRelease:
    return RawRelease(
        source="pf_listings",
        run_id=run_id,
        extract_date="2026-05-04",
        created_at="2026-05-04T12:00:00+00:00",
        files=(),
        metadata=metadata,
    )


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    if not rows:
        return b""
    return ("\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n").encode(
        "utf-8"
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _inventory_rows(s3: FakeS3, key: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in s3.read_text(key=key).splitlines() if line.strip()]
