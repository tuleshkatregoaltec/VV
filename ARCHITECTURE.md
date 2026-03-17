# Architecture

## Release Model

Each ingestion run stages files locally first, then promotes them into a durable raw release.

The staged local release and the raw S3 release both use typed manifests carrying:

- dataset
- release ID
- mode
- source
- checksums
- row counts

## Publish Model

Raw data lands in object storage first. ClickHouse publishing depends on the table strategy declared by each table:

- `full_swap`: load to staging, then `EXCHANGE TABLES`
- `append`: load to staging, then append into target

This keeps raw history immutable while letting each dataset publish according to its own semantics.

## Dagster Model

Holocron uses Dagster to model durable warehouse outputs:

- one local release asset per source
- one raw release asset per source
- one asset per final ClickHouse table
- one cleanup job per source for removing staged local files by release ID
- asset checks for data quality and source-specific assertions

Most Dagster assets are generated from source metadata rather than hand-written per-table
orchestration modules. Hand-written downstream assets are reserved for derived tables such as
`pf_location_hierarchy`.

## Source Contract

Every source is defined locally under `holocron/sources/<source>/`.

`source.py` owns:

- source metadata
- table declarations
- config schema and defaults
- optional extra checks
- the extract function for simple sources that have not been split yet

`extract.py` normally owns:

- source-specific scraping or download logic
- writing one or more CSV files for the release

## Code Layout

- `holocron/assets`: handwritten downstream assets derived from published tables
- `holocron/framework`: release models, validation, Dagster factory, storage helpers
- `holocron/resources`: S3, ClickHouse, and HTTP resources
- `holocron/sources`: source-local contracts and extraction code
- `holocron/scripts`: operator tooling

## Adding a Source

Adding a new source should normally require:

1. adding `holocron/sources/<name>/source.py`
2. adding `holocron/sources/<name>/extract.py`
3. registering the source in `holocron/sources/__init__.py`
4. optionally adding new ClickHouse tables in `holocron/lib/sql/clickhouse_schema.sql`

Some older/simple sources still keep extraction inline in `source.py`, but new source-specific
logic should remain local to the source package rather than being reintroduced through shared
top-level registries or orchestration modules.
