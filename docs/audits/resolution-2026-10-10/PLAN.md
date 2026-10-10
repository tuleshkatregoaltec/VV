# Transactions and Analytics audit resolution

Baseline: `aed5309` on `fix/analytics-numbers` (open PR #41). This branch will open a stacked PR against that baseline. Existing unrelated edits to `docs/data-pipelines/UNIFORM_LAYER_CHANGES.md` remain excluded.

Success criteria: all 14 confirmed findings have an implemented fix and executed regression coverage; source/API/browser values remain consistent; relevant contracts are regenerated; combined checks pass or any external blocker is explicitly recorded; PR contains only authorized fixes, tests and audit evidence. No production writes or warehouse migrations are planned.

Execution is sequential. Each implementation step is checked before the next begins. Canonical project search may resolve two findings through one change; no duplicate workaround will be added.

- [x] T1 Preserve unnumbered leases from different buildings during deduplication.
- [x] T2 Preserve sales in same-named buildings in different areas.
- [x] A1 Resolve Analytics selection against canonical market project names.
- [x] A2 Restrict project stock and unit sizes to that project, including drill-down.
- [x] A3 Separate actual completed supply from overdue planned deliveries.
- [x] A4 Restore master-community search and real drill-down.
- [x] A5 Carry current-quarter deliveries into subsequent projected stock.
- [x] A6 Remove or accurately disclose synthetic bedroom supply counts.
- [x] T3 Prevent selection/navigation of old result rows during page/filter loading.
- [x] T4 Describe selected export criteria accurately.
- [x] T5 Expose filter-option failures and provide retry.
- [x] T6 Focus and contain keyboard navigation in sale details.
- [x] A7 Expose/retry Analytics panel and comparison/forecast errors.
- [x] A8 Support keyboard selection in project and sub-project search.
- [x] Combined backend, ClickHouse, frontend, browser, contract and build checks.
- [x] Updated evidence, review, commits, push and PR.

Historical audit reports remain baseline evidence. Final verification and any limitations will be recorded separately here.

T1: three isolated lease identity regressions passed, including known duplicates and unknown-building preservation. Cache keys versioned; read-only verifier updated.

T2: all 11 Transactions ClickHouse tests passed, including cross-area identity and CSV/scrape deduplication. Both list/facet cache namespaces versioned.

A1/A4: one canonical-market selector replaces the incompatible map catalogue. Isolated search test covers masters, canonical casing and projects without sales; both live master-discovery and 23 Marina browser regressions passed.

A2: nine Analytics ClickHouse tests passed. Direct selection and drill-down now exercise the real service scope; the size assertion allows ClickHouse floating-point cent rounding. Summary cache version changed.

A3: overdue completion regression passed. Pipeline now uses Dubai business date and actual completion evidence; overdue/undated units are explicit response fields and displayed separately.

A5: nine targeted pipeline/scope/router tests passed, including current-quarter carry, overdue and undated exclusions.

A6: live browser regression passed with unsupported bedroom estimates removed. Supply remains area-level, with explicit all-bedroom scope. API client generated for new pipeline fields; final formatting/check run remains pending.

T3: both live delayed-page regressions passed. Placeholder results show loading instead of actionable previous rows; pending counts are labelled as updating.

T4: six export tests passed. Both sales and rental workbooks report only effective selected IDs, with blank-ID inputs retaining ordinary filters.

T5: both injected facet outages recovered through Retry filters in live browser tests.

T6: live modal regression passed with initial focus, focus containment and restoration implemented in the shared dialog.

A7: six live fault/recovery regressions passed: trends, distribution, supply, forecast, comparison summary and comparison trends. Search and development counts also expose retry controls.

A8: four browser keyboard regressions passed, including master drill-down, Tab/Enter, arrows/Escape and modal containment.

Final verification: 353 backend, 53 ClickHouse, 59 frontend and 40 unique browser cases passed; 405 independent Transactions source/API checks passed. Canonical Analytics sales/stock and pipeline totals reconcile. Svelte check has zero errors/warnings; lint, regenerated contracts and production build pass. Expanded recovery coverage found a search-retry focus edge case; retaining input focus fixed it and the final 18-case Analytics run passed. Existing build notices and verification limits are recorded in REPORT.md.

Completed: [PR #42](https://github.com/Kian-Sham/VV/pull/42), stacked on PR #41. Backend fixes, frontend fixes/tests and audit evidence are committed separately. The unrelated pipeline-document edit remains local and excluded.
