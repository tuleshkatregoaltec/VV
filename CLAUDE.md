# CLAUDE

## Active Package

The active runtime package in this repo is `holocron`.

- New work should go into `holocron/`

## Development Workflow

Prefer the repo `justfile` for routine development and environment setup instead of ad hoc command sequences.

- List available commands: `just --list`
- Install Python dependencies: `just sync`
- Run the standard verification pass: `just check`
- Prepare a local env file: `just env local`
- Start the local stack: `just up local`
- Stop the local stack: `just down local`

Use raw `uv`, `ruff`, `pytest`, or `docker compose` commands when you need something the `justfile` does not already cover.

## VPS Workflow

For replication or deploy work on a VPS, prefer the repo recipes:

- `just env prod`
- `just up prod`
- `just down prod`
- `just logs prod`
- `just deploy`

The base `docker-compose.yml` is intended to be VPS-safe and should not depend on bind mounts. Local-only overrides belong in `docker-compose.local.yml`.

## Source Layout

Each source should live under `holocron/sources/<source>/`:

- `source.py` contains the declarative source contract
- `extract.py` normally contains the source-local extraction logic

Keep source-specific logic local to the source package. Do not reintroduce a shared top-level scraper registry.
