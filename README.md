# Vitevue ETL

Dagster OSS orchestration for DLD and GIS batch ingestion into ClickHouse.

## Architecture

```
Hetzner VPS (stateless)          AWS
─────────────────────────        ────────────────────────────────────
Dagster webserver (Dagit)   →    S3 (raw files + manifests)
Dagster daemon              →    Postgres (Dagster metadata)
ETL code (this repo)        →    ClickHouse (analytics tables)
```

Raw data always lands in S3 first. ClickHouse loads directly from S3 via `s3(...)`.
No durable state lives on the VPS.

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

## Pipelines

| Job | Trigger | What it does |
|-----|---------|--------------|
| `dld_ingest` | Daily 06:00 UTC | Fetch DLD CSVs → S3 → ClickHouse → validate |
| `gis_ingest` | Weekly Monday 07:00 UTC | Scrape DDA plots → S3 → ClickHouse → validate |
| `geo_enrichment` | Manual / on demand | Fetch coordinates + polygons → S3 → ClickHouse |
| `full_refresh` | Manual | Run all pipelines in dependency order |

## S3 Layout

```
raw/dld/{batch_id}/transactions.csv
raw/dld/{batch_id}/rent_contracts.csv
raw/dld/{batch_id}/projects.csv
raw/dld/{batch_id}/buildings.csv
raw/dld/{batch_id}/units.csv
raw/dld/{batch_id}/land_registry.csv
raw/dld/{batch_id}/developers.csv

raw/gis/{run_id}/dda_plots.csv
raw/geo/{run_id}/building_coordinates.csv
raw/geo/{run_id}/project_polygons.csv

manifests/dld/{batch_id}.json
manifests/gis/{run_id}.json
manifests/geo/{run_id}.json
```

Paths are immutable. `batch_id` / `run_id` default to `YYYY-MM-DDTHH-MM-SSZ`.

## Environment Variables

See `.env.example` for the full list. Key groups:

- `DAGSTER_POSTGRES_URL` — Dagster metadata DB (AWS Postgres)
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET`
- `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`, `CLICKHOUSE_DATABASE`
- `DLD_BASE_URL`, `GIS_BASE_URL` — source credentials (fill in when available)

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
python -m etl.scripts.backfill --dataset dld --batch-id 2026-03-13T06-00-00Z
```
