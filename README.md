# Holocron

Dagster-based orchestration for release-oriented ingestion into ClickHouse.

## Architecture

Holocron is organized around source-local definitions:

- each source lives in `holocron/sources/<source>/`
- `source.py` defines the source contract, tables, config, and checks
- `extract.py` normally owns the source-specific scraping/download logic
- shared framework code in `holocron/framework/` handles local staging, release manifests, S3 upload, ClickHouse publish, Dagster asset generation, and checks
- handwritten downstream assets live in `holocron/assets/` when a table is derived from another published table rather than extracted directly from a source

Dagster models:

- one local staging asset per source
- one raw release asset per source
- one asset per final ClickHouse table
- one cleanup job per source for removing staged local files after promotion
- asset checks for row counts, uniqueness, empties, and source-specific assertions
- source identity is dataset-level; Dagster grouping is provider-level

## Quickstart

```bash
cp .env.example .env
# fill in .env with your AWS, ClickHouse, and Postgres credentials

uv sync

# apply ClickHouse schema
clickhouse-client < holocron/lib/sql/clickhouse_schema.sql

# start Dagster (webserver at http://localhost:3000)
docker compose up -d

# or run one source locally
uv run python -m holocron.scripts.run_local --source dld_bulk_data
uv run python -m holocron.scripts.run_local --source dda_planning_layers --config '{"max_plots": 100}'
```

## Local Stack

For a self-contained local stack with Dagster, Postgres, ClickHouse, and MinIO:

```bash
cp .env.local.example .env
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```

Notes:

- `docker-compose.local.yml` bootstraps the ClickHouse schema automatically from `holocron/lib/sql/clickhouse_schema.sql`.
- MinIO is used as an S3 mock and the bucket is created automatically.
- The local `.env` uses service names like `clickhouse` and `minio`, so commands should be run inside the compose network if they need those hostnames.
- MinIO API is exposed on `http://localhost:19001` and the console on `http://localhost:19002`.

## Pipelines

| Job | Trigger | What it does |
|-----|---------|--------------|
| `bay_transactions_ingest` | Manual / on demand | Fetch one Bay transactions release, store raw CSVs in S3, publish append-only tables, run checks |
| `dld_bulk_data_ingest` | Daily 06:00 UTC | Fetch one DLD bulk-data release, store raw CSVs in S3, publish tables, run checks |
| `dxbi_lookups_ingest` | Manual / on demand | Fetch one DXBI lookup release, store raw CSVs in S3, publish tables, run checks |
| `dxbi_transactions_ingest` | Manual / on demand | Fetch DXBI transaction/rent history tables from supplied DXBI pages through a browser-backed session, store CSVs in S3, publish append-only tables, run checks |
| `dda_planning_layers_ingest` | Weekly Monday 07:00 UTC | Scrape one DDA planning-layers release, store raw CSVs in S3, publish tables, run checks |
| `geo_buildings_ingest` | Manual / on demand | Fetch one geo buildings release, store raw CSVs in S3, publish tables, run checks |
| `pf_locations_ingest` | Manual / on demand | Scrape one Property Finder locations release, publish the bronze table, then build the derived hierarchy table |

## Naming

- `SourceSpec.name` is the dataset / operational ingestion unit, for example `pf_locations`, `bay_transactions`, or `dda_planning_layers`
- `SourceSpec.provider` is the upstream family used for Dagster grouping, for example `propertyfinder`, `bayut`, or `dda`
- Keep warehouse table names concise and source-scoped: `pf_*`, `dxbi_*`, `dld_*`, `dda_*`, `bay_*`
- Keep hand-written downstream assets in `holocron/assets/` and group them by provider when they are derived from a source table

## S3 Layout

```text
raw/bay_transactions/{release_id}/sales.csv
raw/bay_transactions/{release_id}/rentals.csv

raw/dld_bulk_data/{release_id}/transactions.csv
raw/dld_bulk_data/{release_id}/rent_contracts.csv
raw/dld_bulk_data/{release_id}/projects.csv
raw/dld_bulk_data/{release_id}/buildings.csv
raw/dld_bulk_data/{release_id}/units.csv
raw/dld_bulk_data/{release_id}/land_registry.csv
raw/dld_bulk_data/{release_id}/developers.csv

raw/dxbi_lookups/{release_id}/locations.csv
raw/dxbi_lookups/{release_id}/developers.csv

raw/dxbi_transactions/{release_id}/sales.csv
raw/dxbi_transactions/{release_id}/rentals.csv

raw/dda_planning_layers/{release_id}/dda_plots.csv
raw/dda_planning_layers/{release_id}/dda_project_areas.csv
raw/dda_planning_layers/{release_id}/dda_subproject_areas.csv
raw/dda_planning_layers/{release_id}/dda_plot_building_limits.csv
raw/dda_planning_layers/{release_id}/dda_plot_podium_limits.csv
raw/dda_planning_layers/{release_id}/dda_plot_features.csv
raw/dda_planning_layers/{release_id}/dda_frozen_plots.csv
raw/dda_planning_layers/{release_id}/dda_landuse_symbols.csv
raw/dda_planning_layers/{release_id}/dda_plot_built_to_lines.csv
raw/dda_planning_layers/{release_id}/dda_plot_arcades.csv
raw/dda_planning_layers/{release_id}/dda_plot_retail.csv

raw/geo_buildings/{release_id}/building_coordinates.csv
raw/pf_locations/{release_id}/pf_locations.csv

manifests/bay_transactions/{release_id}.json
manifests/dld_bulk_data/{release_id}.json
manifests/dxbi_lookups/{release_id}.json
manifests/dxbi_transactions/{release_id}.json
manifests/dda_planning_layers/{release_id}.json
manifests/geo_buildings/{release_id}.json
manifests/pf_locations/{release_id}.json
```

Paths are immutable. Release IDs default to `YYYY-MM-DDTHH-MM-SSZ`.

## Code Layout

```text
holocron/assets        # handwritten downstream assets derived from published tables
holocron/framework     # release models, Dagster factory, validation, storage helpers
holocron/resources     # S3, ClickHouse, HTTP resources
holocron/sources       # source-local contracts and extraction logic
holocron/scripts       # operator tooling
```

## Adding a Source

Adding a new source should normally require:

1. `holocron/sources/<newsource>/source.py`
2. `holocron/sources/<newsource>/extract.py`
3. one import in `holocron/sources/__init__.py`
4. optionally schema changes in `holocron/lib/sql/clickhouse_schema.sql`

Small legacy/simple sources may still keep the extract function in `source.py`, but new source-specific logic should stay local to the source package.

`source.py` should define:

- source metadata
- table mappings
- config schema and defaults
- optional extra checks

`extract.py` should define:

- the extraction logic that writes one or more CSVs

The framework generates the Dagster assets, job, schedule, and checks from that source definition.

## Environment Variables

See `.env.example` for the full list. Key groups:

- `DAGSTER_POSTGRES_URL` for Dagster metadata storage
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_USE_PATH_STYLE`
- `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`, `CLICKHOUSE_DATABASE`, `CLICKHOUSE_SECURE`
- `LOCAL_RELEASES_DIR` for mounted local staging before S3 promotion
- `GEO_BUILDINGS_URL` for the geo source input

## Scripts

```bash
uv run python -m holocron.scripts.run_local --source bay_transactions
uv run python -m holocron.scripts.run_local --source dld_bulk_data
uv run python -m holocron.scripts.run_local --source dxbi_lookups
uv run python -m holocron.scripts.run_local --source dxbi_transactions
uv run python -m holocron.scripts.run_local --source dda_planning_layers --config '{"release_id": "2026-03-15T07-00-00Z"}'
uv run python -m holocron.scripts.run_local --source geo_buildings
uv run python -m holocron.scripts.run_local --source pf_locations
```

For `dxbi_transactions`, a real local Chrome-family binary can currently clear DXBI's Cloudflare gate automatically in headless Playwright. `storage_state_path` is optional fallback state for environments where that automatic clearance does not work.
