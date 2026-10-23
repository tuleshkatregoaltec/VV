# Project-specific Analytics findings — 12 October 2026

Read-only investigation of the current local database and current Analytics service. No application fixes, source-data writes or deployment were performed. Private query results: `.evaluation/analytics-project-reasons/results.json` and `details.json`.

## District One Residences

Exact selection: `(D1) District One Residences`. Reproduced 2,587 eligible residential sales, AED 1,842,649.93 mean price, AED 1,807.04 mean PSF, 1,360 leases, AED 110,000 median annual rent. Market split reconciles: 1,664 off-plan + 923 secondary.

| Bedrooms | All recorded sales | Rolling 12-month sales, anchored on 2026-09-25 |
|---|---:|---:|
| 1 | 1,782 | 92 |
| 2 | 621 | 31 |
| 3 | 179 | 15 |
| 4 | 4 | 1 |
| 5 | 1 | 0 |

Confirmed P1 presentation/cohort issues:
- The table labels `sales_last_12m` as “Sales”, beside all-history mean prices and median sizes, under an all-recorded-dates page statement. It does not use one consistent period or explain the difference. File: `frontend/src/lib/components/analytics/ProjectPanel.svelte`.
- `build_configuration_rows` omits an entire configuration when fewer than three sales occurred in its rolling year. This hides the 4- and 5-bedroom observations instead of keeping observed counts and marking unsupported metrics unavailable. File: `backend/app/analytics/metrics.py`.
- `fetch_project_sales_bundle` anchors windows separately by segment. Secondary/All latest sale is 2026-09-25; Off-Plan latest sale is 2024-01-02. Thus Off-Plan “last 12 months” means a historical 2023–2024 window, while All refers to 2025–2026. These tabs cannot be compared as current activity without an explicit common as-of date. File: `backend/app/analytics/queries.py`.

Other figures explained:
- Gross yield 6.47% uses AED 110,000 / AED 1,700,000, the **secondary-only median sale price**, not the displayed mean or the all-sales median (AED 1,501,513). Label should identify the secondary denominator and clarify that this is an aggregate proxy, not matched-property investment yield. File: `backend/app/analytics/service.py`.
- 1-bedroom momentum: 25 vs 34 sales in successive 90-day windows; the code divides the difference by the average of the two counts, producing -30.5%. This is a symmetric change measure; ordinary prior-period percentage change would be -26.5%. The definition needs disclosure.
- 2-bedroom momentum is unavailable because samples are 10 vs 12; 3-bedroom is 4 vs 1. Both fall below the existing minimum of 20 per window.
- Sales/Stock is unavailable because DXBI transactions do not provide a verified registered-stock denominator. This must not be filled from transaction counts.

## ABD ALLH SOLIMAN Binghatti Skyrise - Tower C

The stored raw record has that exact string as its building name, with an empty project. One sale: 2026-04-17, unit C307, Studio, Offplan, AED 975,000 and AED 2,092/sq ft. The exact Analytics selection returns one sale, no leases, no configuration rows and no gross yield.

Confirmed P1 entity-resolution/search issue: Analytics uses project name, otherwise building name, as its search scope. This malformed building string fails the trusted catalogue match and becomes a standalone “project”. The existing DXBI catalogue identifies `Binghatti Skyrise - Tower C, Business Bay` as building `Binghatti Skyrise - Tower C` within project `Binghatti Skyrise`. There are 959 raw Tower C observations under the clean name, before serving deduplication; that is evidence of fragmentation, not a certified corrected count.

The importer already documents the failure mode where hidden agent text precedes the building. It prefers `location_title`, but falls back to cell text and removes only the literal Buyer’s/Seller’s agent prefix, not a person's name. This is consistent with the observed label. The specific original JSONL file named by this record was not found under the local repository roots, so this investigation does not certify the exact original DOM or automatically strip the prefix.

The empty table follows the three-sales threshold; missing rent/yield follows the isolated malformed scope. Correcting the UI to manufacture values would conceal the underlying grouping problem.

## Recommended correction order

1. Use an explicit common as-of date and clearly defined periods across All/Off-Plan/Secondary. Align row counts, prices and size cohorts, or label each period explicitly.
2. Preserve low-sample configuration rows/counts; suppress only statistics that need larger samples. Explain unavailable fields and yield/momentum definitions.
3. Recover original raw title/HTML or reacquire the exact provider detail record, verify its identity, and repair its building/project mapping with provenance. Reconcile duplicate identities before merging counts. Do not merge based solely on stripping apparent personal names.
4. Add regressions for cross-tab period consistency, all-history versus recent totals, low-sample visibility, and malformed labels. Earlier tests proved displayed values matched the API; they did not establish that every displayed period/label or legacy source entity was semantically correct.

## Corrections implemented

- Configuration counts now use all-history `sale_count`, matching the adjacent all-history prices and sizes. Comparison configuration cards use and rank by the same count.
- Every recent period uses a shared UTC calendar cutoff (exclusive tomorrow), not each segment's latest sale. Future-dated records are excluded from recent-period statistics.
- Removed both backend and frontend suppression of entire low-sample configurations. Observed counts/means remain visible; YoY and momentum retain their minimum sample checks.
- Added period and sample explanations; clarified the secondary-median denominator for gross yield. Kept the existing symmetric momentum formula and disclosed it rather than silently changing the business definition.
- Bumped backend summary and frontend query cache versions. Updated the API size-field description and generated contract artifacts.
- Corrected the PR's broader integration checks: Analytics uses public Transactions source operations; SQL inventory retains unresolved interpolation instead of inventing a WHERE table; refreshed the contract fixture.

Binghatti identity repair remains unresolved. The exact detail link returned HTTP 403; no original scrape file, matching raw bronze row, or accessible local authenticated debugging session was available. Unit C307 also has a clean-name record, but that record is dated 2024-12-27 with a different DXBI detail URL, versus 2026-04-17 for the suspect record. Equal unit and price are not enough to merge these identities. No property mapping or source transaction was rewritten. Its one-sale configuration is now allowed to appear, rather than being hidden by the three-sale threshold.

Regression results and the District One screenshot are recorded in the accompanying review notes after validation.
