# AGENTS

## Active Package

The active runtime package in this repo is `holocron`.

- New work should go into `holocron/`

## Source Layout

Each source should live under `holocron/sources/<source>/`:

- `source.py` contains the declarative source contract
- `extract.py` normally contains the source-local extraction logic

Keep source-specific logic local to the source package. Do not reintroduce a shared top-level scraper registry.

Handwritten downstream assets that derive new tables from already-published source tables belong in `holocron/assets/`.

## Onboarding Rule

Adding a new source should normally require:

1. a new `holocron/sources/<source>/source.py`
2. a new `holocron/sources/<source>/extract.py`
3. registration in `holocron/sources/__init__.py`
4. optional ClickHouse schema changes in `holocron/lib/sql/clickhouse_schema.sql`

If a change requires edits in many unrelated framework files, the architecture is probably drifting back toward over-engineering.

Small legacy/simple sources may still inline extraction in `source.py`, but new source-specific extraction code should still be split into `extract.py`.

## Dagster Modeling

- Keep one asset per durable ClickHouse table
- Keep one local release asset per source
- Keep one raw release asset per source
- Express data quality as asset checks
- Generate Dagster assets from source metadata rather than hand-writing per-table asset functions, except for clearly downstream derived assets
- Model `SourceSpec.name` as the dataset / operational ingestion unit, not the whole provider
- Use `SourceSpec.provider` for provider-level grouping in Dagster
- Do not couple source ingest jobs to Dagster asset groups; jobs should target the source's explicit asset set

## Naming

- Prefer short, recognizable dataset ids for sources: `pf_locations`, `bay_transactions`, `dxbi_lookups`
- Prefer provider-scoped warehouse table prefixes: `pf_*`, `bay_*`, `dld_*`, `dxbi_*`, `dda_*`
- For DDA planning data, use `dda_*` rather than `gis_*`; GIS is the data type, not the provider

## Tooling

**Task runner:** `just`

- Prefer `just` recipes for the normal dev loop instead of retyping raw commands
- List commands: `just --list`
- Install deps: `just sync`
- Run the full verification pass: `just check`
- Start the local stack: `just local-up`
- Stop the local stack: `just local-down`
- Prepare local env file: `just env-local`

**Package manager:** `uv`

- Install deps: `uv sync`
- Run a command in the venv: `uv run <command>`
- Add a dependency: `uv add <package>`
- Add a dev dependency: `uv add --dev <package>`

**Linting and formatting:** `ruff`

- Format: `uv run ruff format`
- Lint: `uv run ruff check`
- Lint and auto-fix: `uv run ruff check --fix`
- Line length is 100, target is Python 3.11 (see `pyproject.toml`)

**Tests:** `pytest`

- Run all tests: `uv run pytest`
- Run a specific file: `uv run pytest tests/test_holocron_definitions.py`

For VPS-oriented replication and deploy work, prefer the repo recipes such as `just env-vps`, `just vps-up`, and `just deploy`.

## Migration Note

Keep the repo Holocron-only. Do not reintroduce legacy package names or parallel orchestration stacks.
