# Source Recovery Plan

## Context

- `vitevue-platform` currently serves sales and rental data directly from `ch_transactions` and `ch_rent_contracts`.
- `holocron/` is the new connector platform, but today only `holocron/sources/dxbi/` exists in the new package.
- Most legacy extraction logic still lives in `holocron-v1/`.
- `finder/` contains an independent RSS/news ingestion script that uploads articles into `vitevue-platform` through `/api/v1/upload/news/article`.
- For the Holocron migration, direct database writes should be preferred over calling the platform upload endpoint.

## What The Platform Needs Right Now

The immediate platform dependency is not "perfect history", it is enough fresh coverage to keep:

- transaction search working
- transaction analytics working
- rent contract search working
- project analytics from recent sales/rents working
- news ingestion moving without manual one-off scripts

That means the fastest recovery path is:

1. restore at least one usable sales source
2. restore at least one usable rental source
3. move news into Holocron so it becomes scheduled ETL rather than a sidecar script
4. treat deep historical backfill as a second phase

## Current Source Inventory

### High confidence quick wins

#### 1. Finder news feed ingestion

- `finder/finder/parse.py` already fetches RSS/Atom feeds, uploads thumbnails to object storage, and posts articles into `vitevue-platform`.
- This is the cleanest quick win because it does not depend on captcha-heavy real-estate search flows.
- The current logic is operationally useful, but it lives in the wrong repo and bypasses Holocron scheduling and release tracking.

Recommended action:

- Port the feed-fetch logic into `holocron/` as a small source package, likely `holocron/sources/news_feeds/`.
- Keep the feed extraction step separate from the downstream delivery step.
- Raw release output should be immutable feed/article payloads first.
- A second step can publish deduplicated articles directly into the platform database.

Why this first:

- low anti-bot risk
- immediate visible product value
- proves the new Holocron architecture can own non-tabular ingestion too

#### 2. DDA planning layers

- `holocron-v1/sources/dda/extract.py` uses direct GIS endpoints on `gis.dda.gov.ae`.
- It does not rely on captcha solving.
- It already has retry logic and writes stable CSV outputs.
- This is not transaction data, but it is a dependable supporting source for feasibility, land intelligence, and enrichment.

Recommended action:

- Keep this source in the working set.
- Migrate it from `holocron-v1/` into the new `holocron/` package when transaction recovery is not blocked by it.

### Likely usable with moderate effort

#### 3. Property Finder transaction coverage

- `holocron-v1/sources/pf_transactions/` does not use browser automation or captcha solving.
- It relies on:
  - sitemap discovery
  - `__NEXT_DATA__` extraction from listing pages
  - Next.js JSON endpoints for transaction pages
- The code is explicitly designed for partial public coverage and records a `coverage.csv` table so gaps are measurable.

Why it matters:

- It is a pragmatic fallback when official DLD/Dubai Pulse access is gone.
- It can likely recover at least part of the last 12 months without requiring a solver.

Main caveat:

- This is not a full-market authoritative dataset. It is public-site coverage shaped by Property Finder's visible transaction hierarchy and page caps.

Recommended action:

- Smoke-test `pf_transactions` first among the transaction alternatives.
- If it still resolves `buildId` and `_next/data` payloads, treat it as the fastest external transaction stopgap.

#### 4. DXBI transactions

- Legacy source: `holocron-v1/sources/dxbi_transactions/`
- New source: `holocron/sources/dxbi/`
- Both approaches rely on browser-backed extraction of DXB Interact pages.
- The new source supports:
  - date slicing
  - optional storage state
  - optional 2captcha support
- The legacy source can scrape sale and rental history tables from supplied project pages.

Why it is still viable:

- DXBI already maps closely to the product's transaction/rental use cases.
- The new Holocron source is the most aligned with the future architecture.

Main caveat:

- Cloudflare clearance is still an operational dependency.
- The extractor explicitly fails if a valid browser session cannot obtain `cf_clearance`.

Recommended action:

- Keep DXBI in the active set, but do not treat it as the first "quick win".
- Use it after PF smoke tests, or in parallel where a storage state / real Chrome session is already available on the Holocron VM.

### Low confidence / blocked

#### 5. Bayut transactions

- `holocron-v1/sources/bayut/extract.py` contains explicit hCaptcha detection and 2captcha solving.
- You already called out the current blocker correctly: hCaptcha is the problem source.
- There is historical backfill tooling in `holocron-v1/scripts/backfill_bayut.py`, but it only matters if the upstream challenge can be cleared reliably.

Recommended action:

- De-prioritize Bayut as a quick win.
- Keep it as an R&D track, not as the primary recovery vehicle.

#### 6. Old DLD Dubai Pulse bulk downloads

- `holocron-v1/sources/dld/` targets `www.dubaipulse.gov.ae` dataset pages and CKAN-style API fallbacks.
- This path was appropriate for the old open-data dumps, but it is no longer the dependable primary source.
- The current public DLD pages now explicitly redirect previous-year needs back to Dubai Pulse.
- Current operating reality: the DLD public flow is available, but Dubai Pulse is unavailable and older historical coverage is blocked.

External note:

- On 28 April 2026, the public DLD pages at:
  - `https://dubailand.gov.ae/en/eservices/real-estate-transaction/`
  - `https://dubailand.gov.ae/en/open-data/real-estate-data/`
  state: "For previous year data kindly visit Dubai Pulse".
- The open-data page also exposes transaction and rent search forms plus CSV download affordances, but shows captcha validation in the public HTML.

Recommended action:

- Consider the old DLD bulk pipeline broken for planning purposes.
- Do not treat the current DLD public flow as a historical replacement for Dubai Pulse.
- Use the current DLD flow only if a current-year or otherwise bounded public-window pull is enough for the immediate win.
- Do not invest more time here for older history unless Dubai Pulse access is restored or a new official endpoint is discovered.

## Best Near-Term Transaction Strategy

If the goal is "enough recent data to keep the product alive", the recommended order is:

1. Smoke-test `pf_transactions` for last-12-month coverage.
2. Use the current DLD public flow only if current-year/public-window data is enough for the immediate need.
3. Keep `dxbi_transactions` as the next fallback, especially for project-level history where DXBI pages are known.
4. Defer Bayut until hCaptcha handling is materially improved.

## Finder Integration Plan

The current `finder/` implementation should move into Holocron, but not as a direct copy-paste.

Current operating decisions:

- Holocron should write news directly to the platform database rather than calling the upload API.
- Holocron does not need to clear the platform Redis cache after inserts in this pass.
- Database-level uniqueness enforcement for article URL is deferred for now.

Recommended shape:

### Phase 1

- Create a Holocron source for feed extraction only.
- Inputs:
  - one or more feed URLs
  - optional source label
- Raw output:
  - article metadata
  - thumbnail source URLs
  - normalized publish timestamps

### Phase 2

- Add a downstream delivery step that:
  - uploads thumbnails to object storage
  - writes deduplicated article rows directly into the platform database
  - records per-article delivery state

Why split extraction and delivery:

- raw releases stay immutable
- failed API delivery can be retried without re-scraping feeds
- source lineage remains inside Holocron instead of being hidden in ad hoc scripts
- ETL no longer depends on an application upload endpoint for internal system-to-system writes

Recommended implementation detail:

- Add a small Postgres writer in Holocron for the `news_articles` table.
- Keep dedupe keyed on article URL in application logic, matching the current platform behavior.
- Reuse object storage for thumbnails if you want public CDN URLs in the row.
- Treat the database write as an internal sink owned by the same system, not as a public integration boundary.

Accepted tradeoffs for this phase:

- Newly inserted articles may remain invisible through the cached news endpoint for up to the endpoint TTL.
- Duplicate rows are still possible under retries or concurrent writers because URL uniqueness is not yet enforced at the database level.
- Those issues are acceptable for the current recovery phase and should not block migration out of `finder/`.

## Concrete Next Steps

1. Move Finder news ingestion into `holocron/` as the first low-risk quick win.
2. Run a bounded smoke test on `pf_transactions` for `period=1y`.
3. If current-year data is enough, probe the current DLD public export flow with a narrow date range.
4. Keep DXBI as the next recovery path, using storage state or a real Chrome session on the VM.
5. Stop spending quick-win time on Bayut and on DLD / Dubai Pulse for older history until access changes.
