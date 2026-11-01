# Claude production decision handoff

Review snapshot: 2026-10-31, intended for branch `codex/ai-production-review-20261031` in the existing **private** `Kian-Sham/VV` repository. Commit and publication are managed separately by the coordinating reviewer. The containing Git commit identifies the published snapshot; the evidence records its original base commit and selected source hashes. This is a source review handoff, not authorization to deploy or connect providers.

The snapshot includes pre-existing CRM, UI, import and archive/source changes alongside the assistant implementation. Do not attribute every change to the assistant work. Inspect those areas independently if they are in the proposed production release. Ignored environment files, credentials, local datasets, database dumps, browser sessions, raw audit reports and generated build output are excluded. A fresh clone must not depend on an ignored local `CLAUDE.md` or any unavailable local file.

## Reading order

1. [Repository rules](../AGENTS.md), [development workflow](../development.md) and [canonical recipes](../justfile).
2. [Production reference](../production-readiness-2026-09-29.md), especially identity/tenancy, AI/privacy, launch acceptance and release policy. Its September repository observations describe an older snapshot and its absolute links refer to that old checkout: resolve paths from this repository and verify current code. Recommendations are not evidence of deployment.
3. [Current assistant architecture and planned connectors](ai-assistant-architecture.md). The connector section explicitly describes future work.
4. [Sanitized verification/advisory evidence](review-evidence/ai-assistant-2026-10-31.json). Read its limitations before interpreting counts.
5. [Runtime orchestration](../backend/app/chat/agent.py), [typed workflows](../backend/app/chat/workflows.py), [admission](../backend/app/chat/admission.py), [delivery/history](../backend/app/chat/service.py), [output guards](../backend/app/chat/security.py), [private retrieval](../backend/app/crm/assistant_repository.py) and [shared accounting](../backend/app/token_usage/repository.py).
6. [Action schemas](../backend/app/assistant_actions/models.py), [action service](../backend/app/assistant_actions/service.py), [repository](../backend/app/assistant_actions/repository.py), [confirmation routes](../backend/app/assistant_actions/router.py) and [dormant provider boundary](../backend/app/assistant_actions/adapters.py).
7. [Action migration](../backend/migrations/versions/8a4c1e6b0d93_assistant_actions.py), [admission migration](../backend/migrations/versions/9b5d2f7a1e04_chat_admission.py), [telemetry policy](../backend/app/core/observability.py), [application initialization](../backend/app/main.py) and [database initialization](../backend/app/postgres/client.py).
8. [Chat API wrapper](../frontend/src/lib/api/chat.ts), [query builders](../frontend/src/lib/queries/chat.ts), [shared conversation selection](../frontend/src/lib/chat/conversationSelection.svelte.ts), [action card](../frontend/src/lib/components/chat/ChatActionCard.svelte), [market chat](../frontend/src/routes/chat/+page.svelte) and [CRM assistant](../frontend/src/routes/crm/assistant/+page.svelte).
9. [Security unit tests](../backend/tests/unit/test_chat_security.py), [research tests](../backend/tests/unit/test_chat_workflow_research.py), [private-history tests](../backend/tests/integration/postgres/test_chat_workflow_security.py), [admission tests](../backend/tests/integration/postgres/test_chat_admission.py), [action persistence tests](../backend/tests/integration/postgres/test_assistant_actions_persistence.py), [warehouse tests](../backend/tests/integration/clickhouse/test_chat_capabilities.py), [browser tests](../e2e/chat.spec.ts) and [synthetic model-trial harness](../backend/scripts/evaluation/model_trial.py).

## Implemented boundaries to challenge

The PydanticAI orchestrator delegates to five typed workflows: market research, pricing/comparables, personal CRM retrieval, follow-up planning and action preparation. They share authenticated identity, turn-local evidence and usage limits. There is no arbitrary SQL, shell, generic HTTP or execution tool. Private CRM details share a cumulative **ten-row budget per turn**; numeric aggregates remain supported. Files, document generation, download workarounds, secrets and raw contact/database dumps are outside the assistant's allowed capabilities.

Private retrieval enforces current assignment and organization, including own imported claims, authorship and current parent access. An organization owner does not gain access to colleagues' private CRM. Reassignment, removed membership and inactive subscriptions must revoke private answers, history and proposals. Market chat and the CRM assistant share an authorized persisted conversation. Follow-ups carry only freshly reauthorized handles; historical private prose is not fresh evidence and facts must be retrieved again.

Internal writes require a persisted exact proposal and a separate authenticated application confirmation of its ID. The model cannot confirm. The server locks and reauthorizes current targets, compares their snapshot, enforces expiry/idempotency and executes only the stored payload. Lead mutations, notes, reminders, internal viewings and private listing drafts are implemented. Reminders have no notification delivery; internal viewings do not send calendar invitations. External actions remain disconnected: confirmation returns `not_connected`, never proof of sending, booking or publishing. A typed adapter/outbox contract is not a live connector.

Before content SSE or persistence, the complete buffered response is checked and its private evidence reauthorized. Limits are **24,000 tokens reserved**, **16 model requests**, **24 tool calls**, **300 seconds execution**, **600 seconds admission lease**, **20 active turns per organization**, and **one per user and conversation** across workers. Failed/expired runs conservatively retain reservations; expiry frees concurrency, not credit. Verify every writer participates in the ledger. These limits and provider response caps are not hard dollar guarantees.

Provider requests ask for `zdr: true` and `data_collection: deny`. Verify actual approved endpoints, contracts, residency and telemetry routing independently; request flags are not a privacy certification.

## Planned first three connectors

Mail, calendar and WhatsApp are plans, with no implemented connector domain, grants, callbacks, workers, onboarding, migrations or provider verification implied. Gmail/Outlook mail ingestion is initially read-only and creates private candidates for agent approval. Google/Microsoft calendar availability precedes separately consented exact-approved booking and invitations. Incremental outbound email is a later stage.

Keep both WhatsApp modes distinct: an organization assistant number receives commands only from an authenticated user's revocable phone-possession link; each agent's customer business number receives customer evidence through official business onboarding. Customer threads never inherit agent tools or merge into private assistant history. Plain “yes,” forwarded approvals and inbound messages cannot execute actions. Evaluate Meta policy/eligibility and coexistence for the selected flow before promising support.

Connection consent follows authenticated membership/entitlement and is optional. Provider identity never substitutes for application organization/ownership checks. Planned encrypted grants, durable webhook inbox/jobs, scoped deduplication, refresh/disconnect/offboarding, provider-specific reconciliation and calendar conflict checks need implementation and failure tests. Uncertain provider outcomes must not cause automatic duplicate sends or bookings.

## Evidence and release limits

Prior implementation verification records 1,544 offline backend tests (no skips), 74 disposable PostgreSQL tests, 103 disposable ClickHouse tests, 309 frontend tests and 10 mocked browser tests passing; frontend lint/type checks and production build also passed. Independent focused review recorded 114 offline, 35 PostgreSQL and 25 ClickHouse checks. These historical results are not proof that the full source snapshot is deployable or that live models/providers work.

**Final full-snapshot verification:** the coordinating reviewer reports `just check-all` exited successfully: 1,544 backend tests passed with no skips, 309 frontend tests passed across 30 files, and backend Ruff lint passed. Canonical backend formatting fixed the three earlier baseline failures (`cli.py`, `namespace_delivery.py` and `test_owner_recovery_handoff.py`); that formatting blocker is resolved. Frontend Biome checked 349 files with warnings and no fixes applied. Six whitespace-only cleanups were also made, and the global `git diff --check` passed. The 74 PostgreSQL, 103 ClickHouse, 10 mocked browser tests, frontend build and zero-error/zero-warning type check above are earlier verified checkpoints; they were not rerun during this publication turn.

The preserved dependency snapshot has **293 backend advisory entries affecting 35 packages**, not 293 unique CVEs, and **30 affected frontend packages** after DOMPurify 3.4.17. Exact duplicate records are deduplicated in the evidence, but package/advisory aliases can represent the same vulnerability. Missing version/severity/fix metadata means unknown, not safe. Remediation, reachability analysis and refreshed audits remain open. Bandit scanned 29 files without scanner errors and reported two reviewed warnings: B104 (medium, existing network bind) and B112 (low, dropping failed/inaccessible follow-up handles). Neither has become a zero-finding scan. No penetration test, ASVS conformance or security certification is claimed.

Only disposable databases were migrated in verification. No application or production database migration, deployment, live send, invitation or publication is included. **Pause all AI usage writers for the ledger cutover**, migrate once with the release migrator, switch every writer, reconcile accounting and then resume. Legacy usage rows remain preserved. Automatic admission-migration downgrade is deliberately refused; rollback requires operator-reviewed ledger reconciliation or a compatible fix forward, not dropping ledgers.

The requested live four-model comparison remains pending because its credential expired. No live trial winner, production-model switch or comparative quality claim was established. The mock suites cannot substitute for that evaluation.

Buffered SSE currently has no heartbeat. Validate finite proxy/load-balancer idle and total request timeouts against the 300-second deadline and 600-second lease, plus cancellation, disconnect, drain and settlement behavior on the actual deployed path. Production SSO/identity migration, privacy/procurement, backups/restore, load/failure qualification and release approval remain separate gates.

## Copy/paste review request

```text
Independently review this private VV source snapshot for a production decision. Read
AGENTS.md, development.md, justfile, production-readiness-2026-09-29.md,
docs/ai-assistant-architecture.md, docs/ai-assistant-production-review.md, and
docs/review-evidence/ai-assistant-2026-10-31.json first. Use the handoff's reading
order to trace code, callers, migrations and tests. The containing Git commit is
the review revision; record its SHA and the scope you actually inspected.

Do not accept prior agents' PASS statements as your verdict. Verify implementation
claims from code, distinguish current behavior from plans, and inspect meaningful
negative tests. This full source snapshot includes pre-existing CRM/UI/import
changes; inspect them independently if production release scope includes them.
The September architecture reference describes an older checkout: map its paths
to this repo and identify which findings remain, were resolved, or changed.
Do not depend on ignored local CLAUDE.md, secrets, datasets or raw audit files.

Give separate GO / NO-GO decisions for (1) a bounded internal pilot, (2) private CRM
reads, (3) confirmed internal CRM writes, and (4) each planned provider connector
and external-write capability. State the exact data, users, environment and
restrictions of any GO. Treat missing evidence as an explicit gate, not a pass.

Prioritize ranked, actionable findings with severity, repository path and current
line number, triggering scenario, impact, smallest fix and acceptance check.
Separate demonstrated defects from unverified deployment assumptions and policy
or procurement decisions. Include counterevidence and residual uncertainty.

Challenge current assignment/organization isolation (including owner access),
revoked membership/subscription, private history and fresh follow-up handles,
shared ten-row detail limits, typed tool boundaries, exact persisted confirmation,
stale target snapshots, concurrency/idempotency, output reauthorization, telemetry,
provider policy and cross-worker spend accounting. External not_connected state
must never be described as delivery. No files/raw dumps or customer-message tool
execution should become possible through another specialist or channel.

Produce the minimum Phase 1 architecture for one enterprise of about 150 users.
Keep the modular monolith, existing PydanticAI runtime and PostgreSQL job/outbox
approach unless measured evidence warrants more. Identify decisions to keep,
change before launch, or defer; do not add frameworks by default. Separate code
implemented today from mail/calendar/WhatsApp plans. Cover both WhatsApp modes,
read-only intake vs exact-approved writes, identity linking, consent and scope
reduction, offboarding, webhook replay, grant rotation, uncertain delivery and
provider-specific idempotency/reconciliation. Confirm current vendor requirements
from primary sources if making new policy/scope claims; date your evidence.

Provide a concrete migration, staged rollout and rollback decision. Account for
pausing AI writers during the usage-ledger cutover, the intentionally unsupported
automatic downgrade, reconciliation and preserved legacy rows. No application or
production DB migration/deployment has been performed. Test real edge SSE idle/
request timeouts, no-heartbeat buffered answers, disconnects, cancellation, task
drains and usage settlement. Define staging/load/restore evidence still needed.

Address enterprise SSO/immutable identity mapping, permissions, approved model
endpoints and processing locations, telemetry retention, customer/provider privacy
and procurement, data licenses and operational ownership. Do not infer that AWS,
Cognito, signed artifacts or privacy request flags have already been provisioned
or validated. Separate advisory remediation from scan interpretation: 293 backend
entries across 35 packages are not unique CVEs, 30 frontend packages remain in
the recorded audit, and two reviewed Bandit warnings remain. Refresh verification
for the exact revision before any release recommendation.

Live four-model trials are pending an expired credential, with no selected winner.
Do not claim live quality from synthetic tests. Do not call providers, send messages,
read secrets/customer datasets, apply application DB migrations, deploy, or alter
code during this review. Return the four decision groups, ranked code findings,
a current-versus-planned architecture table, and a short ordered acceptance plan
with owners/decision inputs and explicit evidence gaps. This is a production
review request, not authorization for production actions or a security certificate.
```
