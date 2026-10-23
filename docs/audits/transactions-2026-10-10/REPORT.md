# DXBI Interact Transactions audit

Audited on 10 October 2026 against `fix/analytics-numbers`, commit `aed5309`, using the local WSL test stack and its existing DXBI data. **Six confirmed defects remain: two can silently remove distinct records, and four affect loading, export provenance, filter failures, or keyboard access.** No application fixes were made. Eight added regression checks fail against these six defects.

## Branch and architecture examined

[PR 41](https://github.com/Kian-Sham/VV/pull/41) targets `fix/dxbi-units-and-labels` and changes Analytics calculations and their generated contracts. Its immediate diff does not change Transactions queries or pages. The audit also examined the earlier Transactions changes, including `574b004` for responsive UI, `9698598` for building/project labels, and legacy identity and export logic. None of the six findings is attributed to PR 41 itself.

The serving path examined is:

1. Holocron parses DXBI sale and rental evidence into ClickHouse `dxbi_sales_unit_events` and `dxbi_rental_events`. Sale prices and sizes retain DXBI values. Rental annual amounts use the parsed contract term, falling back to days where appropriate.
2. `backend/app/transaction/queries.py` applies calendar windows, deduplication, place labels, location membership and filters. `dxbi_places`, `dxbi_locations`, `dxbi_location_members`, and `dxbi_location_lease_members` provide place labels and membership. The Transactions path uses DXBI data, separately from Analytics' combined market views.
3. `service.py` maps warehouse rows to Pydantic responses, including missing values and whole AED amounts. `router.py` requires an active subscription. Authentication and organization state use GoTrue/PostgreSQL. Redis caches listings for 600 seconds and filter options for 3600 seconds; export queries are uncached.
4. The frontend's typed API wrappers, TanStack Query builders, and `transactionPages.ts` map responses into sales/rental pages. `DataPanel`, `Pagination`, the dropdown components and `TransactionDetailsModal` implement the controls and rendering. Browser query freshness defaults to five minutes.
5. Exports reuse the source/filter queries, returning selected IDs or up to 50,000 filtered rows. CSV and XLSX include the transaction columns; XLSX adds provenance metadata.

Source reviewed includes these layers, their immediate callers, generated API types, shared formatting, global filters, auth guards, ingestion identity/annualization code, warehouse DDL and relevant tests. Production requirements were checked against `production-readiness-2026-09-29.md`, particularly source publication correctness, read-only serving access, bounded queries and shared market-data authorization. The page displays matching record counts and row amounts; it has no aggregate revenue or rent KPI cards to reconcile.

## Audit coverage and executed evidence

| Area | Executed result and coverage |
| --- | --- |
| Warehouse to API | Existing SELECT-only verifier: **405 checks, 0 mismatches**. Covers five periods, three usages, first/middle/last pages, returned fields, categorical filters, top locations/buildings/projects, all numeric bands and facet options. This compares sampled pages and totals, not every row in the warehouse. |
| Source snapshot | `FINAL` counts: **993,778 sale rows** and **1,684,777 rental rows**. Latest sale date: 2026-10-09; latest lease start: 2026-10-07. Last-year verifier input: 172,940 sales and 891,043 leases, producing 172,940 sales and 868,403 leases under current identity rules. |
| Existing live browser suite | **11 passed**. Both pages: all usage/timeframe combinations, all numeric bands, first/last offered categorical values, resets, pagination, column settings, filtered and selected CSV/Excel downloads; sale details. |
| Additional browser audit | **6 passed, 5 failed**. All fields in the first three rows of each page, hidden rental columns, every column toggle, selection/select-all/deselect/clear, tab navigation, modal close/Escape/backdrop, mobile rental dropdown and mobile sales cards/details in dark mode. The five failures reproduce F3, F5 and F6 below. |
| Exports | **104 live field comparisons passed** across two selected rows in each of sales/rentals CSV/XLSX. Contradictory filters confirmed that IDs override filters. Workbook metadata incorrectly retained those filters, confirming F4. |
| Backend tests | Initial focused offline suite: **10 passed**. Isolated ClickHouse selection: **13 passed, 2 failed, 34 deselected**; this includes eight existing Transactions tests passing and both new identity regressions failing. Export suite after adding provenance regression: **4 passed, 1 failed**. These counts include overlapping reruns and should not be added together. |
| Frontend unit tests | **59 passed**, including eight Transactions mapping/filter tests. |
| API contracts | All six live Transactions/filter OpenAPI operations and all five associated response schemas exactly match `frontend/openapi.json`. |
| Authentication and input validation | Anonymous requests to both lists, both exports and both facets returned **401**. Authenticated invalid limit, offset, period and export format returned **422**. |
| Change hygiene | Only audit documentation/screenshots and regression tests were added or changed. The pre-existing edit to `docs/data-pipelines/UNIFORM_LAYER_CHANGES.md` was preserved. Changed Python tests pass Ruff. |

**Reconciliation limitation:** the independent pandas verifier reimplements the same property identity rules as the SQL, including omitting building identity from unitless-lease matching. Agreement between those implementations cannot establish that the identity rules preserve distinct properties. The isolated counterexamples below demonstrate this gap. The 13,133 unitless leases and 9,507 repeated numbered rows removed by the verifier are not claimed to be incorrect removals.

## Confirmed findings in recommended fix order

### F1 P1 Rental deduplication can discard a lease from another building

**Evidence:** the new `test_missing_unit_in_other_building_is_not_a_duplicate_lease` inserts a numbered lease in Tower A and an unnumbered lease in Tower B, both in Dubai Marina with equal dates, size, bedrooms and amounts. Executed ClickHouse output contains only `tower-a`; expected IDs are `tower-a` and `tower-b`. This changes counts, lists, available facets and exports.

**Root cause and affected files:** the `lease_terms` hash includes area and commercial terms but excludes building/location identity. The `NOT IN` exclusion runs before place normalization. [queries.py:224](/home/maan3/vv/VV-git/backend/app/transaction/queries.py:224), [queries.py:264](/home/maan3/vv/VV-git/backend/app/transaction/queries.py:264). Introduced in `8bc9deb6`, before the current PR.

**Recommended fix:** match duplicate leases using verified canonical property identity as well as terms. Preserve ambiguous unnumbered records when a same-property relationship cannot be established. Retain coverage for legitimate duplicate report views and multi-unit leases. Update the independent verifier's identity expectations too.

**Impact limit:** confirmed with real SQL in a disposable fixture database. Current-data scans found cross-label candidates, but some labels may be aliases or project/building variants; the number of real records wrongly removed is not established.

### F2 P1 Sales in same-named towers across areas collapse into one record

**Evidence:** `test_same_named_towers_in_different_areas_keep_both_sales` inserts distinct DXBI sale IDs/detail URLs for unit 101 in Tower 1, once in Dubai Marina and once in Business Bay, with equal date and price. The query returns only `area-a`; `area-b` disappears.

**Root cause and affected files:** `same_sale` combines building key, unit, date and amount without the area key. `LIMIT 1 BY same_sale` merges the unrelated sales. [queries.py:155](/home/maan3/vv/VV-git/backend/app/transaction/queries.py:155), [queries.py:194](/home/maan3/vv/VV-git/backend/app/transaction/queries.py:194). This predates the current PR, from `0310859e`.

**Recommended fix:** scope fallback sale identity to a canonical property/location and preserve distinct authoritative source identities. Keep a separate explicit rule for verified CSV/scrape duplicates. Test repeated tower names and absent/ambiguous building names.

**Impact limit:** confirmed in isolated ClickHouse tests. A last-year scan found no same-building/unit/date/amount group with multiple area keys in the current local snapshot. This is a reproducible correctness defect, not a measured existing loss in that snapshot.

### F3 P2 Rows from the previous page remain selectable during loading

**Evidence:** on each live page, hold the `offset=30` response and click Next. Pagination immediately reports page 2 and starts at row 31, while page 1 rows and their enabled selection controls remain. Both regression tests fail because the previous rows are still selectable. The hold affects only the audit browser request.

**Root cause and affected files:** `placeholderData` retains previous results, but the UI checks only `isPending`; a placeholder query is not pending. [transactions.ts:25](/home/maan3/vv/VV-git/frontend/src/lib/queries/transactions.ts:25), [sales page:331](/home/maan3/vv/VV-git/frontend/src/routes/transactions/sales/+page.svelte:331), [rentals page:316](/home/maan3/vv/VV-git/frontend/src/routes/transactions/rentals/+page.svelte:316), and selection controls in [DataPanel.svelte](/home/maan3/vv/VV-git/frontend/src/lib/components/transactions/DataPanel.svelte). The placeholder pattern dates to `c23301ec`.

**Recommended fix:** explicitly handle `isPlaceholderData`/fetching state. Label retained rows as belonging to the previous result or replace them with a loading state; prevent selecting or opening those rows as if they belong to the newly requested page/filter. Keep pagination labels consistent with the displayed result.

**Screenshots:** [sales pending page](/home/maan3/vv/VV-git/docs/audits/transactions-2026-10-10/sales-pending-page.png), [rentals pending page](/home/maan3/vv/VV-git/docs/audits/transactions-2026-10-10/rentals-pending-page.png). Incorrect downstream exports caused by a user's click during the race were not separately executed.

### F4 P2 Selected Excel exports claim filters that were not applied

**Evidence:** selected live exports succeed with an intentionally unmatched location and one-day period and return the selected rows, as designed. However, Excel's `Metadata` sheet lists both values under **Filters applied**. The new unit regression fails on `contract_ids=R-1, location=Elsewhere, timeframe_days=7`. Both sales and rental live workbooks reproduced this.

**Root cause and affected files:** queries correctly override filters when IDs are supplied, but exports unconditionally merge IDs with all request filters when constructing metadata. [exports.py:191](/home/maan3/vv/VV-git/backend/app/transaction/exports.py:191), [exports.py:228](/home/maan3/vv/VV-git/backend/app/transaction/exports.py:228), [queries.py:405](/home/maan3/vv/VV-git/backend/app/transaction/queries.py:405). Predates the current PR, from `0310859e`.

**Recommended fix:** describe selection mode and selected IDs as the effective selection criteria. Omit overridden filters, or label them separately as unapplied screen context. Ensure the workbook explains how its contents were actually selected.

### F5 P2 Filter-option failures silently look like no available options

**Evidence:** inject HTTP 503 for the facet endpoint while leaving the live listing intact. After retry backoff, the location dropdown contains only All, while thousands of records remain visible and no filter error or retry control appears. Both sales and rentals fail the regression check.

**Root cause and affected files:** both pages read `facetOptionsQuery.data` with empty-array fallbacks and never render its error state. The existing error panel checks only the main listing query. [sales page:60](/home/maan3/vv/VV-git/frontend/src/routes/transactions/sales/+page.svelte:60), [rentals page:57](/home/maan3/vv/VV-git/frontend/src/routes/transactions/rentals/+page.svelte:57). Present before PR 41.

**Recommended fix:** expose facet loading/error states with a retry control. Distinguish unavailable options from a successful empty response. If retaining cached options, label their stale status.

**Screenshots:** [sales filter failure](/home/maan3/vv/VV-git/docs/audits/transactions-2026-10-10/sales-facet-error.png), [rentals filter failure](/home/maan3/vv/VV-git/docs/audits/transactions-2026-10-10/rentals-facet-error.png). The outage was deliberately injected; no natural facet outage was observed.

### F6 P2 Sale details dialog does not manage keyboard focus

**Evidence:** opening a sale leaves focus outside the dialog. Focusing Close and pressing Tab also moves focus outside it. Both soft assertions fail. Mouse Close, Escape and backdrop dismissal pass.

**Root cause and affected files:** the shared modal supplies `aria-modal` and scroll locking, but no initial focus, focus containment or restoration. [Modal.svelte:32](/home/maan3/vv/VV-git/frontend/src/lib/components/ui/Modal.svelte:32), [TransactionDetailsModal.svelte:44](/home/maan3/vv/VV-git/frontend/src/lib/components/transactions/TransactionDetailsModal.svelte:44). Present before PR 41.

**Recommended fix:** use the established accessible-dialog pattern, move focus into the dialog on open, contain Tab/Shift+Tab and restore focus on dismissal. Also make the desktop row's details action keyboard reachable; the current clickable table row has no focusable details control.

**Screenshot:** [sale details](/home/maan3/vv/VV-git/docs/audits/transactions-2026-10-10/sale-details.png). Keyboard failures are established by browser assertions; the screenshot only shows the dialog involved.

## Remaining unverified behavior

- Live DXBInteract website/report identity, ingestion completeness, scheduled re-scraping and upstream freshness were not audited against a fresh external scrape. Reconciliation uses the authorized local warehouse snapshot.
- The full extent of actual false deduplication in existing rental data remains unresolved. Candidate aliases require source-level identity evidence.
- Warehouse changes during pagination/export, cache expiry and midnight date-window rollover were not exercised. Separate count/row reads and different cache lifetimes were inspected but are not reported as confirmed failures.
- Chromium desktop and 390-pixel mobile layouts were tested. Firefox, WebKit, physical touch devices, screen-reader output and exhaustive keyboard paths remain untested. Dark mobile sales and light desktop/mobile rental controls were sampled, not every theme/viewport combination.
- Active-admin and anonymous API access were tested. Tenant-specific subscription changes, expired-token refresh and all role permutations were not exercised in this run.
- Production infrastructure, Phase 1 concurrency/load, outage recovery and export memory limits were not validated. The complete unrelated backend suite, full application lint/build and ingestion suite were intentionally outside the executed checks.

## Evidence and regression tests

- [Verification results](/home/maan3/vv/VV-git/docs/audits/transactions-2026-10-10/verification-results.txt) contains sanitized command outcomes and failure evidence.
- [ClickHouse identity regressions](/home/maan3/vv/VV-git/backend/tests/integration/clickhouse/test_transactions.py:567).
- [Export metadata regression](/home/maan3/vv/VV-git/backend/tests/unit/test_transaction_exports.py:147).
- [Browser audit tests](/home/maan3/vv/VV-git/e2e/transactions-audit.spec.ts).
- Screenshots are saved alongside this report. Raw traces and authenticated runtime evidence remain in Git-ignored `.evaluation/transactions-audit-2026-10-10`; traces may contain session headers and are not included in the shareable evidence.

The local services were recovered by restarting the existing `vv-engineer-*` containers matching `.env.dev`. The standard `just up` path failed to pull MinIO; no replacement database or warehouse was loaded. Frontend tests initially failed under Node 18, then passed under installed Node 20. Chromium initially lacked runtime libraries; temporary extracted libraries under `/tmp/vv-audit-browser-libs` enabled the browser runs. These setup failures are separate from the six application findings. Initial new-test collection failed due to fixture import placement; moving the tests beside the existing fixture resolved collection. No failed or skipped attempt is represented as a pass.
