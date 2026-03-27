# Feasibility Refactor Plan

## Completed

- Deleted `backend/app/feasibility_v3/` (dead code)
- Renamed `WorkbookAssumptions` → `FeasibilityAssumptions` across all frontend files
- Removed stale TODO comment from `models.ts`

---

## Architecture Principles

- **One engine, two languages.** `engine.ts` (frontend) and `workbook.py` (backend) are 1:1 mirrors. Same function names (camelCase vs snake_case), same section order, same logic, same comments. Only `assumptions` travel over the wire — everything else is derived.
- **One store.** Single exported store combines lifecycle (phase, plot, generation) and workbook state (active sheet). No parallel stores.
- **Generated types win.** `FeasibilityAssumptions` is defined once on the backend. After `just generate-client`, the frontend imports it. No hand-written duplicate.
- **`$derived` not stored.** `outputs` and `validation` are always derived from `assumptions`. Never stored, never stale.

---

## Phase A — Backend: Align `FeasibilityAssumptions`

**Goal:** Add fields that exist on the frontend but are missing from the backend model, so generated types match.

### Step 1 — Add missing fields to `backend/app/feasibility/models.py`

Add to `FeasibilityAssumptions`:
```python
usage: Usage = "unknown"
maxGfaSqm: float = 0.0
maxCoveragePct: float | None = None
maxStoreys: int | None = None
```

These are currently inferred from `PlotDetails` inside `workbook.py` but not part of the assumptions contract. Adding them makes the frontend and backend assumptions contracts identical.

### Step 2 — Update `workbook.py` to prefer assumption fields

Where `workbook.py` currently reads `plot_data.max_gfa_sqm`, `plot_data.max_height`, `plot_data.max_coverage` inline during computation, switch to reading from `assumptions.maxGfaSqm`, `assumptions.maxStoreys`, `assumptions.maxCoveragePct` instead. The seeding of these fields from `PlotDetails` happens at study creation time (in the agent/service layer), not inside the engine.

### Step 3 — Run `just generate-client`

Verify: `frontend/src/lib/api/generated/hey-api/types.gen.ts` now includes the four new fields on `FeasibilityAssumptions`.

### Step 4 — Replace local `FeasibilityAssumptions` in `models.ts` with the generated type

In `frontend/src/lib/feasibility/workbook/models.ts`:
```ts
export type { FeasibilityAssumptions } from '$lib/api/generated/hey-api/types.gen'
```
Delete the hand-written `FeasibilityAssumptions` interface, `UnitConfig`, `PaymentPlanRow`, `UsageType`, `DebtRepaymentMode` — replace with re-exports of generated equivalents where they now exist.

**Verify:** `just build-frontend` passes clean.

---

## Phase B — Frontend: Merge and Complete the Engine

**Goal:** One engine (`engine.ts`), fully featured. Delete `compute.ts`.

### Step 5 — Extend `engine.ts` to cover everything `compute.ts` currently computes

`engine.ts` currently stubs:
- `projectIrrPct: null` — needs Newton-Raphson IRR from monthly cash flow
- `equityIrrPct: null` — same
- Cash flow is 4 simplified periods — needs full monthly period generation

Port these from `workbook.py` faithfully:

**Monthly cash flow:** Generate one period per month from `landAcquisitionDate` to `handoverDate + salesPeriodMonths`. Each period tracks:
- Revenue inflows by payment plan tranche (deposit/pre-handover/handover)
- Cost outflows by timing rule (land at acquisition, construction straight-line over build period, selling costs at sales velocity)
- Debt draws, repayments, interest, commitment fees

**IRR:** Newton-Raphson on the monthly unlevered and levered net cash flow arrays. Return `null` if cash flows are all zero or have no sign change.

**Financing detail:** Land loan capacity, construction loan capacity, peak debt, arrangement fee, total finance costs — already partially in `FundingOutputs`, extend to match backend `FeasibilityFinancingSummary` fields.

Keep `engine.ts` signature: `computeWorkbook(assumptions: FeasibilityAssumptions): WorkbookOutputs`

The `WorkbookOutputs` type gets extended with the new fields. Rename it to `FeasibilityOutputs` to align with the domain naming convention.

### Step 6 — Update `store.svelte.ts` to drop the `workbook` derived

Remove:
```ts
const workbook = $derived(computeDraftWorkbook(...))  // compute.ts path
```
Remove all the fallback inline getter functions (`totalLandCostAedValue`, `constructionCostInclInflationValue`, etc.) — they only existed because `outputs` was incomplete. Now `outputs` is always fully computed when `assumptions` is set.

Update the ~35 getter aliases on the exported object to read directly from `outputs.*` rather than through helper functions.

### Step 7 — Update sheets that used `workbook.*` (snake_case) to use `outputs.*` (camelCase)

Affected files:
- `FinancingSheet.svelte` — `workbook.financing`, `workbook.sources_uses`, `workbook.validation`, `workbook.model_registry.assumptions`, `workbook.cash_flow.periods` → `outputs.financing`, `outputs.sourcesUses`, etc.
- `CashFlowSheet.svelte` — `workbook.cash_flow`, `workbook.returns` → `outputs.cashFlow`, `outputs.returns`
- `MonthlyCashFlowSheet.svelte` — `workbook.cash_flow.periods` → `outputs.cashFlow.periods`

### Step 8 — Delete `compute.ts`

Delete `frontend/src/lib/feasibility/workbook/compute.ts`.

Delete from `utils.ts`: `buildWorkbookStudy`, `buildLegacyStudy` (only existed to feed `compute.ts`).

Delete from `models.ts`: `WorkbookStudy` type (only existed to feed `compute.ts`).

**Verify:** `just build-frontend` passes clean. All sheets render.

---

## Phase C — Frontend: Merge the Two Stores

**Goal:** One store, one import, no split state.

### Step 9 — Merge `feasibilityStudy.svelte.ts` and `store.svelte.ts`

The merged store lives at `frontend/src/lib/stores/feasibilityStudy.svelte.ts` (keep the existing path, absorb `store.svelte.ts` into it).

**Final shape:**

```ts
// Mutable state
const state = $state({
  phase: 'search' as StudyPhase,      // 'search' | 'generating' | 'ready' | 'error'
  plotData: null as PlotDetails | null,
  assumptions: null as FeasibilityAssumptions | null,
  context: null as StudyContext | null,
  research: null as ResearchData | null,
  error: ''
})

const activeSheet = $state({ value: 'key_assumptions' as FeasibilitySheetTab })

// Derived — never stored, always current
const outputs = $derived(
  state.assumptions ? computeWorkbook(state.assumptions) : null
)
const validation = $derived(
  state.assumptions && outputs ? validateWorkbook(state.assumptions, outputs) : null
)
```

**Actions to keep:**
- `selectPlot(plot)` — fetches plot data, seeds assumptions
- `generateStudy()` — calls backend, merges returned assumptions/context/research into state
- `updateAssumptions(patch)` — merges patch into assumptions, triggers recompute via $derived
- `updateUnitConfig(id, patch)`
- `updatePaymentPlan(id, patch)`
- `applyProposal(proposal)` — chat agent proposals
- `setActiveSheet(tab)`
- `reset()`

**Remove from the merge:**
- `sheetDirty` tracking — deleted entirely (outputs are always current via `$derived`)
- `reviewDecisions` — deleted entirely (functionality not wanted)
- `adaptBackendStudy` — deleted (backend now sends matching `FeasibilityAssumptions` shape)
- Duplicate `parseMaxStoreys` / `parseMaxCoverage` helpers — keep one copy
- `.workbook` alias — deleted (was a migration shim)

### Step 10 — Update all 17 component/page imports

Every file currently importing from `$lib/feasibility/workbook/store.svelte` switches to `$lib/stores/feasibilityStudy.svelte`. `feasibilityWorkspace.svelte.ts` (chat/streaming, 75 lines) stays separate — it's cohesive and independent.

### Step 11 — Delete `store.svelte.ts`

Delete `frontend/src/lib/feasibility/workbook/store.svelte.ts`.

**Verify:** `just test-frontend` passes. No component imports from both stores. `ChatPanel.svelte` (currently imports both) is the test case.

---

## Phase D — Type File Cleanup

**Goal:** Delete `frontend/src/lib/types/feasibility.ts` (exists only to paper over backend/frontend mismatches now fixed).

### Step 12 — Audit each type in `types/feasibility.ts`

Each `Omit<ApiType> & { field: null-not-undefined }` re-extension exists because the generated type had `field?: T` (optional/undefined) where the frontend needed `field: T | null`. With backend types corrected in Phase A, regenerate and check which re-extensions are still needed.

For any that remain necessary after the regeneration, inline the fix into the generated type's usage rather than maintaining a separate re-extension file.

### Step 13 — Delete `frontend/src/lib/types/feasibility.ts`

Update all imports to point to `$lib/api/generated/hey-api/types.gen` directly.

**Verify:** `just build-frontend` passes clean.

---

## Phase E — Backend Engine Cleanup

**Goal:** `workbook.py` mirrors `engine.ts` exactly in structure and naming.

### Step 14 — Convert `RatioBand` and `AreaRatioBenchmark` to dataclasses

```python
from dataclasses import dataclass

@dataclass
class RatioBand:
    low: float
    base: float
    high: float

@dataclass
class AreaRatioBenchmark:
    usage: Usage
    building_form: BuildingForm
    coverage_ratio: RatioBand
    bua_to_gfa_efficiency: RatioBand
    gfa_to_gsa_efficiency: RatioBand
    source_notes: list[str]
```

No behavior change.

### Step 15 — Verify function order and naming match `engine.ts`

Section by section confirm parity:
- `compute_area` / `computeArea`
- `compute_program` / `computeProgram`
- `compute_costs` / `computeCosts`
- `compute_funding` / `computeFunding`
- `compute_cash_flow` / `computeCashFlow`
- `compute_returns` / `computeReturns`
- `compute_workbook` / `computeWorkbook` (main entry point)

Same argument order, same section comments. Where logic diverges intentionally (e.g. backend has richer date handling), add a comment noting it.

### Step 16 — Delete `FeasibilityComputedSummary` if unused

Check `router.py` — if `FeasibilityComputedSummary` is not returned by any endpoint, delete it from `models.py`. It's a 20-field denormalized duplicate of `FeasibilityWorkbook`.

**Verify:** `just test-backend` passes clean.

---

## Verification Checkpoints

| After | Command | Expected |
|-------|---------|----------|
| Step 3 | `just generate-client` | No errors, 4 new fields in generated types |
| Step 4 | `just build-frontend` | Clean |
| Step 8 | `just build-frontend` | Clean, all sheets render |
| Step 11 | `just test-frontend` | Clean, no dual-store imports |
| Step 13 | `just build-frontend` | Clean |
| Step 16 | `just test-backend` | Clean |
| Final | `just check-all` | Clean end to end |

---

## File Disposition Summary

| File | Action |
|------|--------|
| `frontend/src/lib/feasibility/workbook/engine.ts` | Extended (Phase B) |
| `frontend/src/lib/feasibility/workbook/compute.ts` | **Deleted** (Phase B) |
| `frontend/src/lib/feasibility/workbook/models.ts` | Gutted to re-exports (Phase A) |
| `frontend/src/lib/feasibility/workbook/utils.ts` | Remove `buildWorkbookStudy`/`buildLegacyStudy` (Phase B) |
| `frontend/src/lib/feasibility/workbook/validation.ts` | Kept, rename type params (Phase A) |
| `frontend/src/lib/feasibility/workbook/store.svelte.ts` | **Deleted** (Phase C) |
| `frontend/src/lib/stores/feasibilityStudy.svelte.ts` | Merged store lives here (Phase C) |
| `frontend/src/lib/stores/feasibilityWorkspace.svelte.ts` | Kept as-is (chat/streaming) |
| `frontend/src/lib/types/feasibility.ts` | **Deleted** (Phase D) |
| `backend/app/feasibility/models.py` | Add 4 fields to `FeasibilityAssumptions` (Phase A) |
| `backend/app/feasibility/workbook.py` | Use assumption fields, dataclasses (Phase A+E) |
