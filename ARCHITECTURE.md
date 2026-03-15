# Architecture

## Release Model

Each ingestion creates a typed release manifest, not just a Dagster run.

The repo tracks current dataset modes like `full_snapshot` and `reference_replace`, but the architecture is intentionally open-ended. New datasets may introduce additional lifecycle or publish patterns later without requiring a repo restructure.

Every release writes immutable raw files to S3 plus a manifest with:

- dataset
- release ID
- mode
- source
- checksums
- row counts
- validation metadata

## Publish Model

Raw data lands in object storage first. ClickHouse publishing depends on the table strategy declared by each table:

- `full_swap`: load to staging, validate non-empty, `EXCHANGE TABLES`
- `append`: load to staging, then append into target

Additional publish strategies can be added later without changing the source registration model.

This keeps raw history immutable while letting each dataset publish according to its own semantics.

## Dataset Semantics

### DLD

DLD exports are treated as complete replacement truth sets. New source drops can reshuffle prior rows arbitrarily, so incremental diff logic is intentionally avoided.

### GIS

GIS publishes weekly full snapshots. All GIS tables in one run share one `release_id`, so the served snapshot is coherent across overlays and plot details.

### DXBI

Cheap lookup/reference tables can be replaced wholesale. Heavier scraped tables should move to append-only bronze keyed by `ingestion_run_id`, with downstream “latest” tables or views built on top.

## Source Contract

Every source is registered through a `SourceSpec` in `etl/orchestration/source_registry.py`.

A source spec owns:

- dataset names
- asset definitions
- validation asset
- ingest job metadata
- optional schedules
- optional source-specific validation hook
- local run-config behavior for operator scripts

This keeps source onboarding declarative without hard-coding source behavior across `definitions.py`, jobs, schedules, and scripts.

## Code Layout

The package root stays `etl/etl`, but internals are split by concern:

- `etl/core`: shared release, registry, load, and validation logic
- `etl/sources`: source-local pipeline code
- `etl/orchestration`: Dagster jobs and schedules
- `etl/resources`: infrastructure clients
- `etl/scripts`: operator tooling

Adding a new source should primarily require:

1. adding dataset/table entries in `etl/core/dataset_registry.py`
2. adding source-local assets and scrape logic under `etl/sources/<name>/`
3. registering a new `SourceSpec` in `etl/orchestration/source_registry.py`
