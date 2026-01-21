# ClickHouse ETL Pipeline

Smart diff-based ETL pipeline for loading ViteVue property data into ClickHouse.

## Overview

This ETL pipeline implements efficient incremental loading using hash-based change detection. Only changed or new rows are uploaded, dramatically reducing data transfer and processing time.

### Key Features

- **Smart Diff**: Only uploads changed rows using sipHash64 comparison
- **Idempotent**: Running twice with same data is fast (skips unchanged rows)
- **Deletion Tracking**: Marks missing rows with `is_deleted` flag
- **Rollback Safety**: Every ETL run has a unique `etl_run_id` for data versioning
- **Schema Optimized**: Tables designed for optimal query performance
- **Project Name Enrichment**: Automatically enriches project names from Units/Buildings CSVs

## Architecture

### Pipeline Flow

```
1. Download & Assemble CSVs from S3
   └─> Fetch chunks from etl/uploads/{session_id}/
   └─> Verify file integrity with SHA256

2. Build Project Name Cache
   └─> Scan Units.csv and Buildings.csv for English project names

3. For Each Table:
   a. Fetch current state from ClickHouse (primary_key → row_hash)
   b. Stream CSV and compute hash for each row
   c. Compare hashes - only keep changed/new rows
   d. Transform: type conversions, enrichment, bucket computation
   e. Load: batch insert changed rows to ClickHouse
   f. Detect deletions: rows in DB but not in CSV
   g. Insert deletion markers (is_deleted = 1)

4. Complete
```

### Module Structure

```
chETL/
├── __init__.py          # Package exports
├── __main__.py          # CLI entry point
├── config.py            # Table configs, connection settings
├── s3.py                # S3 download and assembly
├── hasher.py            # sipHash64 computation
├── differ.py            # Smart diff logic
├── transformer.py       # Type conversions, enrichment, buckets
├── loader.py            # ClickHouse batch insert
├── runner.py            # Main orchestration
└── schemas.sql          # CREATE TABLE statements
```

## Usage

### Prerequisites

1. ClickHouse instance running
2. Environment variables configured (see `.env.example`)
3. Upload session with CSVs in S3

### Running the ETL

```bash
# Basic usage (downloads from S3, uses env vars for ClickHouse connection)
python -m backend.scripts.chETL <session_id>

# Local mode - read CSVs from local directory (skips S3 download)
python -m backend.scripts.chETL <session_id> \
  --local-csv-dir /path/to/csvs

# With custom ClickHouse connection
python -m backend.scripts.chETL <session_id> \
  --ch-host clickhouse.example.com \
  --ch-port 9000 \
  --ch-user default \
  --ch-password secret \
  --ch-database vitevue

# With custom work directory
python -m backend.scripts.chETL <session_id> \
  --work-dir /data/etl

# Verbose logging
python -m backend.scripts.chETL <session_id> -v

# Local mode with verbose logging
python -m backend.scripts.chETL dummy-session-id \
  --local-csv-dir ./data/csvs \
  -v
```

### Local Development Mode

For local development and testing, you can skip S3 download and read CSVs directly from a local directory:

```bash
# Prepare your CSVs in a directory
mkdir -p ./data/csvs
cp /path/to/*.csv ./data/csvs/

# Run ETL in local mode
python -m backend.scripts.chETL dummy-session-id \
  --local-csv-dir ./data/csvs \
  -v
```

**Required CSV files in local directory**:
- `Developers.csv`
- `Areas.csv`
- `Projects.csv`
- `LandRegistry.csv`
- `Buildings.csv`
- `Units.csv`
- `Transactions.csv`
- `RentContracts.csv`

**Note**: When using `--local-csv-dir`, the session_id is only used for the ETL run_id and doesn't need to be a valid S3 session.

### Environment Variables

Add to `backend/.env`:

```bash
# ClickHouse Connection
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=9000
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=
CLICKHOUSE_DB=default

# S3 Configuration (only needed for S3 mode, not for --local-csv-dir)
S3_BUCKET=vitevue-data
S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
```

### Initial Setup

1. Create ClickHouse tables:

```bash
clickhouse-client < backend/scripts/chETL/schemas.sql
```

2. Run first ETL (full load):

```bash
python -m backend.scripts.chETL abc-123-session-id
```

3. Subsequent runs will be incremental (only changed data).

## Schema Design

### Table Overview

1. **ch_transactions** - Property sales transactions
2. **ch_rent_contracts** - Rental contracts (Ejari)
3. **ch_developers** - Developer directory
4. **ch_projects** - Projects with status, timeline, composition
5. **ch_buildings** - Buildings with facility counts
6. **ch_units** - Individual units with specs
7. **ch_land_registry** - Land parcels
8. **ch_areas** - Geographic areas

### Key Design Decisions

**Golden Path Optimization**: ORDER BY optimized for most common query pattern:
- Transactions: `(property_usage_en, instance_date, transaction_id)`
- Rent Contracts: `(property_usage_en, contract_start_date, contract_id, line_number)`

**LowCardinality**: Applied to dropdown columns for instant `SELECT DISTINCT` queries:
- `property_type_en`, `property_usage_en`, `master_project_en`, etc.

**ReplacingMergeTree**: Automatic deduplication based on `etl_inserted_at`:
- Keeps latest version of each primary key
- Use `FINAL` in queries to get deduplicated view

**Projections**: Optimize non-key column filtering:
- Projects: `(developer_id, area_id, is_free_hold, project_id)`
- Buildings: `(project_number, property_usage_en, building_id)`
- Units: `(project_number, building_id, rooms_en, unit_id)`

**Pre-computed Buckets**: Analytics UI buckets stored in DB:
- `price_bucket`, `area_bucket`, `price_sqft_bucket`

### Change Detection

Every row has:
- `row_hash` (UInt64): sipHash64 of critical columns
- `etl_run_id` (String): UUID of ETL run that created/updated this row
- `etl_inserted_at` (DateTime): Timestamp of insert
- `is_deleted` (UInt8): Soft delete flag (0 = active, 1 = deleted)

Smart diff algorithm:
1. Fetch current state: `SELECT primary_key, row_hash FROM table FINAL WHERE is_deleted = 0`
2. For each CSV row: compute hash, compare with current state
3. Only insert if hash differs or row is new
4. Mark missing rows with `is_deleted = 1`

## Performance Characteristics

### ETL Performance

For 2M transactions with 5% change rate (100K changed rows):

- **Fetch current state**: ~3 seconds (2M rows × 16 bytes = 32MB)
- **Stream & diff CSV**: ~30 seconds (parse 2M rows, 95% skipped)
- **Insert changes**: ~5 seconds (100K rows in batches)
- **Total**: ~40 seconds

Memory usage: ~50MB

### Query Performance

**Filter dropdowns** (LowCardinality):
```sql
SELECT DISTINCT property_type_en FROM ch_transactions
WHERE property_usage_en = 'Residential';
```
Expected: <10ms

**Analytics aggregation** (Golden Path):
```sql
SELECT count(), sum(actual_worth), avg(actual_worth)
FROM ch_transactions
WHERE property_usage_en = 'Residential'
  AND instance_date BETWEEN '2024-01-01' AND '2024-12-31';
```
Expected: <50ms

**Attribute filtering** (with projection):
```sql
SELECT * FROM ch_projects
WHERE developer_id = 42 AND is_free_hold = 1;
```
Expected: <20ms

## Table Processing Order

Tables are processed in dependency order:

1. `developers` (independent)
2. `areas` (independent)
3. `projects` (depends on: developers, areas)
4. `land_registry` (depends on: areas)
5. `buildings` (depends on: projects, land_registry)
6. `units` (depends on: projects, buildings)
7. `transactions` (depends on: areas for enrichment)
8. `rent_contracts` (depends on: areas for enrichment)

## Data Transformations

### Type Conversions

- **Dates**: Multiple format support (`%d-%m-%Y`, `%d/%m/%Y`, `%Y-%m-%d`)
- **Decimals**: Precision handling for currency and measurements
- **Booleans**: Converted to UInt8 (0/1)
- **Integers**: Safe parsing with null handling

### Enrichment

**Project Names**: Projects.csv only has Arabic names. English names enriched from:
- Units.csv: `project_number → project_name_en`
- Buildings.csv: `project_number → project_name_en`

Cache is built at start of ETL run and used for all tables.

### Bucket Computation

Pre-computed for analytics UI:

**Price Buckets**:
- <500K, 500K-1M, 1M-2M, 2M-5M, 5M-10M, 10M-25M, >25M

**Area Buckets** (sq.m):
- <50, 50-100, 100-200, 200-500, 500-1K, >1K

**Price per Sq.m Buckets**:
- <10K, 10K-15K, 15K-20K, 20K-25K, 25K-30K, >30K

## Rollback & Recovery

### ETL Run Tracking

Every row has `etl_run_id` (UUID). To query data as of a specific run:

```sql
-- Exclude rows from a failed run
SELECT * FROM ch_transactions
WHERE etl_run_id != 'bad-run-uuid'
  AND is_deleted = 0;
```

### Deletion Recovery

If a row is incorrectly marked as deleted, insert a new version with `is_deleted = 0`:

```sql
INSERT INTO ch_transactions (
  transaction_id, row_hash, etl_run_id, is_deleted, ...
) VALUES (
  'TXN123', <hash>, '<new-run-id>', 0, ...
);
```

ReplacingMergeTree will keep the latest version (undeleted).

## Troubleshooting

### Common Issues

**Hash mismatch during assembly**:
- Chunks may be corrupted during upload
- Check S3 metadata.json for expected_hash
- Re-run upload if needed

**Missing project names**:
- Ensure Units.csv and Buildings.csv are processed first
- Check that project_number matches between CSVs
- Verify project_name_en exists in source data

**ClickHouse connection timeout**:
- Check CLICKHOUSE_HOST and CLICKHOUSE_PORT
- Verify network connectivity
- Increase timeout in clickhouse-connect client

**Out of memory**:
- Reduce batch_size in loader.py
- Process tables individually instead of full pipeline
- Increase available RAM

## Future Enhancements

- [ ] Parallel table processing (independent tables)
- [ ] Incremental project name cache (persist between runs)
- [ ] Retry logic for transient failures
- [ ] Metrics export (Prometheus)
- [ ] Data quality checks (schema validation, constraint checks)
- [ ] Automatic OPTIMIZE FINAL after ETL
- [ ] Support for streaming inserts (no CSV download)
