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
	if (isNaN(d.getTime())) return isoDate
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
const workbook = $derived(s.workbook ?? null)
const research = $derived(workbookStore.research)
const offPlanConfidence = $derived(research?.off_plan_pricing_confidence ?? null)
const offPlanBenchmarks = $derived(research?.off_plan_unit_benchmarks ?? [])
const validation = $derived(s.validation)

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
	if (isNaN(c.getTime()) || isNaN(h.getTime())) return null
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
</script>

<div class="overflow-auto flex-1 bg-white text-[11px] font-[Calibri,'Segoe_UI',Arial,sans-serif] select-none">

	<!-- Model Header -->
	<div class="bg-[#1F3864] text-white px-4 py-2.5 flex items-start justify-between gap-4">
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
		<div class="grid gap-3 xl:grid-cols-2">
			<div class="rounded-lg border border-slate-200 bg-white overflow-hidden">
				<div class="px-3 py-2 bg-slate-50 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
					Market Confidence
				</div>
				<div class="px-3 py-3 space-y-2 text-[11px]">
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
				<td class="p-0">
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

			<!-- 1b. CONFIGURATION -->
			<tr class="bg-[#D6DCE4]">
				<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">1b. &nbsp; Configuration</td>
			</tr>
		</tbody>
	</table>

	<!-- Configuration sub-table (different column count) -->
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
				{@const gsaSf = toSqft(cfg.avgSizeSqm)}
				{@const ppsf = cfg.sellingRatePsqm * 0.092903}
				{@const totalGsaSf = toSqft(cfg.units * cfg.avgSizeSqm)}
				{@const totalRev = cfg.units * cfg.avgSizeSqm * cfg.sellingRatePsqm}
				<tr class="border-b border-[#EBEBEB]">
					<td class="px-2 py-[3px] text-slate-800 border-r border-[#E8E8E8]">{cfg.label}</td>
					<td class="p-0 border-r border-[#E8E8E8]">
						<input
							type="number"
							step="1"
							class={INPUT}
							value={cfg.units}
							oninput={(e) => s.updateUnitConfig(cfg.id, { units: Number(e.currentTarget.value) || 0 })}
						/>
					</td>
					<td class="p-0 border-r border-[#E8E8E8]">
						<input
							type="number"
							step="1"
							class={INPUT}
							value={Math.round(gsaSf)}
							oninput={(e) => s.updateUnitConfig(cfg.id, { avgSizeSqm: (Number(e.currentTarget.value) || 0) * 0.092903 })}
						/>
					</td>
					<td class="p-0 border-r border-[#E8E8E8]">
						<input
							type="number"
							step="1"
							class={INPUT}
							value={Math.round(ppsf)}
							oninput={(e) => s.updateUnitConfig(cfg.id, { sellingRatePsqm: (Number(e.currentTarget.value) || 0) / 0.092903 })}
						/>
					</td>
					<td class="p-0 border-r border-[#E8E8E8]">
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
		<span class={gsaAsPctOfGfa > 100 ? 'text-red-600 font-semibold' : gsaAsPctOfGfa >= 75 ? 'text-emerald-700 font-semibold' : 'text-amber-700 font-semibold'}>
			{fmt(gsaAsPctOfGfa, 1)}% of GFA
		</span>
		&nbsp;<span class="text-slate-400">(target ≈ 80%)</span>
		&nbsp;·&nbsp;
		{#if gsaAsPctOfGfa > 100}
			<span class="text-red-600 font-semibold">⚠ GSA exceeds GFA — review unit mix</span>
		{:else if gsaAsPctOfGfa >= 75}
			<span class="text-emerald-700">✓ Within acceptable range</span>
		{:else}
			<span class="text-amber-700">↑ Consider increasing unit count or sizes</span>
		{/if}
	</div>

	<!-- Resume main table -->
	<table class="w-full border-collapse" style="border-spacing:0">
		<colgroup>
			<col style="width:2.5%">
			<col style="width:44%">
			<col style="width:28%">
			<col style="width:13%">
		</colgroup>
		<tbody>

		<!-- ═══════════════════════════════════════════════════════════
		     SECTION 2 — REVENUE ASSUMPTIONS
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
			<td class="p-0">
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
			<td class="p-0">
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
			<td class="p-0">
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
			<td class="p-0">
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
			<td class={paymentPlanTotal === 100 ? `${VALUE_BOLD_BLACK}` : 'px-2 py-[3px] text-right tabular-nums text-red-600 font-semibold'}>
				{fmt(paymentPlanTotal, 0)}
			</td>
			<td class={UNIT}>%</td>
		</tr>

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

		<!-- 4b. Debt Use -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">4b. &nbsp; Debt Use</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Construction Costs</td>
			<td class={VALUE_BLACK}>{fmtAed(s.debtConstruction)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Design &amp; Supervision</td>
			<td class={VALUE_BLACK}>{fmtAed(s.debtDesignSupervision)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>Marketing / Sales Agent Fees</td>
			<td class={VALUE_BLACK}>{fmtAed(s.debtMarketingSales)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
			<td class={LABEL}>VAT</td>
			<td class={VALUE_BLACK}>{fmtAed(s.debtVat)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">4b-i. &nbsp; Land Loan Parameters</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>
				Land Loan LTV
			</td>
			<td class="p-0 border-r border-[#E8E8E8]">
				<input type="number" step="1" min="0" max="100" class={INPUT}
					value={s.inputs.landLoanLtvPct}
					oninput={(e) => setNumber('landLoanLtvPct', e.currentTarget.value)}
				/>
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>
				Land Loan Rate
			</td>
			<td class={VALUE_GREEN}>{fmt(s.landLoanRatePct, 2)}%</td>
			<td class="px-2 py-[3px] text-slate-400 text-[10px] whitespace-nowrap">↗ EIBOR</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>
				Construction Loan Rate
			</td>
			<td class={VALUE_GREEN}>{fmt(s.constructionLoanRatePct, 2)}%</td>
			<td class="px-2 py-[3px] text-slate-400 text-[10px] whitespace-nowrap">↗ EIBOR</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
			<td class={LABEL}>Land Loan Capacity <span class="text-slate-400 font-normal italic">(Derived)</span></td>
			<td class={VALUE_BLACK}>{fmtAed(s.landLoanCapacity)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">e</td>
			<td class={LABEL + (constructionSqueezed ? ' text-amber-600' : '')}>
				Construction Loan Capacity <span class="font-normal italic">(Derived)</span>
				{#if constructionSqueezed}
					<span class="ml-1 text-amber-500 text-[10px]">Most debt capacity consumed by land tranche</span>
				{/if}
			</td>
			<td class={constructionSqueezed ? 'px-2 py-[3px] text-right tabular-nums text-amber-600 font-semibold' : VALUE_BLACK}>{fmtAed(s.constructionLoanCapacity)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_TOTAL}>
			<td class="px-1 py-[3px]"></td>
			<td class="px-2 py-[3px] text-slate-900 font-semibold">Total Debt</td>
			<td class={VALUE_BOLD_BLACK}>{fmtAed(s.fundingDebt)}</td>
			<td class={UNIT}>AED</td>
		</tr>

		<!-- 4b-ii. Debt Allocation -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">4b-ii. &nbsp; Debt Allocation <span class="text-slate-400 font-normal normal-case italic">(Derived from model)</span></td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>Allocated to Land Tranche</td>
			<td class={VALUE_BLACK}>{fmtAed(s.fundingLandLoan)}</td>
			<td class={UNIT}>AED</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>Allocated to Construction &amp; Soft Costs</td>
			<td class={VALUE_BLACK}>{fmtAed(s.fundingConstructionLoan)}</td>
			<td class={UNIT}>AED</td>
		</tr>

		<!-- 4b-iii. Debt Structure Controls -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">4b-iii. &nbsp; Debt Structure Controls</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
			<td class={LABEL}>
				Debt to Cost Ratio
			</td>
			<td class="p-0 border-r border-[#E8E8E8]">
				<input type="number" step="0.01" min="0" max="1" class={INPUT}
					value={s.inputs.debtToCostRatio}
					oninput={(e) => setNumber('debtToCostRatio', e.currentTarget.value)}
				/>
			</td>
			<td class={UNIT}>ratio</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
			<td class={LABEL}>
				Presale Threshold
			</td>
			<td class="p-0 border-r border-[#E8E8E8]">
				<input type="number" step="1" min="0" max="100" class={INPUT}
					value={s.inputs.presaleThresholdPct}
					oninput={(e) => setNumber('presaleThresholdPct', e.currentTarget.value)}
				/>
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
			<td class={LABEL}>
				Escrow Retention
			</td>
			<td class="p-0 border-r border-[#E8E8E8]">
				<input type="number" step="0.5" min="0" max="100" class={INPUT}
					value={s.inputs.escrowRetentionPct}
					oninput={(e) => setNumber('escrowRetentionPct', e.currentTarget.value)}
				/>
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
			<td class={LABEL}>
				Arrangement Fee
			</td>
			<td class="p-0 border-r border-[#E8E8E8]">
				<input type="number" step="0.1" min="0" max="10" class={INPUT}
					value={s.inputs.arrangementFeePct}
					oninput={(e) => setNumber('arrangementFeePct', e.currentTarget.value)}
				/>
			</td>
			<td class={UNIT}>%</td>
		</tr>
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">e</td>
			<td class={LABEL}>
				Commitment Fee
			</td>
			<td class="p-0 border-r border-[#E8E8E8]">
				<input type="number" step="0.05" min="0" max="5" class={INPUT}
					value={s.inputs.commitmentFeePct}
					oninput={(e) => setNumber('commitmentFeePct', e.currentTarget.value)}
				/>
			</td>
			<td class={UNIT}>% p.a.</td>
		</tr>

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">f</td>
			<td class={LABEL}>
				Debt Repayment Mode
			</td>
			<td class="p-0 border-r border-[#E8E8E8]">
				<select
					class="w-full text-right px-1 py-0 text-[#1565C0] bg-transparent focus:outline-none text-[11px]"
					value={s.inputs.debtRepaymentMode}
					onchange={(e) => s.updateInputs({ debtRepaymentMode: e.currentTarget.value as 'bullet_at_handover' | 'sales_sweep' })}
				>
					<option value="bullet_at_handover">Bullet at Handover</option>
					<option value="sales_sweep">Sales Sweep</option>
				</select>
			</td>
			<td class={UNIT}></td>
		</tr>

		<!-- 4c. Equity Use -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">4c. &nbsp; Equity Use</td>
		</tr>
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

		<!-- 4d. Returns -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="4" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">4d. &nbsp; Returns</td>
		</tr>
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

		<!-- bottom padding -->
		<tr>
			<td colspan="4" class="py-4"></td>
		</tr>

		</tbody>
	</table>
</div>
