# CRM assignment recovery handover — 13 November 2026

Branch: `feat/crm-lead-assignment-next`. All work is uncommitted. Nothing was pushed,
deployed, or applied to the existing application database. Existing UI design is retained.

## Implemented and checked

- Same-team reassignment restarts the saved rule timeout and updates its assignment revision
  under the lead lock. A worker holding an old selection rechecks the new timer. Rotation
  continues in the original order, skipping the current and previously tried agents; exhaustion
  releases to the same team's pool. A team change ends the old rotation, including when the
  assignee belongs to both teams and stays the same person. Notes do not stop rotation.
- Owner approval attempts persist their start time and attempt count. Abandoned attempts become
  failed/retryable after 30 minutes when listed or approved again. Live processing is fenced
  across commits by a PostgreSQL advisory lock on the organization/file digest. Processing uses
  that same connection: losing the fence prevents the old attempt continuing its writes.
- Retries reuse completed imports or replay the existing import identity. A processing result
  is never reported as approved. Held bytes must match the stored digest. Private input is kept
  after failure, so an authorized manager can retry.
- An agent in multiple teams selects the owner file's owning team. Only that team's supervisor
  or an Organisation Admin/Owner may approve. Teamless agents require an administrator.
  Ordinary lead imports and agent self-import remain unchanged.
- The rotation worker has a runnable health command, bounded polling interval, per-lead graceful
  shutdown, failure reports, and protection against alert failures and busy-batch spinning.
  Compose health configuration and ECS/Fargate operating instructions are in `development.md`.
- Sidebar roles/navigation come from backend assignment capabilities: supervisors show Manager,
  ordinary agents have no Manager view/Lead Routing links. Backend checks remain authoritative.

## Verification evidence

| Check | Result |
| --- | --- |
| Targeted PostgreSQL assignment, visibility, approval and replay suite | 56 passed on a disposable migrated database |
| Final owner recovery/replay suite | 13 passed, including terminating the processor's disposable DB connection |
| Final cross-team reassignment rerun | 2 passed, including the same assignee moving teams |
| Backend worker/import/routing/API checks | 41 passed; two AsyncMock warnings in the existing empty-import fixture |
| Frontend assignment unit checks | 11 passed |
| Frontend full unit suite | 275 passed, 2 failed in `crm-backend.test.ts` (calendar read/write expectations) |
| Frontend type check | 0 errors, 0 warnings |
| Final focused CRM browser suite | 11/11 passed: roles/navigation, team administration, imports, selected-team owner upload, languages and 1440px/390px routing controls |
| Final full guard browser suite | 20/21 passed; `admin-organizations` timed out waiting 5 seconds for the Organizations heading, then passed 1/1 when rerun alone. All CRM and auth-guard cases passed. The full run is still recorded as 20/21. |
| Changed Python / frontend files | Ruff and targeted Biome clean; `git diff --check` clean |
| Generated client | Regenerated successfully; final repository-wide lint still reports 6 errors in untouched files |
| Worker CLI health | Missing heartbeat exits 1, fresh exits 0, stale exits 1 |
| Compose validation | Syntax passes; environment warns that `POSTGRES_PASSWORD` is unset; this is not a runtime deployment check |

The initial full guard run had 13 passes and 6 failures (four auth redirects and two CRM
first-load/navigation cases). A later native-module stall was terminated, not counted as a pass.
The quarantined `fsevents` packages were replaced from the official npm registry at their exact
existing versions (frontend 2.3.3; e2e 2.3.2), without changing manifests/lockfiles or disabling
macOS security. Browser tests now wait for their scope response before checking navigation.

## Remaining blockers and limits

1. The real migrations `f6a8c2d4e9b1` and `c3e7a1f9d2b6` were not recovered. Local history/files
   contain only placeholders; the upstream `vitevue/vitevue-platform` remote reports repository
   not found/inaccessible. Authoritative files must be supplied, not invented or bypassed by stamping.
2. Fresh disposable databases upgrade to `b2d4f6a8c0e2`, but the full schema comparison still
   reports 10 drift items from the missing migrations. Fresh setup is **not** production-valid.
3. The existing application database was inspected read-only: it is at `a7c9e1b3d5f2` and lacks
   the new attempt, lease, owning-team and tried-agent columns. Apply `b2d4f6a8c0e2` through the
   controlled migration process before using these changes against that database. No stamping
   or schema changes were performed there.
4. Large owner imports remain request-bound. Crash recovery is implemented; moving execution to
   durable background jobs, as required by the production architecture, remains a launch risk.
   The processing fence requires direct PostgreSQL or session pooling, not transaction pooling.
5. No production worker, health replacement policy, alarm or real Honeybadger delivery was deployed
   or tested. Alerts were tested with injected failures, without paid/external monitoring calls.
6. Agent ratings and performance-based routing remain pending product definition. No ranking
   metrics were invented.

Full backend suites, real-auth browser tests and a live Assistant/model conversation were not
rerun. Browser checks use the real frontend with mocked APIs; they do not establish a deployed,
real-auth end-to-end workflow. The project is not production-ready.
