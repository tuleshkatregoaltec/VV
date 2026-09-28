# Backend architecture and migration

The backend remains a modular monolith organized by business responsibility.
The approved Phase 0–7 migration preserves endpoint paths, operation IDs, request
and response schemas, SSE events, stored JSON, source identifiers, query rules,
transaction boundaries, provider arguments, and frontend behavior.

## Placement and dependency rules

- HTTP endpoints belong to the owning `router.py`: parsing, guards and serialization.
- Application operations belong to the owning service or named capability module.
- Pure rules, identity, geometry, scoring and mapping have no database/provider I/O.
- PostgreSQL SQL belongs to the owning repository; use the caller's session.
  Application operations retain the existing commit/rollback sequence.
- ClickHouse SQL construction and execution belong to the owning query module.
  `app/clickhouse` contains the client, not business query templates.
- Cross-domain calls use public application operations or contracts. Do not import
  another domain's repository, private helper, router or internal query module.
- `market/reference.py` owns shared market names/units; `market/scope.py` owns
  canonical transaction/project scope predicates. Supply owns its public Reelly
  eligibility predicate. These pure helpers are explicit cross-domain exceptions.
- Chat owns conversation/turn lifecycle, agent setup, thin tools, artifact rendering
  and events. Tools call domain capabilities; domains never import chat.
- CRM separates imports, identity, owners/ownership, inbound, matching,
  opportunities, workspaces and reports. Owners never call import orchestration.
- Project owns catalogue and radar. Plots owns GIS/DDA geometry, evidence and
  valuation. Feasibility consumes public plot/project operations through research.
- Feasibility separates saved studies, research, generation, deterministic
  assumptions and agents. Generation calls the HBU agent, never the reverse.
- Admin composes account capabilities and owns no repository. Auth profile
  composition is separate from identity to avoid an organization/auth cycle.
- Provider adapters own SDK/HTTP mechanics. Domain prompts remain in their domain.
- `core/dependencies.py` and authentication middleware are entry adapters allowed
  to compose domain operations. Other core/infrastructure modules are domain-free.
- The PostgreSQL model registry is for migration registration, not runtime imports.
- Add files only for meaningful boundaries. No generic repository framework,
  factories, microservices, queues or interfaces are introduced by this migration.

## Verification

Use `just` with supported host Node/Bun/Python runtimes. `just lint-backend` is
non-mutating. `just test-backend` runs the fast suite and accepts exact pytest
arguments. Database suites run separately against generated test databases;
required unavailable services fail rather than silently skip. Never point an
integration fixture at production. Unit SQL mocks do not prove database behavior.

Tests live in `tests/unit`, `tests/api`, `tests/contracts`, `tests/architecture`,
`tests/agents`, `tests/streaming`, and `tests/integration/{postgres,clickhouse,infrastructure}`.
Run frontend tests/builds and relevant Playwright flows throughout the migration.
Capture expectations before extraction; never refresh a contract fixture merely
because the refactored implementation differs.

## Compatibility exceptions

Existing HTTPException behavior may remain at application boundaries initially.
Pure rules/repositories must not acquire HTTP dependencies. Preserve current
multi-commit workflows, user/org scoping, read-triggered CRM matching refresh,
and quota coverage. Do not enable unregistered chat tools. Keep both existing
workbook implementations and their current callers. Holocron remains a separate
runtime; its news writer/schema-bootstrap behavior is an explicit compatibility
exception, not authorization to alter ingestion contracts.

## Ordered migration checkpoints

0. Characterization, isolated verification and dependency baseline.
1. Analytics, organization and admin router workflows.
2. Reusable analytics and chat orchestration.
3. Account persistence and provider adapters.
4. CRM capabilities and inventory ownership.
5. Project/radar/plots/area ownership.
6. Feasibility, then transactions/facets, listings, and supply as separate slices.
7. News/upload/infrastructure, ingestion contracts, and removal of temporary shims.

Complete and commit each phase before proceeding. A temporary compatibility
function delegates to one implementation; it never duplicates business logic.
The architecture-test exception list must only shrink. Evaluation, new tools,
quota expansion, concurrency/atomicity fixes, changed market formulas, and new
background workers are outside this migration.

## Phase 0 baseline discoveries

The existing migration chain omitted `conversations.organization_id`, although
the model, application and running local database already contain it. Revision
`a34d19c0b621` restores fresh-database setup without rewriting old revisions or
backfilling ownership from current membership. It preserves an existing column
and fails before changing a populated legacy table missing that column. This is
a prerequisite repair discovered by real PostgreSQL tests, not a tenancy change.
The new non-mutating lint recipe also exposed an unused news exception binding;
removing that binding does not change fallback behavior.

Phase 0 verification: 263 fast backend tests, 3 isolated PostgreSQL tests,
1 ClickHouse execution test, 1 Redis integration test, 68 frontend unit tests,
frontend production build, 31 Playwright tests, and backend lint/format checks
passed. Seven pre-existing formatting failures were normalized with identical
Python ASTs. Subsequent phases add capability-specific cases before extraction.

## Phase 1 checkpoint

Analytics routes now delegate workflows to the service, deterministic configuration
metrics to `metrics.py`, and warehouse execution to `queries.py`. Organization
routes delegate account workflows and invitations to their owners; persistence
is isolated in the organization repository. Admin composes public organization,
billing and usage reads. Existing HTTP errors and transaction boundaries remain.

Verification: 265 backend tests (including Bun workbook parity), 5 isolated
PostgreSQL tests, 1 actual ClickHouse test, 68 frontend tests, 31 Playwright tests,
OpenAPI/model/tool/JSON contracts, lint/format and acyclic imports passed. Six
legacy dependency exceptions were removed; no exceptions were added.

## Phase 2 checkpoint

Chat now owns conversation/turn orchestration, its repository, agent registration,
thin tool adapters, artifact envelopes and SSE encoding. Analytics owns reusable
chart results, chart policies and warehouse SQL. Project owns similar-project
lookup; listings owns listing-area resolution. Shared market names, units and
scope predicates live under `market`. Temporary old helper modules only re-export
the single implementation and will be removed in Phase 7.

Verification: 266 backend tests, 5 isolated PostgreSQL tests, 3 actual ClickHouse
tests, 68 frontend tests, production frontend build and 33 Playwright tests passed.
Browser additions cover real conversation create/rename/reload/delete and fixed
SSE/artifact rendering plus message reload; the latter deliberately mocks the
stream, while backend streaming tests exercise the agent lifecycle. Query execution
covers pulse, rankings, sales/project charts and similar projects. The historical
pulse inclusion of non-sales remains distinct from sales-chart filtering.
The graph is acyclic, 13 further legacy edges disappeared, and chat cannot import
ClickHouse or contain warehouse statements. Provider/tool schemas remain frozen.
