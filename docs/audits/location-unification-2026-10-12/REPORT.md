# Location search and DXBI extraction corrections — 12 October 2026

## Scope and data decisions

Transactions sales and rentals now display a single Location column composed of available building, project and area values. Exact repeated labels are omitted. Original structured API fields and export fields remain available; no database hierarchy was flattened. A single debounced keyword input replaces the three location dropdowns; all words must match across the location hierarchy and trusted memberships. Numeric words match complete tokens, so 02 never matches 03 or 102. Suggestions may tolerate typos but typed filtering remains literal; choosing a suggestion applies its actual source name. Other property/date/value filters remain supported, with ten-row pages.

The backend uses the same predicate for lists, counts and filtered exports. Location suggestions ignore their own search restriction while retaining other filters, allowing a failed search to be corrected. Analytics uses the keyword matcher and explicitly labels project, building fallback and area scopes rather than labelling everything Project. This preserves existing aggregate scope identities; it does not introduce new building drilldowns inside named projects.

## Numbered names: evidence contradicts blanket stripping

- **02 / 03 Residence By NED Al Ghurair:** DXBI catalogue has two separate P entries, IDs 95887 and 94902. The developer's own [Current Offerings](https://ned.ae/available-properties/) explicitly uses 02 & 03 Residence. These are not demonstrated unit-number leaks.
- **08 / 09 Life Residences:** DXBI catalogue has distinct B entries, IDs 95845 and 99137, in different locations. [Deniz's own website](https://www.denizae.com/) lists both numbered names. They must remain distinct.
- **014 Tower / 1 Lake Plaza:** both occur as project labels in the stored DXBI catalogue, IDs 47138 and 34265. This establishes provider labels, not independently verified official spelling. No number was removed.
- **(D1) District One Residences:** the catalogue links individually numbered buildings to that project. The project prefix is not treated as a unit.

See numbered-name-evidence.json for retained catalogue and raw-count evidence. These raw counts are not deduplicated headline totals. Catalogue semantics are used as provider evidence; a DXBI building designation need not be the developer's marketing terminology.

## Extraction and repair safety

Property-title parsing now uses Python's HTML parser, accepting single/double quotes, class ordering and escaped characters. Only a unique explicit property title is accepted. The dynamic scraper also retains a compact explicit property title outside the columns array, reducing evidence loss if an old compact record omits detailed cells. Raw location text remains available. No person-name heuristics or leading-number stripping were added.

Both raw-report Python unit extraction and the dynamic JavaScript scraper now leave a final hidden unit empty instead of selecting an earlier building number. Explicit units and leading zeros remain preserved. This fixes a verified code-path defect; the affected historical-record count is not established.

`holocron/scripts/audit_dxbi_name_repairs.py` performs read-only proposals from retained report JSONL/gzip. It requires a unique matching detail URL and explicit property title, checks date/amount/size/unit consistency, retains the stored sale key, records before/after values and source SHA-256/line/warehouse version, and rejects loss of existing hierarchy fields. It has no warehouse-write mode. A title-bearing replay against an already corrected row yields unchanged, not another identity.

Executed on the retained 13-row sample: 8 unchanged, 4 unresolved because their detail URLs have no stored match, 1 unresolved for missing title or identity; 0 proposed repairs and 0 data writes. This is a sample dry-run, not accuracy validation for all transactions or a complete ingestion window.

The ABD ALLH SOLIMAN record remains unresolved: the original file has not been recovered and localhost browser debugging was unavailable. No invented title, guessed match or source repair was published.

## Coverage and release limits

Earlier measured baseline: 993,778 stored sale keys, 993,774 served sales and 922,850 residential Analytics sales, with the latest sale on October 9. Keyword and label changes do not fill missing ingestion windows. No new complete scrape, historical coverage certificate, production promotion, scheduled collector activation or raw-data publication was performed. The PR includes the previously local safeguards: incomplete partition reconciliation cannot authorize replacement; missing loader accounting fails; replacement files must normalize completely and stay inside the requested dates. These are validated safeguards, not proof that every historical window was collected.

Before production data repair: recover archived source manifests or an authorized authenticated collector; dry-run against a stable snapshot; review proposed corrections and identity conflicts; use validated staged publication with a retained rollback version and publication-linked cache invalidation. The existing direct raw loader is not claimed atomic. Backend facet and Analytics-search cache namespaces were advanced for the code change; publication-aware invalidation across independent data releases remains outstanding.

## Validation

Results and screenshots are appended after the final review. Initial browser failures from obsolete three-column assertions were corrected to verify the new combined field against independent API values. No failed run is counted as a passing run.

## Executed verification and review

- Focused PR branch: 354 fast backend tests, 69 disposable ClickHouse tests, 65 frontend unit tests; all passed. Svelte check: zero errors/warnings. Frontend production build passed (adapter-auto still reports no selected production target).
- Ingestion: all 37 targeted tests passed with local ClickHouse integration enabled, including replay/identity guards, replacement preflight and accounting. JavaScript scraper/session suite: 10 passed, none skipped.
- Holocron full `just check`: lint and type checks passed; 559 tests passed, 24 optional integration tests skipped. The targeted ingestion database tests above were separately enabled and executed. One pre-existing collection warning concerns a helper exception named TestStopped.
- Primary local app: 32 browser checks passed in the broad run; two obsolete three-column assertions failed. After updating those assertions, all six selected checks passed (both corrected field comparisons, three new location/Analytics cases, and authentication setup). Screenshots show actual local data, not mocks. Exact PR-branch browser results follow below.
- Self-review checked numeric identity preservation, parameterized SQL, shared count/export predicates, source-only Analytics, generated schema compatibility, cache namespaces, incomplete-window guards and preservation of unrelated checkout changes. No claim of independent human review.

## Rollout and rollback

Application code is locally reloaded and prepared on a separate PR branch based on the still-open Analytics PR #43. Deploy the dependency first. No production deployment or business-data write occurred. Code rollback restores the prior application revision; since this stage publishes no source-data changes, there is no warehouse rollback to perform. Do not run raw replacement as a shortcut to repair names: its atomic publication and historical evidence requirements remain unresolved.

Run the read-only repair command with explicit retained source files and a new output path:

```sh
just audit-dxbi-name-repairs /absolute/path/report.jsonl --output /absolute/path/new-proposals.jsonl
```

The command does not authorize or perform application of proposals. Final production data promotion requires a reviewed stable-source dry-run, staged publication/rollback verification and cache refresh across Transactions and Analytics.

Exact PR branch on ports 8001/5174: **6/6 browser checks passed**, including Compare plotted values against API data, District One configuration counts, both Transactions location searches and numbered-building scope labels.
