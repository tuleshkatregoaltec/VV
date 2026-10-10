# Transactions and Analytics stack merge review — 10 October 2026

The user authorized reviewing and merging PRs [#40](https://github.com/Kian-Sham/VV/pull/40), [#41](https://github.com/Kian-Sham/VV/pull/41) and [#42](https://github.com/Kian-Sham/VV/pull/42) into `VV`. This review covers the combined application, including the prerequisite ingestion changes; it does not authorize or perform production deployment.

## Decision and scope

No additional merge-blocking defect was found in the reviewed stack. The 14 previously confirmed defects are resolved by #42, with evidence and remaining audit limits in [REPORT.md](REPORT.md). This is a code review by the implementing agent, not a claim of independent human approval.

| PR / reviewed application head | Review coverage | Conclusion |
|---|---|---|
| #40 / `574b0040289c5f439c3e544edae6ae2181a0115e` | Morning sales refresh, shared account lock and failure markers; rental normalization v6; DXBI place hierarchy and atomic table replacement; place joins and project filters; typed API contracts; Transactions desktop/mobile tables and theme changes. | Consistent with the DXBI source semantics. Requires the warehouse and ingestion release steps below. |
| #41 / `aed5309f6d351f4da1bf4356c1989560a71833ab` | Recorded bedroom attribution, median positive unit sizes and square-metre conversion, measured price percentiles, sparse-registry suppression, response mappings and frontend labels. | Counterexample tests cover outlier unit sizes, skewed prices and unknown rental bedrooms. The registered-unit ratio remains a coverage-limited indicator, not proof of complete physical stock. |
| #42 / `1c35ba40debd56420a35541199ec69868485ddeb` | Deduplication identities, effective export filters, canonical Analytics scopes, pipeline dates and stock carry, cache namespaces, generated contracts, loading/error/retry states, keyboard selection and modal focus. | Original audit regressions pass. Application code is unchanged by this review documentation commit. |

The review traced immediate callers, shared scope predicates and cache handling rather than inspecting isolated changed lines. Pipeline and price-distribution routes are not server-cached; changed cached summaries, transaction lists and facets use versioned namespaces. Existing subscription guards remain on the data endpoints. No auth, PostgreSQL migration or tenant-data ownership behavior changes in this stack.

## Verification evidence

The combined application already passed 353 backend tests, 53 isolated ClickHouse tests, 59 frontend unit tests, 40 browser cases and 405 independent Transactions source/API reconciliation checks. Analytics source/API reconciliation and screenshots are linked in [REPORT.md](REPORT.md). These results were obtained on the application code reviewed here and were not presented as newly rerun tests during merge review.

Additional merge-review validation covers Holocron formatting, lint, types, the offline suite and the suite with isolated local ClickHouse integration enabled. Exact outcomes are appended to [verification-results.txt](verification-results.txt). The daily/morning shell entrypoint passes `bash -n`. The aggregate diff passes `git diff --check`. Each original PR head has successful `backend-offline`, `frontend-check` and `holocron-check` GitHub checks.

## Release prerequisites and remaining limits

1. Before deploying this API, create **and populate** `dxbi_places` through the updated completed-sweep loader. The new query joins this table unconditionally: an absent table makes Transactions requests fail, and an empty table only provides parsed-name fallbacks. Its DDL is also included in the canonical Holocron schema. Confirm labels and Project facets after loading.
2. Apply the reviewed rental normalization v6 migration through the normal warehouse release procedure, then validate whole-building rental labels/types. This review did not run the migration against production data.
3. Install the updated daily script and morning service/timer using the [location-sweep runbook](../../../holocron/docs/runbooks/dxbi-location-sweep.md). Validate a completed morning run and its subsequent evidence load. The script shares the sales account lock with the location sweep; actual timer execution and provider sessions were not exercised here.
4. Deploy backend and frontend together, then repeat the authenticated smoke checks and source reconciliation in the destination environment. Missing project metadata and registry coverage remain source limitations documented in the audit report.

Production ingestion, deployment, concurrent-user load and exhaustive testing of other consumers of the shared CSS/modal remain unverified. These are explicit coverage limits, not passing test claims. The existing unrelated edit to `docs/data-pipelines/UNIFORM_LAYER_CHANGES.md` is excluded.

## Landing procedure

Merge #40 into `VV` with its reviewed head pinned, retarget #41 to `VV` and merge it, then retarget #42 to `VV` and merge it. Preserve ancestry with merge commits, verify each retargeted diff and head, and check that the final `VV` application tree matches the tested stack. GitHub workflows run validation on `VV`; the repository's image publication/deployment workflow targets `production`.
