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
uv run python -m holocron.scripts.run_local --source dld
uv run python -m holocron.scripts.run_local --source gis --config '{"max_plots": 100}'
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
| `bayut_ingest` | Manual / on demand | Fetch one Bayut release, store raw CSVs in S3, publish append-only tables, run checks |
| `dld_ingest` | Daily 06:00 UTC | Fetch one DLD release, store raw CSVs in S3, publish tables, run checks |
| `dxbi_ingest` | Manual / on demand | Fetch one DXBI release, store raw CSVs in S3, publish tables, run checks |
| `gis_ingest` | Weekly Monday 07:00 UTC | Scrape one GIS release, store raw CSVs in S3, publish tables, run checks |
| `geo_ingest` | Manual / on demand | Fetch one geo release, store raw CSVs in S3, publish tables, run checks |
| `pf_locations_ingest` | Manual / on demand | Scrape one Property Finder locations release, publish the bronze table, then build the derived hierarchy table |

## S3 Layout

```text
raw/bayut/{release_id}/sales.csv
raw/bayut/{release_id}/rentals.csv

raw/dld/{release_id}/transactions.csv
raw/dld/{release_id}/rent_contracts.csv
raw/dld/{release_id}/projects.csv
raw/dld/{release_id}/buildings.csv
raw/dld/{release_id}/units.csv
raw/dld/{release_id}/land_registry.csv
raw/dld/{release_id}/developers.csv

raw/dxbi/{release_id}/locations.csv
raw/dxbi/{release_id}/developers.csv

raw/gis/{release_id}/dda_plots.csv
raw/gis/{release_id}/project_areas.csv
raw/gis/{release_id}/subproject_areas.csv
raw/gis/{release_id}/plot_building_limits.csv
raw/gis/{release_id}/plot_podium_limits.csv
raw/gis/{release_id}/plot_features.csv
raw/gis/{release_id}/frozen_plots.csv
raw/gis/{release_id}/landuse_symbols.csv
raw/gis/{release_id}/plot_built_to_lines.csv
raw/gis/{release_id}/plot_arcades.csv
raw/gis/{release_id}/plot_retail.csv

raw/geo/{release_id}/building_coordinates.csv
raw/pf_locations/{release_id}/pf_locations.csv

manifests/bayut/{release_id}.json
manifests/dld/{release_id}.json
manifests/dxbi/{release_id}.json
manifests/gis/{release_id}.json
manifests/geo/{release_id}.json
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
uv run python -m holocron.scripts.run_local --source bayut
uv run python -m holocron.scripts.run_local --source dld
uv run python -m holocron.scripts.run_local --source dxbi
uv run python -m holocron.scripts.run_local --source gis --config '{"release_id": "2026-03-15T07-00-00Z"}'
uv run python -m holocron.scripts.run_local --source geo
uv run python -m holocron.scripts.run_local --source pf_locations
```
