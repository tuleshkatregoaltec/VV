# Holocron

Holocron is being rebuilt from first principles as a small connector platform.

Current scope:

- source contracts
- immutable raw release manifests
- shared S3 and ClickHouse clients
- source registry
- thin Dagster definitions

## Architecture

The intended flow is:

```text
source connector
  -> immutable raw release in S3
  -> bronze ClickHouse tables
  -> optional domain outputs
```

Dagster is the control plane around those assets, not the place where source logic lives.

## Setup

The repo now ships with a `justfile` so the local and VPS workflows stay aligned.

Common commands:

- `just sync` installs Python dependencies with `uv`
- `just check` runs format, lint, and tests
- `just news-sync` runs the legacy direct platform news sync
- `just env local` creates `.env.local` from `.env.local.example`
- `just env prod` writes `.env` from Bitwarden Secrets Manager
- `just env prod-manual` creates `.env` from `.env.example`
- `just env r2` creates `.env.r2-test` from `.env.r2.example`
- `just up <target>` starts a stack; targets are `local`, `prod`, or `r2`
- `just down <target>`, `just ps <target>`, and `just logs <target>` operate a stack
- `just deploy` pulls the latest code and rebuilds the VPS stack

## VPS Flow

The production compose file is intentionally Dagster-only. A VPS should be disposable:

- raw releases and manifests live in AWS S3
- bronze warehouse tables live in external ClickHouse
- Dagster run/event/schedule metadata lives in external Postgres
- the VPS runs only `dagster-webserver` and `dagster-daemon`

Fresh VPS bootstrap:

1. Install `docker`, Docker Compose, `git`, and `just`.
2. Clone the repo.
3. Export `BWS_ACCESS_TOKEN` and `BWS_PROJECT_ID` for the Holocron Bitwarden
   Secrets Manager project.
4. Run `just env prod`.
5. Run `just doctor prod`.
6. Run `just up prod`.

For manual setup without Bitwarden, run `just env prod-manual` and fill in `.env` from
`.env.example`.

After that, Dagster is available on `http://<vps-ip>:3000` unless `DAGSTER_PORT`
is changed.

To move VPSs, stop the old machine, clone the same repo on the new machine, put
the same Bitwarden machine account token and project id in the shell, then run
`just env prod --force` and `just up prod`. No ClickHouse or S3 data is
stored on the VPS.

For local development, use `docker-compose.local.yml` through `just up local`;
that override adds bind mounts plus local Postgres, ClickHouse, and MinIO.

### Temporary R2 Raw Test

Before production S3, ClickHouse, and external Dagster Postgres are ready, you
can smoke-test raw extraction on a VPS with an R2 bucket and temporary local
Postgres for Dagster metadata:

```bash
just env r2
# fill .env.r2-test with R2 credentials and any source credentials needed
just up r2
```

If `BWS_ACCESS_TOKEN` and `BWS_PROJECT_ID` are exported, `just env r2` pulls
`.env.r2-test` from Bitwarden instead. The R2 Bitwarden values should include:

```text
DAGSTER_POSTGRES_URL=postgresql://dagster:dagster@postgres:5432/dagster
AWS_REGION=auto
S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
S3_USE_PATH_STYLE=true
```

This starts only Dagster plus local Postgres. Raw releases and manifests are
written to R2. Do not run bronze jobs in this mode unless `.env.r2-test` has
real ClickHouse values.

Useful commands:

```bash
just ps r2
just logs r2
just down r2
```

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

## Documentation

Raw ingestion standards and operational notes live under `docs/`:

- `docs/ingestion-patterns.md` defines chunked raw scrapes, asset hydration,
  R2 manifests, checkpoints, and source naming guidance.
- `docs/logging.md` defines common progress and error logging expectations.
- `docs/scraping-investigation.md` is the playbook for new or fragile scrapers.
- `docs/runbooks/long-running-jobs.md` covers overnight job launch and status
  checks.

Each active source package has a short `holocron/sources/<source>/README.md`
covering raw files, config knobs, R2 layout, and current limitations. Bronze
lineage docs are intentionally deferred until the raw source set is stable.

## Status

The current MVP focus is:

- source-local raw extraction into immutable releases
- bronze loading contracts per source
- thin Dagster orchestration around raw and bronze only

`dda_planning_layers` is now wired end-to-end in the active harness (raw extraction + bronze load).

Silver layers are intentionally deferred until a few sources are producing real
raw and bronze data and the cleaning requirements are clearer.

## News Sync

Holocron includes a raw-first news feed source at `holocron/sources/news_feeds/`.
It polls RSS/Atom feeds, archives feed/article rows to R2, mirrors thumbnails to
stable media keys, then upserts recent frontend-ready rows into platform
Postgres `news_articles`.

Required configuration:

- `PLATFORM_POSTGRES_URL` for writes to `vitevue-platform`'s database

Feed configuration:

- Holocron ships with a curated default RSS/Atom list for property,
  construction, logistics, Gulf business, MEED, World Property Journal, and
  Bloomberg business feeds.
- `NEWS_FEED_URLS` with one feed URL per line, `feed_urls`, or
  `feed_urls_file` can be used to replace the curated defaults for a run.

Optional configuration:

- `S3_PUBLIC_URL_BASE` to publish mirrored thumbnail CDN URLs
- `S3_BUCKET`/R2 settings for raw manifests and thumbnail media

Dagster jobs:

- `news_feeds_poll_and_publish`: 15-minute schedule, stopped by default until
  feed URLs, R2, and Postgres are configured.
- `news_publish_backfill`: hydrates thumbnails and publishes recent raw articles
  to Postgres, defaulting to a 3-day lookback.
- `news_thumbnail_assets_backfill`: thumbnail-only backfill.
- `news_feeds_manual_poll`: raw feed polling only.

Examples:

```bash
uv run dagster job execute -m holocron.definitions -j news_publish_backfill
uv run dagster job execute -m holocron.definitions -j news_feeds_poll_and_publish
```

The older direct sync remains available for quick local checks:

```bash
just news-sync
just news-sync --feed-url https://meconstructionnews.com/feed/atom
just news-sync --skip-thumbnail-upload
```
