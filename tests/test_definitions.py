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
        "reelly_supply_raw",
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
        "reelly_supply_archive_chunk",
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
    assert _selected_assets("reelly_supply_archive_chunk") == {"reelly_supply_raw"}
    scheduled_jobs = {schedule.job_name for schedule in defs.schedules}
    assert (
        not {
            "bay_locations_manual_full_fetch",
            "bay_transactions_manual_backfill",
            "dld_transactions_manual_backfill",
            "dxbi_transactions_manual_backfill",
            "dda_planning_layers_manual_full_refresh",
            "reelly_supply_archive_chunk",
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
    assert reelly_config["download_documents"] is True
    assert reelly_config["download_all_project_docs"] is True


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
