# Vitevue ETL

Dagster OSS orchestration for release-based ingestion into ClickHouse.

## Architecture

```
Hetzner VPS (stateless)          AWS
─────────────────────────        ────────────────────────────────────
Dagster webserver (Dagit)   →    S3 (raw files + manifests)
Dagster daemon              →    Postgres (Dagster metadata)
ETL code (this repo)        →    ClickHouse (analytics tables)
```

Raw data always lands in S3 first. Publish behavior is dataset-specific:

- DLD: full snapshot -> atomic full-table swap
- GIS: coherent weekly release -> atomic full-table swap
- DXBI: reference replace today, designed to expand into append-style bronze ingestion
- Geo: reference replace

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design.

## Quickstart

```bash
cp .env.example .env
# fill in .env with your AWS, ClickHouse, and Postgres credentials

# apply ClickHouse schema
clickhouse-client < etl/lib/sql/clickhouse_schema.sql

# verify connectivity
python -m etl.scripts.doctor

# start Dagster (webserver at http://localhost:3000)
docker compose up -d

# or run a job directly
python -m etl.scripts.run_local --job dld_ingest
```

## Local Stack

For a self-contained local test stack with Dagster, Postgres, ClickHouse, and MinIO:

```bash
cp .env.local.example .env
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build

# run health checks inside the compose network
docker compose -f docker-compose.yml -f docker-compose.local.yml exec dagster-webserver \
  python -m etl.scripts.doctor
```

Notes:

- `docker-compose.local.yml` bootstraps the ClickHouse schema automatically.
- MinIO is used as an S3 mock and the bucket is created automatically.
- The local `.env` uses service names like `clickhouse` and `minio`, so ETL commands should be run inside the compose network, not directly from the host shell.
- MinIO API is exposed on `http://localhost:19001` and the MinIO console on `http://localhost:19002`.

## Pipelines

| Job | Trigger | What it does |
|-----|---------|--------------|
| `dld_ingest` | Daily 06:00 UTC | Fetch one DLD snapshot release → S3 → atomic publish → validate |
| `dxbi_ingest` | Manual / on demand | Fetch one DXBI reference release → S3 → publish → validate |
| `gis_ingest` | Weekly Monday 07:00 UTC | Scrape one coherent GIS release → S3 → atomic publish → validate |
| `geo_enrichment` | Manual / on demand | Fetch one geo reference release → S3 → publish → validate |
| `full_refresh` | Manual | Run the current release pipelines across all datasets |

## S3 Layout

```
raw/dld/{batch_id}/transactions.csv
raw/dld/{batch_id}/rent_contracts.csv
raw/dld/{batch_id}/projects.csv
raw/dld/{batch_id}/buildings.csv
raw/dld/{batch_id}/units.csv
raw/dld/{batch_id}/land_registry.csv
raw/dld/{batch_id}/developers.csv

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

manifests/dld/{batch_id}.json
manifests/dxbi/{release_id}.json
manifests/gis/{release_id}.json
manifests/geo/{release_id}.json
```

Paths are immutable. Release IDs default to `YYYY-MM-DDTHH-MM-SSZ`.

## Code Layout

```text
etl/core            # shared release, registry, load, validation logic
etl/sources         # source-local assets and scraper code
etl/orchestration   # Dagster jobs and schedules
etl/resources       # infra clients
etl/scripts         # operator tooling
```

## Environment Variables

See `.env.example` for the full list. Key groups:

- `DAGSTER_POSTGRES_URL` — Dagster metadata DB (AWS Postgres)
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_USE_PATH_STYLE`
- `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`, `CLICKHOUSE_DATABASE`
- `DLD_BASE_URL`, `GIS_BASE_URL` — source configuration
- `GEO_BUILDINGS_URL` — geo release source URL when enabled

## Replacing the VPS

```bash
# On a new VPS with Docker installed:
git clone <repo>
cd etl
cp .env.example .env && vi .env   # fill credentials
docker compose up -d
```

## Scripts

```bash
python -m etl.scripts.doctor          # check S3 / ClickHouse / Postgres connectivity
python -m etl.scripts.run_local --job dld_ingest
python -m etl.scripts.run_local --job dxbi_ingest
python -m etl.scripts.run_local --job gis_ingest --release-id 2026-03-15T07-00-00Z
python -m etl.scripts.backfill --dataset dld --release-id 2026-03-13T06-00-00Z
```
