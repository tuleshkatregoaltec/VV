# Analytics DXBI / Compare — PR review (11 October 2026)

## Scope and review decisions

Base: `VV`. The previous #40–#42 PRs are already merged. This branch includes Analytics source isolation, comparison/search/chart fixes, tests, and their shared DXBI normalization prerequisites. Scrapers, ingestion orchestration, transaction-page redesign, exports, pagination changes and source enrichment are excluded.

The initial development diff depended on an uncommitted enrichment table. Review removed that dependency rather than shipping an unfinished enrichment pipeline. The serving query never joins DLD patches. A test deliberately creates a poisoned patch table and DLD-only records to verify they cannot affect ordinary Analytics. DLD remains available in both Upcoming views.

Reviewed: source projections and cohort eligibility; deduplication across provider links and registration identifiers; ambiguous catalogue joins; shared Transaction facet semantics; summary grouping/period anchors; missing-value handling; SQL parameter binding; source-specific caches and authorization; comparison query selection, display precision, chart lifecycle and date alignment; fixtures and rollout dependencies. No external/independent reviewer is claimed.

Shared normalization changes are included because Analytics must use the same identities and labels as Transactions. Cache namespaces for affected transaction lists/facets are included so cached old mappings are not served after rollout. No public API schema, auth guard or tenant-data contract changes.

## Required rollout order

1. Before promoting the backend, apply the single additive ClickHouse schema statement from the repository schema using the authorized migration role:
   `ALTER TABLE dxbi_sales_unit_events ADD COLUMN IF NOT EXISTS dld_transaction_number String DEFAULT '';`
   New table definitions also include the column. Existing rows keep an empty identifier; no identifiers are inferred or source records replaced. The query needs the column to avoid collapsing distinct verified identities.
2. Verify the runtime read-only role can read the existing DXBI sales, rentals and reference tables. Deploy the backend and frontend together. New Analytics cache namespaces exclude combined-source cache results; transaction/facet namespaces exclude old normalized results.
3. Smoke-test DXBI search and a known comparison, including upcoming supply. Ingestion freshness and production concurrency remain separate release checks.

Rollback: restore the previous backend/frontend versions. The added optional identifier String field with an empty default is backward-compatible and should remain; do not drop source data. Clear only affected Analytics/Transactions/filter namespaces if restoring older code could reuse stale responses. No production migration, writes or deployment are performed by this PR preparation.

## Remaining risks

The local sales source ends on October 9, and complete historical coverage has not been established. Some DXBI property labels remain unresolved. Cold full-history summary scans are materially slower than cached requests; the per-worker concurrency bound is not a global production load limit. Registered stock and delivery-based forecasts remain unavailable without authorized supporting DXBI data. Separate chat market-metrics consumers are outside this Analytics-page change.

## Validation

Exact isolated-branch results (no skipped tests):

- ClickHouse integration: **65 passed** using disposable local databases and repository DDL.
- Analytics unit/API: **16 passed**.
- Frontend units: **59 passed**, 11 files.
- Chromium: **20 passed in 4.5 minutes**, including authentication setup and 19 Analytics interaction tests. The final test compares rendered counts/PSF and actual plotted datasets with both API responses. Screenshots in this directory were refreshed from this branch.
- Full backend Ruff lint/format: passed (280 files formatted); full frontend Biome: passed (230 files).
- Svelte/TypeScript: zero errors, zero warnings. Frontend production build: passed, with existing dependency and adapter-auto deployment-target notices.
- Git diff whitespace check: passed.

Initial alternate-port browser setup attempts failed because a dependency symlink was outside Vite's allow-list and the local API URL still pointed to the original port. Installing locked dependencies inside the worktree and using its same-origin proxy corrected test setup; no product-auth changes were made. Tests then passed on the isolated branch at ports 5174/8001. Local development app processes were separately restarted at 5173/8000 and the Analytics page returned HTTP 200.

The earlier development-checkout counts in REPORT.md include tests for excluded work. These exact branch results supersede those counts for the PR. Production deployment/load tests and a full cross-product browser suite were not run. No external reviewer approval is claimed.
