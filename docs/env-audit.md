# Environment Variable Audit

Date: 2026-06-10

## Scope

This audit covers committed env examples, Pydantic settings, direct
`process.env` / `os.environ` usage, Docker Compose files, and Holocron's
Bitwarden env generation script after importing `holocron/` into the monorepo.

No local secret values were inspected.

## Recommended Canonical Names

Use one canonical name for shared infrastructure, then keep temporary aliases in
code where needed for compatibility.

| Concern | Canonical env vars | Notes |
| --- | --- | --- |
| App Postgres | `DATABASE_URL` | Backend app database. Also used by legacy/import scripts that write app data. |
| Dagster Postgres | `DAGSTER_POSTGRES_URL` | Holocron/Dagster run/event/schedule metadata. Distinct from app Postgres. |
| Pipeline-to-app Postgres | `PLATFORM_POSTGRES_URL` | Holocron writes platform-facing records, currently news, into app Postgres. |
| Redis | `REDIS_URL`, `REDIS_PASSWORD` | Backend-only today. |
| ClickHouse | `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`, `CLICKHOUSE_DATABASE`, `CLICKHOUSE_SECURE` | Prefer `CLICKHOUSE_DATABASE`; keep backend `CLICKHOUSE_DB` as a legacy alias until deploy envs are migrated. |
| Object storage | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_USE_PATH_STYLE`, `S3_PUBLIC_URL_BASE` | Works for AWS S3, R2, and MinIO. Prefer AWS credential names over `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY`. |
| Frontend public API/auth | `PUBLIC_API_BASE_URL`, `PUBLIC_AUTH_BASE_URL` | Browser-exposed, configured by Cloudflare Pages. |

## Current Runtime Owners

### Backend

Backend settings live in `backend/app/config.py`. Required runtime settings
today are:

- App/Postgres: `DATABASE_URL`
- Redis: `REDIS_URL`, `REDIS_PASSWORD`
- Backend URLs/CORS: `FRONTEND_URL`, `ALLOWED_ORIGINS`
- Security: `SESSION_SECRET`, `SERVICE_API_KEY`
- Auth: `AUTH_URL`, `AUTH_SERVICE_ROLE_KEY`
- OpenRouter: `OPENROUTER_API_KEY`, `DEFAULT_CHAT_MODEL`
- Object storage: currently accepts `S3_ENDPOINT_URL` or `AWS_ENDPOINT_URL`,
  `AWS_ACCESS_KEY_ID` or `S3_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` or
  `S3_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME` or `S3_BUCKET`, and `AWS_REGION` or
  `S3_REGION`
- ClickHouse: `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `CLICKHOUSE_USER`,
  `CLICKHOUSE_PASSWORD`, `CLICKHOUSE_DB`
- Stripe: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
  `STRIPE_PRICE_ID_TIER1`, `STRIPE_PRICE_ID_TIER2`,
  `FRONTEND_SUCCESS_URL`, `FRONTEND_CANCEL_URL`

Optional backend settings found in code but initially missing from
`backend/.env.example`:

- `ENVIRONMENT`
- `LOGFIRE_TOKEN`
- `PUBLIC_API_BASE_URL`
- `FIRST_SUPERUSER`
- `FIRST_SUPERUSER_PASSWORD`
- `FIRST_SUPERUSER_RENAME_FROM`
- `FIRST_SUPERUSER_FIRST_NAME`
- `FIRST_SUPERUSER_LAST_NAME`
- `FIRST_SUPERUSER_AVATAR_URL`

Settings with defaults that do not need to appear in every env file:

- `API_V1_STR`
- `PROJECT_NAME`

### Frontend

Frontend uses:

- `PUBLIC_API_BASE_URL`
- `PUBLIC_AUTH_BASE_URL`
- `PUBLIC_POSTHOG_HOST`
- `PUBLIC_POSTHOG_KEY`

`frontend/.env.example` initially declared `PUBLIC_STRIPE_PUBLISHABLE_KEY`, but
no frontend code currently reads it.

### E2E

Playwright uses optional env overrides:

- `PLAYWRIGHT_BASE_URL`
- `PLAYWRIGHT_API_BASE_URL`
- `PLAYWRIGHT_AUTH_BASE_URL`
- `PLAYWRIGHT_INBUCKET_BASE_URL`
- `TEST_EMAIL`
- `TEST_PASSWORD`
- `FIRST_SUPERUSER`
- `FIRST_SUPERUSER_PASSWORD`
- `CI`

There was no committed E2E env example before the initial cleanup.

### Holocron

Holocron settings live in `holocron/holocron/platform/settings.py`, Dagster reads
`DAGSTER_POSTGRES_URL` from `holocron/dagster.yaml`, and
`holocron/scripts/pull-bitwarden-env.sh` defines expected Bitwarden keys.

Required for full Holocron production:

- `DAGSTER_POSTGRES_URL`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `S3_BUCKET`
- `CLICKHOUSE_HOST`
- `CLICKHOUSE_PORT`
- `CLICKHOUSE_USER`
- `CLICKHOUSE_PASSWORD`
- `CLICKHOUSE_DATABASE`
- `CLICKHOUSE_SECURE`

Required for raw-only R2 smoke tests:

- `DAGSTER_POSTGRES_URL`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `S3_BUCKET`

Optional source/publish settings:

- `REELLY_EMAIL`
- `REELLY_PASSWORD`
- `TWOCAPTCHA_API_KEY`
- `CAPTCHA_API_KEY` as a fallback for DXBI CAPTCHA solving, but it is not in
  examples
- `PLATFORM_POSTGRES_URL`
- `NEWS_FEED_URLS`
- `HOLOCRON_SCRATCH_DIR` for DLD Pulse bronze scratch location, but it is not in
  examples

## Initial Problems Found

### Split Names For Shared Infrastructure

- Backend uses `CLICKHOUSE_DB`; Holocron uses `CLICKHOUSE_DATABASE`.
- Backend examples use `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`,
  `S3_BUCKET_NAME`, and `S3_REGION`; Holocron uses `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET`, and `AWS_REGION`.
- Backend scripts accept extra object-storage aliases such as `AWS_BUCKET_NAME`
  and `AWS_BUCKET`, but those aliases are not documented anywhere.

### Declared But Not Used

In `backend/.env.example`:

- `AUTH_ADMIN_EMAIL`
- `AUTH_ADMIN_PASSWORD`
- `SYSTEM_ADMIN_EMAIL`
- `OPENROUTER_BASE_URL`
- `ENTERPRISE_CONTACT_EMAIL`

In `frontend/.env.example`:

- `PUBLIC_STRIPE_PUBLISHABLE_KEY`

In `holocron/scripts/pull-bitwarden-env.sh`:

- `BAYUT_API_KEY`; Bayut sources appear to have been retired.

In `holocron/holocron/platform/settings.py`:

- `R2_ENDPOINT`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`

Those R2-specific names are not in examples. The S3-compatible names already
cover R2 and are used by the examples.

### Used But Missing From Examples

Backend:

- `ENVIRONMENT`
- `LOGFIRE_TOKEN`
- `PUBLIC_API_BASE_URL`
- `FIRST_SUPERUSER`
- `FIRST_SUPERUSER_PASSWORD`
- `FIRST_SUPERUSER_RENAME_FROM`
- `FIRST_SUPERUSER_FIRST_NAME`
- `FIRST_SUPERUSER_LAST_NAME`
- `FIRST_SUPERUSER_AVATAR_URL`

E2E:

- `PLAYWRIGHT_BASE_URL`
- `PLAYWRIGHT_API_BASE_URL`
- `PLAYWRIGHT_AUTH_BASE_URL`
- `PLAYWRIGHT_INBUCKET_BASE_URL`
- `TEST_EMAIL`
- `TEST_PASSWORD`

Holocron:

- `CAPTCHA_API_KEY`
- `HOLOCRON_SCRATCH_DIR`

### ClickHouse Port Ambiguity

Backend runtime clients use `CLICKHOUSE_PORT`, while
`backend/scripts/clickhouse/build_fact_tables.py` uses
`CLICKHOUSE_NATIVE_PORT` with a default of `9001`.

That distinction exists because the app uses HTTP-style ClickHouse clients in
some places and the fact builder uses `clickhouse-driver` over the native port.
It should be documented or the fact builder should be moved to Holocron and
given a clearer env contract.

### News Thumbnail Prefix Drift

Backend treats S3 thumbnail keys as private/proxyable only when they start with:

```text
media/news/thumbnails/
```

Holocron's news asset code and docs also use `media/news/thumbnails`, but the
Holocron env examples and platform setting default currently say:

```text
media/images/news/thumbnails
```

That is likely stale and should be corrected before relying on news thumbnail
publishing across the monorepo.

## Proposed Cleanup Order

1. Update examples and settings to make `CLICKHOUSE_DATABASE`, `S3_BUCKET`, and
   AWS credential names canonical, while keeping backend aliases for the old
   names.
2. Remove stale example keys and stale Bitwarden expected keys.
3. Add missing optional settings to examples with clear comments.
4. Add an E2E env example for Playwright overrides.
5. Fix the news thumbnail prefix examples/default.
6. Move ClickHouse fact/view scripts out of `backend/scripts/clickhouse` before
   doing deeper ClickHouse env cleanup.

## Cleanup Applied

Initial low-risk cleanup on the monorepo import branch:

- Backend accepts canonical `CLICKHOUSE_DATABASE` while retaining legacy
  `CLICKHOUSE_DB` compatibility.
- `backend/.env.example` now prefers `CLICKHOUSE_DATABASE`, `S3_BUCKET`,
  `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_REGION`.
- Removed stale backend example keys:
  `AUTH_ADMIN_EMAIL`, `AUTH_ADMIN_PASSWORD`, `SYSTEM_ADMIN_EMAIL`,
  `OPENROUTER_BASE_URL`, and `ENTERPRISE_CONTACT_EMAIL`.
- Added missing backend example keys for `ENVIRONMENT`, `PUBLIC_API_BASE_URL`,
  `LOGFIRE_TOKEN`, and local bootstrap superuser settings.
- Removed currently unused `PUBLIC_STRIPE_PUBLISHABLE_KEY` from
  `frontend/.env.example`.
- Added `e2e/.env.example` for Playwright overrides.
- Fixed Holocron news thumbnail prefix examples/default to
  `media/news/thumbnails`.
- Removed retired `BAYUT_API_KEY` from Holocron Bitwarden expected keys.

Remaining deliberate non-changes:

- R2-specific Holocron aliases remain in code for now, though examples use the
  S3-compatible names.
- `CLICKHOUSE_NATIVE_PORT` remains undocumented pending migration of
  ClickHouse fact/view scripts out of backend ownership.
