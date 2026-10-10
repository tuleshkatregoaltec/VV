# DXBI Interact — Analytics full-stack audit

Audited 10 October 2026 on `fix/analytics-numbers`, HEAD `aed5309`, including [PR #41](https://github.com/Kian-Sham/VV/pull/41) against `fix/dxbi-units-and-labels` and the legacy paths it calls. Eight confirmed findings are listed below in recommended fix order. No application fixes, production writes, migrations, or destructive service operations were performed. Existing Transactions audit work and the unrelated `UNIFORM_LAYER_CHANGES.md` edit were preserved.

## Architecture examined

`/analytics` composes `ProjectSearchInput`, `ProjectPanel`, and `AnalyticsCompareView`. Search uses the **shared projects catalogue**, not the analytics search endpoint. Selection becomes a project/master name in typed API wrappers; TanStack Query keys include scope and options. Summary, trends, forecast, price distribution and area supply load independently. Chart.js renders the returned series and additional frontend transformations.

FastAPI `/api/v1/analytics/project/*` routes require an active subscription. Auth uses the existing local GoTrue/PostgreSQL test account; Redis caches responses, including summary for 15 minutes. Services gather scoped ClickHouse queries and calculate bedroom rows, yields, sales/stock ratios, forecast points and quarterly supply. Frontend queries normally remain fresh for five minutes; the project catalogue has infinite frontend stale time and a one-hour backend cache.

Live view definitions were inspected: `ch_transactions` reads served `market_sale_events`; `ch_rent_contracts` reads served `market_rental_events`; `ch_units` reads DLD unit bronze records; `ch_projects` selects the latest DLD project snapshot per project number. The project search catalogue instead uses the radar geography/Reelly catalogue. That identity boundary is central to F1 and F4.

Relevant implementation: [page](/home/maan3/vv/VV-git/frontend/src/routes/analytics/+page.svelte), [API wrappers](/home/maan3/vv/VV-git/frontend/src/lib/api/analytics.ts), [query builders](/home/maan3/vv/VV-git/frontend/src/lib/queries/analytics.ts), [panel](/home/maan3/vv/VV-git/frontend/src/lib/components/analytics/ProjectPanel.svelte), [comparison](/home/maan3/vv/VV-git/frontend/src/lib/components/analytics/AnalyticsCompareView.svelte), [router](/home/maan3/vv/VV-git/backend/app/analytics/router.py), [service](/home/maan3/vv/VV-git/backend/app/analytics/service.py), [queries](/home/maan3/vv/VV-git/backend/app/analytics/queries.py), [metrics](/home/maan3/vv/VV-git/backend/app/analytics/metrics.py), [serving views](/home/maan3/vv/VV-git/backend/scripts/clickhouse/create_compatibility_views.py).

## Audit coverage and executed verification

Environment: host-run WSL frontend `localhost:5173`, API `127.0.0.1:8000`, existing local Docker services and configured test credentials. Browser: Playwright Chromium, desktop 1440×1000 and mobile 390×844. Failure injection only intercepts requests in the audit browser. SQL writes were limited to uniquely named disposable test databases.

| Area | Evidence and result |
|---|---|
| Current PR | Reviewed all ten changed files and their callers. Existing tests exercise median unit size, recorded rental bedrooms, p16/p84 bounds, and sample/stock guards. These changes do not resolve the legacy findings below. |
| Backend tests | Final targeted unit/API run: **14 passed, 2 failed**. Isolated ClickHouse run: **6 passed, 2 failed, 43 unrelated tests deselected**. Four retained failures reproduce F2, F3 and F5. |
| Frontend unit tests | **59 passed across 11 files**, including query builders. These do not prove live project identity or keyboard correctness. |
| Browser | **11 scenarios: 3 pass, 8 confirmed defect failures**, combining the final full run with the corrected market-control rerun; accounting is in `verification-results.txt`. Exercised default market, sales/price-per-square-foot trend mode, all/off-plan/secondary configuration tables, rental mode, distribution segment and bedroom tabs, supply bedroom tabs, real project selection, compare entry/exit and both chart modes, Dubai reset, desktop/mobile layouts, dark mode, keyboard selection and injected failures. |
| Source → API → UI | Dubai: **1,183,664** eligible residential sales; total value **AED 2,381,110,541,729**; average **AED 2,011,643.96**; median **AED 1,275,369**; average price/sq ft **AED 1,446.91**. Direct source queries match API figures. UI shows the corresponding rounded/count values. |
| PR calculation mappings | Source median annual rent **AED 51,000**, **7,367,624** contracts; studio median size **411.93 sq ft**, shown as **412**; p16 **AED 583,000**, p84 **AED 2,974,000**, shown as **AED 583K–2.97M**. These match the response and display. This validates the transformation against the local source, not the source's real-world completeness. |
| Actual chart data | Read live Chart.js datasets. Recorded monthly price and price/sq-ft series follow API metrics. Market split is **626,253 off-plan + 557,411 secondary = 1,183,664**. Supply bedroom scaling is confirmed in F6. |
| Contracts and auth | All **11 Analytics OpenAPI paths** and **13 relevant response schemas** match `frontend/openapi.json`. Seven anonymous requests covering the six project data endpoints and catalogue returned **401**. Summary HTTP 503 produces an explicit error; subordinate failures do not. |
| Selected scopes | Real browser selections include Binghatti Skyrise and Sobha Orbis for populated panels/comparison, and 23 Marina for the false-zero reproduction. Direct API checks include Marina Pinnacle and Dubai Marina master. Master drill-down keyboard coverage requires a catalogue fixture because F4 blocks the real entry path. |

There are no Analytics pagination or export controls to test. Global application destinations were not audited as part of this page. Read-only code review covered legacy Analytics sales/rental/market-trend endpoints; live verification concentrated on endpoints actually used by `/analytics`.

## Confirmed findings, in recommended fix order

### F1 — P1: selecting a catalogue project can show zero recorded transactions

**Evidence:** selecting **23 Marina** sends `project=23 Marina` and returns zero sales; requesting **23 MARINA** against the same live API returns **893** eligible sales. **Marina Pinnacle** returns zero, while **MARINA PINNACLE** returns **2,262**. The browser regression compares the two names against the live API and fails `0 != 893`. The visible panel confidently labels the result “0 transactions.”

**Cause / affected files:** the page passes the catalogue display name into an exact, case-sensitive warehouse predicate. [page:33](/home/maan3/vv/VV-git/frontend/src/routes/analytics/+page.svelte:33), [scope.py:44](/home/maan3/vv/VV-git/backend/app/market/scope.py:44), [catalogue query:56](/home/maan3/vv/VV-git/backend/app/project/queries.py:56), [radar catalogue](/home/maan3/vv/VV-git/backend/app/project/radar_queries.py:21). Legacy integration defect, outside the PR #41 diff. The catalogue source changed in `986e9b90` while Analytics continued to consume names.

**Recommended fix:** resolve catalogue entries to canonical warehouse project identities and use those consistently for sales, rentals, metadata and stock. A tested case-normalized match can address this reproduction, but names alone need collision/alias handling. Do not present an unresolved identity as a verified zero.

**Screenshot:** [false zero for 23 Marina](/home/maan3/vv/VV-git/docs/audits/analytics-2026-10-10/project-name-zero.png).

### F2 — P1: project stock, sizes and sales/stock denominators use the wrong scope

**Evidence:** live **Binghatti Skyrise** has **2,907** sales and **3,358** registered unit rows with its exact project name. Its response nevertheless has an empty `unit_composition`. Source bedroom medians include Studio **449.39 sq ft** and 1 B/R **830.76 sq ft**. The panel cannot populate those project sizes/stock ratios. In isolated ClickHouse tests, selecting Tower A returns no units; drilling into Tower A with Master A returns both Tower A and sibling Tower B instead of only Tower A.

**Cause / affected files:** direct project scope filters `master_project_en`, and the service optionally substitutes the parent master name. [service.py:117](/home/maan3/vv/VV-git/backend/app/analytics/service.py:117), [queries.py:264](/home/maan3/vv/VV-git/backend/app/analytics/queries.py:264), downstream [metrics.py:144](/home/maan3/vv/VV-git/backend/app/analytics/metrics.py:144). Legacy behavior; PR median/ratio changes still consume this incorrectly scoped stock.

**Recommended fix:** use the selected project's canonical identity for project stock, retaining separate master aggregation. Test direct selection and master drill-down against the same expected units, median sizes and ratio denominator. Keep any broader-stock fallback explicit and out of project ratios.

**Evidence:** [populated project panel with missing configuration sizes](/home/maan3/vv/VV-git/docs/audits/analytics-2026-10-10/project-desktop.png), [isolated regression tests](/home/maan3/vv/VV-git/backend/tests/integration/clickhouse/test_analytics_audit.py).

### F3 — P1: overdue, unfinished projects are counted as completed stock

**Evidence:** the local register contains **160** non-cancelled projects with **37,759 units**, no completion date, an elapsed planned end date and completion below 100%. Example: **Binghatti Hillviews**, 2,339 units, ACTIVE, 32.6%, planned 1 April 2026. Analytics places these units in `completed_by_quarter` and cumulative existing stock. A unit test with an active 32.6%-complete project reproduces the misclassification.

**Cause / affected files:** `_coalesce_delivery_date` replaces absent actual completion with planned end date; `completion_dt <= anchor` is treated as completion evidence. [metrics.py:98](/home/maan3/vv/VV-git/backend/app/analytics/metrics.py:98), [service.py:565](/home/maan3/vv/VV-git/backend/app/analytics/service.py:565). Legacy logic from `b3f1ecad`. It conflicts with the newer [delivery definitions](/home/maan3/vv/VV-git/backend/app/project/delivery.py:28), which distinguish actual completion from overdue planned delivery.

**Recommended fix:** apply the existing delivery-status definitions to Analytics. Only documented completion should become existing stock; show overdue and undated delivery separately. The 37,759 is the affected source-record unit total, not an independently verified physical-home count.

### F4 — P2: master-community search and its drill-down are unreachable

**Evidence:** every one of the **2,144** real `/projects/list` entries has `master_project_en=null`. Searching “Dubai Marina” exposes project results but no Master option. Yet the Analytics master API returns **66,837** sales for Dubai Marina. A browser regression fails to find the advertised Master selection.

**Cause / affected files:** [catalogue query:64](/home/maan3/vv/VV-git/backend/app/project/queries.py:64) explicitly returns `'' AS master_project_en`. [ProjectSearchInput:20](/home/maan3/vv/VV-git/frontend/src/lib/components/projects/ProjectSearchInput.svelte:20) constructs its entire master index from that field. The [Analytics page](/home/maan3/vv/VV-git/frontend/src/routes/analytics/+page.svelte:19) uses this catalogue rather than the existing analytics scope search. Legacy defect introduced at the catalogue boundary, not by this PR.

**Recommended fix:** provide a scope-aware Analytics catalogue with real master/project identities, or restore verified master relationships in the shared catalogue. Add an integration test covering catalogue response through master selection and drill-down.

**Screenshot:** [missing master option](/home/maan3/vv/VV-git/docs/audits/analytics-2026-10-10/missing-master.png).

### F5 — P2: current-quarter deliveries vanish from later cumulative supply

**Evidence:** Dubai API reports Q4 2026 existing stock **473,280** and new pipeline **41,027**. Q1 2027 carried stock remains **473,280**, omitting those 41,027 units; it adds only Q1's 17,270 deliveries. The plotted Q1 total is **490,550**, rather than **531,577** under the chart's own cumulative-delivery assumption. A focused test expects 100 existing + 50 current-quarter deliveries = 150 carried into next quarter, but receives 100.

**Cause / affected files:** the current-quarter branch appends its deliveries and `continue`s without adding them to `cumulative_future`. [service.py:579](/home/maan3/vv/VV-git/backend/app/analytics/service.py:579). Current-quarter branch dates to `59124c3c`; outside PR #41.

**Recommended fix:** carry current-quarter scheduled additions into every later quarter, with explicit beginning/end-of-quarter semantics. Test the current-quarter transition and quarter-boundary dates.

**Screenshot / test:** [supply chart](/home/maan3/vv/VV-git/docs/audits/analytics-2026-10-10/supply-carry.png), [pipeline regressions](/home/maan3/vv/VV-git/backend/tests/unit/test_analytics_audit.py).

### F6 — P2: bedroom supply controls present proportional estimates as actual counts

**Evidence:** choosing Studio multiplies every area's historical and future supply point by the selected scope's studio stock share. In live Dubai data, the **41,027** Q4 pipeline becomes **6,441** studios because `round(41027 × 15.7%) = 6441`. The browser's Chart.js dataset confirms this. No pipeline bedroom data was queried. The title, legend and tooltip still say “Upcoming supply” and “units”; no estimate or assumption is disclosed. For individual projects, the same method applies that project's mix to its whole area's pipeline.

**Cause / affected files:** [ProjectPanel:142](/home/maan3/vv/VV-git/frontend/src/lib/components/analytics/ProjectPanel.svelte:142), chart labels at [ProjectPanel:753](/home/maan3/vv/VV-git/frontend/src/lib/components/analytics/ProjectPanel.svelte:753), bedroom controls at [ProjectPanel:1555](/home/maan3/vv/VV-git/frontend/src/lib/components/analytics/ProjectPanel.svelte:1555). Legacy frontend calculation from `b3f1ecad`.

**Recommended fix:** query actual delivery bedroom composition when available. Otherwise remove the apparent filter or explicitly label the result as an estimate and disclose its population, share and assumptions. Avoid applying project stock mix to unrelated area developments.

**Screenshot:** [undisclosed bedroom estimate](/home/maan3/vv/VV-git/docs/audits/analytics-2026-10-10/supply-bedroom-estimate.png).

### F7 — P2: subordinate API failures masquerade as empty market data

**Evidence:** browser-only HTTP 503 injection for distribution and pipeline produces “No distribution data available” and “No pipeline data available for this scope” after retries. The corrected trend failure test likewise receives “No trend data available” after HTTP 503. The summary stays visible, making these look like successful zero-result sections. Summary failure itself correctly produces an error message.

**Cause / affected files:** [trend rendering:1206](/home/maan3/vv/VV-git/frontend/src/lib/components/analytics/ProjectPanel.svelte:1206), [distribution rendering:1522](/home/maan3/vv/VV-git/frontend/src/lib/components/analytics/ProjectPanel.svelte:1522), [pipeline rendering:1581](/home/maan3/vv/VV-git/frontend/src/lib/components/analytics/ProjectPanel.svelte:1581) check loading/data but do not distinguish `isError`. Comparison has similar empty-trend handling, but its failure path was not separately browser-tested.

**Recommended fix:** render a per-panel failure state with retry; distinguish successful empty results from failed requests and label any retained stale values. Add equivalent tests for comparison and forecast failures.

**Screenshots:** [trend 503](/home/maan3/vv/VV-git/docs/audits/analytics-2026-10-10/trends-failure.png), [distribution 503](/home/maan3/vv/VV-git/docs/audits/analytics-2026-10-10/price-distribution-failure.png), [pipeline 503](/home/maan3/vv/VV-git/docs/audits/analytics-2026-10-10/pipeline-failure.png).

### F8 — P2: keyboard users cannot reliably select projects or sub-projects

**Evidence:** in real search, type Binghatti Skyrise, Tab into results, wait 250 ms, then press Enter: the list has closed and Dubai remains selected. For master drill-down, focus a sub-project button and press Enter: the dropdown stays open and selection does not change. The latter test injects only a master-capable catalogue record to bypass F4; the master summary and sub-project list remain real.

**Cause / affected files:** [ProjectSearchInput:81](/home/maan3/vv/VV-git/frontend/src/lib/components/projects/ProjectSearchInput.svelte:81) closes the whole menu 150 ms after input blur even when focus moves into it. [ProjectPanel:1049](/home/maan3/vv/VV-git/frontend/src/lib/components/analytics/ProjectPanel.svelte:1049) and [ProjectPanel:1060](/home/maan3/vv/VV-git/frontend/src/lib/components/analytics/ProjectPanel.svelte:1060) bind sub-project buttons only to `mousedown`, which Enter/Space do not dispatch. These are legacy controls.

**Recommended fix:** retain the menu while focus remains within the control; implement consistent keyboard navigation and Escape behavior. Use button click activation for both pointer and keyboard selection. Test Tab/Enter/Space with deliberate pauses.

**Screenshots:** [search after failed keyboard selection](/home/maan3/vv/VV-git/docs/audits/analytics-2026-10-10/search-keyboard.png), [sub-project Enter failure](/home/maan3/vv/VV-git/docs/audits/analytics-2026-10-10/subproject-keyboard.png).

## Limits and explicitly unverified behavior

- This is a local snapshot audit, not a production or complete external DXBI/DLD source reconciliation. Latest non-future sale in the local view is 9 October 2026. Cache expiry under a real source refresh, concurrent-user load and production deployment were not exercised.
- The registry has 2,070,461 nonempty-bedroom rows but 840,685 have property ID zero; all 1,229,776 nonzero IDs are unique in this snapshot. **The difference is not proof of duplicate homes or stock inflation.** An initial concern was investigated and excluded from confirmed findings. Physical stock completeness and identity for missing-ID rows remain unverified.
- Forecast queries, rendering and delivery anchors were inspected and populated project panels exercised. Predictive accuracy, sparse-history behavior, all date/interval edge cases, and forecast-only service failure were not exhaustively validated.
- Every project, alias, bedroom type and possible source record was not tested. Master pointer drill-down and broad master comparison need an end-to-end recheck after F4; the keyboard fixture is not proof that the live catalogue flow works.
- Anonymous rejection and the configured active test account were exercised. Cross-tenant, expired-subscription and every role permutation were not tested in this audit.
- Mobile rendering and comparison were exercised in Chromium, including dark mode. Other browser engines, touch hardware and a full screen-reader/contrast audit remain untested.
- Earlier harness-only failures (field name, nested section selector, incorrect active-button attribute, and a bedroom-list enumeration timeout) were corrected and excluded from product findings. A stalled browser rerun was stopped; final evidence uses a fresh run with traces disabled and bounded screenshots.

## Reproduction artifacts

[Backend audit tests](/home/maan3/vv/VV-git/backend/tests/unit/test_analytics_audit.py), [ClickHouse audit tests](/home/maan3/vv/VV-git/backend/tests/integration/clickhouse/test_analytics_audit.py), [browser audit tests](/home/maan3/vv/VV-git/e2e/analytics-audit.spec.ts), and [verification results](/home/maan3/vv/VV-git/docs/audits/analytics-2026-10-10/verification-results.txt) are saved alongside the screenshots. Regression tests intentionally fail until the documented defects are fixed; they are not marked skipped or expected-failure.

Backend commands:

```sh
just test-backend tests/unit/test_analytics_metrics.py tests/unit/test_analytics_empty_summaries.py tests/unit/test_analytics_market_scope.py tests/api/test_analytics_router.py tests/unit/test_analytics_audit.py -q
just test-backend-clickhouse -k analytics -q
just test-frontend
```

Browser execution used `bunx playwright test --config /tmp/vv-analytics-audit.config.cjs` from `e2e`, reusing the authenticated local test session and bypassing the normal user-creating setup. The config uses only `analytics-audit.spec.ts`, one worker and no retries. Private sessions, response snapshots and detailed logs remain in ignored `.evaluation/analytics-audit-2026-10-10/`; credentials and authenticated traces are not included in the shareable report.

Additional screenshots: [market desktop](/home/maan3/vv/VV-git/docs/audits/analytics-2026-10-10/market-desktop.png), [comparison desktop](/home/maan3/vv/VV-git/docs/audits/analytics-2026-10-10/compare-desktop.png), [comparison mobile](/home/maan3/vv/VV-git/docs/audits/analytics-2026-10-10/compare-mobile.png), [market mobile dark](/home/maan3/vv/VV-git/docs/audits/analytics-2026-10-10/market-mobile-dark.png).
