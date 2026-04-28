# Holocron

Holocron is being rebuilt from first principles as a small connector platform.

Current scope:

- source contracts
- immutable raw release manifests
- shared S3 and ClickHouse clients
- source registry
- thin Dagster definitions

`holocron-v1/` holds the previous implementation. New work goes into `holocron/`.

## Architecture

The intended flow is:

```text
source connector
  -> immutable raw release in S3
  -> bronze ClickHouse tables
  -> silver ClickHouse tables
  -> optional domain outputs
```

Dagster is the control plane around those assets, not the place where source logic lives.

## Setup

The repo now ships with a `justfile` so the local and VPS workflows stay aligned.

Common commands:

- `just sync` installs Python dependencies with `uv`
- `just check` runs format, lint, and tests
- `just news-sync` runs the direct platform news sync
- `just env-local` creates `.env.local` from `.env.local.example`
- `just env-vps` creates `.env` from `.env.example`
- `just local-up` starts the full local stack with Postgres, ClickHouse, and MinIO
- `just vps-up` starts the VPS stack against the services configured in `.env`
- `just deploy` pulls the latest code and rebuilds the VPS stack

## VPS Flow

The base `docker-compose.yml` is now production-oriented:

- it builds the application image
- it does not rely on bind mounts
- it reads runtime configuration from `.env`

Suggested VPS bootstrap:

1. Install `docker`, `docker compose`, and `just`.
2. Clone the repo on the VPS.
3. Run `just env-vps` and fill in `.env`.
4. Run `just vps-up`.

For local development, use `docker-compose.local.yml` through `just local-up`; that override adds bind mounts and local infra services on top of the base stack.

## Package Layout

```text
holocron/
  contracts.py
  definitions.py
  platform/
  sources/
  orchestration/
  domain/
```

- `contracts.py` defines the small core types.
- `platform/` holds shared infra.
- `sources/` holds the source registry and will hold source packages.
- `orchestration/` exposes Dagster definitions.
- `domain/` is reserved for cross-source outputs.

## Status

There are no production sources in the new package yet. The current pass only establishes the minimal core infrastructure so sources can be added one by one.

## News Sync

Holocron now includes a thin direct news sync at `holocron.domain.news`.

Required configuration:

- `PLATFORM_POSTGRES_URL` for direct writes to `vitevue-platform`'s database
- `NEWS_FEED_URLS` with one feed URL per line, or pass `--feed-url`

Optional configuration:

- `S3_PUBLIC_URL_BASE` to mirror thumbnails into object storage and write public CDN URLs
- `NEWS_THUMBNAIL_PREFIX` to override the object-storage prefix

Example:

```bash
just news-sync
just news-sync --feed-url https://meconstructionnews.com/feed/atom
just news-sync --skip-thumbnail-upload
```
