# ViteVue ETL Tool (naive_insert)

Run-based ETL pipeline with S3 integration for immutable data storage and PK-only diffing.

## Overview

This ETL tool processes Dubai real estate data from CSV files and loads them into PostgreSQL using high-performance COPY operations. It features:

- **Immutable S3 runs** - Each ETL run is archived with full audit trail
- **PK-only diffing** - Efficient incremental loads using primary key caching
- **Synchronous boto3** - Simple, reliable S3 operations
- **Hash verification** - Guaranteed data integrity
- **Manifest-based state** - Single source of truth for current data

## Usage

### From S3 Sessions

Process uploaded chunks from S3:

```bash
cd backend
uv run python -m scripts.naive_insert session_abc session_def
```

### From Local Directory

Process local CSV files (useful for testing):

```bash
cd backend
uv run python -m scripts.naive_insert --local /path/to/data/current
```

### Options

```
--table, -t TABLE     Process specific table(s) only
--full-refresh, -f    Ignore previous data, recreate schema
--dry-run             Simulate without writing to database
--local, -l DIR       Use local directory instead of S3
```

### Examples

```bash
# Full refresh with schema recreation
uv run python -m scripts.naive_insert session_abc --full-refresh

# Process only transactions table
uv run python -m scripts.naive_insert session_abc --table transactions

# Dry run to preview changes
uv run python -m scripts.naive_insert session_abc --dry-run

# Test with local data
uv run python -m scripts.naive_insert --local ../data/current --full-refresh
```

## Environment Variables

Copy `.env.example` to `backend/.env` and configure:

```bash
# S3/R2 Configuration
ETL_S3_ENDPOINT_URL=https://xxx.r2.cloudflarestorage.com
ETL_S3_ACCESS_KEY_ID=your_access_key
ETL_S3_SECRET_ACCESS_KEY=your_secret_key
ETL_S3_BUCKET_NAME=vitevue-data
ETL_S3_REGION=auto

# Database
DATABASE_URL=postgresql://user:pass@host:5432/analytics
```

## S3 Structure

```
s3://{bucket}/
├── etl/
│   ├── uploads/{session_id}/     # Temporary chunk storage
│   │   ├── chunk_0001
│   │   ├── chunk_0002
│   │   └── metadata.json
│   │
│   ├── runs/{run_id}/            # Immutable run archives
│   │   ├── datasets/             # Assembled CSVs
│   │   │   ├── Transactions.csv
│   │   │   └── ...
│   │   ├── pks/                  # PK caches
│   │   │   ├── transactions.pks
│   │   │   └── ...
│   │   └── run_metadata.json
│   │
│   └── manifests/
│       └── latest.json           # Current production run
```

## Processing Order

Tables are processed in dependency order:

1. `property_types` (lookup)
2. `property_sub_types` (lookup)
3. `transaction_groups`
4. `areas`
5. `transaction_procedures`
6. `master_projects` (lookup)
7. `developers`
8. `projects`
9. `land_registry`
10. `buildings`
11. `units`
12. `transactions`
13. `rent_contracts`

## Project Name Enhancement

English project names (`project_name_en`) are extracted from `Units.csv` and `Buildings.csv` and merged into the projects table during ETL. The supply endpoints return English names with Arabic fallback.

## Architecture

```
naive_insert/
├── __init__.py          # Package marker
├── __main__.py          # CLI entry point
├── runner.py            # Main orchestrator
├── config.py            # Table configs
├── transformers.py      # Polars type casting
├── differ.py            # PK diffing utilities
├── upserter.py          # Database COPY operations
├── s3_client.py         # Synchronous S3 client
├── assembler.py         # Chunk assembly
├── manifest.py          # Run management
├── project_names.py     # English name cache
├── utils.py             # Shared utilities
├── .env.example         # Environment template
└── README.md            # This file
```

## Rollback

To rollback to a previous run:

```bash
# 1. Identify the good run
GOOD_RUN="20260117_100000_e5f6g7h8"

# 2. Update manifest
echo '{"current_run_id": "'$GOOD_RUN'", "updated_at": "'$(date -Iseconds)'"}' | \
  aws s3 cp - s3://bucket/etl/manifests/latest.json

# 3. (Optional) Delete bad run
aws s3 rm --recursive s3://bucket/etl/runs/$BAD_RUN/
```
