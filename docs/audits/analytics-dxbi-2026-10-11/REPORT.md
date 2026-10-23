# Analytics DXBI-only sources and comparison repair

## Inspection and plan (before implementation)

Scope: Analytics searches, summaries, comparisons, distributions, trends and rental/configuration figures must use DXBI only, including labels. DLD is permitted only for upcoming supply. The separate Upcoming page stays unchanged. Clarification requested whether Analytics' Upcoming Supply chart should also remain; initial assumption is yes.

Confirmed: Analytics reads the combined market tables through `ch_transactions` and `ch_rent_contracts`; search additionally includes DLD projects/units. Summary unit stock/developer/delivery metadata and the price-forecast delivery curve use DLD. Therefore merely filtering the combined rows by a DXBI source marker would still leak DLD-enriched fields. Transactions' reusable sale source also has optional DLD patches that must be explicitly bypassed for Analytics.

Browser baseline: Compare opens and renders Dubai vs 23 MARINA locally, with two canvases and no captured browser error. A universal Compare crash is not reproduced. Confirmed display defect: per-square-foot values are rounded into `AED 1K` for different prices despite a displayed -27.1% difference. Comparison repeats Units metadata and offers catalogue choices without verified DXBI activity. Investigate stale charts/search transitions through actual interactions after changing the source.

Implementation stages:
1. Add an Analytics-owned DXBI projection using the same normalized/deduplicated records as Transactions, with DLD patches disabled. Keep shared market views unchanged for unrelated consumers. Map DXBI locations into existing community scopes explicitly; preserve unknown bedrooms/status/size.
2. Switch all page queries and search to that projection. Remove registry-stock and delivery-forecast dependencies outside upcoming supply. Unsupported registry figures must be unavailable, never transaction counts relabeled as stock. Keep response contracts compatible where possible. Bump Analytics cache identity.
3. Repair and exercise both selectors, comparison entry/exit, switching selections, chart metric controls, configuration segments and price-distribution filters. Show precise comparison values. Fix only reproduced or code-proven defects.
4. Run targeted source-isolation tests with poisoned DLD values, query/API checks and real-browser regressions. Independently reconcile live DXBI totals, collect screenshots and document remaining gaps.

Acceptance: a DLD-only transaction/project and a DLD patch cannot change any ordinary Analytics response; DXBI sales/rental totals and cohorts reconcile to normalized source records; valid searches and all comparison selections populate available metrics/charts; zero/missing/error states remain distinguishable; upcoming is the only allowed DLD dependency; no production writes or unrelated page changes.

## Implemented source boundary

The user confirmed DLD should remain in **both** upcoming views. Ordinary Analytics page data now comes from the normalized DXBI sale/rental records, not `market_sale_events`, `market_rental_events` or their `ch_*` views. `backend/app/analytics/dxbi.py` projects existing Transactions identities, catalogue labels, bedrooms, status, amounts and DXBI PSF into Analytics' existing query contracts. The PR serving query does not join DLD patches. Shared warehouse views and the separate Upcoming page are unchanged; the additive identifier-column prerequisite is documented in REVIEW.md; no source records are rewritten.

A selectable scope is the DXBI project when present, otherwise its recorded building; community is DXBI's displayed location. Search includes rental-only scopes, ranks exact/prefix matches first, preserves provider casing, and handles case-insensitive scope requests. DLD-only launches are not ordinary Analytics search results. This does not certify every legacy DXBI address string as a verified property name.

DLD is retained for the Upcoming Supply endpoint, including completion/scheduled-unit information. Its metadata lookup is isolated from ordinary summaries. If a DXBI selection has no DLD project metadata, a known DXBI location can restrict the DLD supply lookup by an exact area/community name; no fuzzy transaction/property match is created. An unresolved location returns unavailable supply, not a citywide fallback.

Registered property stock, developer/delivery metadata and delivery-based price forecasts are not supported by the loaded DXBI transaction dataset. Ordinary summary cards no longer display DLD registry metadata; unit composition is unavailable and sales/stock ratios remain unavailable. Configuration size now means **median observed DXBI sale size**, explicitly labeled. Transactions are never relabeled as registered stock. The forecast API remains compatible but returns no invented forecast and explains the source limitation.

Existing Analytics eligibility remains explicit: the project-summary cards and comparisons cover positive-price residential sales excluding plots/whole buildings, and residential annual rents. They are not all-property Transactions counts. Monetary chart axes may abbreviate for space; displayed monetary values and comparison cells retain numeric precision, including PSF.

## Comparison and interaction corrections

- Replaced lossy `AED 1K` PSF/value displays with actual formatted amounts; removed duplicate/unsupported registry metadata from comparison cards.
- Comparison uses the same DXBI summary/trend query definitions on both sides, with a shared date axis. Missing observations remain gaps; isolated points remain visible.
- Clear/exit, both selectors, master drill-down, keyboard navigation and recovery controls are exercised by browser tests.
- Search is debounced; stale search results cannot be selected with Enter while a new term is pending. Search/sub-project cache entries expire instead of remaining indefinitely fresh.
- A bedroom distribution selection resets to All when absent from the new segment; trend/supply chart instances are disposed when their data disappears.
- DXBI-specific cache namespaces prevent old combined-source results from surviving the source switch.

## Performance investigation

The first direct-source experiment reproduced warehouse pressure: the previous summary dispatched thirteen parallel queries and repeated source scans. Those test queries were cancelled; no records were mutated. The final summary combines summary/bedroom/configuration aggregates into one grouped sales scan and limits concurrent Analytics warehouse scans to two per worker with bounded execution time. Search scans each source once. New search/trend/distribution response caches use five minutes; the existing summary policy remains fifteen minutes under a new source-version namespace.

Measured direct local probes (not production benchmarks): search 5.69 seconds; cold citywide summary 10.59 seconds, versus 22.12 seconds before the grouped scan; trends 3.04 seconds; distribution 5.96 seconds. Cached browser requests are faster. Cold full-history requests and production concurrency still merit load testing; this change does not claim instantaneous responses or resolve ingestion freshness.

## Data checks

On the current local snapshot the DXBI-only citywide residential summary is:

| Metric | Value |
|---|---:|
| Sales | 922,850 |
| Sales value | AED 2,156,606,516,752 |
| Mean sale price | AED 2,336,898.21 |
| Mean DXBI price/sq ft | AED 1,619.37 |
| Rental contracts | 1,105,561 |
| Annual rental value | AED 102,804,912,297 |
| Median annual rent | AED 65,000 |

The independent distribution query returns the same 922,850 eligible sales. Source-level count/value/PSF reconciliation is saved privately in `.evaluation/analytics-dxbi/reconciliation.json`; the complete live API/service probe is in `probe.json`. These are snapshot figures, not a claim of complete Dubai coverage. Source freshness/completeness issues from the transaction readiness audit remain outstanding.

## Files and release behavior

- Backend: `app/analytics/dxbi.py`, `queries.py`, `service.py`, `metrics.py`, `router.py`; `app/transaction/queries.py` supplies shared DXBI normalization and excludes DLD patches.
- Frontend: Analytics page, query builders, ProjectSelector, ProjectPanel and AnalyticsCompareView.
- Tests: DXBI source-isolation integration tests; existing aggregation fixtures adapted to the projection contract; query-cache tests; extended browser audit plus an actual chart-dataset comparison test.

No public response fields changed, so client regeneration was unnecessary. No new dependencies, infrastructure, production writes or deployment were made during implementation. PR packaging and its exact checks are documented in REVIEW.md. All unrelated pre-existing changes were preserved. Rolling back code restores the prior source behavior; use fresh/invalidate Analytics cache namespaces when doing so. No data rollback is required.

## Remaining limitations

- The local source still ends on October 9; this task does not claim to fix the missing complete October 10 ingestion or historical reconciliation.
- Some old DXBI source addresses contain unresolved/agent-prefixed strings. Exact canonical suggestions are prioritized, but uncertain strings are not silently merged into another property. Further trusted source repair belongs to the existing data-quality work.
- Unknown rental/stock/delivery/yield figures are not manufactured. Zero recorded contracts is shown as zero; an unsupported rent/yield remains unavailable.
- Shared warehouse datasets and the separate chat market-metrics service are not redefined by this Analytics-page change. No claim is made that DLD has been removed globally from unrelated product modules.

## Final verification

- ClickHouse integration suite: **67 passed**, including isolated real-DXBI fixtures with poisoned DLD tables and an otherwise eligible DLD enrichment patch.
- Analytics unit/API tests: **16 passed**; minimum sample sizes, period comparisons, empty responses, cache behavior and authorization remain covered.
- Frontend unit suite: **63 passed** across 12 files.
- Chromium browser suite: **20 passed** (authentication setup plus 19 interaction tests), with no skipped tests. Covers search, keyboard selection, communities/developments, comparison entry/exit/clear, both chart metrics, configuration segments, distribution and supply controls, desktop/mobile layouts, and injected API failures/retries.
- The comparison test checks rendered counts and precise PSF values against both summary responses and reads the actual Chart.js datasets to compare every plotted PSF point with the corresponding trend responses. The fixture source-isolation tests separately verify backend aggregates against known records.
- Targeted Ruff and Biome checks pass; `git diff --check` passes.
- Final `just check-frontend`: zero errors and zero warnings. Final `just build-frontend`: passed. The local build emits dependency unused-import warnings and adapter-auto's unsupported deployment-target notice; a successful local build is not a deployment check.

Earlier browser attempts exposed broad test locators and a run started without the required local environment; those attempts were not counted as successful validation. The final suite loaded `.env.dev` and ran against a stable host app without simultaneous builds or source edits. All database fixture writes were local/test-only. This is local validation, not production deployment, production load testing or certification of every historical source record.

Evidence:

- [Desktop comparison](screenshots/compare-verified.png)
- [Actual comparison chart](screenshots/compare-chart.png)
- [Mobile comparison](screenshots/compare-verified-mobile.png)
- [Market controls](screenshots/market-controls.png)
- [Community drill-down](screenshots/master-drilldown.png)

Detailed execution logs are retained locally under `.evaluation/analytics-dxbi/`; they are not source data or release artifacts.

## PR packaging update

The original verification above covered the development checkout. See [PR review and release notes](REVIEW.md) for the isolated PR contents and its separate validation. The PR excludes the unfinished enrichment pipeline and preserves DXBI-only transaction values.
