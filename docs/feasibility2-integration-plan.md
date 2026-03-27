# Feasibility 2 Integration Plan

## Purpose

This document is an execution playbook for integrating selected work from `origin/kian` into `feat/feasibility2-integration` without merging `kian` directly.

It is intentionally detailed and operational. It is meant to reduce integration drift, avoid accidental scope creep, preserve current `main` conventions, and keep the implementation sequence stable across multiple working sessions.

## Progress Snapshot

Completed on `feat/feasibility2-integration`:

- Analytics backend expansion aligned to `main` patterns
- Analytics frontend panel/query/client integration
- Feasibility backend draft-case contract
- Feasibility case persistence tables, models, and router endpoints
- Frontend feasibility API/query integration for draft and saved cases

Current state of Feasibility 2 integration:

- backend draft/persistence foundation is in place
- frontend Feasibility 2 workspace/store/sheets are not yet ported
- workbook metadata remains intentionally thin on the backend
- the next major slice is frontend state/workspace composition on top of the new canonical draft contract

The branch strategy is:

- Base branch for integration work: `feat/feasibility2-integration`
- Reference branch only: `origin/kian`
- No direct merges from `kian`
- No wholesale cherry-picks of the large commits from `kian`
- Rebuild selected feature slices on top of current `main` patterns

## Architectural Rule

The existing design patterns on current `main` are the standard to follow.

`origin/kian` is not the architectural template. It is a reference branch for:

- desired product behavior
- candidate business logic
- useful UX ideas
- example schemas and calculations

It must not dictate:

- layering decisions
- separation of concerns
- API/client conventions
- frontend state architecture
- migration strategy
- query organization

When there is tension between how `main` is structured and how `origin/kian` is structured, prefer `main` unless there is a clear, deliberate, reviewed reason to change the pattern.

Practical implication:

- port behavior, not architecture
- port domain logic selectively
- rewrite implementation details to match `main`
- reject backend/UI overcoupling even if it exists in `origin/kian`

## Current Situation

### Branch topology

- `feat/feasibility2-integration` is branched from `main` at `2e69009`
- `origin/kian` currently points to `da5be09`
- Local `kian` is stale and should not be treated as authoritative
- `origin/kian` is effectively two major commits on top of the old merge base:
  - `b597005` - broad feasibility v2, persistence, benchmarks, analytics updates
  - `da5be09` - deeper feasibility2 underwriting workspace build

### Why we are not merging `kian`

`kian` is not a clean feature branch relative to current `main`. It bundles desired work with stale implementation assumptions and unrelated drift.

Direct merge/cherry-pick is high-risk because:

- `main` has moved significantly in frontend API patterns
- `main` now uses generated OpenAPI types and a shared runtime client pattern
- `main` has centralized query factories and key builders
- `main` has a consolidated migration baseline, which invalidates `kian` migration ancestry
- `kian` contains unrelated changes outside desired feature scope

The correct path is selective porting by concept, not by commit.

## Pattern Preservation Rules

These rules override convenience during implementation.

### Rule 1: `main` owns the architecture

If `origin/kian` implements a feature using a different pattern than `main`, adapt the feature to `main` rather than adapting `main` to `origin/kian`.

### Rule 2: Backend owns canonical domain logic, not workbook rendering

Keep on the backend:

- deterministic calculations
- underwriting rules
- validation logic
- persistence logic
- canonical case/draft generation
- domain-level schemas

Keep out of the backend unless clearly justified:

- workbook tab structure
- sheet ordering
- display-oriented grouping
- UI labels and interaction metadata that exist only for the frontend
- render-ready spreadsheet view models

### Rule 3: Frontend composes presentation

The frontend should transform canonical backend outputs into:

- workbook tabs
- sheet views
- presentation-focused summaries
- export layouts

The backend should not be forced to mirror the exact structure of the workbook UI unless that structure is truly part of the domain model.

### Rule 4: Current API patterns remain in force

- generated OpenAPI types remain the source of truth for frontend typing
- shared runtime client patterns remain in force
- centralized query factories remain in force
- stores must not become alternate API schema definitions

### Rule 5: Migration and model registration follow current branch reality

- migration ancestry must be built from current `main`
- current model export conventions must be preserved
- no adoption of stale migration assumptions from `origin/kian`

## Desired Outcome

Integrate the following from `origin/kian`:

- Feasibility 2 backend domain expansion
- Feasibility 2 persistence and saved-case flow
- Feasibility 2 frontend workspace and workbook-style sheets
- Analytics frontend redesign
- Analytics backend expansions required by that redesign

Avoid integrating the following unless explicitly re-approved during execution:

- `docker-compose.yml` changes
- data import script additions
- binary deliverables
- documentation placeholders not required by implementation
- unrelated auth/admin/profile/dashboard fixes
- broad operational changes in `backend/app/main.py`
- unrelated navigation or filter defaults unless needed to expose completed feature work

## Source Surface From `origin/kian`

### Analytics-related files

- `backend/app/analytics/models.py`
- `backend/app/analytics/router.py`
- `backend/app/analytics/service.py`
- `backend/app/clickhouse/queries.py`
- `backend/app/clickhouse/client.py`
- `frontend/src/lib/api/analytics.ts`
- `frontend/src/lib/components/analytics/ProjectPanel.svelte`
- `frontend/src/lib/components/analytics/ProjectSelector.svelte`
- `frontend/src/routes/analytics/+page.svelte`

### Feasibility backend files

- `backend/app/feasibility/agent.py`
- `backend/app/feasibility/benchmarks.py`
- `backend/app/feasibility/metric_registry.py`
- `backend/app/feasibility/models.py`
- `backend/app/feasibility/persistence.py`
- `backend/app/feasibility/persistence_models.py`
- `backend/app/feasibility/pricing_benchmarks.py`
- `backend/app/feasibility/router.py`
- `backend/app/feasibility/service.py`
- `backend/app/postgres/models/__init__.py`
- `backend/migrations/versions/b3f0e6e0a1d2_add_feasibility_case_tables.py`

### Feasibility frontend files

- `frontend/src/lib/api/feasibility.ts`
- `frontend/src/lib/stores/feasibility.svelte.ts`
- `frontend/src/lib/stores/feasibility2.svelte.ts`
- `frontend/src/lib/stores/researchPanel2.svelte.ts`
- `frontend/src/lib/utils/exportFeasibility2.ts`
- `frontend/src/lib/utils/feasibilityModelGraph.ts`
- `frontend/src/routes/feasibility-2/+page.svelte`
- `frontend/src/lib/components/feasibility2/**`

### Existing feasibility files touched in `origin/kian`

- `frontend/src/lib/components/feasibility/StepPlot.svelte`
- `frontend/src/lib/components/feasibility/StepHBUStudy.svelte`
- `frontend/src/lib/components/feasibility/SpreadsheetPanel.svelte`
- `frontend/src/lib/components/feasibility/FeasibilityChat.svelte`

These should be treated as compatibility or bridge changes, not as a reason to destabilize the existing Feasibility v1 flow unless truly necessary.

## Mainline Constraints To Respect

### Frontend API conventions

Current branch conventions from `main`:

- Use generated OpenAPI types from `frontend/src/lib/api/generated/hey-api`
- Use the shared runtime client in `frontend/src/lib/api/client.ts`
- Do not couple API type definitions to Svelte stores
- Prefer centralized query builders under `frontend/src/lib/queries`

Implication:

- Do not transplant `origin/kian` versions of `frontend/src/lib/api/analytics.ts` or `frontend/src/lib/api/feasibility.ts` directly
- Rebuild their added methods on top of current generated types and runtime client conventions
- Regenerate client/types after backend endpoint changes

### Frontend query conventions

Current branch conventions from `main`:

- Query keys belong in centralized factories
- Query builders belong in `frontend/src/lib/queries`
- Avoid ad hoc inline query-key assembly in page and component files

Implication:

- New analytics endpoints require extending `frontend/src/lib/queries/analytics.ts`
- New feasibility endpoints should likely extend `frontend/src/lib/queries/feasibility.ts`
- `origin/kian` query logic should be treated as behavior reference only

### Layering conventions

Current branch conventions from `main` should also govern feature layering:

- domain logic stays domain-oriented
- frontend stores manage state and interaction, not canonical business rules
- view components should consume canonical typed data rather than inventing their own schemas
- export helpers may transform data for workbook output, but should not force backend contracts to become workbook-shaped

Implication:

- `origin/kian` backend additions that mainly exist to support workbook rendering should be reconsidered before adoption
- `origin/kian` frontend store logic that duplicates backend calculation logic should be reduced or eliminated where possible
- metric registries and similar metadata should only stay backend-side if they are truly domain metadata, not UI scaffolding

### Migration constraints

Current branch state:

- Only migration present on `main`: `8395bd1f2518_baseline_schema.py`
- `origin/kian` migration uses down revision `746b42cc1a6f`, which is not present

Implication:

- `backend/migrations/versions/b3f0e6e0a1d2_add_feasibility_case_tables.py` cannot be reused directly
- Feasibility persistence migration must be rewritten fresh on top of current baseline

### Backend model registration

Current branch:

- `backend/app/postgres/models/__init__.py` does not export feasibility persistence models

Implication:

- Any feasibility persistence adoption requires explicit model registration
- This must be coordinated with the fresh migration creation

## High-Level Integration Strategy

Implement in explicit layers with hard boundaries.

Do not start frontend workbook/UI porting until backend structures and client contracts are stable enough to support them.

Do not preserve `origin/kian` layering just because it already exists. Re-slice the feature to fit `main`.

Recommended implementation sequence:

1. Analytics backend slice
2. Analytics client/query layer
3. Analytics frontend slice
4. Feasibility backend core slice
5. Feasibility persistence slice
6. Feasibility client/query layer
7. Feasibility frontend workspace shell
8. Feasibility workbook/model layer
9. Feasibility export layer
10. Exposure polish and validation

This is intentionally more granular than the original rough plan because the latest `origin/kian` commit increased the size and coupling of Feasibility 2 substantially.

## Slice Breakdown

### Slice A: Analytics backend

Goal:

- Bring in the backend support needed for the redesigned analytics experience

Target source concepts from `origin/kian`:

- configuration analysis rows
- forecast endpoint/service
- pipeline endpoint/service
- price distribution endpoint/service
- expanded project metadata fields
- supporting ClickHouse queries

Expected touched files on this branch:

- `backend/app/analytics/models.py`
- `backend/app/analytics/router.py`
- `backend/app/analytics/service.py`
- `backend/app/clickhouse/queries.py`

Optional and likely separate:

- `backend/app/clickhouse/client.py`

Notes:

- The ClickHouse client pool in `origin/kian` may be a useful improvement but is not required to unlock the feature set
- Treat it as a separate performance/operational decision unless profiling shows the new analytics fan-out actually needs it

Definition of done:

- Backend exposes the new project analytics endpoints
- Schemas are compatible with OpenAPI generation
- No regression to existing analytics endpoints

### Slice B: Analytics client and query layer

Goal:

- Surface the new analytics endpoints through current frontend patterns

Expected touched files:

- `frontend/src/lib/api/analytics.ts`
- `frontend/src/lib/queries/analytics.ts`
- generated client/types after backend changes if necessary

Rules:

- Follow current generated-type conventions
- Do not reintroduce manually duplicated response interfaces if generated types can represent them
- If generated types are insufficient because of backend modeling issues, fix the backend schema instead of encoding drift in the frontend

Definition of done:

- Frontend can call summary/trends/forecast/pipeline/price-distribution through typed helpers and centralized query builders

### Slice C: Analytics frontend

Goal:

- Port the redesigned analytics experience without regressing current repo patterns

Target source concepts from `origin/kian`:

- richer `ProjectPanel`
- optional redesigned `/analytics` page
- more efficient project selector behavior

Expected touched files:

- `frontend/src/lib/components/analytics/ProjectPanel.svelte`
- `frontend/src/lib/components/analytics/ProjectSelector.svelte`
- `frontend/src/routes/analytics/+page.svelte`

Important implementation note:

- `origin/kian` page redesign uses `ProjectSearchInput` backed by `projectsAPI.list()`
- This may be worth adopting, but it is a UX enhancement, not a hard requirement for the analytics backend integration
- If it complicates the slice too much, keep the current selector temporarily and port the page redesign later

Definition of done:

- Desired analytics frontend capabilities are available
- No untyped query sprawl
- No conflict with current project search infrastructure

### Slice D: Feasibility backend core

Goal:

- Port the deterministic underwriting and draft-case generation core from `origin/kian`

Target source concepts:

- expanded feasibility models
- draft feasibility case building
- validation summary generation
- benchmark/pricing logic
- metric registry support
- deeper underwriting outputs introduced in latest `origin/kian`

Expected touched files:

- `backend/app/feasibility/models.py`
- `backend/app/feasibility/service.py`
- `backend/app/feasibility/router.py`
- `backend/app/feasibility/benchmarks.py`
- `backend/app/feasibility/pricing_benchmarks.py`
- `backend/app/feasibility/metric_registry.py`
- possibly `backend/app/feasibility/agent.py`

Important caution:

- `backend/app/feasibility/service.py` is now the single highest-risk file in the entire integration
- It has grown materially between `b597005` and `da5be09`
- This file should be ported deliberately, ideally in sub-commits by capability rather than as one monolithic transplant
- It should also be reviewed for misplaced presentation/workbook concerns before porting

Sub-capabilities likely inside this slice:

- expanded site/program/cost/funding/schedule/cashflow/returns models
- validation issue generation
- assumptions patch handling
- metric registry linkage
- budget timing / sources-uses / financing richness from latest commit

Additional filter before adoption:

- if a backend structure exists only to make a specific sheet easier to render, prefer moving that concern to the frontend or export layer
- if a backend registry is mainly labels/tooltips/affected-tab metadata for the workbook UI, it probably should not be treated as canonical backend logic

Definition of done:

- Backend can build a draft feasibility case with the richer model outputs required by Feasibility 2 sheets
- Output schema is stable enough for frontend/client generation

### Slice E: Feasibility persistence

Goal:

- Port save/list/get/delete case behavior

Expected touched files:

- `backend/app/feasibility/persistence.py`
- `backend/app/feasibility/persistence_models.py`
- `backend/app/postgres/models/__init__.py`
- fresh migration file on this branch

Critical constraint:

- Do not reuse `origin/kian` migration directly
- Write a new migration against current baseline

Questions to verify during implementation:

- Are case payload JSON blobs acceptable in their current shape for storage size and queryability?
- Is per-user scoping sufficient, or should organization scoping be enforced more broadly?
- Do we need indexes beyond what `origin/kian` used?

Definition of done:

- Cases can be persisted and restored from current backend schema
- Migration applies cleanly on top of current baseline

### Slice F: Feasibility client/query layer

Goal:

- Expose draft and persistence endpoints through current frontend conventions

Expected touched files:

- `frontend/src/lib/api/feasibility.ts`
- `frontend/src/lib/queries/feasibility.ts`
- generated client/types

Rules:

- Avoid importing API types from stores
- Prefer generated types
- If generated names differ from `origin/kian` hand-authored names, adapt the store/frontend code to generated names rather than bypassing generation

Definition of done:

- Draft case creation and case persistence are accessible through typed frontend helpers

### Slice G: Feasibility frontend workspace shell

Goal:

- Bring up the overall Feasibility 2 page and multi-panel shell on current branch conventions

Target source files:

- `frontend/src/routes/feasibility-2/+page.svelte`
- `frontend/src/lib/components/feasibility2/FeasibilityChat.svelte`
- `frontend/src/lib/components/feasibility2/ResearchPanel.svelte`
- `frontend/src/lib/components/feasibility2/StepProgress.svelte`
- `frontend/src/lib/components/feasibility2/SpreadsheetPanel.svelte`
- `frontend/src/lib/stores/researchPanel2.svelte.ts`

Important note:

- This shell is now more workbook-centric after `da5be09`
- It should be integrated only after the draft-case backend shape is stable

Definition of done:

- Route loads
- plot selection -> HBU -> draft-case -> workspace flow functions
- save/load/delete case flow is wired

### Slice H: Feasibility frontend model/store layer

Goal:

- Port and adapt `feasibility2Store` and supporting assumptions graph logic

Target source files:

- `frontend/src/lib/stores/feasibility2.svelte.ts`
- `frontend/src/lib/utils/feasibilityModelGraph.ts`
- updates in `frontend/src/lib/stores/feasibility.svelte.ts`

Why this is separate:

- The latest `origin/kian` commit turns this into more than a view model
- It now contains a substantial assumptions engine, review decisions, financing-rate changes, and workbook dependency behavior

Primary risks:

- Tight coupling to hand-authored API types
- Tight coupling to workbook sheet assumptions
- Potential duplication of backend formulas
- Pulling workbook-specific domain shaping back into backend contracts

Hard rule:

- Frontend store may manage state and local editing behavior, but the backend remains the calculation source of truth
- If any logic in the store recreates backend financial formulas, treat it with suspicion and trim where possible
- If any backend contract exists mainly because the store/workbook wants it in that shape, challenge that contract before adopting it

Definition of done:

- Store supports UI editing, backend round-tripping, and export support without becoming an authoritative calculation engine

### Slice I: Feasibility workbook sheets

Goal:

- Port the workbook UI sheets required by the Feasibility 2 workspace

Target source files:

- `frontend/src/lib/components/feasibility2/sheets/KeyAssumptionsSheet.svelte`
- `BudgetSheet.svelte`
- `ChecksSheet.svelte`
- `CostsSheet.svelte`
- `EiborSheet.svelte`
- `FinancingSheet.svelte`
- `MonthlyCashFlowSheet.svelte`
- `PricingEvidenceSheet.svelte`
- `ProgramSheet.svelte`
- `ReturnsSheet.svelte`
- `RevenueSheet.svelte`
- `CashFlowSheet.svelte`
- `SiteSheet.svelte`
- `ScheduleSheet.svelte`
- `CalibrationSheet.svelte`
- `BlankSheet.svelte`

This is likely the single largest frontend slice.

Implementation approach:

- Start with a minimal working tab set tied to stable backend outputs
- Add secondary/advanced sheets after base sheets render correctly
- Expect to adapt labels and field names to generated types and any backend shape refinements
- Prefer composing sheet-specific structures in the frontend from canonical backend data rather than extending backend schemas for every sheet need

Suggested sub-order:

1. Site
2. Program
3. Pricing Evidence
4. Revenue / Sales & Collections
5. Costs / Budget
6. Financing
7. Cash Flow / Monthly CF
8. Returns
9. Checks
10. EIBOR and any calibration utilities

Definition of done:

- Sheets render from backend draft data
- User edits flow through supported assumptions/update pathways
- No silent dependence on stale local-only formulas

### Slice J: Export layer

Goal:

- Port the Excel export model in a way that matches current backend data structures

Target source files:

- `frontend/src/lib/utils/exportFeasibility2.ts`
- `frontend/src/lib/utils/feasibilityModelGraph.ts`

Notes:

- Latest `origin/kian` expands export substantially
- Export should come after workbook data structures settle
- Do not optimize export too early; first make sure it mirrors stable backend fields

Definition of done:

- Export works against the final integrated Feasibility 2 draft shape
- Export formulas and workbook references are internally consistent

### Slice K: Exposure and polish

Potential touched files:

- `frontend/src/lib/components/navigation/Navbar.svelte`
- `frontend/src/lib/components/navigation/MobileMenu.svelte`
- `frontend/src/lib/components/filters/globalFilters.svelte.ts`

Rules:

- Only expose navigation once the route is stable enough for regular use
- Do not carry over unrelated default/filter changes unless specifically desired

## Explicit Exclusions

Unless requirements change during implementation, do not integrate:

- `backend/scripts/insert/insert_current_local.py`
- `docker-compose.yml`
- `Deliverables/Comps report template V1.xlsx`
- `docs/feasibility-benchmark-ranges.md`
- `docs/feasibility-market-conventions.md`
- `docs/feasibility-metric-dictionary.md`
- `docs/feasibility-v1-scope.md`
- `docs/feasibility-validation-principles.md`
- `frontend/src/lib/api/auth.ts`
- `frontend/src/routes/admin/organizations/[id]/+page.svelte`
- `frontend/src/routes/profile/+page.svelte`
- `frontend/src/lib/components/dashboard/ChatBox.svelte`
- unrelated chart component tweaks

These may contain reasonable ideas, but they are not part of the desired integration target as currently defined.

## Order of Execution

Recommended concrete working order on this branch:

1. Reconfirm current `origin/kian` state before each implementation session
2. Implement Slice A: analytics backend
3. Regenerate client/types if backend schema changes require it
4. Implement Slice B: analytics client/query layer
5. Implement Slice C: analytics frontend
6. Implement Slice D: feasibility backend core
7. Implement Slice E: feasibility persistence with fresh migration
8. Regenerate client/types again
9. Implement Slice F: feasibility client/query layer
10. Implement Slice G: feasibility route/workspace shell
11. Implement Slice H: feasibility store/model behavior
12. Implement Slice I: workbook sheets
13. Implement Slice J: export layer
14. Implement Slice K: navigation exposure and low-risk polish
15. Run full validation

## Validation Strategy

### Backend validation

For analytics backend slices:

- add or update targeted backend tests for new analytics endpoints
- verify schema generation does not regress
- sanity-check project-level query behavior with representative data

For feasibility backend slices:

- add targeted tests for draft-case generation
- add targeted tests for persistence service
- add tests for validation summary logic
- add tests for migration application if practical in current test harness

### Frontend validation

For analytics:

- `just test-frontend`
- `just build-frontend`
- manual verification of project selection, comparison mode, and new project panels

For feasibility:

- `just test-frontend`
- `just build-frontend`
- manual verification of:
  - plot selection
  - HBU study application
  - draft-case generation
  - saved case load/save/delete
  - sheet rendering
  - export behavior

### Full branch validation

Before merge consideration:

- `just test-backend`
- `just test-frontend`
- `just build-frontend`
- any targeted Playwright flows that meaningfully cover `/analytics` and `/feasibility-2`

## Risk Register

### Risk 1: Feasibility service transplant becomes unreviewable

Reason:

- `backend/app/feasibility/service.py` is very large and semantically dense

Mitigation:

- Port in sub-capabilities
- keep commits scoped by behavior, not just by file
- verify intermediate backend shapes before frontend adoption
- explicitly reject view-model concerns from the backend during port

### Risk 2: Frontend store duplicates backend financial logic

Reason:

- latest Feasibility 2 store and export graph include formula-like behavior

Mitigation:

- keep backend authoritative
- audit store logic during port
- remove or simplify duplicated financial computation where possible

### Risk 3: Backend becomes workbook-coupled

Reason:

- latest `origin/kian` feasibility work appears to push some workbook/supporting logic into backend-adjacent structures

Mitigation:

- review every new backend type for whether it is domain-facing or presentation-facing
- keep workbook tab/layout/label concerns in frontend/export layers
- resist returning sheet-shaped payloads from the backend

### Risk 4: Generated client friction slows frontend progress

Reason:

- `origin/kian` uses hand-authored API interfaces in places

Mitigation:

- fix backend OpenAPI modeling early
- regenerate often at stable checkpoints
- adapt frontend to generated shapes instead of bypassing generation

### Risk 5: Migration rewrite causes persistence drift

Reason:

- `origin/kian` migration ancestry is invalid on current branch

Mitigation:

- write fresh migration from current baseline
- verify model exports and migration contents together

### Risk 6: Analytics redesign drags unrelated search/page refactors

Reason:

- redesigned `/analytics` page changes project selection behavior too

Mitigation:

- separate backend capability from page redesign
- keep selector migration optional if it blocks the core analytics value

## Implementation Rules For Future Sessions

- Always compare against `origin/kian`, not local `kian`
- Before starting a slice, re-run a targeted diff against current `origin/kian`
- Do not copy `origin/kian` frontend API files directly
- Do not copy `origin/kian` migration file directly
- Prefer selective adaptation over large file replacement where `main` conventions changed materially
- Treat `main` as the source of truth for design patterns and layering
- Port behavior from `origin/kian`, not its structural assumptions
- Challenge backend additions that appear to exist mainly for workbook/UI convenience
- Keep unrelated drift out even if it looks harmless
- If a slice becomes too broad, split it again rather than forcing a giant patch

## Current Interpretation Of Scope

In scope right now:

- analytics backend/frontend improvements
- feasibility 2 underwriting system
- feasibility 2 saved-case flow
- feasibility 2 workbook UI
- feasibility 2 export

Not in scope right now:

- infra/dev tooling refresh
- local data import tooling
- broad docs import
- unrelated profile/admin/auth/dashboard cleanup

## Next Action After This Plan

Start implementation with Slice A: analytics backend, unless priorities change.

Reason:

- It is lower risk than Feasibility 2
- It creates a cleaner first integration checkpoint
- It validates the selective-port workflow before entering the large Feasibility 2 domain
