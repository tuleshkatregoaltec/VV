# Feasibility Plan

## Purpose

This is the canonical implementation plan for the feasibility feature in this repo.

This plan is for the current canonical `/feasibility` feature, not a side-by-side replacement track.

---

## Product Direction

The feasibility product should behave like a fast underwriting workspace:

- search for a plot
- inspect raw plot facts
- generate a seeded study
- land directly in the workbook
- edit assumptions live
- use chat to explain or propose structured changes

Important constraint:

- do not create a local placeholder or empty workbook study before the backend returns the seeded study
- the workbook UI is only shown once the seeded study has been generated successfully

That means the backend owns study seeding, and the frontend owns live editing after seed generation.

---

## Architecture Principles

### 1. One canonical feasibility domain

There is no `feasibility_v2` or `feasibility_v3` target architecture anymore.

The canonical implementation lives under:

- `backend/app/feasibility`
- `frontend/src/lib/components/feasibility`
- `frontend/src/lib/api/feasibility.ts`
- `frontend/src/lib/queries/feasibility.ts`
- `frontend/src/lib/stores/feasibilityStudy.svelte.ts`
- `frontend/src/routes/feasibility/+page.svelte`

### 2. One assumptions contract

`FeasibilityAssumptions` is defined on the backend and generated to the frontend.

The frontend must not maintain a competing handwritten assumptions contract.

### 3. One live study store

The frontend should have one canonical study store for the working feasibility session.

That store owns:

- route/workflow phase
- selected plot
- seeded study payload
- assumptions
- study context
- research
- active sheet
- derived outputs
- derived validation
- chat/proposal state if it remains tightly coupled to the study

There should not be a separate workbook state store that has to be synchronized from another store.

### 4. Dual runtime engine is intentional

The feasibility engine should exist in both runtimes with aligned naming:

- backend: `engine.py`
- frontend: `engine.ts`

This is deliberate. The two implementations should remain structurally aligned so that:

- frontend edits are instant
- backend can verify, export, persist, or reuse calculations
- parity is practical to maintain

### 5. Derived outputs are not primary state

The canonical mutable model is:

- `assumptions`

The following are derived:

- `outputs`
- `validation`

They should be recomputed, not hand-maintained.

### 6. Backend follows repo layering

The feasibility backend should follow the repo standard:

1. `models.py`
2. `service.py`
3. `router.py`
4. `main.py` registration

Routers stay thin. Business logic and orchestration live in `service.py`.

### 7. Frontend follows repo layering

The feasibility frontend should follow the repo standard:

1. API client
2. query builders / query keys
3. store only where needed for cross-component state
4. feature components
5. thin route

Components should not assemble ad hoc query keys or call backend endpoints directly when a shared query layer is appropriate.

---

## Target Domain Model

The canonical frontend working study shape is:

- `plot_data`
- `assumptions`
- `study_context`
- `research`

Derived locally:

- `outputs`
- `validation`

### `plot_data`

Reference plot context used for identity, display, and stateless backend calls.

`plot_data` should not be the primary home for compute-critical site-envelope inputs once they have been seeded into `assumptions`.

Examples:

- plot number
- community
- project name
- master developer
- gfa type
- site plan dates
- verification status
- land use
- general notes
- setbacks
- coordinates
- GIS-derived warnings

Examples of values that should be seeded into `assumptions` instead of treated as primary `plot_data` compute inputs:

- `plotAreaSqm`
- `maxGfaSqm`
- `maxCoveragePct`
- `maxStoreys`
- `maxFar`
- `usage`

### `assumptions`

The canonical editable underwriting input model.

Important nuance:

- `assumptions` is the canonical compute contract
- not every field inside `assumptions` is necessarily a user-editable knob
- some fields are seeded regulatory or site-envelope inputs that should still travel with `assumptions` because chat and compute depend on them

Examples:

- usage override
- area/program assumptions
- unit mix
- pricing
- cost assumptions
- financing assumptions
- timing assumptions
- payment plan

### `study_context`

Compact human-readable rationale for the seeded study.

Examples:

- headline
- positioning
- summary points
- pricing rationale
- cost rationale
- timing rationale
- financing rationale

### `research`

Evidence and benchmark context used to seed and explain the study.

Examples:

- market pricing
- off-plan benchmarks
- competition evidence
- land sales evidence
- warnings

### `outputs`

Purely derived workbook outputs from `assumptions`.

Examples:

- area outputs
- program outputs
- cost outputs
- funding outputs
- cash flow
- returns
- financing
- sources and uses

### `validation`

Purely derived checks over assumptions and outputs.

Examples:

- hard fails
- warnings
- missing evidence

---

## Target Data Flow

### 1. Plot discovery

Frontend:

- fetches communities
- fetches/searches plots

Backend returns factual search data only.

### 2. Plot selection

Frontend:

- selects a plot
- fetches `plot_data`
- stores `plot_data`
- shows the selected raw plot facts

No workbook study is created yet.

### 3. Study generation

Frontend sends:

- `plot_number`
- optional `usage_override`

Backend returns the seeded study payload:

- `plot_data`
- `assumptions`
- `study_context`
- `research`

Only after this succeeds does the frontend enter the workbook workspace.

### 4. Live workbook editing

Frontend derives:

- `outputs = computeWorkbook(assumptions)`
- `validation = validateWorkbook(assumptions, outputs)`

User edits update `assumptions`, which triggers immediate local recompute.

### 5. Chat and proposals

Because the backend is stateless for chat and seed-related operations, the frontend sends the current context needed for that call.

Frontend sends:

- user messages
- current `plot_data`
- current `assumptions`
- current `research`

Backend streams:

- assistant text
- structured proposals
- optional research reveal events

Frontend applies accepted proposals to local `assumptions` and recomputes locally.

Important traffic rule:

- `plot_data` does not need to be resent for normal local workbook edits, because those do not hit the backend
- `plot_data` should be sent when a stateless backend operation needs the full current plot context, such as chat

---

## Target Backend Structure

### `backend/app/feasibility/models.py`

Owns:

- request and response schemas
- canonical `FeasibilityAssumptions`
- plot/research/context/workbook response types
- chat stream payload shapes where needed

Rules:

- do not define request/response schemas inline in router handlers
- remove duplicate denormalized models that are not part of the API contract

### `backend/app/feasibility/service.py`

Owns:

- plot lookup orchestration
- seeded study generation
- study context assembly
- research assembly
- workbook computation orchestration
- chat request orchestration
- future persistence orchestration if added

Rules:

- raise `HTTPException` here where appropriate
- router should not directly coordinate query helpers and agents

### `backend/app/feasibility/router.py`

Owns:

- endpoint definitions
- auth guards
- request/response typing
- delegation to service functions

Rules:

- no business logic beyond light request handling

### `backend/app/feasibility/queries.py`

Owns:

- GIS and analytical query helpers
- row-to-model mapping helpers tied to data access

Rules:

- keep data access here
- keep orchestration out

### `backend/app/feasibility/hbu_agent.py`

Owns:

- research and seeding assistant logic

Rules:

- should be invoked by service, not router

### `backend/app/feasibility/chat_agent.py`

Owns:

- streaming assistant behavior
- proposal generation
- research reveal events

Rules:

- should be invoked by service, not router

### `backend/app/feasibility/engine.py`

Owns:

- pure or mostly pure feasibility computation
- parity-friendly compute structure

Rules:

- keep this structurally aligned with frontend `engine.ts`
- prefer assumptions as compute inputs
- avoid UI-specific concerns

---

## Target Frontend Structure

### `frontend/src/lib/api/feasibility.ts`

Owns:

- runtime HTTP methods for feasibility endpoints

Rules:

- import generated types for contracts
- do not redefine API contracts locally

### `frontend/src/lib/queries/feasibility.ts`

Owns:

- feasibility query keys
- feasibility query builders

Rules:

- centralize query keys here
- do not assemble feasibility query keys ad hoc inside components

### `frontend/src/lib/stores/feasibilityStudy.svelte.ts`

Owns:

- the canonical working study state
- phase and selected plot state
- seeded study payload
- active sheet
- derived outputs
- derived validation
- proposal application helpers
- optionally chat state if kept together

Rules:

- this becomes the single state surface for workbook components
- no separate synchronized workbook store
- the merge should start from the richer current workbook-store implementation, not from the thinner workflow wrapper
- if the existing `feasibilityStudy` store contains workflow state that is still needed, that state must be deliberately carried over during the merge rather than dropped by accident

### `frontend/src/lib/feasibility/workbook/engine.ts`

Owns:

- pure frontend computation from `assumptions` to `outputs`

Rules:

- keep function structure aligned with backend `workbook.py`
- do not couple to Svelte store state

### `frontend/src/lib/feasibility/workbook/validation.ts`

Owns:

- pure validation over assumptions and outputs

### `frontend/src/lib/components/feasibility/**`

Owns:

- UI only

Rules:

- bind to the canonical store
- do not call the API directly from workbook sheets

### `frontend/src/routes/feasibility/+page.svelte`

Owns:

- top-level route composition only

Rules:

- keep the route thin

---

## Implementation Gaps To Close

## Current Status

Status as of 2026-03-27.

- Phase 1 is materially complete on the frontend.
- The canonical store now lives in `frontend/src/lib/stores/feasibilityStudy.svelte.ts`.
- `frontend/src/lib/feasibility/workbook/store.svelte.ts` has been removed.
- Plot selection no longer creates a local placeholder study.
- The workbook appears only after backend study generation succeeds.
- Workbook and workspace components now bind to the canonical store surface and use canonical naming such as `assumptions`, `outputs`, `plotData`, and `selectedPlot`.
- Feasibility query keys/builders are centralized in `frontend/src/lib/queries/feasibility.ts`, and key UI surfaces have been moved off inline query/API usage.
- Chat transport logic has been moved out of the component and into `frontend/src/lib/stores/feasibilityWorkspace.svelte.ts`.
- Shared frontend formatting and view-model helpers now live in `frontend/src/lib/feasibility/format.ts` and `frontend/src/lib/feasibility/view-models.ts`.

Still open:

- Phase 2 is only partially complete. Generated API types are used in several places, but the frontend still depends on workbook-local model types such as `FeasibilityStudy`, `FeasibilityAssumptions`, and `UnitConfig` in some surfaces.
- Backend layering cleanup has not been completed yet. `backend/app/feasibility/service.py` still needs to become the orchestration boundary.
- Dirty-sheet and review-decision state still exist in the canonical store and need a product-level keep-or-delete decision.
- Test coverage still needs a dedicated pass for the current seeded-study workflow.

### 1. Replace multiple stale plans with this one

Done by this document.

### 2. Collapse frontend state to one canonical study store

Status:

- complete

Current issue:

- lifecycle state and workbook state are split across multiple stores

Target:

- use the current richer workbook-store implementation as the merge base
- carry over any still-needed workflow state from the current `feasibilityStudy` wrapper
- converge on one canonical store surface under `frontend/src/lib/stores/feasibilityStudy.svelte.ts`
- delete `frontend/src/lib/feasibility/workbook/store.svelte.ts`
- update all components to use the canonical study store

### 3. Remove local placeholder-study creation

Status:

- complete

Current issue:

- the frontend builds local base-study objects before backend seeding

Target:

- selecting a plot should only fetch and display raw plot facts
- the study object is created from the backend seeded response only

### 4. Make generated types authoritative

Status:

- in progress

Current issue:

- frontend still maintains a handwritten `FeasibilityAssumptions` interface

Target:

- use generated `FeasibilityAssumptions`, `FeasibilityUnitConfig`, and related types directly where possible
- remove frontend duplicates
- resolve any remaining optional/nullability mismatches deliberately

### 5. Remove workbook compatibility shims

Status:

- mostly complete

Current issue:

- workbook store still exposes migration-era aliases and redundant getters

Target:

- remove `.workbook` alias
- remove stale compatibility getters where `outputs.*` is sufficient
- remove any duplicate helper layers that only exist for earlier migration stages

### 6. Remove obsolete review/dirty mechanisms unless still justified

Status:

- open

Current issue:

- dirty-tab tracking and review-decision state still exist from an earlier state model

Target:

- delete them if they are no longer part of the intended product behavior

### 7. Introduce backend `service.py`

Status:

- open

Current issue:

- router still orchestrates queries and agents directly

Target:

- move orchestration into `backend/app/feasibility/service.py`
- keep the router thin and conventional

### 8. Clean backend engine support code

Status:

- open

Current issue:

- backend engine module still carries some structural cleanup debt

Target:

- convert small immutable helper classes to dataclasses where appropriate
- remove unused duplicate summary models if they are not part of any endpoint contract
- keep backend/frontend compute structure aligned

### 9. Bring frontend query usage back to repo conventions

Status:

- mostly complete

Current issue:

- some feasibility UI still uses inline query keys or direct API calls where shared query builders should be used

Target:

- route all feasibility query-key definitions through `frontend/src/lib/queries/feasibility.ts`

### 10. Update tests to match the current product

Status:

- open

Current issue:

- e2e coverage still reflects the old wizard-oriented feasibility flow

Target:

- rewrite tests around the current seed-from-plot workflow
- add tests for seeded study loading and workbook rendering
- add tests for proposal application where practical

---

## Recommended Execution Order

### Phase 1 — Replace the state architecture

Status:

- complete

1. Audit the current `workbookStore` and `feasibilityStudy` stores field by field
2. Use the richer `workbookStore` as the merge base
3. Carry over any still-needed workflow state from `feasibilityStudy`
4. Remove local placeholder-study creation
5. Update workbook components to consume the canonical store
6. Delete `frontend/src/lib/feasibility/workbook/store.svelte.ts`

### Phase 2 — Clean the type boundary

Status:

- in progress

1. Replace handwritten frontend feasibility contract types with generated ones
2. Regenerate client if backend contract changes are required
3. Remove redundant type shims and aliases

### Phase 3 — Restore backend layering

Status:

- open

1. Add `backend/app/feasibility/service.py`
2. Move orchestration from router into service
3. Keep router thin and typed

### Phase 4 — Clean compute and support surfaces

Status:

- in progress

1. Remove obsolete compatibility getters and state
2. Remove dead summary models if unused
3. Tighten frontend/backend workbook parity

### Phase 5 — Repair test coverage

Status:

- open

1. Update e2e tests to the current seeded-study flow
2. Add or update targeted frontend tests
3. Add or update backend tests around service orchestration if needed

---

## Definition Of Done

The feasibility feature is considered structurally clean when all of the following are true:

- there is one feasibility plan document in `docs/`
- there is one canonical frontend study store
- there is no separate synchronized workbook store
- selecting a plot does not create a local placeholder study
- the workbook only appears after backend study generation succeeds
- generated backend types are the source of truth for feasibility contracts
- backend orchestration lives in `service.py`
- router handlers are thin
- frontend query keys are centralized
- stale compatibility aliases and dead models are removed
- e2e coverage matches the current seeded-study workflow

---

## Verification

At each implementation phase, verify with the repo-standard commands most relevant to the change:

- `just test-frontend`
- `just build-frontend`
- `just test-backend`
- `just test-e2e`
- `just check-all`

The exact sequence should stay targeted to the current slice of work, then finish with broader verification once the full cleanup is complete.
