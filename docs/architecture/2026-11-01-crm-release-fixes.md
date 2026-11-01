# CRM read performance and durable import changes

Implementation branch: `codex/crm-release-fixes`, based on PR #53
(`claude/owner-import-brokers-cleanup`, baseline `260e3ee`). This preserves the
newer broker/import behavior and excludes the earlier uncommitted listings cache.
No operational data migration, warehouse build, cloud change or deployment was
performed. The preceding inspection describes a different audited snapshot;
measurements below explicitly identify synthetic fixtures and current checks.

## Changes and boundaries

| Inspection area | Implemented behavior | Remaining boundary |
|---|---|---|
| Owner revisions and cold reads | Indexed tenant revision tokens; statement triggers cover ORM/direct writes, reassignment and rollback. Non-reused sequence values prevent rolled-back cache-token collisions. Compact JSONB evidence/header projections retain original documents unchanged. | Full owner profiles still build/filter per organization; request admission bounds overlapping work. Representative live-data RSS/load acceptance remains. |
| Rental lead precompute | Shared pure SQL in both runtimes; validated downstream asset, staging/guard, previous artifact, atomic exchange, full-input/view/transform fingerprint and live fallback. Area pruning retains selected-area reads. | `CRM_RENTAL_BASE_ENABLED` defaults false. Inputs must be quiescent for publication; metadata stability is not a global atomic source snapshot. |
| Exact-area correctness | v2 publication policy rejects a pre-ranking identity spanning distinct exact display-area labels, even if their normalized identity keys collide. Old unchecked markers are rejected. | Unsafe/changed inputs keep the live query; identity normalization and ranking rules are unchanged. |
| Frontend identity and requests | Identity-scoped keys, synchronous eviction/remount, late-response/write protection, shared concurrent reads and one registry request instead of five. | Real GoTrue identity integration remains a deployment acceptance check. |
| Pagination and completeness | Fixed-size offset renewal pages, accumulated rows beyond 200; capped lead/inbox and page-local owner filters are labeled honestly. Unsupported toggles/workflows are unavailable or deferred. | Complete server filtering/search over every lead/inbox row remains future contract work; this change does not claim uncapped results. |
| Matching reads | Valid empty results remain reads; explicit refresh performs generation. Ignored options no longer multiply query keys. | Matching quality and ownership-rule promotion still require domain acceptance. |
| Imports | Owner, inbound and source-only uploads persist private input manifests and return HTTP 202. One bounded worker claims durable jobs, revalidates authorization, verifies input, fences every publication and handles leases/retries/replay. | Deploy the worker with the web/client release; provide private storage policy, retention/orphan reconciliation and workload sizing. |
| Import status and polling | Queued/retry states render distinctly from completion. Polling backs off to 60 seconds and invalidates relevant current-identity views at completion. Import metadata composition removes source-list N+1 queries. | Cross-navigation watch IDs are session-only; after a full reload, open import history to resume watching active jobs. |
| Admission and cancellation | All CRM route aliases share worker/tenant admission. Warehouse queries share a semaphore, memory/thread/deadline settings. Blocking parsers/projections retain admission until cancelled threads actually finish. | Limits are per worker; deployment must budget the sum across processes/replicas. WAF/global controls remain operational. |
| Upload expansion | XLSX member/expanded-size/shared-string/ratio checks precede decoding; CSV/worksheet row and column materialization is bounded. | Proxy/multipart limits, malware policy and representative hostile-file/staging qualification remain deployment controls. |
| Mutation audit and isolation | Atomic, metadata-only append-only mutation records on private CRM stores. Actor identity is applied to an auth-opened transaction and later transactions. Tests exercise real membership checks, two organizations, warmed caches and denied storage/mutations. | This is not a complete private-read/admin/assistant security trail or privileged-admin-proof archive. Protected archival and production DB-role review remain. |
| Other release gates | Existing digest, redaction and provider-retention controls are preserved. | External AI/provider approval, backup/restore, licensed operator-host publication, data-quality acceptance and production cutover/load checks are not established by this PR. |

## Migration and rollout

1. Verify staging backups/recovery and drain old request-bound imports. Use a
   controlled migration window: projection backfill takes locks, and the durable
   import migration marks interrupted legacy processing rows failed because no
   durable original input exists for them.
2. Apply `b6c2e9a4f871` (compact sources/revisions), `c7d3f0b5a982` (durable jobs)
   and `d8e4a1c6b093` (mutation audit), in that order, using the production migrator.
   Fresh-database and upgrade/downgrade/model agreement were tested in disposable
   PostgreSQL databases. Do not disable the private-store TRUNCATE guard to run
   normal application operations.
3. Provision the private input prefix and start the bounded worker described in
   [the worker runbook](../crm-import-worker.md). Deploy the API and regenerated
   frontend together: three upload endpoints change from synchronous HTTP 201
   completion to HTTP 202 acceptance, with queued/retry states.
4. Set worker/replica resource budgets. Defaults per web worker are two admitted
   CRM requests, two per organization, one warehouse query, 3 GB/query and two
   query threads. Warehouse statements have a 60-second deadline. The import
   worker has separate process memory/wall limits; validate them on real fixtures.
5. Keep rental precompute disabled until the downstream publication and fallback
   contract in [the rental runbook](2026-11-01-crm-rental-ranked-base.md) passes
   staging acceptance. Only then enable `CRM_RENTAL_BASE_ENABLED`.
6. Verify access/audit/queue progress, old-client refresh, crash/retry and rollback
   behavior before inviting pilot users. See [mutation audit details](2026-11-01-crm-mutation-audit.md).

## Evidence

- Full backend fast suite with dummy credentials and sockets blocked: **1,473
  passed**, no skipped tests.
- Full disposable PostgreSQL suite: **98 passed**, no skips. This includes real
  authorization-database reads before first-mutation audit attribution.
- Full disposable ClickHouse suite: **105 passed**, no skips; 75 full-column
  equivalence cases plus the exact-area collision refusal/fallback regression.
  Selected-area reads were 8,192 versus 25,041 in the seeded fixture.
- Import stream follow-up: seven real-SDK wrapper regressions pass for short
  network chunks, corrupt/truncated/oversized objects and response cleanup; all
  25 durable-job PostgreSQL tests passed again. Reads consume at most the saved
  size plus one byte before checksum/size validation.
- Frontend: **327 unit tests**, **15 mocked browser guards**, type check with zero
  errors/warnings, lint and production build passed. Browser guards include two
  identity transitions, 230 renewal rows and both queued upload/navigation flows.
- Holocron full check: format/lint/types passed; **590 passed, 32 existing optional
  tests skipped**, one existing collection warning.
- Backend lint/format, client generation and whitespace checks passed. The local
  backend image built successfully; its API/worker import and CLI smoke checks
  use dummy configuration with networking disabled.
- Synthetic 1,000-row SQL comparison: original/compact evidence was
  16,542/161 bytes per selected test row; one run measured 78.651/2.891 ms. This
  isolates a synthetic projection, not full request latency or production sizing.
- Independent verifier reproduced and closed first-transaction audit, alias
  admission, cancelled preview and exact-area precompute issues. Final verdict:
  pass, no remaining review findings.

Not run: production deployment, existing-data migration/warehouse rebuild, live
provider calls, real-identity browser acceptance, representative production RSS,
concurrent load, cloud privileges or backup restore. Their absence is not a claim
that these checks passed.

Crew: three `crew_scout` agents used gpt-6-luna/high; five scoped `crew_builder`
agents and the fresh `crew_verifier` used gpt-6.1-sol/high. The planner integrated
shared changes and PR delivery. No model fallback or worker commits/pushes.
