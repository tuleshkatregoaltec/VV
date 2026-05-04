import pytest
from dagster import (
    DagsterInvalidConfigError,
    DefaultScheduleStatus,
    Definitions,
    validate_run_config,
)

from holocron.contracts import BronzeTable, SourceSpec
from holocron.definitions import defs
from holocron.orchestration.factory import _run_bronze_loader


def test_definitions_validate_loadable() -> None:
    Definitions.validate_loadable(defs)


def test_definitions_expose_source_assets_and_news_sync() -> None:
    asset_keys = {asset.key.to_user_string() for asset in defs.assets}

    assert asset_keys == {
        "bay_locations_raw",
        "bay_locations_bronze",
        "bay_listings_raw",
        "bay_listings_bronze",
        "bay_transactions_raw",
        "bay_transactions_bronze",
        "dda_planning_layers_raw",
        "dda_planning_layers_bronze",
        "dld_transactions_raw",
        "dld_transactions_bronze",
        "dxbi_transactions_raw",
        "dxbi_transactions_bronze",
        "news_feeds_raw",
        "news_thumbnail_assets",
        "news_publish",
        "pf_locations_raw",
        "pf_listings_raw",
        "pf_listing_media_assets",
        "reelly_supply_raw",
        "reelly_supply_document_assets",
        "reelly_supply_project_media_assets",
        "news_sync",
    }


def test_definitions_expose_named_operational_jobs() -> None:
    assert {job.name for job in defs.jobs} == {
        "bay_listings_daily_incremental",
        "bay_transactions_daily_incremental",
        "dld_transactions_daily_incremental",
        "dxbi_transactions_daily_incremental",
        "dda_planning_layers_weekly_full_refresh",
        "bay_locations_manual_full_fetch",
        "bay_transactions_manual_backfill",
        "dld_transactions_manual_backfill",
        "dxbi_transactions_manual_backfill",
        "dda_planning_layers_manual_full_refresh",
        "pf_locations_manual_full_fetch",
        "pf_listings_manual_snapshot",
        "pf_listings_plan_snapshot",
        "pf_listings_search_chunk",
        "pf_listings_detail_chunk",
        "news_feeds_poll_and_publish",
        "news_feeds_manual_poll",
        "news_thumbnail_assets_backfill",
        "news_publish_backfill",
        "reelly_supply_archive_chunk",
        "reelly_supply_document_assets_backfill",
        "reelly_supply_project_media_assets_backfill",
        "pf_listing_media_assets_backfill",
        "news_sync_pipeline",
    }


def test_definitions_expose_only_recurring_operational_schedules() -> None:
    assert {
        schedule.name: (
            schedule.job_name,
            schedule.cron_schedule,
            schedule.execution_timezone,
            schedule.default_status,
        )
        for schedule in defs.schedules
    } == {
        "dld_transactions_daily_incremental_schedule": (
            "dld_transactions_daily_incremental",
            "0 5 * * *",
            "Asia/Dubai",
            DefaultScheduleStatus.STOPPED,
        ),
        "bay_transactions_daily_incremental_schedule": (
            "bay_transactions_daily_incremental",
            "30 5 * * *",
            "Asia/Dubai",
            DefaultScheduleStatus.STOPPED,
        ),
        "dxbi_transactions_daily_incremental_schedule": (
            "dxbi_transactions_daily_incremental",
            "0 6 * * *",
            "Asia/Dubai",
            DefaultScheduleStatus.STOPPED,
        ),
        "bay_listings_daily_incremental_schedule": (
            "bay_listings_daily_incremental",
            "30 6 * * *",
            "Asia/Dubai",
            DefaultScheduleStatus.STOPPED,
        ),
        "dda_planning_layers_weekly_full_refresh_schedule": (
            "dda_planning_layers_weekly_full_refresh",
            "0 6 * * 0",
            "Asia/Dubai",
            DefaultScheduleStatus.STOPPED,
        ),
        "news_feeds_poll_and_publish_schedule": (
            "news_feeds_poll_and_publish",
            "*/15 * * * *",
            "Asia/Dubai",
            DefaultScheduleStatus.STOPPED,
        ),
    }


def test_scheduled_source_jobs_select_raw_and_bronze_assets() -> None:
    assert _selected_assets("bay_listings_daily_incremental") == {
        "bay_listings_raw",
        "bay_listings_bronze",
    }
    assert _selected_assets("bay_transactions_daily_incremental") == {
        "bay_transactions_raw",
        "bay_transactions_bronze",
    }
    assert _selected_assets("dld_transactions_daily_incremental") == {
        "dld_transactions_raw",
        "dld_transactions_bronze",
    }
    assert _selected_assets("dxbi_transactions_daily_incremental") == {
        "dxbi_transactions_raw",
        "dxbi_transactions_bronze",
    }
    assert _selected_assets("news_feeds_poll_and_publish") == {
        "news_feeds_raw",
        "news_thumbnail_assets",
        "news_publish",
    }
    assert _selected_assets("dda_planning_layers_weekly_full_refresh") == {
        "dda_planning_layers_raw",
        "dda_planning_layers_bronze",
    }


def test_manual_one_shot_jobs_select_expected_assets_without_schedules() -> None:
    assert _selected_assets("bay_locations_manual_full_fetch") == {
        "bay_locations_raw",
        "bay_locations_bronze",
    }
    assert _selected_assets("dda_planning_layers_manual_full_refresh") == {
        "dda_planning_layers_raw",
        "dda_planning_layers_bronze",
    }
    assert _selected_assets("pf_locations_manual_full_fetch") == {"pf_locations_raw"}
    assert _selected_assets("pf_listings_manual_snapshot") == {"pf_listings_raw"}
    assert _selected_assets("pf_listings_plan_snapshot") == {"pf_listings_raw"}
    assert _selected_assets("pf_listings_search_chunk") == {"pf_listings_raw"}
    assert _selected_assets("pf_listings_detail_chunk") == {"pf_listings_raw"}
    assert _selected_assets("pf_listing_media_assets_backfill") == {"pf_listing_media_assets"}
    assert _selected_assets("news_feeds_manual_poll") == {"news_feeds_raw"}
    assert _selected_assets("news_thumbnail_assets_backfill") == {"news_thumbnail_assets"}
    assert _selected_assets("news_publish_backfill") == {
        "news_thumbnail_assets",
        "news_publish",
    }
    assert _selected_assets("reelly_supply_archive_chunk") == {"reelly_supply_raw"}
    assert _selected_assets("reelly_supply_document_assets_backfill") == {
        "reelly_supply_document_assets"
    }
    assert _selected_assets("reelly_supply_project_media_assets_backfill") == {
        "reelly_supply_project_media_assets"
    }
    scheduled_jobs = {schedule.job_name for schedule in defs.schedules}
    assert (
        not {
            "bay_locations_manual_full_fetch",
            "bay_transactions_manual_backfill",
            "dld_transactions_manual_backfill",
            "dxbi_transactions_manual_backfill",
            "dda_planning_layers_manual_full_refresh",
            "pf_locations_manual_full_fetch",
            "pf_listings_manual_snapshot",
            "pf_listings_plan_snapshot",
            "pf_listings_search_chunk",
            "pf_listings_detail_chunk",
            "pf_listing_media_assets_backfill",
            "news_feeds_manual_poll",
            "news_thumbnail_assets_backfill",
            "news_publish_backfill",
            "reelly_supply_archive_chunk",
            "reelly_supply_document_assets_backfill",
            "reelly_supply_project_media_assets_backfill",
        }
        & scheduled_jobs
    )


@pytest.mark.parametrize(
    ("job_name", "raw_asset_name"),
    [
        ("bay_transactions_manual_backfill", "bay_transactions_raw"),
        ("dld_transactions_manual_backfill", "dld_transactions_raw"),
        ("dxbi_transactions_manual_backfill", "dxbi_transactions_raw"),
    ],
)
def test_manual_backfill_jobs_require_dates_and_inject_backfill_mode(
    job_name: str,
    raw_asset_name: str,
) -> None:
    job = defs.resolve_job_def(job_name)

    with pytest.raises(DagsterInvalidConfigError):
        validate_run_config(job, {"start_date": "2026-01-01"})

    run_config = validate_run_config(
        job,
        {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "max_pages": 3,
        },
    )

    raw_config = run_config["ops"][raw_asset_name]["config"]
    assert raw_config["mode"] == "backfill"
    assert raw_config["start_date"] == "2026-01-01"
    assert raw_config["end_date"] == "2026-01-31"
    assert raw_config["max_pages"] == 3


def test_manual_one_shot_jobs_default_raw_config() -> None:
    bay_locations_config = validate_run_config(
        defs.resolve_job_def("bay_locations_manual_full_fetch"),
        {},
    )["ops"]["bay_locations_raw"]["config"]
    assert len(bay_locations_config["queries"]) > 10
    assert bay_locations_config["max_pages"] == 20
    assert bay_locations_config["include_ancestors"] is True

    reelly_config = validate_run_config(
        defs.resolve_job_def("reelly_supply_archive_chunk"),
        {"page_cursor": 7},
    )["ops"]["reelly_supply_raw"]["config"]
    assert reelly_config["pages_per_run"] == 5
    assert reelly_config["page_cursor"] == 7
    assert reelly_config["download_documents"] is False
    assert reelly_config["download_all_project_docs"] is True

    reelly_document_config = validate_run_config(
        defs.resolve_job_def("reelly_supply_document_assets_backfill"),
        {},
    )["ops"]["reelly_supply_document_assets"]["config"]
    assert reelly_document_config["manifest_prefix"] == "raw/source=reelly_supply/manifests/"
    assert reelly_document_config["target_prefix"] == "media/reelly_supply/documents"
    assert reelly_document_config["max_assets_per_run"] == 500
    assert reelly_document_config["overwrite_existing"] is False
    assert reelly_document_config["include_project_documents"] is True
    assert reelly_document_config["include_project_detail_media"] is False
    assert reelly_document_config["structured_target_keys"] is False
    assert reelly_document_config["max_concurrent_downloads"] == 1

    reelly_media_config = validate_run_config(
        defs.resolve_job_def("reelly_supply_project_media_assets_backfill"),
        {},
    )["ops"]["reelly_supply_project_media_assets"]["config"]
    assert reelly_media_config["manifest_prefix"] == "raw/source=reelly_supply/manifests/"
    assert reelly_media_config["target_prefix"] == "media/reelly_supply/project_media"
    assert reelly_media_config["inventory_prefix"] == (
        "raw/source=reelly_supply/project_media_asset_manifests"
    )
    assert reelly_media_config["inventory_file_name"] == "reelly_supply_project_media_assets.jsonl"
    assert reelly_media_config["include_project_documents"] is False
    assert reelly_media_config["include_project_detail_media"] is True
    assert reelly_media_config["structured_target_keys"] is True
    assert reelly_media_config["max_concurrent_downloads"] == 8
    assert "brochure" not in reelly_media_config["asset_type_allowlist"]
    assert "profile_image" not in reelly_media_config["asset_type_allowlist"]
    assert {"cover_image", "developer_logo", "floorplan"} <= set(
        reelly_media_config["asset_type_allowlist"]
    )

    pf_listings_config = validate_run_config(
        defs.resolve_job_def("pf_listings_manual_snapshot"),
        {},
    )["ops"]["pf_listings_raw"]["config"]
    assert pf_listings_config["mode"] == "snapshot"
    assert pf_listings_config["max_planned_queries"] == 12000
    assert pf_listings_config["max_search_pages_per_run"] == 50000
    assert pf_listings_config["max_details_per_run"] == 100000
    assert pf_listings_config["fetch_details"] is True
    assert pf_listings_config["split_by_location"] is True

    pf_plan_config = validate_run_config(
        defs.resolve_job_def("pf_listings_plan_snapshot"),
        {},
    )["ops"]["pf_listings_raw"]["config"]
    assert pf_plan_config["mode"] == "plan"
    assert pf_plan_config["max_planned_queries"] == 25000
    assert pf_plan_config["max_results_per_query"] == 750
    assert pf_plan_config["max_partition_depth"] == 10

    pf_search_config = validate_run_config(
        defs.resolve_job_def("pf_listings_search_chunk"),
        {},
    )["ops"]["pf_listings_raw"]["config"]
    assert pf_search_config["mode"] == "search"
    assert pf_search_config["max_search_pages_per_run"] == 10000
    assert pf_search_config["fetch_details"] is False

    pf_detail_config = validate_run_config(
        defs.resolve_job_def("pf_listings_detail_chunk"),
        {},
    )["ops"]["pf_listings_raw"]["config"]
    assert pf_detail_config["mode"] == "details"
    assert pf_detail_config["max_details_per_run"] == 25000

    pf_media_config = validate_run_config(
        defs.resolve_job_def("pf_listing_media_assets_backfill"),
        {},
    )["ops"]["pf_listing_media_assets"]["config"]
    assert pf_media_config["manifest_prefix"] == "raw/source=pf_listings/manifests/"
    assert pf_media_config["target_prefix"] == "media/pf_listings/listing_media"
    assert pf_media_config["inventory_prefix"] == (
        "raw/source=pf_listings/listing_media_asset_manifests"
    )
    assert pf_media_config["inventory_file_name"] == "pf_listing_media_assets.jsonl"
    assert pf_media_config["max_assets_per_run"] == 100000
    assert pf_media_config["overwrite_existing"] is False
    assert pf_media_config["include_search_listing_media"] is True
    assert pf_media_config["include_detail_media"] is True
    assert pf_media_config["max_concurrent_downloads"] == 8
    assert "static.shared.propertyfinder.ae" in pf_media_config["allowed_media_hosts"]

    news_thumbnail_config = validate_run_config(
        defs.resolve_job_def("news_thumbnail_assets_backfill"),
        {},
    )["ops"]["news_thumbnail_assets"]["config"]
    assert news_thumbnail_config["manifest_prefix"] == "raw/source=news_feeds/manifests/"
    assert news_thumbnail_config["target_prefix"] == "media/news/thumbnails"
    assert news_thumbnail_config["inventory_prefix"] == (
        "raw/source=news_feeds/thumbnail_asset_manifests"
    )
    assert news_thumbnail_config["inventory_file_name"] == "news_thumbnail_assets.jsonl"
    assert news_thumbnail_config["lookback_days"] == 3
    assert news_thumbnail_config["max_assets_per_run"] == 1000
    assert news_thumbnail_config["overwrite_existing"] is False
    assert news_thumbnail_config["max_concurrent_downloads"] == 8

    news_publish_config = validate_run_config(
        defs.resolve_job_def("news_publish_backfill"),
        {},
    )
    assert news_publish_config["ops"]["news_thumbnail_assets"]["config"]["lookback_days"] == 3
    assert news_publish_config["ops"]["news_publish"]["config"]["manifest_prefix"] == (
        "raw/source=news_feeds/manifests/"
    )
    assert news_publish_config["ops"]["news_publish"]["config"]["thumbnail_inventory_prefix"] == (
        "raw/source=news_feeds/thumbnail_asset_manifests"
    )
    assert news_publish_config["ops"]["news_publish"]["config"]["lookback_days"] == 3
    assert news_publish_config["ops"]["news_publish"]["config"]["max_articles_per_run"] == 1000
    assert news_publish_config["ops"]["news_publish"]["config"]["ensure_schema"] is True
    assert news_publish_config["ops"]["news_publish"]["config"]["dry_run"] is False


def test_bronze_loader_routes_through_source_metadata() -> None:
    calls = []

    def extractor() -> None:
        return None

    def bronze_loader(**kwargs):
        calls.append(kwargs)
        return {
            "run_id": "run-1",
            "table_count": 1,
            "total_rows": 2,
            "table_row_counts": {"synthetic_bronze": 2},
        }

    source = SourceSpec(
        name="synthetic_source",
        provider="synthetic",
        extractor=extractor,
        bronze_loader=bronze_loader,
        bronze_tables=(BronzeTable(name="synthetic_bronze"),),
    )

    class Resource:
        def __init__(self, client: str) -> None:
            self._client = client

        def client(self) -> str:
            return self._client

    result = _run_bronze_loader(
        context=None,  # type: ignore[arg-type]
        source=source,
        raw_release={"source": "synthetic_source", "run_id": "run-1"},
        s3=Resource("s3-client"),  # type: ignore[arg-type]
        clickhouse=Resource("clickhouse-client"),  # type: ignore[arg-type]
    )

    assert calls == [
        {
            "raw_release": {"source": "synthetic_source", "run_id": "run-1"},
            "s3": "s3-client",
            "clickhouse": "clickhouse-client",
        }
    ]
    assert result.metadata["source"] == "synthetic_source"
    assert result.metadata["run_id"] == "run-1"


def _selected_assets(job_name: str) -> set[str]:
    job = defs.resolve_job_def(job_name)
    return {key.to_user_string() for key in job.asset_layer.selected_asset_keys}
