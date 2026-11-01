# Durable CRM imports

Owner CSV/XLSX, inbound CSV/XLSX and reviewed source-only JSON uploads persist a
private raw object and a PostgreSQL import/job before returning HTTP 202 with
`status: queued`. Existing import list/detail responses expose `queued`,
`processing`, `retry_wait`, `completed` and `failed`; clients poll while any of the
first three states apply. Parsing, model mapping and contact publication happen
only in a separate worker. Source-only jobs preserve their reviewed source
classification and never request warehouse enrichment.

Run locally against `.env.dev` using `just crm-import-worker`, or use
`just crm-import-worker --once` for at most one job. Deployment runs
`python -m app.crm.import_worker` in a separate private regional worker service
using the backend image and the same database/private object-storage configuration.
Drain old request-coupled import requests before the release migration. Apply
migrations through the release migrator before starting the worker. Existing
pre-worker processing imports have no durable raw input and are marked failed by
the migration so they can be explicitly deleted/re-uploaded. The HTTP
service never starts a worker or runs startup migrations.

Each worker supervisor runs one child/job at a time, with a hard 1,800-second
wall limit and a 2,048-MiB address-space limit. Child termination rolls back open
transactions; a replacement attempt reclaims the lease after expiry. CLI options
`--wall-seconds` (30–3,600), `--memory-mib` (512–8,192), `--lease-seconds` (30–900,
default 120), and `--poll-seconds` (1–60, default 5) are validated. Set a container
memory limit consistent with the child budget plus supervisor overhead, private
networking, a non-root runtime, and deployment replicas explicitly; begin with one
worker replica. Raising limits or concurrency requires a staged representative
import/RSS test. The limits are resource guards, not a claim that every maximum
500,000-row input fits the default memory budget. Upload caps remain 50 MiB for
spreadsheets and 100 MiB for reviewed JSON; reviewed payload schema retains its
existing 250,000 source-row and 100,000 reference limits.

Claims use PostgreSQL `FOR UPDATE SKIP LOCKED`, random lease tokens and separate
sessions. Heartbeats extend valid leases every lease/3 seconds. Retryable failures
wait 10/20 seconds and stop after three total attempts. Invalid/missing/corrupt
input or revoked membership/subscription fails permanently. A crashed final attempt
is marked failed by the next worker reconciliation, avoiding permanent processing
status. Workers must keep running for recovery; alert on expired processing leases,
old queued jobs, terminal failures, and stopped workers.

Before processing and again inside the fenced publication transaction, workers
check the original creator's current membership and active/trialing organization.
Tenant/creator come from server-persisted job metadata. Publication locks and
validates the current unexpired lease token before committing results and job
completion together. A stale worker rolls back, and deleting an import cascades
its job. Retry publication reuses the same import ID and one atomic transaction;
it cannot duplicate claims/enquiries after a crash. A failed owner replay retains
the previous result. Worker dropped-row logs use an attempt-specific object key,
so a stale attempt cannot overwrite the published log. Execution/publication audit
uses creator/org and job ID correlation; claim/heartbeat/retry reconciliation is
system automation and does not impersonate a new user action.

Raw objects use unique keys under `crm/<organization>/import-inputs/` in the
configured private bucket; never publish or presign them. Require regional private
storage, encryption, least-privilege API/worker object access and a documented
retention policy. The worker bounds download size and verifies raw SHA-256 and byte
length before parsing. Duplicate upload races delete only the losing upload's key.
Database failures clean up the owned raw upload; import deletion cleans its input
after the database deletion commits. Configure an operator-reviewed orphan sweep
for unreferenced input/attempt-log objects after a grace period longer than the
maximum job and retry window. Do not expire referenced pending inputs or published
drop logs. A process crash between upload and database commit can leave an orphan;
cleanup errors log only a generic event and require this sweep. An ambiguous
database commit retains the object unless PostgreSQL confirms it is unreferenced. This repository
does not provision bucket lifecycle/IAM or worker infrastructure.

An identical raw owner/source file resolves to the tenant's existing import. Inbound
identity retains raw bytes plus case-insensitive campaign context. Different
mapping options for an already queued/imported source return 409 rather than
silently reusing incompatible results. Explicit owner replay requires the original
checksum and a completed legacy resolver; deterministic saved mapping remains the
replay authority. Terminal new-import failures remain visible in history; delete
the failed import and upload again after correcting the input or dependency.
