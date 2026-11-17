# Transactional CRM mutation audit

Migration `d8e4a1c6b093` follows durable imports `c7d3f0b5a982`. It adds
`crm_mutation_audit` and PostgreSQL statement triggers to the sixteen private
CRM stores: owner imports/lists/claims/workspaces/notes, lead workspaces/notes,
saved leads, area preferences, inbound imports/contacts/enquiries/notes/activities/
matches, and durable import jobs. Derived owner revision tokens and shared public
licensed-broker reference data are excluded.

Each INSERT/UPDATE/DELETE appends one event per affected organization, statement,
and table. The record contains actor ID/type, database principal, organization,
server-generated request/job correlation ID, action, table resource, success
outcome, affected row count, and database time. It contains no customer row keys,
owner keys (which can contain phones), contact values, bodies, headers, URLs,
filenames, before/after field copies, or free-text notes. A 100,000-row statement
creates one event per affected organization, rather than 100,000 payload copies.
ORM statements, direct SQL, cascades, source imports, worker jobs, and bulk writes
use the same mechanism. ORM executemany may emit several statements and events;
this is statement aggregation rather than one event per HTTP operation.

The event commits in the mutation's transaction. A rollback discards both. If
inserting an audit event fails, the private write fails too. Only successful,
committed mutation metadata is retained: rejected attempts and rolled-back
operations do not become misleading successful events. UPDATE tenant moves from
unscoped system writers record both old and new organizations. Row counts for an
UPDATE are the greater of the old/new affected counts for that organization.

## Trusted actor context

`app.postgres.actor_context.transaction_actor(actor_id=..., organization_id=...,
request_id=...)` sets task-local context. Enter it **before the first database
operation of the transaction**, in the same async task that executes the work.
The generic PostgreSQL engine begin hook copies it to transaction-local settings
with bound values. Every service commit/new transaction reapplies context; pool
reuse with no context clears it. There is no CRM dependency in infrastructure.
Synchronous FastAPI dependencies must not set this ContextVar because their thread
context does not propagate back to the request task.

The CRM router's async dependency uses the authenticated organization/user and a
fresh server-generated UUID. It never accepts a client-selected actor or request
identifier. Durable workers must revalidate the queued creator's current
membership and subscription before processing and enter creator context before
any processing transaction begins. Claim/lease housekeeping without user context
is explicitly attributed to the PostgreSQL principal (`actor_kind=database`),
not to a fabricated authenticated user.

The trigger derives every event's organization from transition rows. When user
context exists, any affected old **or** new organization differing from the
context aborts the entire statement. Incomplete user/org settings fail closed.
These settings are trusted application metadata; anyone with arbitrary database
credentials can set custom PostgreSQL settings. They are not a replacement for
application authentication, scoped reads, membership checks, or least-privilege
SQL access.

## Append-only enforcement and operations

Statement triggers reject audit UPDATE, DELETE, and TRUNCATE, including direct
SQL. An insert guard rejects direct audit INSERT outside another trigger. All
private-store TRUNCATE operations are rejected because they bypass transition-row
mutation auditing. Delete private data through normal scoped DELETE operations.
The audit function uses invoker rights and a schema-qualified audit target; it
does not use SECURITY DEFINER.

Use separate migration and application database roles in production. The runtime
role needs ordinary private-table DML plus audit INSERT/sequence usage for invoker
triggers; it must not own these tables, disable triggers, create replacement
functions/triggers, or hold superuser/replication privileges. Enforce the reviewed
production privilege policy rather than granting DDL to the application. Migration
downgrades intentionally remove these controls and require privileged maintenance.

This table is **not immutable against a privileged database administrator**. A
superuser/table owner can alter/drop triggers or tables and delete data. Protected
regional archival, retention/legal policy, role provisioning, tamper detection,
monitoring, and restore drills remain operational release requirements. Do not
purge or truncate this table to implement ordinary contact deletion.

## Evidence and remaining boundaries

Run `just test-backend-postgres -k 'mutation_audit or tenant_http' -q`.
The recipe always includes the PostgreSQL directory; use `-k` to narrow selection.
The existing fixture creates and migrates a uniquely named disposable local
database and drops it after the run. No live CRM data or auth users are required.
The actor hook is installed on the isolated test engine as it is in production.

The tests exercise real PostgreSQL statements/triggers and production CRM routes
through ASGI. Two mocked authenticated user/org contexts cover tenant-private
imports/lists/profiles/history/notes/workspaces/matches and object-access denials,
with caches warmed in both tenant orders and mocked membership revocation.
Storage and freshness adapters are deterministic fakes; source-only evidence avoids
warehouse calls. These are authenticated-context boundary tests, **not end-to-end
GoTrue login or real object-storage authorization tests**.

Successful private reads, exports, admin access, assistant tool access, denied
requests, and other platform domains do not yet have a complete durable security
audit trail. HTTP post-response logging is deliberately not presented as an atomic
mutation audit. This change does not close the complete platform audit/archive,
backup/restore, external provider approval, or production identity acceptance gates.


HTTP authorization may open the shared session before actor context is available.
The CRM async dependency therefore applies the verified actor to that current
transaction with `apply_actor_context`, while the engine begin hook sets it again
for every later service transaction. Requests without a started transaction do
not connect merely to establish actor context. Real authorization-database tests
cover attribution and cross-organization rejection on the first commit.
