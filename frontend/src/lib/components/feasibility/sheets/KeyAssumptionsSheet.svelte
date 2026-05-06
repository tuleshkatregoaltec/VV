<script lang="ts">
import { workbookStore } from '$lib/feasibility/workbook/store.svelte'
import { toSqft } from '$lib/utils/units'

function fmt(value: number, digits = 0): string {
	return value.toLocaleString('en-AE', {
		minimumFractionDigits: digits,
		maximumFractionDigits: digits
	})
}

function fmtAed(value: number): string {
	return fmt(Math.round(value))
}

function dateToQuarter(isoDate: string): string {
	if (!isoDate) return '—'
	const d = new Date(isoDate)
	if (Number.isNaN(d.getTime())) return isoDate
	const q = Math.ceil((d.getMonth() + 1) / 3)
	return `Q${q} ${d.getFullYear()}`
}

function setNumber<K extends keyof typeof workbookStore.inputs>(key: K, raw: string) {
	const v = Number(raw)
	workbookStore.updateInputs({ [key]: Number.isFinite(v) ? v : 0 })
}

function setAed<K extends keyof typeof workbookStore.inputs>(key: K, raw: string) {
	const v = Number(raw)
	workbookStore.updateInputs({ [key]: Number.isFinite(v) ? v : 0 })
}

const s = workbookStore
const isBtr = $derived(s.inputs.developmentModel === 'build_to_rent_residential')
const workbook = $derived(s.workbook ?? null)
const research = $derived(workbookStore.research)
const offPlanConfidence = $derived(research?.off_plan_pricing_confidence ?? null)
const offPlanBenchmarks = $derived(research?.off_plan_unit_benchmarks ?? [])
const rentalMarketSummary = $derived(research?.rental_market_summary ?? null)
const rentalComparables = $derived(research?.rental_comparables ?? [])
const validation = $derived(s.validation)
const massing = $derived(workbook?.siteMassing ?? null)
const btrConfigs = $derived(s.inputs.btrUnitConfigs ?? [])

// Derived display values
const gfaSqft = $derived(toSqft(s.maxGfaSqm))
const plotAreaSqft = $derived(toSqft(s.inputs.plotAreaSqm))
const buaSqft = $derived(toSqft(s.totalBuaSqm))

const avgGsaPerUnit = $derived(
	s.totalUnits > 0 ? toSqft(s.totalConfiguredAreaSqm / s.totalUnits) : 0
)
const avgSalesPricePerUnit = $derived(
	s.totalUnits > 0 ? s.totalConfiguredRevenue / s.totalUnits : 0
)
const paymentPlanTotal = $derived(
	s.paymentPlan.depositPct + s.paymentPlan.constructionPct + s.paymentPlan.handoverPct
)
const gsaAsPctOfGfa = $derived(gfaSqft > 0 ? (toSqft(s.totalConfiguredAreaSqm) / gfaSqft) * 100 : 0)
const btrTotalGlaSqm = $derived(
	workbook?.btr?.program.totalAreaSqm ??
		btrConfigs.reduce((acc, config) => acc + config.units * config.avgSizeSqm, 0)
)
const btrGlaAsPctOfGfa = $derived(s.maxGfaSqm > 0 ? (btrTotalGlaSqm / s.maxGfaSqm) * 100 : 0)
const constructionSqueezed = $derived(
	s.totalDebtCapacity > 0 && s.constructionLoanCapacity / s.totalDebtCapacity < 0.2
)

const devCostSubtotal = $derived(
	s.designSupervisionCost +
		s.demolitionCost +
		s.constructionCostInclInflation +
		s.inputs.infrastructureCostAed +
		s.inputs.governmentFeesAed +
		s.marketingCost +
		s.salesAgentFees +
		s.inputs.masterCommunityFeesAed +
		s.inputs.ffeOsePreopeningCostAed +
		s.contingencyCost
)

const moic = $derived(s.workbook?.returns?.projectMoic ?? s.revenueMultiple)

const constructionDurationMonths = $derived.by(() => {
	const c = new Date(s.inputs.constructionDate)
	const h = new Date(s.inputs.handoverDate)
	if (Number.isNaN(c.getTime()) || Number.isNaN(h.getTime())) return null
	return Math.max(0, (h.getFullYear() - c.getFullYear()) * 12 + (h.getMonth() - c.getMonth()))
})

// Input cell classes — blue text, minimal styling
const INPUT =
	'w-full text-right px-1 py-0 text-[#1565C0] bg-transparent focus:outline-none tabular-nums'
const INPUT_LEFT = 'w-full text-left px-1 py-0 text-[#1565C0] bg-transparent focus:outline-none'

// Row classes
const ROW_STD = 'border-b border-[#D9D9D9]'
const ROW_TOTAL = 'border-t border-[#1F3864] border-b border-[#D9D9D9]'
const ROW_GRAND = 'border-t-2 border-[#1F3864]'
const ROW_INDENT = 'border-b border-[#D9D9D9] bg-[#F9F9F9]'

// Cell classes
const LABEL = 'px-2 py-[3px] text-slate-800'
const LABEL_INDENT = 'pl-6 pr-2 py-[3px] text-slate-600 italic text-[10px]'
const VALUE_BLUE = 'px-2 py-[3px] text-right tabular-nums text-[#1565C0] font-normal'
const VALUE_BLACK = 'px-2 py-[3px] text-right tabular-nums text-slate-900 font-normal'
const VALUE_BOLD_BLACK = 'px-2 py-[3px] text-right tabular-nums text-slate-900 font-semibold'
const VALUE_BOLD_BLUE = 'px-2 py-[3px] text-right tabular-nums text-[#1565C0] font-semibold'
const VALUE_GREEN = 'px-2 py-[3px] text-right tabular-nums text-emerald-700 font-normal'
const VALUE_BOLD_GREEN = 'px-2 py-[3px] text-right tabular-nums text-emerald-700 font-semibold'
const UNIT = 'px-2 py-[3px] text-slate-500 whitespace-nowrap'

let sheetScroller = $state<HTMLDivElement | null>(null)
let lastHighlightSequence = $state(0)

function fieldTokens(...fields: string[]): string {
	return fields.join(' ')
}

function hasHighlightedField(...fields: string[]): boolean {
	const active = s.highlightedFields
	return fields.some((field) => active.includes(field))
}

function highlightClass(...fields: string[]): string {
	return hasHighlightedField(...fields) ? 'feasibility-change-flash' : ''
}

function scrollToFirstHighlightedField(): void {
	const fields = s.highlightedFields
	if (!sheetScroller || fields.length === 0) return
	const nodes = Array.from(sheetScroller.querySelectorAll<HTMLElement>('[data-feasibility-field]'))
	const priorityFields = [...fields.filter((field) => field !== 'assumptions'), 'assumptions']
	const target = priorityFields
		.map((field) =>
			nodes.find((node) => {
				const tokens = node.dataset.feasibilityField?.split(/\s+/) ?? []
				return tokens.includes(field)
			})
		)
		.find(Boolean)
	target?.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' })
}

$effect(() => {
	if (!sheetScroller || s.highlightSequence === lastHighlightSequence) return
	lastHighlightSequence = s.highlightSequence
	setTimeout(scrollToFirstHighlightedField, 80)
})

function updateBtrUnitConfig(id: string, patch: Record<string, number | string>) {
	const updated = (s.inputs.btrUnitConfigs ?? []).map((c) => (c.id === id ? { ...c, ...patch } : c))
	s.updateInputs({ btrUnitConfigs: updated } as any)
}

function setBtrNumber<K extends string>(key: K, raw: string) {
	const v = Number(raw)
	s.updateInputs({ [key]: Number.isFinite(v) ? v : 0 } as any)
}
</script>

<div
	bind:this={sheetScroller}
	class="overflow-auto flex-1 bg-white text-[11px] font-[Calibri,'Segoe_UI',Arial,sans-serif] select-none"
>

	<!-- Model Header -->
	<div
		class="bg-[#1F3864] text-white px-4 py-2.5 flex items-start justify-between gap-4 {highlightClass('assumptions')}"
		data-feasibility-field="assumptions"
	>
		<div>
			<div class="text-[13px] font-bold tracking-wide">KEY ASSUMPTIONS</div>
			<div class="text-[10px] text-blue-200 mt-0.5">Feasibility 2 Model &mdash; All monetary values in AED unless stated</div>
		</div>
		<div class="text-[10px] text-right leading-5 mt-0.5 shrink-0">
			<div><span class="text-[#90CAF9] font-semibold">■</span> <span class="text-[#90CAF9]">Blue text</span> = Original Input / Hardcoded</div>
			<div><span class="text-white font-semibold">■</span> <span class="text-white">Black text</span> = Formula / Derived Value</div>
		</div>
	</div>

	<!-- Summary cards: Market Confidence + Model QA -->
	<div class="px-4 py-3 border-b border-[#D9D9D9] bg-[#F8FAFC]">
		<div class="grid gap-3 xl:grid-cols-3">
			<div class="rounded-lg border border-slate-200 bg-white overflow-hidden">
				<div class="px-3 py-2 bg-slate-50 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
					Market Confidence
				</div>
				<div class="px-3 py-3 space-y-2 text-[11px]">
					{#if isBtr}
						<div class="flex items-start justify-between gap-3">
							<span class="text-slate-500">Area avg rent</span>
							<span class="font-medium text-slate-800">
								{rentalMarketSummary?.avg_rent_price_sqm_12m ? `AED ${fmt(rentalMarketSummary.avg_rent_price_sqm_12m)} /sqm/yr` : 'N/A'}
							</span>
						</div>
						<div class="flex items-start justify-between gap-3">
							<span class="text-slate-500">Rental contracts</span>
							<span class="font-medium text-slate-800">{rentalMarketSummary?.rental_contract_count_12m ?? 0}</span>
						</div>
						<div class="flex items-start justify-between gap-3">
							<span class="text-slate-500">Rental comparables</span>
							<span class="font-medium text-slate-800">{rentalComparables.length}</span>
						</div>
						<div class="flex items-start justify-between gap-3">
							<span class="text-slate-500">Gross yield anchor</span>
							<span class="font-medium text-slate-800">
								{rentalMarketSummary?.gross_yield_pct ? `${fmt(rentalMarketSummary.gross_yield_pct, 2)}%` : 'N/A'}
							</span>
						</div>
					{:else}
						<div class="flex items-start justify-between gap-3">
							<span class="text-slate-500">Off-plan pricing confidence</span>
							<span class="font-medium {offPlanConfidence?.confidence_label === 'low' ? 'text-amber-700' : offPlanConfidence?.confidence_label === 'medium' ? 'text-sky-700' : 'text-emerald-700'}">
								{offPlanConfidence ? `${offPlanConfidence.confidence_label} · ${fmt(offPlanConfidence.confidence_score, 1)}` : 'N/A'}
							</span>
						</div>
						<div class="flex items-start justify-between gap-3">
							<span class="text-slate-500">Unit benchmarks</span>
							<span class="font-medium text-slate-800">{offPlanBenchmarks.length}</span>
						</div>
						<div class="flex items-start justify-between gap-3">
							<span class="text-slate-500">Fallback pricing rows</span>
							<span class="font-medium text-slate-800">{offPlanBenchmarks.filter((row) => row.fallback_used).length}</span>
						</div>
						<div class="flex items-start justify-between gap-3">
							<span class="text-slate-500">Low-confidence unit rows</span>
							<span class="font-medium text-slate-800">{offPlanBenchmarks.filter((row) => row.confidence_label === 'low').length}</span>
						</div>
						{#if offPlanConfidence}
							<div class="pt-2 border-t border-slate-100 text-slate-400 leading-4">
								{offPlanConfidence.note}
							</div>
						{/if}
					{/if}
				</div>
			</div>

			<div class="rounded-lg border border-slate-200 bg-white overflow-hidden">
				<div class="px-3 py-2 bg-slate-50 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
					Site Capacity
				</div>
				<div class="px-3 py-3 space-y-2 text-[11px]">
					<div class="flex items-start justify-between gap-3">
						<span class="text-slate-500">Applied coverage</span>
						<span class="font-medium text-slate-800">{massing ? `${fmt(massing.appliedCoveragePct, 1)}%` : 'N/A'}</span>
					</div>
					<div class="flex items-start justify-between gap-3">
						<span class="text-slate-500">Building count</span>
						<span class="font-medium text-slate-800">{massing?.buildingCount ?? 'N/A'}</span>
					</div>
					<div class="flex items-start justify-between gap-3">
						<span class="text-slate-500">Required floors</span>
						<span class="font-medium {(massing?.gfaShortfallSqm ?? 0) > 0 || (massing?.unitCapacityGap ?? 0) < 0 ? 'text-rose-700' : 'text-slate-800'}">{massing ? fmt(Math.max(massing.requiredFloorsAtCoverage, massing.requiredTotalFloorsForProgram)) : 'N/A'}</span>
					</div>
					<div class="flex items-start justify-between gap-3">
						<span class="text-slate-500">Unit capacity gap</span>
						<span class="font-medium {(massing?.unitCapacityGap ?? 0) < 0 ? 'text-rose-700' : 'text-emerald-700'}">{massing ? fmt(massing.unitCapacityGap) : 'N/A'} units</span>
					</div>
					<div class="flex items-start justify-between gap-3">
						<span class="text-slate-500">GFA shortfall</span>
						<span class="font-medium {(massing?.gfaShortfallSqm ?? 0) > 0 ? 'text-rose-700' : 'text-emerald-700'}">{massing ? fmt(massing.gfaShortfallSqm) : 'N/A'} sqm</span>
					</div>
					<div class="pt-2 border-t border-slate-100 text-slate-400 leading-4">
						Coverage × selected floors determines whether the paid-for GFA physically fits.
					</div>
				</div>
			</div>

			<div class="rounded-lg border border-slate-200 bg-white overflow-hidden">
				<div class="px-3 py-2 bg-slate-50 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
					Model QA
				</div>
				<div class="px-3 py-3 space-y-2 text-[11px]">
					<div class="flex items-start justify-between gap-3">
						<span class="text-slate-500">Validation status</span>
						<span class="font-medium {validation?.status === 'invalid' ? 'text-rose-700' : validation?.status === 'needs_review' ? 'text-amber-700' : 'text-emerald-700'}">
							{validation ? validation.status.replace('_', ' ') : 'N/A'}
						</span>
					</div>
					<div class="flex items-start justify-between gap-3">
						<span class="text-slate-500">Hard fails</span>
						<span class="font-medium {(validation?.hardFailures ?? 0) > 0 ? 'text-rose-700' : 'text-slate-800'}">{validation?.hardFailures ?? 0}</span>
					</div>
					<div class="flex items-start justify-between gap-3">
						<span class="text-slate-500">Warnings</span>
						<span class="font-medium {(validation?.warnings ?? 0) > 0 ? 'text-amber-700' : 'text-slate-800'}">{validation?.warnings ?? 0}</span>
					</div>
					<div class="flex items-start justify-between gap-3">
						<span class="text-slate-500">Missing evidence</span>
						<span class="font-medium {(validation?.missingEvidence ?? 0) > 0 ? 'text-sky-700' : 'text-slate-800'}">{validation?.missingEvidence ?? 0}</span>
					</div>
					{#if Object.keys(s.reviewDecisions).length > 0}
					<div class="pt-2 border-t border-slate-100 space-y-1">
						<div class="flex items-center justify-between gap-3"><span class="text-slate-500">✓ Accepted</span><span class="font-medium text-emerald-700">{Object.values(s.reviewDecisions).filter((r) => r.decision === 'accepted').length}</span></div>
						<div class="flex items-center justify-between gap-3"><span class="text-slate-500">↻ Review later</span><span class="font-medium text-amber-700">{Object.values(s.reviewDecisions).filter((r) => r.decision === 'review_later').length}</span></div>
						<div class="flex items-center justify-between gap-3"><span class="text-slate-500">? Needs evidence</span><span class="font-medium text-sky-700">{Object.values(s.reviewDecisions).filter((r) => r.decision === 'needs_evidence').length}</span></div>
					</div>
					{/if}
					<div class="pt-2 border-t border-slate-100 text-slate-400 leading-4">
						Use the Checks tab for reconciliation issues and final underwriting review.
					</div>
				</div>
			</div>
		</div>
	</div>

	<!-- Main table -->
	<table class="w-full border-collapse" style="border-spacing:0">
		<colgroup>
			<col style="width:2.5%">
			<col style="width:44%">
			<col style="width:28%">
			<col style="width:13%">
		</colgroup>

		<!-- ═══════════════════════════════════════════════════════════
		     SECTION 1 — AREAS & UNITS
		     ═══════════════════════════════════════════════════════════ -->
		<tbody>
			<tr class="bg-[#1F3864]">
				<td colspan="4" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">1. &nbsp; AREAS &amp; UNITS</td>
			</tr>

			<!-- 1a. AREA -->
			<tr class="bg-[#D6DCE4]">
				<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">1a. &nbsp; Area</td>
			</tr>

			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
				<td class={LABEL}>Location</td>
				<td class={VALUE_BLUE}>
					{s.plotDetails?.community_name ?? s.plot?.community_name ?? '—'}
				</td>
				<td class={UNIT}></td>
			</tr>
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
				<td class={LABEL}>
					Plot Area
				</td>
				<td class={VALUE_BLUE}>{fmt(plotAreaSqft, 0)}</td>
				<td class={UNIT}>sq ft</td>
			</tr>
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
				<td class={LABEL}>
					GFA
				</td>
				<td class={VALUE_BLUE}>{fmt(gfaSqft, 0)}</td>
				<td class={UNIT}>sq ft</td>
			</tr>
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
				<td class={LABEL}>BUA Multiple</td>
				<td
					class={`p-0 ${highlightClass('buaMultiplier')}`}
					data-feasibility-field="buaMultiplier"
				>
					<input
						type="number"
						step="0.01"
						min="1.0"
						max="2.0"
						class={INPUT}
						value={s.inputs.buaMultiplier}
						oninput={(e) => setNumber('buaMultiplier', e.currentTarget.value)}
					/>
				</td>
				<td class={UNIT}>x</td>
			</tr>
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">e</td>
				<td class={LABEL}>Parking Spaces — Total</td>
				<td class={VALUE_BLACK}>{fmt(s.totalParkingSpaces, 0)}</td>
				<td class={UNIT}>spaces</td>
			</tr>
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">f</td>
				<td class={LABEL}>BUA <span class="text-slate-400 font-normal italic">(GFA × BUA Multiple + 350 sf × Spaces)</span></td>
				<td class={VALUE_BLACK}>{fmt(buaSqft, 0)}</td>
				<td class={UNIT}>sq ft</td>
			</tr>

			<!-- 1a-ii. Building Configuration -->
			<tr class="bg-[#D6DCE4]">
				<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">1a-ii. &nbsp; Building Configuration</td>
			</tr>
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
				<td class={LABEL}>Regulatory Max Storeys <span class="text-slate-400 font-normal italic">(optional cap)</span></td>
				<td
					class={`p-0 ${highlightClass('maxStoreys')}`}
					data-feasibility-field="maxStoreys"
				>
					<input type="number" step="1" min="0" class={INPUT}
						value={s.inputs.maxStoreys && s.inputs.maxStoreys > 0 ? s.inputs.maxStoreys : ''}
						placeholder="No cap"
						oninput={(e) => setNumber('maxStoreys', e.currentTarget.value)}
					/>
				</td>
				<td class={UNIT}>floors</td>
			</tr>
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
				<td class={LABEL}>Basement Parking Floors</td>
				<td
					class={`p-0 ${highlightClass('basementParkingFloors')}`}
					data-feasibility-field="basementParkingFloors"
				>
					<input type="number" step="1" min="0" class={INPUT}
						value={s.inputs.basementParkingFloors ?? 4}
						oninput={(e) => setNumber('basementParkingFloors', e.currentTarget.value)}
					/>
				</td>
				<td class={UNIT}>floors</td>
			</tr>
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
				<td class={LABEL}>Podium Floors</td>
				<td
					class={`p-0 ${highlightClass('podiumFloors')}`}
					data-feasibility-field="podiumFloors"
				>
					<input type="number" step="1" min="0" class={INPUT}
						value={s.inputs.podiumFloors ?? 5}
						oninput={(e) => setNumber('podiumFloors', e.currentTarget.value)}
					/>
				</td>
				<td class={UNIT}>floors</td>
			</tr>
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
				<td class={LABEL}>{isBtr ? 'Selected Residential Floors' : 'Residential Floors'}</td>
				<td
					class={`p-0 ${highlightClass('residentialFloors')}`}
					data-feasibility-field="residentialFloors"
				>
					<input type="number" step="1" min="0" class={INPUT}
						value={s.inputs.residentialFloors ?? 30}
						oninput={(e) => setNumber('residentialFloors', e.currentTarget.value)}
					/>
				</td>
				<td class={UNIT}>floors</td>
			</tr>
			{#if isBtr && massing}
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">—</td>
				<td class={`${LABEL} pl-8 italic text-slate-600`}>↳ Required total GFA floors</td>
				<td class={massing.gfaShortfallSqm > 0 ? 'px-1 py-[3px] text-right text-[11px] tabular-nums text-rose-700' : VALUE_BLACK}>{fmt(massing.requiredFloorsAtCoverage)}</td>
				<td class={UNIT}>floors</td>
			</tr>
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">—</td>
				<td class={`${LABEL} pl-8 italic text-slate-600`}>↳ Required residential floors for unit mix</td>
				<td class={massing.unitCapacityGap < 0 ? 'px-1 py-[3px] text-right text-[11px] tabular-nums text-rose-700' : VALUE_BLACK}>{fmt(massing.requiredResidentialFloorsForUnits)}</td>
				<td class={UNIT}>floors</td>
			</tr>
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">—</td>
				<td class={`${LABEL} pl-8 italic text-slate-600`}>↳ Selected / capped total floors</td>
				<td class={VALUE_BLACK}>{massing.buildings[0] ? fmt(massing.buildings[0].totalFloors) : '—'}</td>
				<td class={UNIT}>floors</td>
			</tr>
			{/if}
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">e</td>
				<td class={LABEL}>Amenity / Roof Floors</td>
				<td
					class={`p-0 ${highlightClass('amenityRoofFloors')}`}
					data-feasibility-field="amenityRoofFloors"
				>
					<input type="number" step="1" min="0" class={INPUT}
						value={s.inputs.amenityRoofFloors ?? 1}
						oninput={(e) => setNumber('amenityRoofFloors', e.currentTarget.value)}
					/>
				</td>
				<td class={UNIT}>floors</td>
			</tr>
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">f</td>
				<td class={LABEL}>Parking Area per Space</td>
				<td
					class={`p-0 ${highlightClass('parkingAreaPerSpaceSqm')}`}
					data-feasibility-field="parkingAreaPerSpaceSqm"
				>
					<input type="number" step="1" min="0" class={INPUT}
						value={s.inputs.parkingAreaPerSpaceSqm ?? 30}
						oninput={(e) => setNumber('parkingAreaPerSpaceSqm', e.currentTarget.value)}
					/>
				</td>
				<td class={UNIT}>sqm</td>
			</tr>
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">g</td>
				<td class={LABEL}>Above-grade BUA Factor</td>
				<td
					class={`p-0 ${highlightClass('aboveGradeBuaFactor')}`}
					data-feasibility-field="aboveGradeBuaFactor"
				>
					<input type="number" step="0.01" min="0" class={INPUT}
						value={s.inputs.aboveGradeBuaFactor ?? 1.1}
						oninput={(e) => setNumber('aboveGradeBuaFactor', e.currentTarget.value)}
					/>
				</td>
				<td class={UNIT}>x</td>
			</tr>
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">h</td>
				<td class={LABEL}>Service / BOH / Plant %</td>
				<td
					class={`p-0 ${highlightClass('serviceBohPlantPct')}`}
					data-feasibility-field="serviceBohPlantPct"
				>
					<input type="number" step="0.01" min="0" max="100" class={INPUT}
						value={Math.round((s.inputs.serviceBohPlantPct ?? 0.03) * 100)}
						oninput={(e) => s.updateInputs({ serviceBohPlantPct: (Number(e.currentTarget.value) || 0) / 100 })}
					/>
				</td>
				<td class={UNIT}>%</td>
			</tr>

			<!-- 1b. CONFIGURATION -->
			<tr class="bg-[#D6DCE4]">
				<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">1b. &nbsp; {isBtr ? 'Rental Unit Mix' : 'Configuration'}</td>
			</tr>
		</tbody>
	</table>

	{#if isBtr}
	<!-- BTR Rental Unit Config sub-table -->
	<table class="w-full border-collapse border-b border-[#D9D9D9]" style="border-spacing:0">
		<colgroup>
			<col style="width:13%">
			<col style="width:8%">
			<col style="width:12%">
			<col style="width:14%">
			<col style="width:14%">
			<col style="width:10%">
			<col style="width:14%">
		</colgroup>
		<thead>
			<tr class="bg-[#EEF2F7] border-b border-[#B8C4CE]">
				<th class="px-2 py-[4px] text-left text-[10px] font-semibold text-slate-600 uppercase tracking-wider border-r border-[#D9D9D9]">Type</th>
				<th class="px-2 py-[4px] text-right text-[10px] font-semibold text-slate-600 uppercase tracking-wider border-r border-[#D9D9D9]">Units</th>
				<th class="px-2 py-[4px] text-right text-[10px] font-semibold text-slate-600 uppercase tracking-wider border-r border-[#D9D9D9]">Avg Size (sqm)</th>
				<th class="px-2 py-[4px] text-right text-[10px] font-semibold text-slate-600 uppercase tracking-wider border-r border-[#D9D9D9]">Monthly Rent (AED)</th>
				<th class="px-2 py-[4px] text-right text-[10px] font-semibold text-slate-600 uppercase tracking-wider border-r border-[#D9D9D9]">Annual Rent (AED)</th>
				<th class="px-2 py-[4px] text-right text-[10px] font-semibold text-slate-600 uppercase tracking-wider border-r border-[#D9D9D9]">Parking</th>
				<th class="px-2 py-[4px] text-right text-[10px] font-semibold text-slate-600 uppercase tracking-wider">Total Area (sqm)</th>
			</tr>
		</thead>
		<tbody>
			{#each btrConfigs as cfg (cfg.id)}
				<tr class="border-b border-[#EBEBEB]">
					<td class="px-2 py-[3px] text-slate-800 border-r border-[#E8E8E8]">{cfg.label}</td>
					<td class="p-0 border-r border-[#E8E8E8]">
						<input type="number" step="1" class={INPUT} value={cfg.units}
							oninput={(e) => updateBtrUnitConfig(cfg.id, { units: Number(e.currentTarget.value) || 0 })}
						/>
					</td>
					<td class="p-0 border-r border-[#E8E8E8]">
						<input type="number" step="1" class={INPUT} value={cfg.avgSizeSqm}
							oninput={(e) => updateBtrUnitConfig(cfg.id, { avgSizeSqm: Number(e.currentTarget.value) || 0 })}
						/>
					</td>
					<td class="p-0 border-r border-[#E8E8E8]">
						<input type="number" step="100" class={INPUT} value={cfg.monthlyRentAed}
							oninput={(e) => updateBtrUnitConfig(cfg.id, { monthlyRentAed: Number(e.currentTarget.value) || 0 })}
						/>
					</td>
					<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 border-r border-[#E8E8E8]">{fmtAed(cfg.units * cfg.monthlyRentAed * 12)}</td>
					<td class="p-0 border-r border-[#E8E8E8]">
						<input type="number" step="0.5" min="0" class={INPUT} value={cfg.parkingRatio}
							oninput={(e) => updateBtrUnitConfig(cfg.id, { parkingRatio: Number(e.currentTarget.value) || 0 })}
						/>
					</td>
					<td class="px-2 py-[3px] text-right tabular-nums text-slate-900">{fmt(cfg.units * cfg.avgSizeSqm, 0)}</td>
				</tr>
			{/each}
			{#if btrConfigs.length > 0}
			<tr class="border-t-2 border-[#1F3864] bg-[#EEF2F7]">
				<td class="px-2 py-[3px] text-slate-900 font-semibold text-[10px] border-r border-[#E8E8E8]">Total</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 font-semibold border-r border-[#E8E8E8]">{fmt(btrConfigs.reduce((acc, c) => acc + c.units, 0))}</td>
				<td class="border-r border-[#E8E8E8]"></td>
				<td class="border-r border-[#E8E8E8]"></td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 font-semibold border-r border-[#E8E8E8]">{fmtAed(btrConfigs.reduce((acc, c) => acc + c.units * c.monthlyRentAed * 12, 0))}</td>
				<td class="border-r border-[#E8E8E8]"></td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 font-semibold">{fmt(btrConfigs.reduce((acc, c) => acc + c.units * c.avgSizeSqm, 0), 0)}</td>
			</tr>
			{:else}
			<tr class="border-b border-[#EBEBEB]">
				<td colspan="7" class="px-3 py-4 text-center text-slate-400 italic">
					No rental unit configs — will derive from BTS unit mix with estimated rents
				</td>
			</tr>
			{/if}
		</tbody>
	</table>
	<div class="px-3 py-1.5 text-[10px] bg-[#FFFDE7] border-b border-[#D9D9D9] text-slate-600">
		<span class="font-medium">Efficiency check:</span>
		Total GLA {fmt(btrTotalGlaSqm, 0)} sqm ({fmt(toSqft(btrTotalGlaSqm), 0)} sf)
		vs GFA {fmt(s.maxGfaSqm, 0)} sqm ({fmt(gfaSqft, 0)} sf)
		&nbsp;→&nbsp;
		<span class={btrGlaAsPctOfGfa > 100 ? 'text-rose-700 font-semibold' : btrGlaAsPctOfGfa >= 75 ? 'text-emerald-700 font-semibold' : 'text-amber-700 font-semibold'}>
			{fmt(btrGlaAsPctOfGfa, 1)}% of GFA
		</span>
		&nbsp;<span class="text-slate-400">(target ~75-85%)</span>
		&nbsp;·&nbsp;
		{#if btrGlaAsPctOfGfa > 100}
			<span class="text-rose-700 font-semibold">GLA exceeds GFA - impossible programme</span>
		{:else if btrGlaAsPctOfGfa >= 75}
			<span class="text-emerald-700">Within typical residential efficiency range</span>
		{:else}
			<span class="text-amber-700">Under-utilised GFA - review units, floors, or coverage</span>
		{/if}
	</div>
	{:else}
	<!-- BTS Sales Unit Config sub-table -->
	<table class="w-full border-collapse border-b border-[#D9D9D9]" style="border-spacing:0">
		<colgroup>
			<col style="width:11%">
			<col style="width:8%">
			<col style="width:13%">
			<col style="width:13%">
			<col style="width:11%">
			<col style="width:13%">
			<col style="width:14%">
		</colgroup>
		<thead>
			<tr class="bg-[#EEF2F7] border-b border-[#B8C4CE]">
				<th class="px-2 py-[4px] text-left text-[10px] font-semibold text-slate-600 uppercase tracking-wider border-r border-[#D9D9D9]">Type</th>
				<th class="px-2 py-[4px] text-right text-[10px] font-semibold text-slate-600 uppercase tracking-wider border-r border-[#D9D9D9]">No.</th>
				<th class="px-2 py-[4px] text-right text-[10px] font-semibold text-slate-600 uppercase tracking-wider border-r border-[#D9D9D9]">Avg GSA (SF)</th>
				<th class="px-2 py-[4px] text-right text-[10px] font-semibold text-slate-600 uppercase tracking-wider border-r border-[#D9D9D9]">Avg PPSF (AED)</th>
				<th class="px-2 py-[4px] text-right text-[10px] font-semibold text-slate-600 uppercase tracking-wider border-r border-[#D9D9D9]">Parking / Unit</th>
				<th class="px-2 py-[4px] text-right text-[10px] font-semibold text-slate-600 uppercase tracking-wider border-r border-[#D9D9D9]">Total GSA (SF)</th>
				<th class="px-2 py-[4px] text-right text-[10px] font-semibold text-slate-600 uppercase tracking-wider">Total Revenue (AED)</th>
			</tr>
		</thead>
		<tbody>
			{#each s.unitConfigs as cfg (cfg.id)}
				{@const unitConfigField = `unitConfig:${cfg.id}`}
				{@const gsaSf = toSqft(cfg.avgSizeSqm)}
				{@const ppsf = cfg.sellingRatePsqm * 0.092903}
				{@const totalGsaSf = toSqft(cfg.units * cfg.avgSizeSqm)}
				{@const totalRev = cfg.units * cfg.avgSizeSqm * cfg.sellingRatePsqm}
				<tr class="border-b border-[#EBEBEB]">
					<td class="px-2 py-[3px] text-slate-800 border-r border-[#E8E8E8]">{cfg.label}</td>
					<td
						class={`p-0 border-r border-[#E8E8E8] ${highlightClass(`${unitConfigField}:units`, 'unitMix')}`}
						data-feasibility-field={fieldTokens(`${unitConfigField}:units`, 'unitMix')}
					>
						<input
							type="number"
							step="1"
							class={INPUT}
							value={cfg.units}
							oninput={(e) => s.updateUnitConfig(cfg.id, { units: Number(e.currentTarget.value) || 0 })}
						/>
					</td>
					<td
						class={`p-0 border-r border-[#E8E8E8] ${highlightClass(`${unitConfigField}:avgSizeSqm`, 'unitMix')}`}
						data-feasibility-field={fieldTokens(`${unitConfigField}:avgSizeSqm`, 'unitMix')}
					>
						<input
							type="number"
							step="1"
							class={INPUT}
							value={Math.round(gsaSf)}
							oninput={(e) => s.updateUnitConfig(cfg.id, { avgSizeSqm: (Number(e.currentTarget.value) || 0) * 0.092903 })}
						/>
					</td>
					<td
						class={`p-0 border-r border-[#E8E8E8] ${highlightClass(`${unitConfigField}:sellingRatePsqm`, 'priceUpdate', 'unitMix')}`}
						data-feasibility-field={fieldTokens(`${unitConfigField}:sellingRatePsqm`, 'priceUpdate', 'unitMix')}
					>
						<input
							type="number"
							step="1"
							class={INPUT}
							value={Math.round(ppsf)}
							oninput={(e) => s.updateUnitConfig(cfg.id, { sellingRatePsqm: (Number(e.currentTarget.value) || 0) / 0.092903 })}
						/>
					</td>
					<td
						class={`p-0 border-r border-[#E8E8E8] ${highlightClass(`${unitConfigField}:parkingRatio`, 'unitMix')}`}
						data-feasibility-field={fieldTokens(`${unitConfigField}:parkingRatio`, 'unitMix')}
					>
						<input
							type="number"
							step="0.5"
							min="0"
							class={INPUT}
							value={cfg.parkingRatio}
							oninput={(e) => s.updateUnitConfig(cfg.id, { parkingRatio: Number(e.currentTarget.value) ?? 0 })}
						/>
					</td>
					<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 border-r border-[#E8E8E8]">{fmt(totalGsaSf, 0)}</td>
					<td class="px-2 py-[3px] text-right tabular-nums text-slate-900">{fmtAed(totalRev)}</td>
				</tr>
			{/each}
			<!-- Totals row -->
			<tr class="border-t-2 border-[#1F3864] bg-[#EEF2F7]">
				<td class="px-2 py-[4px] font-semibold text-slate-800 border-r border-[#D9D9D9]">Total</td>
				<td class="px-2 py-[4px] text-right tabular-nums font-semibold text-slate-900 border-r border-[#D9D9D9]">{fmt(s.totalUnits, 0)}</td>
				<td class="px-2 py-[4px] text-right tabular-nums text-slate-500 border-r border-[#D9D9D9]">—</td>
				<td class="px-2 py-[4px] text-right tabular-nums font-semibold text-slate-900 border-r border-[#D9D9D9]">
					{s.totalConfiguredAreaSqm > 0 ? fmt(s.averageSellingPricePsqm * 0.092903, 0) : '—'}
				</td>
				<td class="px-2 py-[4px] text-right tabular-nums font-semibold text-slate-900 border-r border-[#D9D9D9]">{fmt(s.totalParkingSpaces, 0)}</td>
				<td class="px-2 py-[4px] text-right tabular-nums font-semibold text-slate-900 border-r border-[#D9D9D9]">{fmt(toSqft(s.totalConfiguredAreaSqm), 0)}</td>
				<td class="px-2 py-[4px] text-right tabular-nums font-semibold text-slate-900">{fmtAed(s.totalConfiguredRevenue)}</td>
			</tr>
		</tbody>
	</table>
	<!-- GSA vs GFA constraint note -->
	<div class="px-3 py-1.5 text-[10px] bg-[#FFFDE7] border-b border-[#D9D9D9] text-slate-600">
		<span class="font-medium">Constraint check:</span>
		Total GSA {fmt(toSqft(s.totalConfiguredAreaSqm), 0)} sf
		vs GFA {fmt(gfaSqft, 0)} sf
		&nbsp;→&nbsp;
		<span class={gsaAsPctOfGfa > 100 ? 'text-rose-700 font-semibold' : gsaAsPctOfGfa >= 75 ? 'text-emerald-700 font-semibold' : 'text-amber-700 font-semibold'}>
			{fmt(gsaAsPctOfGfa, 1)}% of GFA
		</span>
		&nbsp;<span class="text-slate-400">(target ≈ 80%)</span>
		&nbsp;·&nbsp;
		{#if gsaAsPctOfGfa > 100}
			<span class="text-rose-700 font-semibold">⚠ GSA exceeds GFA — review unit mix</span>
		{:else if gsaAsPctOfGfa >= 75}
			<span class="text-emerald-700">✓ Within acceptable range</span>
		{:else}
			<span class="text-amber-700">↑ Consider increasing unit count or sizes</span>
		{/if}
	</div>
	{/if}

	<!-- Resume main table -->
	<table class="w-full border-collapse" style="border-spacing:0">
		<colgroup>
			<col style="width:2.5%">
			<col style="width:44%">
			<col style="width:28%">
			<col style="width:13%">
		</colgroup>
		<tbody>

		{#if isBtr}
		<!-- ═══════════════════════════════════════════════════════════
		     SECTION 2 (BTR) — OPERATING ASSUMPTIONS
		     ═══════════════════════════════════════════════════════════ -->
		<tr class="bg-[#1F3864]">
			<td colspan="4" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">2. &nbsp; BTR OPERATING ASSUMPTIONS</td>
		</tr>

		<!-- 2a. Lease-Up & Occupancy -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">2a. &nbsp; Lease-Up &amp; Occupancy</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Hold Period</td>
			<td class="p-0"><input type="number" step="1" min="1" class={INPUT} value={s.inputs.btrHoldPeriodYears ?? 10}
				oninput={(e) => setBtrNumber('btrHoldPeriodYears', e.currentTarget.value)} /></td>
			<td class={UNIT}>years</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Lease-Up Pace</td>
			<td class="p-0"><input type="number" step="1" min="1" class={INPUT} value={s.inputs.btrLeaseUpPaceUnitsPerMonth ?? 20}
				oninput={(e) => setBtrNumber('btrLeaseUpPaceUnitsPerMonth', e.currentTarget.value)} /></td>
			<td class={UNIT}>units/mo</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>Stabilized Occupancy</td>
			<td class="p-0"><input type="number" step="1" min="50" max="100" class={INPUT} value={s.inputs.btrStabilizedOccupancyPct ?? 97}
				oninput={(e) => setBtrNumber('btrStabilizedOccupancyPct', e.currentTarget.value)} /></td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
			<td class={LABEL}>Free Rent Concession</td>
			<td class="p-0"><input type="number" step="1" min="0" class={INPUT} value={s.inputs.btrFreeRentMonths ?? 0}
				oninput={(e) => setBtrNumber('btrFreeRentMonths', e.currentTarget.value)} /></td>
			<td class={UNIT}>months</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">e</td>
			<td class={LABEL}>Physical Vacancy <span class="text-slate-400 font-normal italic">(post-stabilization)</span></td>
			<td class="p-0"><input type="number" step="0.5" min="0" class={INPUT} value={s.inputs.btrGeneralVacancyPct ?? 5}
				oninput={(e) => setBtrNumber('btrGeneralVacancyPct', e.currentTarget.value)} /></td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">f</td>
			<td class={LABEL}>Credit Loss / Bad Debt</td>
			<td class="p-0"><input type="number" step="0.25" min="0" class={INPUT} value={s.inputs.btrCreditLossPct ?? 1}
				oninput={(e) => setBtrNumber('btrCreditLossPct', e.currentTarget.value)} /></td>
			<td class={UNIT}>%</td>
		</tr>

		<!-- 2b. Growth & Other Income -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">2b. &nbsp; Growth, Escalation &amp; Other Income</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Market Rent Growth</td>
			<td class="p-0"><input type="number" step="0.5" min="0" class={INPUT} value={s.inputs.btrMarketRentGrowthPct ?? s.inputs.btrAnnualRentGrowthPct ?? 5}
				oninput={(e) => {
					const value = Number(e.currentTarget.value) || 0
					s.updateInputs({ btrMarketRentGrowthPct: value, btrAnnualRentGrowthPct: value })
				}} /></td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Renewal Rent Growth</td>
			<td class="p-0"><input type="number" step="0.5" min="0" class={INPUT} value={s.inputs.btrRenewalRentGrowthPct ?? 5}
				oninput={(e) => setBtrNumber('btrRenewalRentGrowthPct', e.currentTarget.value)} /></td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>Other Income Growth</td>
			<td class="p-0"><input type="number" step="0.5" min="0" class={INPUT} value={s.inputs.btrAncillaryGrowthPct ?? 3}
				oninput={(e) => setBtrNumber('btrAncillaryGrowthPct', e.currentTarget.value)} /></td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
			<td class={LABEL}>OpEx Annual Escalation</td>
			<td class="p-0"><input type="number" step="0.5" min="0" class={INPUT} value={s.inputs.btrOpExGrowthPct ?? 3}
				oninput={(e) => setBtrNumber('btrOpExGrowthPct', e.currentTarget.value)} /></td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">e</td>
			<td class={LABEL}>Dev Cost Escalation / Inflation</td>
			<td class="p-0"><input type="number" step="0.5" min="0" class={INPUT} value={s.inputs.btrDevCostEscalationPct ?? 4}
				oninput={(e) => setBtrNumber('btrDevCostEscalationPct', e.currentTarget.value)} /></td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">f</td>
			<td class={LABEL}>Terminal NOI Growth</td>
			<td class="p-0"><input type="number" step="0.5" min="0" class={INPUT} value={s.inputs.btrTerminalGrowthPct ?? 4}
				oninput={(e) => setBtrNumber('btrTerminalGrowthPct', e.currentTarget.value)} /></td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">g</td>
			<td class={LABEL}>Parking Income</td>
			<td class="p-0"><input type="number" step="10000" min="0" class={INPUT} value={s.inputs.btrParkingIncomeAed ?? 0}
				oninput={(e) => setBtrNumber('btrParkingIncomeAed', e.currentTarget.value)} /></td>
			<td class={UNIT}>AED/yr</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">h</td>
			<td class={LABEL}>Ancillary Income</td>
			<td class="p-0"><input type="number" step="10000" min="0" class={INPUT} value={s.inputs.btrAncillaryIncomeAed ?? 0}
				oninput={(e) => setBtrNumber('btrAncillaryIncomeAed', e.currentTarget.value)} /></td>
			<td class={UNIT}>AED/yr</td>
		</tr>

		<!-- 2b. Operating Expenses -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">2c. &nbsp; Operating Expenses</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Property Management</td>
			<td class="p-0"><input type="number" step="0.5" min="0" class={INPUT} value={s.inputs.btrPropertyManagementPct ?? 5}
				oninput={(e) => setBtrNumber('btrPropertyManagementPct', e.currentTarget.value)} /></td>
			<td class={UNIT}>% of EGR</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Repairs & Maintenance</td>
			<td class="p-0"><input type="number" step="5" min="0" class={INPUT} value={s.inputs.btrRepairsMaintenancePsqm ?? 50}
				oninput={(e) => setBtrNumber('btrRepairsMaintenancePsqm', e.currentTarget.value)} /></td>
			<td class={UNIT}>AED/sqm/yr</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>Insurance</td>
			<td class="p-0"><input type="number" step="1" min="0" class={INPUT} value={s.inputs.btrInsurancePsqm ?? 10}
				oninput={(e) => setBtrNumber('btrInsurancePsqm', e.currentTarget.value)} /></td>
			<td class={UNIT}>AED/sqm/yr</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
			<td class={LABEL}>Service Charge (RERA)</td>
			<td class="p-0"><input type="number" step="5" min="0" class={INPUT} value={s.inputs.btrServiceChargePsqm ?? 80}
				oninput={(e) => setBtrNumber('btrServiceChargePsqm', e.currentTarget.value)} /></td>
			<td class={UNIT}>AED/sqm/yr</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">e</td>
			<td class={LABEL}>Utilities</td>
			<td class="p-0"><input type="number" step="5" min="0" class={INPUT} value={s.inputs.btrUtilitiesPsqm ?? 30}
				oninput={(e) => setBtrNumber('btrUtilitiesPsqm', e.currentTarget.value)} /></td>
			<td class={UNIT}>AED/sqm/yr</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">f</td>
			<td class={LABEL}>Marketing & Leasing</td>
			<td class="p-0"><input type="number" step="0.5" min="0" class={INPUT} value={s.inputs.btrMarketingLeasingPct ?? 2}
				oninput={(e) => setBtrNumber('btrMarketingLeasingPct', e.currentTarget.value)} /></td>
			<td class={UNIT}>% of EGR</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">g</td>
			<td class={LABEL}>CapEx Reserve</td>
			<td class="p-0"><input type="number" step="0.5" min="0" class={INPUT} value={s.inputs.btrCapexReservePct ?? 5}
				oninput={(e) => setBtrNumber('btrCapexReservePct', e.currentTarget.value)} /></td>
			<td class={UNIT}>% of NOI</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">h</td>
			<td class={LABEL}>Payroll &amp; Staffing</td>
			<td class="p-0"><input type="number" step="5" min="0" class={INPUT} value={s.inputs.btrPayrollPsqm ?? 40}
				oninput={(e) => setBtrNumber('btrPayrollPsqm', e.currentTarget.value)} /></td>
			<td class={UNIT}>AED/sqm/yr</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">i</td>
			<td class={LABEL}>General &amp; Administrative</td>
			<td class="p-0"><input type="number" step="0.25" min="0" class={INPUT} value={s.inputs.btrGeneralAdminPct ?? 1}
				oninput={(e) => setBtrNumber('btrGeneralAdminPct', e.currentTarget.value)} /></td>
			<td class={UNIT}>% of EGR</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">j</td>
			<td class={LABEL}>Contract Services</td>
			<td class="p-0"><input type="number" step="5" min="0" class={INPUT} value={s.inputs.btrContractServicesPsqm ?? 25}
				oninput={(e) => setBtrNumber('btrContractServicesPsqm', e.currentTarget.value)} /></td>
			<td class={UNIT}>AED/sqm/yr</td>
		</tr>

		<!-- 2c. Exit & Valuation -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">2d. &nbsp; Exit &amp; Valuation</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Exit Cap Rate</td>
			<td class="p-0"><input type="number" step="0.25" min="0" class={INPUT} value={s.inputs.btrExitCapRatePct ?? 5.5}
				oninput={(e) => setBtrNumber('btrExitCapRatePct', e.currentTarget.value)} /></td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Exit Transaction Costs</td>
			<td class="p-0"><input type="number" step="0.5" min="0" class={INPUT} value={s.inputs.btrExitCostPct ?? 6}
				oninput={(e) => setBtrNumber('btrExitCostPct', e.currentTarget.value)} /></td>
			<td class={UNIT}>% (DLD+broker+legal)</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>Refi Valuation Cap Rate</td>
			<td class="p-0"><input type="number" step="0.25" min="0" class={INPUT} value={s.inputs.btrRefiCapRatePct ?? 5.5}
				oninput={(e) => setBtrNumber('btrRefiCapRatePct', e.currentTarget.value)} /></td>
			<td class={UNIT}>%</td>
		</tr>

		<!-- 2d. Permanent Debt -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">2e. &nbsp; Permanent Debt (Refi at Stabilization)</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Perm Debt LTV</td>
			<td class="p-0"><input type="number" step="1" min="0" max="90" class={INPUT} value={s.inputs.btrPermDebtLtvPct ?? 65}
				oninput={(e) => setBtrNumber('btrPermDebtLtvPct', e.currentTarget.value)} /></td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Perm Debt Spread <span class="text-slate-400 font-normal italic">(over EIBOR)</span></td>
			<td class="p-0"><input type="number" step="25" min="0" class={INPUT} value={s.inputs.btrPermDebtSpreadBps ?? 165}
				oninput={(e) => setBtrNumber('btrPermDebtSpreadBps', e.currentTarget.value)} /></td>
			<td class={UNIT}>bps</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>All-In Rate <span class="text-slate-400 font-normal italic">(derived)</span></td>
			<td class={VALUE_BLACK}>{fmt((s.inputs.eiborRatePct ?? 0) + ((s.inputs.btrPermDebtSpreadBps ?? 165) / 100), 2)}</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
			<td class={LABEL}>Amortization Period</td>
			<td class="p-0"><input type="number" step="1" min="5" class={INPUT} value={s.inputs.btrPermDebtAmortYears ?? 25}
				oninput={(e) => setBtrNumber('btrPermDebtAmortYears', e.currentTarget.value)} /></td>
			<td class={UNIT}>years</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">e</td>
			<td class={LABEL}>I/O Period</td>
			<td class="p-0"><input type="number" step="1" min="0" class={INPUT} value={s.inputs.btrPermDebtIoYears ?? 1}
				oninput={(e) => setBtrNumber('btrPermDebtIoYears', e.currentTarget.value)} /></td>
			<td class={UNIT}>years</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">f</td>
			<td class={LABEL}>Perm Debt Points/Fees</td>
			<td class="p-0"><input type="number" step="0.25" min="0" class={INPUT} value={s.inputs.btrPermDebtPointsPct ?? 1}
				oninput={(e) => setBtrNumber('btrPermDebtPointsPct', e.currentTarget.value)} /></td>
			<td class={UNIT}>% of perm loan</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">g</td>
			<td class={LABEL}>Minimum DSCR</td>
			<td class="p-0"><input type="number" step="0.05" min="1" class={INPUT} value={s.inputs.btrDscrMinimum ?? 1.25}
				oninput={(e) => setBtrNumber('btrDscrMinimum', e.currentTarget.value)} /></td>
			<td class={UNIT}>x</td>
		</tr>

		<!-- 2e. Additional Operating -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">2f. &nbsp; Additional Operating Assumptions</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Stabilized Free Rent (Renewals)</td>
			<td class="p-0"><input type="number" step="1" min="0" class={INPUT} value={s.inputs.btrStabilizedFreeRentMonths ?? 0}
				oninput={(e) => setBtrNumber('btrStabilizedFreeRentMonths', e.currentTarget.value)} /></td>
			<td class={UNIT}>months</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Model / Show Units</td>
			<td class="p-0"><input type="number" step="1" min="0" class={INPUT} value={s.inputs.btrModelUnits ?? 1}
				oninput={(e) => setBtrNumber('btrModelUnits', e.currentTarget.value)} /></td>
			<td class={UNIT}>units</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>Lease-Up Marketing Budget</td>
			<td class="p-0"><input type="number" step="10000" min="0" class={INPUT} value={s.inputs.btrLeaseUpMarketingAed ?? 0}
				oninput={(e) => setBtrNumber('btrLeaseUpMarketingAed', e.currentTarget.value)} /></td>
			<td class={UNIT}>AED</td>
		</tr>

		{:else}
		<!-- ═══════════════════════════════════════════════════════════
		     SECTION 2 (BTS) — REVENUE ASSUMPTIONS
		     ═══════════════════════════════════════════════════════════ -->
		<tr class="bg-[#1F3864]">
			<td colspan="4" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">2. &nbsp; REVENUE ASSUMPTIONS</td>
		</tr>

		<!-- 2a. Sales Timeline -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">2a. &nbsp; Sales Timeline</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>
				Sales Commencement
			</td>
			<td class="p-0 relative cursor-pointer">
				<div class="flex items-center justify-end px-2 py-[3px] pointer-events-none">
					<span class="text-[#1565C0] tabular-nums">{dateToQuarter(s.inputs.salesCommencementDate)}</span>
					<span class="ml-1 text-[9px] text-slate-400 border border-slate-200 rounded px-1">▾</span>
				</div>
				<input
					type="date"
					class="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
					value={s.inputs.salesCommencementDate}
					oninput={(e) => s.updateInputs({ salesCommencementDate: e.currentTarget.value })}
				/>
			</td>
			<td class={UNIT}>Q &amp; Year</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>
				Sales Period
			</td>
			<td
				class={`p-0 ${highlightClass('salesPeriodMonths')}`}
				data-feasibility-field="salesPeriodMonths"
			>
				<input
					type="number"
					step="1"
					class={INPUT}
					value={s.inputs.salesPeriodMonths}
					oninput={(e) => setNumber('salesPeriodMonths', e.currentTarget.value)}
				/>
			</td>
			<td class={UNIT}>months</td>
		</tr>

		<!-- 2b. Sales Prices -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">2b. &nbsp; Sales Prices</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Average GSA per Unit <span class="text-slate-400 font-normal italic">(derived)</span></td>
			<td class={VALUE_BLACK}>{s.totalUnits > 0 ? fmt(avgGsaPerUnit, 0) : '—'}</td>
			<td class={UNIT}>sq ft</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Average Sales Price per Unit</td>
			<td class={VALUE_BLACK}>{s.totalUnits > 0 ? fmtAed(avgSalesPricePerUnit) : '—'}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_INDENT}>
			<td class="px-1 py-[3px]"></td>
			<td class={LABEL_INDENT}>
				↳ Weighted Avg Rate (model)
			</td>
			<td class={VALUE_BLACK}>{s.totalConfiguredAreaSqm > 0 ? fmt(s.totalConfiguredRevenue / s.totalConfiguredAreaSqm, 0) : '—'}</td>
			<td class={UNIT}>AED/sqm</td>
		</tr>
		<tr class={ROW_INDENT}>
			<td class="px-1 py-[3px]"></td>
			<td class={LABEL_INDENT}>
				↳ Modelled saleable area
			</td>
			<td class={VALUE_BLACK}>{fmt(s.totalConfiguredAreaSqm, 0)}</td>
			<td class={UNIT}>sqm</td>
		</tr>
		<tr class={ROW_TOTAL}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class="px-2 py-[3px] text-slate-900 font-semibold">Total Gross Proceeds</td>
			<td class={VALUE_BOLD_BLACK}>{fmtAed(s.totalConfiguredRevenue)}</td>
			<td class={UNIT}>AED</td>
		</tr>

		<!-- 2c. Payment Plan -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">2c. &nbsp; Residential Payment Plan</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>
				Deposit
			</td>
			<td
				class={`p-0 ${highlightClass('paymentPlan:depositPct', 'paymentPlan')}`}
				data-feasibility-field={fieldTokens('paymentPlan:depositPct', 'paymentPlan')}
			>
				<input
					type="number"
					step="1"
					class={INPUT}
					value={s.paymentPlan.depositPct}
					oninput={(e) => s.updatePaymentPlan({ depositPct: Number(e.currentTarget.value) || 0 })}
				/>
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>
				Pre-Handover
			</td>
			<td
				class={`p-0 ${highlightClass('paymentPlan:constructionPct', 'paymentPlan')}`}
				data-feasibility-field={fieldTokens('paymentPlan:constructionPct', 'paymentPlan')}
			>
				<input
					type="number"
					step="1"
					class={INPUT}
					value={s.paymentPlan.constructionPct}
					oninput={(e) => s.updatePaymentPlan({ constructionPct: Number(e.currentTarget.value) || 0 })}
				/>
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>
				At Handover
			</td>
			<td
				class={`p-0 ${highlightClass('paymentPlan:handoverPct', 'paymentPlan')}`}
				data-feasibility-field={fieldTokens('paymentPlan:handoverPct', 'paymentPlan')}
			>
				<input
					type="number"
					step="1"
					class={INPUT}
					value={s.paymentPlan.handoverPct}
					oninput={(e) => s.updatePaymentPlan({ handoverPct: Number(e.currentTarget.value) || 0 })}
				/>
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_TOTAL}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center"></td>
			<td class="px-2 py-[3px] text-slate-700 font-semibold">Total</td>
			<td class={paymentPlanTotal === 100 ? `${VALUE_BOLD_BLACK}` : 'px-2 py-[3px] text-right tabular-nums text-rose-700 font-semibold'}>
				{fmt(paymentPlanTotal, 0)}
			</td>
			<td class={UNIT}>%</td>
		</tr>

		<!-- 2d. S-Curve Configuration -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">2d. &nbsp; S-Curve Configuration</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Construction Curve Steepness</td>
			<td class="p-0">
				<input type="number" step="1" min="1" class={INPUT}
					value={s.inputs.constructionCurveSteepness ?? 8}
					oninput={(e) => setNumber('constructionCurveSteepness', e.currentTarget.value)}
				/>
			</td>
			<td class={UNIT}></td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Sales Curve Steepness</td>
			<td class="p-0">
				<input type="number" step="1" min="1" class={INPUT}
					value={s.inputs.salesCurveSteepness ?? 8}
					oninput={(e) => setNumber('salesCurveSteepness', e.currentTarget.value)}
				/>
			</td>
			<td class={UNIT}></td>
		</tr>

		{/if}

		<!-- ═══════════════════════════════════════════════════════════
		     SECTION 3 — DEVELOPMENT ASSUMPTIONS
		     ═══════════════════════════════════════════════════════════ -->
		<tr class="bg-[#1F3864]">
			<td colspan="4" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">3. &nbsp; DEVELOPMENT ASSUMPTIONS</td>
		</tr>

		<!-- 3a. Timelines -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">3a. &nbsp; Timelines</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Land Acquisition</td>
			<td class="p-0 relative cursor-pointer">
				<div class="flex items-center justify-end px-2 py-[3px] pointer-events-none">
					<span class="text-[#1565C0] tabular-nums">{dateToQuarter(s.inputs.landAcquisitionDate)}</span>
					<span class="ml-1 text-[9px] text-slate-400 border border-slate-200 rounded px-1">▾</span>
				</div>
				<input
					type="date"
					class="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
					value={s.inputs.landAcquisitionDate}
					oninput={(e) => s.updateInputs({ landAcquisitionDate: e.currentTarget.value })}
				/>
			</td>
			<td class={UNIT}>Q &amp; Year</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Demolition / Enabling Works</td>
			<td class="p-0 relative cursor-pointer">
				<div class="flex items-center justify-end px-2 py-[3px] pointer-events-none">
					<span class="text-[#1565C0] tabular-nums">{dateToQuarter(s.inputs.demolitionEnablingDate)}</span>
					<span class="ml-1 text-[9px] text-slate-400 border border-slate-200 rounded px-1">▾</span>
				</div>
				<input
					type="date"
					class="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
					value={s.inputs.demolitionEnablingDate}
					oninput={(e) => s.updateInputs({ demolitionEnablingDate: e.currentTarget.value })}
				/>
			</td>
			<td class={UNIT}>Q &amp; Year</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>
				Construction Start
			</td>
			<td class="p-0 relative cursor-pointer">
				<div class="flex items-center justify-end px-2 py-[3px] pointer-events-none">
					<span class="text-[#1565C0] tabular-nums">{dateToQuarter(s.inputs.constructionDate)}</span>
					<span class="ml-1 text-[9px] text-slate-400 border border-slate-200 rounded px-1">▾</span>
				</div>
				<input
					type="date"
					class="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
					value={s.inputs.constructionDate}
					oninput={(e) => s.updateInputs({ constructionDate: e.currentTarget.value })}
				/>
			</td>
			<td class={UNIT}>Q &amp; Year</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
			<td class={LABEL}>
				Handover
			</td>
			<td class="p-0 relative cursor-pointer">
				<div class="flex items-center justify-end px-2 py-[3px] pointer-events-none">
					<span class="text-[#1565C0] tabular-nums">{dateToQuarter(s.inputs.handoverDate)}</span>
					<span class="ml-1 text-[9px] text-slate-400 border border-slate-200 rounded px-1">▾</span>
				</div>
				<input
					type="date"
					class="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
					value={s.inputs.handoverDate}
					oninput={(e) => s.updateInputs({ handoverDate: e.currentTarget.value })}
				/>
			</td>
			<td class={UNIT}>Q &amp; Year</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">—</td>
			<td class={LABEL}>
				Construction Duration <span class="text-slate-400 font-normal italic">(derived)</span>
			</td>
			<td class={VALUE_BLACK}>{constructionDurationMonths ?? '—'}</td>
			<td class={UNIT}>months</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">e</td>
			<td class={LABEL}>Pre-Handover Milestone</td>
			<td class="p-0 relative cursor-pointer">
				<div class="flex items-center justify-end px-2 py-[3px] pointer-events-none">
					<span class="text-[#1565C0] tabular-nums">{dateToQuarter(s.inputs.preHandoverMilestoneDate)}</span>
					<span class="ml-1 text-[9px] text-slate-400 border border-slate-200 rounded px-1">▾</span>
				</div>
				<input
					type="date"
					class="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
					value={s.inputs.preHandoverMilestoneDate}
					oninput={(e) => s.updateInputs({ preHandoverMilestoneDate: e.currentTarget.value })}
				/>
			</td>
			<td class={UNIT}>Q &amp; Year</td>
		</tr>

		<!-- 3b. Land Costs -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">3b. &nbsp; Land Costs</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Land Acquisition Cost</td>
			<td class={VALUE_GREEN}>{fmtAed(s.plotAcquisitionCost)}</td>
			<td class="px-2 py-[3px] text-slate-400 text-[10px] whitespace-nowrap">↗ Budget</td>
		</tr>
		<tr class={ROW_INDENT}>
			<td class="px-1 py-[3px]"></td>
			<td class={LABEL_INDENT}>↳ Implied rate</td>
			<td class={VALUE_BLACK}>{s.maxGfaSqm > 0 ? fmtAed(s.plotAcquisitionCost / toSqft(s.maxGfaSqm)) : '—'}</td>
			<td class="px-2 py-[3px] text-slate-400 text-[10px] whitespace-nowrap">AED / sqft GFA</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Land Transfer Fee <span class="text-slate-400 font-normal italic">(4% of Acquisition)</span></td>
			<td class={VALUE_BLACK}>{fmtAed(s.landTransferFeeAed)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>Brokerage Fee</td>
			<td class={VALUE_GREEN}>{fmtAed(s.inputs.brokerageFeeAed)}</td>
			<td class="px-2 py-[3px] text-slate-400 text-[10px] whitespace-nowrap">↗ Budget</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
			<td class={LABEL}>Legal / DD Cost</td>
			<td class={VALUE_GREEN}>{fmtAed(s.inputs.legalDdCostAed)}</td>
			<td class="px-2 py-[3px] text-slate-400 text-[10px] whitespace-nowrap">↗ Budget</td>
		</tr>
		<tr class={ROW_TOTAL}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center"></td>
			<td class="px-2 py-[3px] text-slate-900 font-semibold">Total Land Cost</td>
			<td class={VALUE_BOLD_BLACK}>{fmtAed(s.totalLandCostAed)}</td>
			<td class={UNIT}>AED</td>
		</tr>

		<!-- 3c. Development Costs -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">3c. &nbsp; Development Costs</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>
				Design &amp; Supervision
			</td>
			<td class={VALUE_GREEN}>{fmtAed(s.designSupervisionCost)}</td>
			<td class="px-2 py-[3px] text-slate-400 text-[10px] whitespace-nowrap">↗ Budget</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Demolition</td>
			<td class={VALUE_GREEN}>{fmtAed(s.inputs.demolitionCostAed)}</td>
			<td class="px-2 py-[3px] text-slate-400 text-[10px] whitespace-nowrap">↗ Budget</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>
				Construction <span class="text-slate-400 font-normal italic">(Cost Rate × BUA)</span>
			</td>
			<td class={VALUE_GREEN}>{fmtAed(s.constructionCostInclInflation)}</td>
			<td class="px-2 py-[3px] text-slate-400 text-[10px] whitespace-nowrap">↗ Budget</td>
		</tr>
		<tr class={ROW_INDENT}>
			<td class="px-1 py-[3px]"></td>
			<td class={LABEL_INDENT}>↳ Construction Cost Rate</td>
			<td class={VALUE_GREEN}>{Math.round(s.inputs.constructionCostPsqmBua * 0.092903)}</td>
			<td class="px-2 py-[3px] text-slate-400 text-[10px] whitespace-nowrap">↗ Budget</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
			<td class={LABEL}>Infrastructure, Utilities &amp; Landscaping</td>
			<td class={VALUE_GREEN}>{fmtAed(s.inputs.infrastructureCostAed)}</td>
			<td class="px-2 py-[3px] text-slate-400 text-[10px] whitespace-nowrap">↗ Budget</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">e</td>
			<td class={LABEL}>Authority &amp; Connection Fees</td>
			<td class={VALUE_GREEN}>{fmtAed(s.inputs.governmentFeesAed)}</td>
			<td class="px-2 py-[3px] text-slate-400 text-[10px] whitespace-nowrap">↗ Budget</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">f</td>
			<td class={LABEL}>
				Marketing
			</td>
			<td class={VALUE_BLACK}>{fmtAed(s.marketingCost)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">g</td>
			<td class={LABEL}>
				Sales Agent Fees
			</td>
			<td class={VALUE_BLACK}>{fmtAed(s.salesAgentFees)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">h</td>
			<td class={LABEL}>Master Community Fees</td>
			<td class={VALUE_GREEN}>{fmtAed(s.inputs.masterCommunityFeesAed)}</td>
			<td class="px-2 py-[3px] text-slate-400 text-[10px] whitespace-nowrap">↗ Budget</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">i</td>
			<td class={LABEL}>
				Contingency
			</td>
			<td class={VALUE_BLACK}>{fmtAed(s.contingencyCost)}</td>
			<td class={UNIT}>AED</td>
		</tr>

		<!-- Sub-total development costs -->
		<tr class={ROW_TOTAL}>
			<td class="px-1 py-[3px]"></td>
			<td class="px-2 py-[3px] text-slate-700 font-semibold">Sub-Total Development Costs</td>
			<td class={VALUE_BOLD_BLACK}>{fmtAed(devCostSubtotal)}</td>
			<td class={UNIT}>AED</td>
		</tr>

		<!-- Spacer row -->
		<tr class="border-b border-[#D9D9D9] bg-[#F5F5F5]">
			<td colspan="4" class="py-[2px]"></td>
		</tr>

		<!-- Total excl VAT -->
		<tr class="border-t-2 border-[#1F3864] border-b border-[#D9D9D9]">
			<td class="px-1 py-[4px]"></td>
			<td class="px-2 py-[4px] text-slate-900 font-bold">TOTAL COST (excl. VAT)</td>
			<td class="px-2 py-[4px] text-right tabular-nums text-slate-900 font-bold">{fmtAed(s.totalCostsExclVat)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px]"></td>
			<td class={LABEL}>
				VAT
			</td>
			<td class={VALUE_BLACK}>{fmtAed(s.vatAmount)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<!-- Grand total -->
		<tr class="border-t-2 border-[#1F3864] border-b border-[#D9D9D9] bg-[#E8F0FE]">
			<td class="px-1 py-[4px]"></td>
			<td class="px-2 py-[4px] text-slate-900 font-bold">TOTAL COST (incl. VAT)</td>
			<td class="px-2 py-[4px] text-right tabular-nums text-slate-900 font-bold">{fmtAed(s.modelTotalCostsInclVat)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px]"></td>
			<td class={LABEL}>BUA Rate — All-in (incl. VAT)</td>
			<td class={VALUE_BLACK}>{fmt(s.buaRateAllIn, 0)}</td>
			<td class={UNIT}>AED / sqft</td>
		</tr>

		<!-- ═══════════════════════════════════════════════════════════
		     SECTION 4 — FUNDING & RETURNS
		     ═══════════════════════════════════════════════════════════ -->
		<tr class="bg-[#1F3864]">
			<td colspan="4" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">4. &nbsp; FUNDING &amp; RETURNS</td>
		</tr>

		<!-- 4a. Sources of Funds -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">4a. &nbsp; Sources of Funds</td>
		</tr>
		{#if isBtr && s.workbook?.btr?.sourcesUses}
		{@const btrSU = s.workbook.btr.sourcesUses}
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Acquisition debt <span class="text-slate-400 font-normal italic">(peak LTV-based land tranche)</span></td>
			<td class={VALUE_BLACK}>{fmtAed(btrSU.peakAcqDebtAed)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Construction debt <span class="text-slate-400 font-normal italic">(peak LTC-based construction tranche)</span></td>
			<td class={VALUE_BLACK}>{fmtAed(btrSU.peakConDebtAed)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>Sponsor equity <span class="text-slate-400 font-normal italic">(actual monthly equity contributions)</span></td>
			<td class={VALUE_BLACK}>{fmtAed(btrSU.actualEquityAed)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
			<td class={LABEL}>VAT refunds <span class="text-slate-400 font-normal italic">(input VAT recovered during dev tail)</span></td>
			<td class={VALUE_BLACK}>{fmtAed(btrSU.vatRefundsAed)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_TOTAL}>
			<td class="px-1 py-[3px]"></td>
			<td class="px-2 py-[3px] text-slate-900 font-semibold">Total Sources</td>
			<td class={VALUE_BOLD_BLACK}>{fmtAed(btrSU.totalSourcesAed)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px]"></td>
			<td class="px-2 py-[3px] text-slate-700">Total Uses <span class="text-slate-400 font-normal italic">(dev cost + VAT + financing)</span></td>
			<td class={VALUE_BLACK}>{fmtAed(btrSU.totalUsesAed)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		{:else}
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Off-Plan Proceeds <span class="text-slate-400 font-normal italic">(Deposit + Pre-Handover)</span></td>
			<td class={VALUE_BLACK}>{fmtAed(s.offPlanSalesProceeds)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Debt <span class="text-slate-400 font-normal italic">{s.hasDraftCase ? "(Derived from model)" : "(Est. — build model to confirm)"}</span></td>
			<td class={VALUE_BLACK}>{fmtAed(s.fundingDebt)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>Equity <span class="text-slate-400 font-normal italic">{s.hasDraftCase ? "(Derived from model)" : "(Est. — build model to confirm)"}</span></td>
			<td class={VALUE_BLACK}>{fmtAed(s.fundingEquity)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
			<td class={LABEL}>VAT Refunds <span class="text-slate-400 font-normal italic">(5% of Construction Cost)</span></td>
			<td class={VALUE_BLACK}>{fmtAed(s.vatRefunds)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_TOTAL}>
			<td class="px-1 py-[3px]"></td>
			<td class="px-2 py-[3px] text-slate-900 font-semibold">Total Sources</td>
			<td class={VALUE_BOLD_BLACK}>{fmtAed(s.sourcesOfFundsTotal)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px]"></td>
			<td class="px-2 py-[3px] text-slate-700">Total Uses <span class="text-slate-400 font-normal italic">(= Total Cost incl. VAT)</span></td>
			<td class={VALUE_BLACK}>{fmtAed(s.usesOfFundingTotal)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		{/if}

		<!-- 4b. Debt Eligibility — aligned with engine tranche logic -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">4b. &nbsp; Debt-Eligible Cost Allocation</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Acquisition tranche <span class="text-slate-400 font-normal italic">(land + fees × LTV)</span></td>
			<td class={VALUE_GREEN}>{fmtAed(s.fundingLandLoan)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Construction tranche <span class="text-slate-400 font-normal italic">(hard + soft + contingency + permit × LTC)</span></td>
			<td class={VALUE_GREEN}>{fmtAed(s.fundingConstructionLoan)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_INDENT}>
			<td class="px-1 py-[3px]"></td>
			<td class={LABEL_INDENT}>of which: hard cost</td>
			<td class={VALUE_BLACK}>{fmtAed(s.debtConstruction)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_INDENT}>
			<td class="px-1 py-[3px]"></td>
			<td class={LABEL_INDENT}>of which: soft cost / design</td>
			<td class={VALUE_BLACK}>{fmtAed(s.debtDesignSupervision)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>Equity-only costs <span class="text-slate-400 font-normal italic">(marketing, sales, VAT, infra, govt)</span></td>
			<td class={VALUE_BLACK}>{fmtAed(s.equityOtherCosts)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">4b-i. &nbsp; Debt Structure</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Acquisition LTV</td>
			<td class="p-0">
				<input type="number" step="1" min="0" max="100" class={INPUT}
					value={Math.round((s.inputs.acquisitionDebtLtv ?? 0.70) * 100)}
					oninput={(e) => s.updateInputs({ acquisitionDebtLtv: (Number(e.currentTarget.value) || 0) / 100 })}
				/>
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Construction LTC</td>
			<td class="p-0">
				<input type="number" step="1" min="0" max="100" class={INPUT}
					value={Math.round((s.inputs.constructionDebtLtc ?? 0.70) * 100)}
					oninput={(e) => s.updateInputs({ constructionDebtLtc: (Number(e.currentTarget.value) || 0) / 100 })}
				/>
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>Acquisition Spread <span class="text-slate-400 font-normal italic">(over EIBOR)</span></td>
			<td class="p-0">
				<input type="number" step="25" min="0" max="1000" class={INPUT}
					value={s.inputs.landLoanSpreadBps || Math.round((s.inputs.debtSpreadPa ?? 0.02) * 10000)}
					oninput={(e) => s.updateInputs({ landLoanSpreadBps: Number(e.currentTarget.value) || 0 })}
				/>
			</td>
			<td class={UNIT}>bps</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
			<td class={LABEL}>Construction Spread <span class="text-slate-400 font-normal italic">(over EIBOR)</span></td>
			<td class="p-0">
				<input type="number" step="25" min="0" max="1000" class={INPUT}
					value={s.inputs.constructionLoanSpreadBps || Math.round((s.inputs.debtSpreadPa ?? 0.02) * 10000)}
					oninput={(e) => s.updateInputs({ constructionLoanSpreadBps: Number(e.currentTarget.value) || 0 })}
				/>
			</td>
			<td class={UNIT}>bps</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">e</td>
			<td class={LABEL}>Financing Fee</td>
			<td class="p-0">
				<input type="number" step="0.01" min="0" max="100" class={INPUT}
					value={Math.round((s.inputs.financingFeePct ?? 0.01) * 10000) / 100}
					oninput={(e) => s.updateInputs({ financingFeePct: (Number(e.currentTarget.value) || 0) / 100 })}
				/>
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">f</td>
			<td class={LABEL}>Exit Fee</td>
			<td class="p-0">
				<input type="number" step="0.01" min="0" max="100" class={INPUT}
					value={Math.round((s.inputs.exitFeePct ?? 0.01) * 10000) / 100}
					oninput={(e) => s.updateInputs({ exitFeePct: (Number(e.currentTarget.value) || 0) / 100 })}
				/>
			</td>
			<td class={UNIT}>%</td>
		</tr>

		<!-- 4b-ii. Derived Debt Allocation -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">4b-ii. &nbsp; Debt Allocation <span class="text-slate-400 font-normal normal-case italic">(Derived)</span></td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>All-in Rate (Land)</td>
			<td class={VALUE_GREEN}>{fmt(s.landLoanRatePct, 2)}%</td>
			<td class="px-2 py-[3px] text-slate-400 text-[10px] whitespace-nowrap">↗ EIBOR + spread</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>All-in Rate (Construction)</td>
			<td class={VALUE_GREEN}>{fmt(s.constructionLoanRatePct, 2)}%</td>
			<td class="px-2 py-[3px] text-slate-400 text-[10px] whitespace-nowrap">↗ EIBOR + spread</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>Land Loan Capacity</td>
			<td class={VALUE_BLACK}>{fmtAed(s.landLoanCapacity)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
			<td class={LABEL}>Construction Loan Capacity</td>
			<td class={VALUE_BLACK}>{fmtAed(s.constructionLoanCapacity)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_TOTAL}>
			<td class="px-1 py-[3px]"></td>
			<td class="px-2 py-[3px] text-slate-900 font-semibold">Total Debt</td>
			<td class={VALUE_BOLD_BLACK}>{fmtAed(s.fundingDebt)}</td>
			<td class={UNIT}>AED</td>
		</tr>

			<!-- 4b-iv. Facility Controls -->
			<tr class="bg-[#D6DCE4]">
				<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">4b-iv. &nbsp; Facility Controls</td>
			</tr>
			{#if !isBtr}
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
				<td class={LABEL}>Escrow Retention <span class="text-slate-400 font-normal italic">(BTS off-plan only)</span></td>
				<td class="p-0 border-r border-[#E8E8E8]">
					<input type="number" step="0.5" min="0" max="100" class={INPUT}
						value={s.inputs.escrowRetentionPct}
						oninput={(e) => setNumber('escrowRetentionPct', e.currentTarget.value)}
					/>
				</td>
				<td class={UNIT}>%</td>
			</tr>
			{/if}
			<tr class={ROW_STD}>
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">{isBtr ? 'a' : 'b'}</td>
				<td colspan="3" class="px-2 py-[4px] text-[10px] text-slate-500 italic">
					{#if isBtr}
					Live BTR controls: acquisition LTV, construction LTC, debt spread, financing fee, exit fee, perm debt LTV/rate, exit cap rate. Escrow is not applicable — BTR has no off-plan sales (RERA escrow only applies to BTS).
					{:else}
					Live workbook controls are acquisition LTV, construction LTC, debt spread, financing fee, exit fee, and escrow retention. Legacy presale-threshold, debt-to-cost, commitment, arrangement, and sales-sweep toggles stay hidden until they are wired back into the active model.
					{/if}
				</td>
			</tr>

		<!-- 4c. Equity Waterfall (BTS only) -->
		{#if !isBtr}
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">4c. &nbsp; Equity Waterfall</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Preferred Return p.a.</td>
			<td class="p-0">
				<input type="number" step="0.5" min="0" max="100" class={INPUT}
					value={Math.round((s.inputs.preferredReturnPa ?? 0.08) * 200) / 2}
					oninput={(e) => s.updateInputs({ preferredReturnPa: (Number(e.currentTarget.value) || 0) / 100 })}
				/>
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Sponsor Promote %</td>
			<td class="p-0">
				<input type="number" step="1" min="0" max="100" class={INPUT}
					value={Math.round((s.inputs.sponsorPromotePct ?? 0.20) * 100)}
					oninput={(e) => s.updateInputs({ sponsorPromotePct: (Number(e.currentTarget.value) || 0) / 100 })}
				/>
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>Project Years</td>
			<td class="p-0">
				<input type="number" step="1" min="1" class={INPUT}
					value={s.inputs.projectYears ?? 5}
					oninput={(e) => setNumber('projectYears', e.currentTarget.value)}
				/>
			</td>
			<td class={UNIT}>years</td>
		</tr>
		{/if}

		<!-- 4d. Equity Use -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">4d. &nbsp; Equity Use</td>
		</tr>
		{#if isBtr && s.workbook?.btr?.returns}
		{@const btrR = s.workbook.btr.returns}
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Dev equity contributed <span class="text-slate-400 font-normal italic">(actual monthly equity drawn)</span></td>
			<td class={VALUE_BLACK}>{fmtAed(btrR.devEquityFundedAed)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Peak equity deployed <span class="text-slate-400 font-normal italic">(before refi proceeds)</span></td>
			<td class={VALUE_BLACK}>{fmtAed(btrR.peakEquityAed)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_TOTAL}>
			<td class="px-1 py-[3px]"></td>
			<td class="px-2 py-[3px] text-slate-900 font-semibold">Total Equity Invested</td>
			<td class={VALUE_BOLD_BLACK}>{fmtAed(btrR.totalEquityInvestedAed)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		{:else}
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Land Costs <span class="text-slate-400 font-normal italic">(Acquisition + Transfer + Other)</span></td>
			<td class={VALUE_BLACK}>{fmtAed(s.equityLand)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Construction &amp; Development Costs <span class="text-slate-400 font-normal italic">(equity-funded portion)</span></td>
			<td class={VALUE_BLACK}>{fmtAed(s.equityConstruction + s.equityOtherCosts)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_TOTAL}>
			<td class="px-1 py-[3px]"></td>
			<td class="px-2 py-[3px] text-slate-900 font-semibold">Total Equity</td>
			<td class={VALUE_BOLD_BLACK}>{fmtAed(s.fundingEquity)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		{/if}

		<!-- 4e. Returns -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">4e. &nbsp; Returns</td>
		</tr>
		{#if isBtr && s.workbook?.btr?.returns}
		{@const btrRet = s.workbook.btr.returns}
		<tr class="border-b border-[#EBEBEB] bg-[#FFFDE7]">
			<td colspan="4" class="px-3 py-[4px] text-[9px] text-slate-500 italic">
				BTR returns: <strong class="text-slate-600">Yield on Cost</strong> = stabilized NOI ÷ total dev cost. <strong class="text-slate-600">IRR</strong> spans dev phase (equity out) through ops + exit (equity in). Unlevered excludes debt carry; Levered net of perm debt service and refi proceeds.
			</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Stabilized NOI</td>
			<td class={VALUE_BLACK}>{fmtAed(btrRet.stabilizedNoiAed)}</td>
			<td class={UNIT}>AED/yr</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Yield on Cost <span class="text-slate-400 font-normal italic">(stabilized NOI ÷ total dev cost)</span></td>
			<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 font-semibold text-[12px]">
				{fmt(btrRet.stabilizedYieldOnCostPct, 2)}%
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>IRR — Unlevered <span class="text-slate-400 font-normal italic">(project, excl. debt)</span></td>
			<td class="px-2 py-[3px] text-right tabular-nums font-semibold text-[12px] {btrRet.unleveredIrrPct != null ? 'text-slate-900' : 'text-slate-400'}">
				{btrRet.unleveredIrrPct != null ? fmt(btrRet.unleveredIrrPct, 1) + '%' : '—'}
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
			<td class={LABEL}>IRR — Levered <span class="text-slate-400 font-normal italic">(equity, incl. perm debt service)</span></td>
			<td class="px-2 py-[3px] text-right tabular-nums font-semibold text-[12px] {btrRet.leveredIrrPct != null ? 'text-slate-900' : 'text-slate-400'}">
				{btrRet.leveredIrrPct != null ? fmt(btrRet.leveredIrrPct, 1) + '%' : '—'}
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class="border-b border-[#D9D9D9] pb-4">
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">e</td>
			<td class={LABEL}>Equity Multiple (MoIC) <span class="text-slate-400 font-normal italic">(levered)</span></td>
			<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 font-semibold text-[12px]">
				{fmt(btrRet.leveredMoic, 2)}x
			</td>
			<td class={UNIT}>x</td>
		</tr>
		{:else}
		<tr class="border-b border-[#EBEBEB] bg-[#FFFDE7]">
			<td colspan="4" class="px-3 py-[4px] text-[9px] text-slate-500 italic">
				<strong class="text-slate-600">Project IRR</strong> is unlevered — independent of interest rate (see Budget sheet for Equity IRR which responds to financing costs).
			</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>IRR — Project <span class="text-slate-400 font-normal italic">(unlevered)</span></td>
			<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 font-semibold text-[12px]">
				{s.projectIrrPct != null ? fmt(s.projectIrrPct, 1) + '%' : '—'}
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>IRR — Equity <span class="text-slate-400 font-normal italic">(levered, incl. interest)</span></td>
			<td class="px-2 py-[3px] text-right tabular-nums font-semibold text-[12px] {s.workbook?.returns?.equityIrrPct != null ? 'text-slate-900' : 'text-slate-400'}">
				{s.workbook?.returns?.equityIrrPct != null ? fmt(s.workbook.returns.equityIrrPct, 1) + '%' : s.workbook ? '—' : 'Run model'}
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class="border-b border-[#D9D9D9] pb-4">
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>MoIC</td>
			<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 font-semibold text-[12px]">
				{fmt(moic, 2)}x
			</td>
			<td class={UNIT}>x</td>
		</tr>
		{/if}

		<!-- bottom padding -->
		<tr>
			<td colspan="4" class="py-4"></td>
		</tr>

		</tbody>
	</table>
</div>

<style>
	:global(.feasibility-change-flash) {
		animation: feasibility-change-flash 2.4s ease-out;
	}

	@keyframes feasibility-change-flash {
		0%,
		100% {
			background-color: transparent;
			box-shadow: none;
		}
		12% {
			background-color: rgba(34, 197, 94, 0.18);
			box-shadow: inset 0 0 0 1px rgba(20, 184, 166, 0.35);
		}
		36% {
			background-color: rgba(56, 189, 248, 0.16);
			box-shadow: inset 0 0 0 1px rgba(14, 165, 233, 0.28);
		}
		68% {
			background-color: rgba(34, 197, 94, 0.1);
			box-shadow: inset 0 0 0 1px rgba(20, 184, 166, 0.18);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		:global(.feasibility-change-flash) {
			animation: none;
			background-color: rgba(34, 197, 94, 0.14);
			box-shadow: inset 0 0 0 1px rgba(20, 184, 166, 0.24);
		}
	}
</style>
