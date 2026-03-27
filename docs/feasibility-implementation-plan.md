# Feasibility Implementation Plan

## Purpose

This document is the implementation plan for the next-generation feasibility tool.

It is not a product brief for stakeholders. It is an execution document for engineering work in this repo. It should be detailed enough that future implementation decisions can be made from this document without re-litigating the core architecture each session.

This plan reflects the current intended direction:

- side-by-side implementation under a `feasibility_v3` namespace
- one-shot seeded study flow
- minimal friction between plot selection and workbook
- agent mostly hidden behind the scenes
- concise rationale visible to the user
- frontend-owned live study state
- stateless backend for seed and chat operations in the initial implementation
- workbook computed on both frontend and backend
- mirrored workbook architecture across runtimes

## Implementation Safety Rule

The new implementation should be built next to the current feasibility feature, not by rewriting the current implementation in place.

This is a hard migration rule.

The purpose is to:

- preserve the current working feature while the replacement is under construction
- make workbook parity verification practical
- make UI and behavioral comparison practical
- reduce the risk of partially migrated dead-ends
- avoid deleting useful behavior before its replacement exists

Practical implications:

- do not use the current feasibility files as the long-term construction site for the new architecture
- build new route/store/workbook modules alongside the current implementation
- keep the old feature available as a comparison surface until cutover is justified
- only remove or redirect the old implementation once the new implementation is complete enough to replace it

## Product Position

The feasibility tool should feel like a fast underwriting workspace, not an AI co-authoring ceremony.

The user intent is:

- find a plot
- generate a credible first-pass study
- land in an editable workbook
- refine assumptions and outputs as needed

The product promise is not:

- step through a long multi-stage AI workflow
- inspect every internal heuristic the agent used
- manage the agent as a collaborator before a study exists

The product promise is:

- give me a realistic seeded study quickly
- let me inspect the result
- let me edit assumptions directly
- let me use chat to revise or explain the model

## Design Principles

### 1. Reduce friction aggressively

There should be no dedicated intermediate “review the HBU study before entering the workbook” step.

Plot selection should lead directly into study generation, then directly into the workbook.

### 2. Hide internal complexity

The system will do a large amount of internal research, fallback handling, estimation, and refinement. Most of that should remain hidden from the user.

The user should see:

- raw plot facts
- a loading state while the system seeds the study
- the seeded workbook
- concise study context explaining the key assumptions

The user should not see:

- internal confidence mechanics
- internal fallback logic
- multi-stage chain-of-thought style processing
- noisy agent orchestration details

### 3. Keep the editable model explicit

Even though the seed process is hidden, the resulting assumptions must remain visible and editable.

The user should be able to:

- inspect the seeded assumptions
- change assumptions manually in the workbook
- ask chat to revise assumptions
- understand the short rationale behind major assumption groups

### 4. Treat frontend/backend workbook execution as deliberate dual runtime support

The workbook will be computed on both frontend and backend.

This is not an accidental duplication. It must be treated as a planned architecture with explicit parity controls.

### 5. Prefer simple domain language

Avoid overdesigned names.

Use:

- `feasibility_study`
- `plot_data`
- `assumptions`
- `study_context`
- `workbook`

Do not use terms like:

- `dossier`
- `scenario` as a first-class concept in v1
- `memo`
- `thesis` unless a UI surface specifically benefits from it

## Core Domain Model

The first implementation should keep the model simple.

### `feasibility_study`

The single working study object for one feasibility study session.

It contains:

- plot data
- assumptions
- workbook
- study context
- chat history
- generation status

In the initial implementation this should be frontend-owned working state, not a persisted backend object.

### `plot_data`

The raw and enriched plot information used to seed the study.

Typical contents:

- plot number
- community
- project name
- plot area
- max GFA
- max height
- max coverage
- inferred usage
- verification status
- warnings that are truly material
- land use and other GIS-derived fields

`plot_data` is factual input context, not an opinionated recommendation object.

### `assumptions`

The editable financial and program inputs used to compute the workbook.

This includes:

- unit mix
- pricing
- build costs
- soft costs
- financing assumptions
- sales timing
- construction timing
- payment plan
- parking assumptions
- land assumptions

`assumptions` are the primary editable model state.

### `workbook`

The computed output of the feasibility model at a point in time.

This includes:

- program outputs
- revenue outputs
- cost outputs
- funding outputs
- cash flow outputs
- returns outputs
- checks and validation outputs

`workbook` is derived state. It should not be hand-edited directly.

### `study_context`

The compact human-readable explanation layer that accompanies the seeded study.

This is what the user should see in chat and/or the left sidebar as the narrative behind the seeded study.

Typical contents:

- project tier
- positioning
- headline study summary
- unit mix rationale
- pricing rationale
- cost rationale
- timing rationale
- financing rationale
- short market context summary

`study_context` is not the full hidden internal reasoning log. It is the user-facing explanation of the seeded study.

## Concrete Study Shape

The following is not final API code, but it is the intended structural direction.

```json
{
  "status": "ready",
  "plot_data": {
    "plot_number": "3460688",
    "community_name": "Business Bay",
    "project_name": "Plot 3460688",
    "plot_area_sqm": 10450.0,
    "max_gfa_sqm": 41800.0,
    "max_height": "G+2P+22",
    "max_coverage": "60%",
    "gfa_type": "GFA",
    "far": 4.0,
    "inferred_usage": "residential",
    "is_verified": true
  },
  "study_context": {
    "headline": "Upper-premium family residential tower",
    "project_tier": "upper_premium",
    "positioning": "Family-oriented large-format apartments",
    "summary_points": [
      "Seeded toward 3BR and 4BR product due to plot scale and nearby competing stock.",
      "Pricing is based on recent off-plan evidence with a conservative launch haircut.",
      "Build costs are set toward the upper end of local residential tower benchmarks."
    ],
    "unit_mix_rationale": "Large-family product is a better fit than small-investor inventory for this plot size and tower form.",
    "pricing_rationale": "Off-plan evidence in the area supports launch pricing above existing stock, but the first pass uses a conservative starting point.",
    "cost_rationale": "Facade/spec and tower complexity justify an above-mid build cost assumption.",
    "timing_rationale": "Launch is assumed after initial design and approvals with a realistic construction and sell-through period.",
    "financing_rationale": "Debt is sized to maintain a workable first-pass capital stack without over-assuming proceeds timing.",
    "market_summary": "The immediate area supports premium residential product, but launch pricing still needs discipline given competing supply."
  },
  "assumptions": {},
  "workbook": {},
  "chat": {
    "history": []
  }
}
```

## Intended User Flow

### Step 1. Plot search and selection

The user arrives on the feasibility page and searches for a plot.

The page should show:

- plot search
- raw plot info once selected
- no AI-generated analysis yet

The immediate purpose of this step is to let the user confirm they have selected the correct plot.

### Step 2. Generate study

Once the user confirms the plot, they click a clear action such as `Generate Study`.

That should trigger backend orchestration for the seeded feasibility study.

The frontend should move into a focused loading state. This should likely be a full-page or dominant-state loading screen, not a tiny inline spinner.

Recommended loading progress copy:

- Reading plot data
- Researching market evidence
- Setting project assumptions
- Building financial model
- Finalizing study

This should communicate progress without exposing internal mechanics.

### Step 3. Land directly in workbook

Once the seed process completes, the user should land directly in the workbook.

The workbook should appear as a one-shotted initial study. It should not feel like the user still needs to “accept” the AI before they can work.

The user should see:

- workbook sheets
- current assumptions
- study context
- research/evidence panels where useful
- chat panel

### Step 4. Refine

From the workbook, the user can:

- manually edit assumptions
- inspect pricing/comps context
- ask chat to adjust the model
- let the workbook recompute automatically from updated assumptions

This is the main operating mode of the feature.

## Explicitly Rejected Flow

The following flow is intentionally not the target design:

- select plot
- generate an intermediate HBU study
- force the user to inspect or approve that study
- only then enter the workbook

This adds friction without enough value.

If the system is capable of producing a credible seeded study, the user should go straight to the editable workbook and inspect the rationale there.

## Agent Role

The agent should behave like an internal analyst, not a visible co-pilot the user must actively manage before work begins.

### Agent responsibilities

The backend seed process should:

- analyze `plot_data`
- determine a realistic project tier and positioning
- gather market comparables
- gather land evidence
- infer pricing stance
- determine initial unit mix
- seed cost and timing assumptions
- seed financing assumptions
- compute the workbook
- produce concise `study_context`

### Agent internals should remain hidden

The system will likely perform multiple tool calls, adjustments, and estimation passes. Most of this should remain internal.

Do not expose:

- detailed confidence scoring as a primary UX element
- chain-of-thought-like intermediate reasoning
- internal repair loops unless necessary for debugging

### User-facing output from the agent

The user should see:

- the final seeded assumptions
- the workbook outputs
- short rationale summaries

Example user-facing rationale:

- “Unit mix targets the luxury family market with emphasis on larger 3BR and 4BR apartments given plot scale and nearby competing stock.”
- “Build cost is seeded toward the upper end of local residential tower benchmarks due to product tier and expected facade/spec level.”
- “Launch pricing is based on recent off-plan evidence in the area with a conservative haircut for first-pass underwriting.”

This is the right level of visibility.

## Frontend Architecture

## Goals

Frontend architecture should support:

- fast loading from seed to workbook
- clear separation between UI state and workbook logic
- direct editing of assumptions
- mirrored workbook computation
- easy maintenance

## Frontend State Model

The frontend should not continue to rely on one oversized store responsible for all concerns.

The state should be organized around a few clear concerns.

### `feasibilityStudy_v3`

Canonical client-side representation of the current `feasibility_study`.

Suggested responsibilities:

- `plot_data`
- `assumptions`
- `workbook`
- `study_context`
- seed status
- backend sync status for generation/chat requests

### `feasibilityWorkspace_v3`

Workspace interaction state.

Suggested responsibilities:

- active sheet
- panel open/close state
- loading screen state
- resize widths
- chat messages
- pending assistant proposals
- streaming state
- approval/decline state
- local selection state
- transient toasts or banners

The key boundary is:

- `feasibilityStudy_v3` owns study state
- `feasibilityWorkspace_v3` owns workspace interaction state

## Frontend Component Structure

The workbook UI should continue to use separate sheet components.

That is the correct level of separation for the presentation layer.

Recommended high-level structure:

- route page composes the overall experience
- top-level workspace components own layout
- each sheet is a dedicated component
- shared assumption editing components are reused across sheets

Do not let sheet components become sources of workbook business logic.

Sheets should primarily:

- read from current `assumptions` and `workbook`
- render inputs and outputs
- dispatch assumption changes
- display rationale or evidence where relevant

## Frontend Workbook Engine

Because the workbook will be computed on the frontend as well, the frontend needs a dedicated engine module.

This should live under:

- `frontend/src/lib/feasibility_v3/workbook/models.ts`
- `frontend/src/lib/feasibility_v3/workbook/compute.ts`
- `frontend/src/lib/feasibility_v3/workbook/utils.ts`

This structure is intentionally centralized.

It avoids both extremes:

- a single giant monolithic file
- too many tiny files that make the model hard to follow

## Backend Architecture

## Goals

Backend architecture should support:

- seed orchestration
- hidden agent/tool execution
- backend workbook computation for parity and agent use
- chat-driven updates
- parity with frontend workbook logic

## Backend Service Shape

The backend feasibility domain should be structured around a small number of responsibilities:

- plot data retrieval and enrichment
- seed orchestration
- workbook compute
- chat interactions

At a high level:

- router layer for API contracts
- domain/service layer for stateless request orchestration
- workbook engine for deterministic model logic
- agent modules for seed and chat behavior

## Backend Workbook Engine

Because workbook logic is also required on the backend, the backend should mirror the frontend structure:

- `backend/app/feasibility_v3/workbook/models.py`
- `backend/app/feasibility_v3/workbook/compute.py`
- `backend/app/feasibility_v3/workbook/utils.py`

These files should mirror the frontend runtime closely.

The primary maintenance rule is:

- if the workbook contract changes, update `models`
- if reusable low-level helpers change, update `utils`
- if the business logic changes, update `compute`

## Backend State Model

For the initial implementation, the backend should be stateless with respect to the live study.

That means:

- the frontend owns the current `feasibility_study`
- the backend receives `plot_data`, `assumptions`, `workbook`, and chat context as request input
- the backend returns seeded study data, chat output, and derived analysis

The backend should not persist live study state yet unless and until draft saving is added as a deliberate later feature.

Later persistence can store:

- study metadata
- assumptions
- study context
- workbook snapshots

But that is explicitly out of scope for the first implementation.

## Simplified API Direction

The exact endpoints can change, but the workflow should look roughly like this:

- `GET /api/v1/feasibility_v3/plots/{plot_number}`
- `POST /api/v1/feasibility_v3/generate-study`
- `POST /api/v1/feasibility_v3/chat/stream`

The important part is not the exact path naming. The important part is the state model:

- plot data retrieval
- seed generation
- frontend-owned assumption mutation
- frontend automatic workbook recompute
- stateless chat interaction

## Concrete API Direction

The final route names may shift, but the data flow should be concrete enough to guide implementation.

### 1. Fetch plot data

Response:

```json
{
  "plot_data": {
    "plot_number": "3460688",
    "community_name": "Business Bay",
    "plot_area_sqm": 10450.0,
    "max_gfa_sqm": 41800.0,
    "max_height": "G+2P+22",
    "max_coverage": "60%",
    "inferred_usage": "residential",
    "is_verified": true
  }
}
```

At this point the frontend has enough to show raw plot facts before generation begins.

### 2. Generate seeded study

Request:

```json
{
  "plot_data": {
    "plot_number": "3460688"
  }
}
```

Response options:

- synchronous if fast enough
- asynchronous job-based if generation is expected to take noticeable time

Preferred practical direction:

- send selected plot context
- trigger generation job
- poll or stream progress
- return the seeded study payload when ready

Suggested progress event shape:

```json
{
  "type": "progress",
  "step": "building_financial_model",
  "label": "Building financial model"
}
```

### 3. Completed seeded study

Response:

```json
{
  "status": "ready",
  "plot_data": {},
  "study_context": {},
  "assumptions": {},
  "workbook": {}
}
```

There does not need to be a dedicated `updateAssumptions` backend route in the first implementation if the frontend owns live study state and computes the workbook locally. The frontend can update assumptions locally and only call backend for seed/chat flows.

### 4. Chat request

Request:

```json
{
  "plot_data": {},
  "assumptions": {},
  "workbook": {},
  "study_context": {},
  "messages": [
    {
      "role": "user",
      "content": "Reduce pricing by 5% and tell me what happens to returns."
    }
  ]
}
```

Potential stream event shapes:

```json
{
  "type": "text",
  "content": "Reducing launch pricing by 5% compresses gross margin and project IRR."
}
```

```json
{
  "type": "pending_action",
  "action": "update_assumptions",
  "payload": {
    "pricingAdjustmentPct": -5
  }
}
```

```json
{
  "type": "done"
}
```

## Concrete Assumptions Shape

The exact fields will remain domain-specific, but the working shape should stay flat enough to edit easily and stable enough to mirror across runtimes.

```json
{
  "plotAreaSqm": 10450,
  "maxFar": 4.0,
  "numberOfTowers": 1,
  "numberOfFloors": 22,
  "nsaEfficiencyPct": 80,
  "constructionCostPsqmBua": 4650,
  "landPricePsqm": 6200,
  "designSupervisionPct": 6,
  "salesAgentFeePct": 5,
  "marketingCostPct": 1,
  "contingencyPct": 5,
  "debtToCostRatio": 0.55,
  "salesCommencementDate": "2026-09-01",
  "constructionDate": "2026-12-01",
  "handoverDate": "2029-03-01",
  "unitConfigs": [
    {
      "id": "threebr",
      "label": "3BR",
      "units": 96,
      "avgSizeSqm": 165,
      "sellingRatePsqm": 29500,
      "parkingRatio": 2
    },
    {
      "id": "fourbr",
      "label": "4BR",
      "units": 48,
      "avgSizeSqm": 245,
      "sellingRatePsqm": 33000,
      "parkingRatio": 2.5
    }
  ],
  "paymentPlan": [
    { "id": "deposit", "label": "Deposit", "percent": 20 },
    { "id": "pre_handover", "label": "Pre-Handover", "percent": 40 },
    { "id": "handover", "label": "At Handover", "percent": 40 }
  ]
}
```

## Concrete Workbook Shape

The workbook should continue to group into major sections rather than behaving like a flat export blob.

```json
{
  "generated_at": "2026-03-24T00:00:00Z",
  "plot_number": "3460688",
  "site": {},
  "program": {},
  "costs": {},
  "funding": {},
  "schedule": {},
  "cash_flow": {},
  "returns": {},
  "checks": {}
}
```

The exact field names can evolve, but the high-level groupings should remain stable because they map naturally to workbook sheets and support parity testing.

## Workbook Parity Strategy

This is one of the most important parts of the implementation.

The workbook is intentionally computed in both runtimes. Therefore parity cannot be left informal.

## Source-of-truth principle

We are not maintaining “two separate workbook implementations.”

We are maintaining:

- one workbook specification
- one logical calculation pipeline
- two runtime implementations

This framing must remain true during implementation and maintenance.

## Preferred Mirrored Function Shape

The mirrored structure should exist not only at the file level, but also at the function level where practical.

Recommended `compute` shape in both runtimes:

- `normalize_inputs(...)`
- `compute_site_section(...)`
- `compute_program_section(...)`
- `compute_revenue_section(...)`
- `compute_costs_section(...)`
- `compute_funding_section(...)`
- `compute_cash_flow_section(...)`
- `compute_returns_section(...)`
- `compute_checks_section(...)`
- `compute_workbook(...)`

The names do not have to be perfectly identical if runtime language constraints make that awkward, but they should be intentionally parallel.

## Mirrored file structure

The workbook engine should be mirrored exactly at the top level:

Backend:

- `workbook/models.py`
- `workbook/compute.py`
- `workbook/utils.py`

Frontend:

- `workbook/models.ts`
- `workbook/compute.ts`
- `workbook/utils.ts`

This should be treated as a hard rule.

## Mirrored internal structure

`compute.py` and `compute.ts` should follow the same top-to-bottom calculation order.

Recommended major sections:

1. normalize inputs
2. derive site and program values
3. compute revenue
4. compute costs
5. compute funding
6. compute cash flow
7. compute returns
8. compute checks
9. assemble workbook

These sections should appear in the same order in both runtimes.

Where practical, use the same function names and section comments in both files.

## Shared contract discipline

The following must match exactly across frontend and backend:

- input field names
- output field names
- enum values
- date handling rules
- rounding behavior
- null/default behavior
- array ordering
- validation rules
- helper semantics

If any of these drift, the model will become expensive to trust and maintain.

## Rounding policy

A formal rounding policy must be defined and documented in code comments and tests.

Need explicit rules for:

- when rounding occurs
- whether line items round before summation or after
- percentage rounding
- displayed precision versus stored precision
- IRR and MOIC precision

Do not leave this to “close enough” implementation differences.

## Date policy

Date handling must also be explicit.

Need matching rules for:

- ISO parsing
- timezone assumptions
- month boundaries
- month-end generation
- construction period derivation
- sales period derivation
- handover milestone timing

Date drift is one of the most likely sources of frontend/backend mismatch.

## Workbook Test Strategy

Parity testing is mandatory.

### Golden fixtures

Create a set of workbook fixtures containing:

- `plot_data`
- `assumptions`
- expected `workbook`

These should represent a range of realistic cases:

- base residential tower
- smaller residential case
- mixed-use or commercial case if supported
- case with demolition
- case with edge timing
- case with sparse unit mix

### Backend tests

Backend should verify:

- fixture inputs compute expected workbook values
- workbook schema remains stable
- edge cases behave correctly

### Frontend tests

Frontend should verify:

- fixture inputs compute expected workbook values
- important totals and outputs match fixture expectations

### Cross-runtime parity tests

There should also be an explicit parity workflow.

This can be done by:

- running the same fixture set in both runtimes
- comparing output JSON snapshots or selected canonical fields

Recommended parity check categories:

- exact equality fields
- tolerance-based float fields
- section shape and array ordering fields
- validation/check outputs

If exact equality is not always practical for floating point-heavy sections, define narrow tolerance rules explicitly. Do not rely on informal eyeballing.

## Workbook Spec

The workbook engine should be accompanied by a living workbook specification in the repo.

That spec should define for each major field:

- field name
- dependencies
- formula or derivation rule
- rounding policy
- notes

This does not need to be a giant spreadsheet copy. It needs to be a precise engineering spec that makes dual implementation maintainable.

This should be added as a follow-up document once the architecture is in place.

## Study Context Design

`study_context` should be compact and presentation-friendly.

Suggested shape:

- `headline`
- `project_tier`
- `positioning`
- `summary_points`
- `unit_mix_rationale`
- `pricing_rationale`
- `cost_rationale`
- `timing_rationale`
- `financing_rationale`
- `market_summary`

This object should be written for UI consumption.

It should not expose:

- internal chain-of-thought
- large unfiltered evidence dumps
- raw confidence instrumentation as a primary field group

## Chat Design

Chat should support the workspace, not replace it.

The chat system should be able to:

- explain current study assumptions
- explain workbook outputs
- propose assumption changes
- recommend assumption edits from market context
- trigger evidence views where needed

Chat should not directly own the workbook state.

Preferred pattern:

- chat proposes a structured patch
- frontend shows proposed change summary
- user accepts or declines
- accepted change mutates `assumptions`
- workbook recomputes automatically on the frontend

Even if frontend temporarily applies patches locally first for responsiveness, the conceptual model should remain:

- chat suggests
- study state updates
- workbook recomputes

## What the UI Should Surface Prominently

Prominent:

- current workbook
- editable assumptions
- compact study context
- relevant evidence panels
- chat

Less prominent:

- system warnings unless materially important
- internal validation bookkeeping
- internal confidence framing

This does not mean validation should not exist. It means it should not dominate the product framing unless something is actually broken or materially suspect.

## Recommended Workbook Layout Direction

Keep the sheet-based workbook experience.

The current sheet framing is directionally right, even if the internal architecture is messy today.

Likely stable sheets:

- Key Assumptions
- Sales / Revenue
- Budget / Costs
- Financing
- Cash Flow
- Returns
- Checks
- Pricing Evidence

The exact sheet set can evolve, but the important rule is:

- sheets are presentation surfaces
- workbook engine owns the calculations

## Migration Direction From Current Implementation

The current feature should not be treated as architecture to preserve.

It is useful as:

- UI reference
- field inventory
- workbook output reference
- rough behavior reference

It is not useful as the ideal underlying architecture.

## Coexistence Migration Rule

The migration must proceed by coexistence first, replacement second.

This means:

- build the new implementation beside the existing one
- verify the new flow end-to-end
- compare workbook outputs and UI coverage against the current feature
- only then cut over traffic and remove legacy paths

The current implementation is therefore:

- not the target architecture
- still a valid reference implementation during migration

## Proposed New Surface Area

The exact file names can evolve, but the general direction should look like this.

### Frontend

- `frontend/src/routes/feasibility-v3/+page.svelte`
- `frontend/src/lib/api/feasibility_v3.ts`
- `frontend/src/lib/stores/feasibilityStudy_v3.svelte.ts`
- `frontend/src/lib/stores/feasibilityWorkspace_v3.svelte.ts`
- `frontend/src/lib/feasibility_v3/workbook/models.ts`
- `frontend/src/lib/feasibility_v3/workbook/utils.ts`
- `frontend/src/lib/feasibility_v3/workbook/compute.ts`
- `frontend/src/lib/components/feasibility_v3/**`

### Backend

- `backend/app/feasibility_v3/router.py`
- `backend/app/feasibility_v3/models.py`
- `backend/app/feasibility_v3/service.py`
- `backend/app/feasibility_v3/seed_agent.py`
- `backend/app/feasibility_v3/chat_agent.py`
- `backend/app/feasibility_v3/workbook/models.py`
- `backend/app/feasibility_v3/workbook/utils.py`
- `backend/app/feasibility_v3/workbook/compute.py`

This does not require deleting or destabilizing the current feasibility files while the replacement is still being built.

### Key migration goals

1. Remove the dedicated intermediate HBU review step from the product flow.
2. Replace the current “study first, workspace second” UX with one-shot seed to workbook.
3. Replace the oversized frontend feasibility store with a clearer state model.
4. Replace the single-file workbook logic with mirrored workbook runtime modules.
5. Preserve the useful workbook sheet surfaces while rebuilding the underlying flow.

### Important note on the current codebase

There is existing feasibility functionality in:

- frontend route/workspace components
- frontend store logic
- frontend workbook utilities
- backend router/agent/workbook code

The goal is not incremental patching forever. The goal is to converge on a cleaner target structure deliberately.

## Proposed Implementation Phases

### Phase 1. Lock the target contract

Define and stabilize:

- `feasibility_study`
- `plot_data`
- `assumptions`
- `study_context`
- `workbook`

This includes agreeing on exact field names and major object boundaries.

Deliverables:

- written study contract in code and doc form
- initial API payload definitions
- stable naming for new route/store/workbook surfaces

### Phase 2. Build mirrored workbook module skeletons

Create:

- backend `feasibility_v3/workbook/models.py`
- backend `feasibility_v3/workbook/compute.py`
- backend `feasibility_v3/workbook/utils.py`
- frontend `feasibility_v3/workbook/models.ts`
- frontend `feasibility_v3/workbook/compute.ts`
- frontend `feasibility_v3/workbook/utils.ts`

Populate them with the existing workbook logic, reorganized into the new structure.

The first priority is structural parity, not immediate functional perfection.

Deliverables:

- new mirrored workbook modules in both runtimes
- current workbook logic reorganized into the new structure
- no required cutover yet

### Phase 3. Establish parity tests

Before major further feature work, create:

- backend workbook fixtures
- frontend workbook fixtures
- parity comparison tests

This phase protects the rest of the migration.

Deliverables:

- golden fixtures committed
- backend workbook tests
- frontend workbook tests
- explicit parity workflow

### Phase 4. Rebuild seed flow

Refactor the flow to:

- select plot
- show raw plot info
- trigger seed generation
- show loading state
- land in workbook

This likely means replacing the existing explicit HBU review step in the frontend.

Deliverables:

- new plot selection to generation flow
- new loading screen
- direct landing into seeded workbook
- seeded `study_context` visible in workspace

### Phase 5. Rework frontend state and workspace composition

Reorganize the frontend around:

- study state
- workspace interaction state

Then point sheets and panels at the new state shape.

Deliverables:

- new study/workspace stores
- new `feasibilityStudy_v3` and `feasibilityWorkspace_v3` stores
- new workspace route/components
- existing useful sheets ported or rebuilt on top of new state

### Phase 6. Rework chat mutation flow

Ensure chat works as a structured patch-proposal system tied to current assumptions and workbook state.

Deliverables:

- new chat stream wiring against study state
- structured patch proposals
- approval/apply/decline flow

### Phase 7. Optional later persistence phase

Do not implement backend draft persistence as part of the initial v3 architecture unless requirements change.

If draft saving is later added, it should be introduced as an explicit follow-up phase.

Deliverables:

- decision on whether draft saving is needed
- persistence shape for `feasibility_study` if approved
- cleanup plan for old implementation once replacement is proven

## Non-Goals For Initial Implementation

The following should not drive the architecture yet:

- first-class multi-scenario comparison
- complex scenario trees
- showing every hidden agent step to the user
- building a generalized spreadsheet engine
- over-designing study confidence systems in the UI
- fully abstracting the workbook into dozens of tiny modules

These may become valuable later, but they should not complicate the initial implementation plan.

## Naming Rules

Prefer concrete names.

Use:

- `plot_data`
- `study_context`
- `assumptions`
- `workbook`
- `feasibility_study`
- `feasibility_v3`

Avoid:

- `dossier`
- `scenario` unless product requirements truly need it
- overly formal or consultant-heavy labels

## Execution Checklist

The implementation should satisfy these conditions:

- plot selection leads directly to a seed-generation flow
- the user lands directly in a seeded workbook
- the workbook is computed on both frontend and backend
- workbook engines use mirrored `models`, `utils`, and `compute` files
- frontend/backend workbook outputs are parity-tested
- the user sees concise rationale, not internal agent mechanics
- assumptions remain directly editable
- chat proposes structured changes against the current study

## Final Direction

The feasibility tool should become a one-shot seeded underwriting workspace.

The user should experience:

- raw plot intake
- a short generation wait
- a credible seeded base case
- direct editing and chat-assisted refinement

The implementation should center on a simple study model and a disciplined mirrored workbook engine across frontend and backend.

That is the target state this document is intended to drive.
