<script lang="ts">
import { workbookStore } from '$lib/feasibility/workbook/store.svelte'
import { toSqft } from '$lib/utils/units'
import AmountInput from '../AmountInput.svelte'

function fmt(value: number, digits = 0): string {
	return value.toLocaleString('en-AE', {
		minimumFractionDigits: digits,
		maximumFractionDigits: digits
	})
}

function fmtAed(value: number): string {
	return fmt(Math.round(value))
}

function fmtPct(value: number, digits = 1): string {
	return fmt(value, digits) + '%'
}

function dateToQuarter(isoDate: string): string {
	if (!isoDate) return '—'
	const d = new Date(isoDate)
	if (isNaN(d.getTime())) return isoDate
	const q = Math.ceil((d.getMonth() + 1) / 3)
	return `Q${q} ${d.getFullYear()}`
}

function monthsBetween(startIso: string, endIso: string): number | null {
	if (!startIso || !endIso) return null
	const s = new Date(startIso)
	const e = new Date(endIso)
	if (isNaN(s.getTime()) || isNaN(e.getTime())) return null
	return (e.getFullYear() - s.getFullYear()) * 12 + (e.getMonth() - s.getMonth())
}

function setNumber<K extends keyof typeof workbookStore.inputs>(key: K, raw: string) {
	const v = Number(raw)
	workbookStore.updateInputs({ [key]: Number.isFinite(v) ? v : 0 })
}

const s = workbookStore
const draftBudgetTiming = $derived(s.workbook?.budgetTiming ?? null)
const draftSourcesUses = $derived(s.workbook?.sourcesUses ?? null)

// ── Derived metrics ──────────────────────────────────────────────────────────

const constructionMonths = $derived(
	monthsBetween(s.inputs.constructionDate, s.inputs.handoverDate) ?? 0
)

// Finance costs — prefer draft case values when available
const totalInterestPaid = $derived(s.workbook?.returns?.totalInterestPaidAed ?? 0)
const totalCommitmentFees = $derived(s.workbook?.returns?.totalCommitmentFeesAed ?? 0)
const arrangementFee = $derived(
	s.workbook?.financing?.arrangementFeeAed ??
		s.totalDebtCapacity * (s.inputs.arrangementFeePct / 100)
)
const totalFinanceCosts = $derived(totalInterestPaid + totalCommitmentFees + arrangementFee)

// Cost base (pre-finance) — aligns with backend ordering
const preFinanceCosts = $derived(
	s.totalLandCostAed +
		s.constructionCostInclInflation +
		s.designSupervisionCost +
		s.marketingCost +
		s.salesAgentFees +
		s.inputs.infrastructureCostAed +
		s.inputs.governmentFeesAed +
		s.inputs.masterCommunityFeesAed +
		(s.inputs.demolitionEnabled ? s.demolitionCost : 0) +
		s.inputs.ffeOsePreopeningCostAed +
		s.contingencyCost
)

// Per-unit / per-sqft metrics
const costPerUnitAed = $derived(s.totalUnits > 0 ? s.modelTotalCostsInclVat / s.totalUnits : 0)
const costPerSqftBua = $derived(
	s.totalBuaSqm > 0 ? s.modelTotalCostsInclVat / toSqft(s.totalBuaSqm) : 0
)
const revenuePerUnitAed = $derived(s.totalUnits > 0 ? s.totalConfiguredRevenue / s.totalUnits : 0)
const profitPerUnitAed = $derived(revenuePerUnitAed - costPerUnitAed)
const grossMarginPct = $derived(
	s.totalConfiguredRevenue > 0
		? ((s.totalConfiguredRevenue - s.modelTotalCostsInclVat) / s.totalConfiguredRevenue) * 100
		: 0
)

// All-in margin (includes finance costs)
const allInProfit = $derived(
	s.workbook?.returns?.allInProjectProfitAed ??
		s.totalConfiguredRevenue - s.modelTotalCostsInclVat - totalFinanceCosts
)
const allInMarginPct = $derived(
	s.workbook?.returns?.allInMarginPct ??
		(s.totalConfiguredRevenue > 0 ? (allInProfit / s.totalConfiguredRevenue) * 100 : 0)
)

// Returns
const equityIrrPct = $derived(s.workbook?.returns?.equityIrrPct ?? null)
const projectIrrPct = $derived(s.projectIrrPct)

// Pct of total
const pct = (amount: number) =>
	s.modelTotalCostsInclVat > 0 ? (amount / s.modelTotalCostsInclVat) * 100 : 0
const revPct = (amount: number) =>
	s.totalConfiguredRevenue > 0 ? (amount / s.totalConfiguredRevenue) * 100 : 0

// Styles — mirroring KeyAssumptionsSheet palette
const INPUT =
	'w-full text-right px-1 py-0 text-[#1565C0] bg-transparent focus:outline-none tabular-nums text-[11px]'
const ROW_STD = 'border-b border-[#D9D9D9]'
const ROW_TOTAL = 'border-t border-[#1F3864] border-b border-[#D9D9D9]'
const LABEL = 'px-2 py-[3px] text-slate-800'
const LABEL_INDENT = 'pl-6 pr-2 py-[3px] text-slate-600 italic text-[10px]'
const LABEL_SM = 'px-2 py-[3px] text-slate-600 text-[10px]'
const VALUE_BLACK = 'px-2 py-[3px] text-right tabular-nums text-slate-900 font-normal'
const VALUE_BOLD = 'px-2 py-[3px] text-right tabular-nums text-slate-900 font-semibold'
const VALUE_BLUE = 'px-2 py-[3px] text-right tabular-nums text-[#1565C0] font-normal'
const PCT_COL = 'px-2 py-[3px] text-right tabular-nums text-slate-400 text-[10px]'
const UNIT = 'px-2 py-[3px] text-slate-500 whitespace-nowrap text-[10px]'
const ROW_INDENT = 'border-b border-[#D9D9D9] bg-[#F9F9F9]'
</script>

<div class="overflow-auto flex-1 bg-white text-[11px] font-[Calibri,'Segoe_UI',Arial,sans-serif] select-none">

	<!-- Header -->
	<div class="bg-[#1F3864] text-white px-4 py-2.5 flex items-start justify-between gap-4">
		<div>
			<div class="text-[13px] font-bold tracking-wide">DEVELOPMENT BUDGET</div>
			<div class="text-[10px] text-blue-200 mt-0.5">Full cost build-up with input assumptions &amp; timings &mdash; AED unless stated</div>
		</div>
		<div class="text-right text-[10px] leading-5 mt-0.5 shrink-0">
			<div><span class="text-[#90CAF9] font-semibold">■</span> <span class="text-[#90CAF9]">Blue</span> = Input</div>
			<div><span class="text-white font-semibold">■</span> <span class="text-white">Black</span> = Derived</div>
		</div>
	</div>

	<!-- Summary bar -->
	<div class="grid grid-cols-4 border-b border-[#B8C4CE] bg-[#EEF2F7]">
		<div class="px-3 py-2 border-r border-[#D9D9D9]">
			<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Total Budget (incl. VAT)</div>
			<div class="text-[13px] font-bold text-slate-900 tabular-nums mt-0.5">{fmtAed(s.modelTotalCostsInclVat)}</div>
			<div class="text-[10px] text-slate-500">AED</div>
		</div>
		<div class="px-3 py-2 border-r border-[#D9D9D9]">
			<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Gross Margin</div>
			<div class="text-[13px] font-bold text-slate-900 tabular-nums mt-0.5">{fmtPct(grossMarginPct)}</div>
			<div class="text-[10px] text-slate-500">of gross revenue</div>
		</div>
		<div class="px-3 py-2 border-r border-[#D9D9D9]">
			<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">All-in Margin</div>
			<div class="text-[13px] font-bold {allInMarginPct < 10 ? 'text-rose-600' : allInMarginPct < 15 ? 'text-amber-600' : 'text-emerald-700'} tabular-nums mt-0.5">{fmtPct(allInMarginPct)}</div>
			<div class="text-[10px] text-slate-500">after finance costs</div>
		</div>
		<div class="px-3 py-2">
			<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Construction Period</div>
			<div class="text-[13px] font-bold text-slate-900 tabular-nums mt-0.5">{constructionMonths > 0 ? constructionMonths : '—'}</div>
			<div class="text-[10px] text-slate-500">months</div>
		</div>
	</div>

	{#if draftBudgetTiming}
		<div class="grid grid-cols-4 border-b border-[#D9D9D9] bg-slate-50">
			<div class="px-3 py-2 border-r border-[#D9D9D9]">
				<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Timed Budget Total</div>
				<div class="text-[13px] font-bold text-slate-900 tabular-nums mt-0.5">{fmtAed(draftBudgetTiming.totalBudgetedCostsAed)}</div>
				<div class="text-[10px] text-slate-500">Backend timed costs</div>
			</div>
			<div class="px-3 py-2 border-r border-[#D9D9D9]">
				<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Source / Use Gap</div>
				<div class="text-[13px] font-bold {draftSourcesUses && Math.abs(draftSourcesUses.gapAed) > 1_000_000 ? 'text-amber-700' : 'text-slate-900'} tabular-nums mt-0.5">
					{fmtAed(draftSourcesUses?.gapAed ?? 0)}
				</div>
				<div class="text-[10px] text-slate-500">Backend sources and uses</div>
			</div>
			<div class="px-3 py-2 border-r border-[#D9D9D9]">
				<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Selling Costs</div>
				<div class="text-[13px] font-bold text-slate-900 tabular-nums mt-0.5">
					{fmtAed(draftBudgetTiming.periods.reduce((sum: number, period: { sellingCostsAed: number }) => sum + period.sellingCostsAed, 0))}
				</div>
				<div class="text-[10px] text-slate-500">Marketing + agency timing</div>
			</div>
			<div class="px-3 py-2">
				<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Construction-Related</div>
				<div class="text-[13px] font-bold text-slate-900 tabular-nums mt-0.5">
					{fmtAed(draftBudgetTiming.periods.reduce((sum: number, period: { constructionRelatedCostsAed: number }) => sum + period.constructionRelatedCostsAed, 0))}
				</div>
				<div class="text-[10px] text-slate-500">Land, hard, soft, authority</div>
			</div>
		</div>

		<div class="border-b border-[#D9D9D9] bg-white">
			<div class="px-4 py-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500 bg-slate-50 border-b border-[#E5E7EB]">
				Backend Timed Budget
			</div>
			<div class="overflow-x-auto">
				<table class="w-full border-collapse text-[10px]">
					<thead>
						<tr class="bg-[#EEF2F7] border-b border-[#D9D9D9]">
							<th class="px-2 py-[4px] text-left text-slate-600 font-semibold uppercase tracking-[0.08em]">Period</th>
							<th class="px-2 py-[4px] text-right text-slate-600 font-semibold uppercase tracking-[0.08em]">Budgeted</th>
							<th class="px-2 py-[4px] text-right text-slate-600 font-semibold uppercase tracking-[0.08em]">Selling</th>
							<th class="px-2 py-[4px] text-right text-slate-600 font-semibold uppercase tracking-[0.08em]">Construction Rel.</th>
							<th class="px-2 py-[4px] text-right text-slate-600 font-semibold uppercase tracking-[0.08em]">VAT</th>
						</tr>
					</thead>
					<tbody>
						{#each draftBudgetTiming.periods as period (period.periodEndDate)}
							<tr class="border-b border-[#F1F5F9]">
								<td class="px-2 py-[3px] text-slate-700">{period.periodLabel}</td>
								<td class="px-2 py-[3px] text-right tabular-nums text-slate-900">{fmtAed(period.budgetedCostsAed)}</td>
								<td class="px-2 py-[3px] text-right tabular-nums text-slate-500">{period.sellingCostsAed > 0 ? fmtAed(period.sellingCostsAed) : '—'}</td>
								<td class="px-2 py-[3px] text-right tabular-nums text-slate-500">{period.constructionRelatedCostsAed > 0 ? fmtAed(period.constructionRelatedCostsAed) : '—'}</td>
								<td class="px-2 py-[3px] text-right tabular-nums text-slate-500">{period.vatCostsAed > 0 ? fmtAed(period.vatCostsAed) : '—'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}

	<table class="w-full border-collapse" style="border-spacing:0">
		<colgroup>
			<col style="width:2.5%">    <!-- row ref -->
			<col style="width:38%">     <!-- label -->
			<col style="width:8%">      <!-- timing -->
			<col style="width:20%">     <!-- amount -->
			<col style="width:10%">     <!-- rate/pct -->
			<col style="width:8%">      <!-- % of total -->
			<col style="width:13%">     <!-- unit -->
		</colgroup>

		<!-- Column headers -->
		<thead>
			<tr class="bg-[#D6DCE4] border-b border-[#B8C4CE]">
				<th class="px-1 py-[4px] text-center text-[9px] font-semibold text-slate-500 uppercase tracking-wider">#</th>
				<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Line Item</th>
				<th class="px-2 py-[4px] text-center text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Timing</th>
				<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Amount (AED)</th>
				<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Rate / %</th>
				<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">% Budget</th>
				<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Basis</th>
			</tr>
		</thead>

		<tbody>

		<!-- ═══════════════════════════════════════════════════════════
		     SECTION A — LAND ACQUISITION
		     ═══════════════════════════════════════════════════════════ -->
		<tr class="bg-[#1F3864]">
			<td colspan="7" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">A. &nbsp; LAND ACQUISITION</td>
		</tr>

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">1</td>
			<td class={LABEL}>Land Purchase Price</td>
			<td class="p-0 relative">
				<div class="flex items-center justify-center px-1 py-[3px] pointer-events-none">
					<span class="text-[#1565C0] tabular-nums text-[10px]">{dateToQuarter(s.inputs.landAcquisitionDate)}</span>
					<span class="ml-0.5 text-[8px] text-slate-400 border border-slate-200 rounded px-0.5">▾</span>
				</div>
				<input type="date" class="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
					value={s.inputs.landAcquisitionDate}
					oninput={(e) => s.updateInputs({ landAcquisitionDate: e.currentTarget.value })} />
			</td>
			<td class="p-0">
				<AmountInput
					value={s.plotAcquisitionCost}
					oncommit={(v) => s.updateInputs({ landAcquisitionCostOverrideAed: v > 0 ? v : null })}
					class={INPUT}
				/>
			</td>
			<td class="p-0">
				<input type="number" step="100" class={INPUT}
					value={Math.round(s.inputs.landPricePsqm ?? 0)}
					oninput={(e) => s.updateInputs({ landPricePsqm: Number(e.currentTarget.value) || 0 })} />
			</td>
			<td class={PCT_COL}>{fmtPct(pct(s.plotAcquisitionCost))}</td>
			<td class={UNIT}>AED / sqm plot</td>
		</tr>

		<tr class={ROW_INDENT}>
			<td></td>
			<td class={LABEL_INDENT}>↳ Transfer Fee (4% of purchase)</td>
			<td class="px-2 py-[3px] text-center text-[10px] text-slate-400">{dateToQuarter(s.inputs.landAcquisitionDate)}</td>
			<td class={VALUE_BLACK}>{fmtAed(s.landTransferFeeAed)}</td>
			<td class="px-2 py-[3px] text-right text-[10px] text-slate-400">4.0%</td>
			<td class={PCT_COL}>{fmtPct(pct(s.landTransferFeeAed))}</td>
			<td class={UNIT}>of purchase</td>
		</tr>

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">2</td>
			<td class={LABEL}>Brokerage Fee</td>
			<td class="px-2 py-[3px] text-center text-[10px] text-slate-400">{dateToQuarter(s.inputs.landAcquisitionDate)}</td>
			<td class="p-0">
				<AmountInput value={s.inputs.brokerageFeeAed}
					oncommit={(v) => s.updateInputs({ brokerageFeeAed: v })} class={INPUT} />
			</td>
			<td class={PCT_COL}></td>
			<td class={PCT_COL}>{fmtPct(pct(s.inputs.brokerageFeeAed))}</td>
			<td class={UNIT}>fixed AED</td>
		</tr>

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">3</td>
			<td class={LABEL}>Legal / Due Diligence</td>
			<td class="px-2 py-[3px] text-center text-[10px] text-slate-400">{dateToQuarter(s.inputs.landAcquisitionDate)}</td>
			<td class="p-0">
				<AmountInput value={s.inputs.legalDdCostAed}
					oncommit={(v) => s.updateInputs({ legalDdCostAed: v })} class={INPUT} />
			</td>
			<td class={PCT_COL}></td>
			<td class={PCT_COL}>{fmtPct(pct(s.inputs.legalDdCostAed))}</td>
			<td class={UNIT}>fixed AED</td>
		</tr>

		<tr class={ROW_TOTAL}>
			<td></td>
			<td class="px-2 py-[3px] font-semibold text-slate-900">Total Land Cost</td>
			<td></td>
			<td class={VALUE_BOLD}>{fmtAed(s.totalLandCostAed)}</td>
			<td></td>
			<td class="px-2 py-[3px] text-right tabular-nums text-slate-600 text-[10px] font-semibold">{fmtPct(pct(s.totalLandCostAed))}</td>
			<td class={UNIT}>AED</td>
		</tr>

		<!-- ═══════════════════════════════════════════════════════════
		     SECTION B — CONSTRUCTION
		     ═══════════════════════════════════════════════════════════ -->
		<tr class="bg-[#1F3864]">
			<td colspan="7" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">B. &nbsp; CONSTRUCTION</td>
		</tr>

		{#if s.inputs.demolitionEnabled}
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">4</td>
			<td class={LABEL}>Demolition / Enabling Works</td>
			<td class="p-0 relative">
				<div class="flex items-center justify-center px-1 py-[3px] pointer-events-none">
					<span class="text-[#1565C0] tabular-nums text-[10px]">{dateToQuarter(s.inputs.demolitionEnablingDate)}</span>
					<span class="ml-0.5 text-[8px] text-slate-400 border border-slate-200 rounded px-0.5">▾</span>
				</div>
				<input type="date" class="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
					value={s.inputs.demolitionEnablingDate}
					oninput={(e) => s.updateInputs({ demolitionEnablingDate: e.currentTarget.value })} />
			</td>
			<td class="p-0">
				<AmountInput value={s.inputs.demolitionCostAed}
					oncommit={(v) => s.updateInputs({ demolitionCostAed: v })} class={INPUT} />
			</td>
			<td class={PCT_COL}></td>
			<td class={PCT_COL}>{fmtPct(pct(s.demolitionCost))}</td>
			<td class={UNIT}>fixed AED</td>
		</tr>
		{/if}

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">5</td>
			<td class={LABEL}>Construction Cost <span class="text-slate-400 font-normal italic">(Rate × BUA)</span></td>
			<td class="p-0 relative">
				<div class="flex items-center justify-center px-1 py-[3px] pointer-events-none">
					<span class="text-[#1565C0] tabular-nums text-[10px]">{dateToQuarter(s.inputs.constructionDate)}</span>
					<span class="ml-0.5 text-[8px] text-slate-400 border border-slate-200 rounded px-0.5">▾</span>
				</div>
				<input type="date" class="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
					value={s.inputs.constructionDate}
					oninput={(e) => s.updateInputs({ constructionDate: e.currentTarget.value })} />
			</td>
			<td class={VALUE_BLACK}>{fmtAed(s.constructionCostInclInflation)}</td>
			<td class="p-0">
				<input type="number" step="10" class={INPUT}
					value={Math.round(s.inputs.constructionCostPsqmBua * 0.092903)}
					oninput={(e) => s.updateInputs({ constructionCostPsqmBua: (Number(e.currentTarget.value) || 0) / 0.092903 })} />
			</td>
			<td class={PCT_COL}>{fmtPct(pct(s.constructionCostInclInflation))}</td>
			<td class={UNIT}>AED / sqft BUA</td>
		</tr>

		<tr class={ROW_INDENT}>
			<td></td>
			<td class={LABEL_INDENT}>↳ BUA ({fmt(toSqft(s.totalBuaSqm), 0)} sqft = GFA × {s.inputs.buaMultiplier}x + parking)</td>
			<td></td>
			<td class={VALUE_BLACK}></td>
			<td class={PCT_COL}></td>
			<td></td>
			<td class={UNIT}></td>
		</tr>

		{#if s.inputs.midPointInflationPct > 0}
		<tr class={ROW_INDENT}>
			<td></td>
			<td class={LABEL_INDENT}>↳ Inflation adjustment ({fmt(s.inputs.midPointInflationPct, 1)}%)</td>
			<td></td>
			<td class={VALUE_BLACK}>{fmtAed(s.inflationCost)}</td>
			<td class="p-0">
				<input type="number" step="0.1" min="0" class={INPUT}
					value={s.inputs.midPointInflationPct}
					oninput={(e) => setNumber('midPointInflationPct', e.currentTarget.value)} />
			</td>
			<td></td>
			<td class={UNIT}>% of base cost</td>
		</tr>
		{/if}

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">→</td>
			<td class={LABEL_SM}>Handover Date</td>
			<td class="p-0 relative">
				<div class="flex items-center justify-center px-1 py-[3px] pointer-events-none">
					<span class="text-[#1565C0] tabular-nums text-[10px]">{dateToQuarter(s.inputs.handoverDate)}</span>
					<span class="ml-0.5 text-[8px] text-slate-400 border border-slate-200 rounded px-0.5">▾</span>
				</div>
				<input type="date" class="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
					value={s.inputs.handoverDate}
					oninput={(e) => s.updateInputs({ handoverDate: e.currentTarget.value })} />
			</td>
			<td class="px-2 py-[3px] text-right text-[10px] text-slate-500">
				{constructionMonths > 0 ? constructionMonths + ' month build' : '—'}
			</td>
			<td></td>
			<td></td>
			<td class={UNIT}>Q &amp; Year</td>
		</tr>

		<!-- ═══════════════════════════════════════════════════════════
		     SECTION C — SOFT COSTS
		     ═══════════════════════════════════════════════════════════ -->
		<tr class="bg-[#1F3864]">
			<td colspan="7" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">C. &nbsp; SOFT COSTS</td>
		</tr>

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">6</td>
			<td class={LABEL}>Design &amp; Supervision</td>
			<td class="px-2 py-[3px] text-center text-[10px] text-slate-400">Con→HO</td>
			<td class="p-0">
				<AmountInput value={s.designSupervisionCost}
					oncommit={(v) => s.updateInputs({ designSupervisionCostOverrideAed: v > 0 ? v : null })}
					class={INPUT} />
			</td>
			<td class="p-0">
				<input type="number" step="0.5" min="0" class={INPUT}
					value={s.inputs.designSupervisionPct}
					oninput={(e) => setNumber('designSupervisionPct', e.currentTarget.value)} />
			</td>
			<td class={PCT_COL}>{fmtPct(pct(s.designSupervisionCost))}</td>
			<td class={UNIT}>% of construction</td>
		</tr>

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">7</td>
			<td class={LABEL}>Marketing</td>
			<td class="px-2 py-[3px] text-center text-[10px] text-slate-400">Sales period</td>
			<td class="p-0">
				<AmountInput value={s.marketingCost}
					oncommit={(v) => s.updateInputs({ marketingCostOverrideAed: v > 0 ? v : null })}
					class={INPUT} />
			</td>
			<td class="p-0">
				<input type="number" step="0.1" min="0" class={INPUT}
					value={s.inputs.marketingCostPct}
					oninput={(e) => setNumber('marketingCostPct', e.currentTarget.value)} />
			</td>
			<td class={PCT_COL}>{fmtPct(pct(s.marketingCost))}</td>
			<td class={UNIT}>% of revenue</td>
		</tr>

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">8</td>
			<td class={LABEL}>Sales Agent Fees</td>
			<td class="px-2 py-[3px] text-center text-[10px] text-slate-400">Sales period</td>
			<td class="p-0">
				<AmountInput value={s.salesAgentFees}
					oncommit={(v) => s.updateInputs({ salesAgentFeesOverrideAed: v > 0 ? v : null })}
					class={INPUT} />
			</td>
			<td class="p-0">
				<input type="number" step="0.1" min="0" class={INPUT}
					value={s.inputs.salesAgentFeePct}
					oninput={(e) => setNumber('salesAgentFeePct', e.currentTarget.value)} />
			</td>
			<td class={PCT_COL}>{fmtPct(pct(s.salesAgentFees))}</td>
			<td class={UNIT}>% of revenue</td>
		</tr>

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">9</td>
			<td class={LABEL}>Contingency</td>
			<td class="px-2 py-[3px] text-center text-[10px] text-slate-400">Con→HO</td>
			<td class="p-0">
				<AmountInput value={s.contingencyCost}
					oncommit={(v) => s.updateInputs({ contingencyCostOverrideAed: v > 0 ? v : null })}
					class={INPUT} />
			</td>
			<td class="p-0">
				<input type="number" step="0.5" min="0" class={INPUT}
					value={s.inputs.contingencyPct}
					oninput={(e) => setNumber('contingencyPct', e.currentTarget.value)} />
			</td>
			<td class={PCT_COL}>{fmtPct(pct(s.contingencyCost))}</td>
			<td class={UNIT}>% of construction</td>
		</tr>

		<!-- ═══════════════════════════════════════════════════════════
		     SECTION D — STATUTORY & DEVELOPMENT COSTS
		     ═══════════════════════════════════════════════════════════ -->
		<tr class="bg-[#1F3864]">
			<td colspan="7" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">D. &nbsp; STATUTORY &amp; DEVELOPMENT COSTS</td>
		</tr>

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">10</td>
			<td class={LABEL}>Infrastructure, Utilities &amp; Landscaping</td>
			<td class="px-2 py-[3px] text-center text-[10px] text-slate-400">Con→HO</td>
			<td class="p-0">
				<AmountInput value={s.inputs.infrastructureCostAed}
					oncommit={(v) => s.updateInputs({ infrastructureCostAed: v })} class={INPUT} />
			</td>
			<td class="px-2 py-[3px] text-right text-[10px] text-slate-400">
				{s.inputs.plotAreaSqm > 0 ? fmt(s.inputs.infrastructureCostAed / toSqft(s.inputs.plotAreaSqm), 0) : '—'}
			</td>
			<td class={PCT_COL}>{fmtPct(pct(s.inputs.infrastructureCostAed))}</td>
			<td class={UNIT}>AED / sqft plot</td>
		</tr>

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">11</td>
			<td class={LABEL}>Authority &amp; Connection Fees</td>
			<td class="px-2 py-[3px] text-center text-[10px] text-slate-400">Pre-con</td>
			<td class="p-0">
				<AmountInput value={s.inputs.governmentFeesAed}
					oncommit={(v) => s.updateInputs({ governmentFeesAed: v })} class={INPUT} />
			</td>
			<td class="px-2 py-[3px] text-right text-[10px] text-slate-400">
				{s.maxGfaSqm > 0 ? fmt(s.inputs.governmentFeesAed / toSqft(s.maxGfaSqm), 0) : '—'}
			</td>
			<td class={PCT_COL}>{fmtPct(pct(s.inputs.governmentFeesAed))}</td>
			<td class={UNIT}>AED / sqft GFA</td>
		</tr>

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">12</td>
			<td class={LABEL}>Master Community Fees</td>
			<td class="px-2 py-[3px] text-center text-[10px] text-slate-400">Pre-HO</td>
			<td class="p-0">
				<AmountInput value={s.inputs.masterCommunityFeesAed}
					oncommit={(v) => s.updateInputs({ masterCommunityFeesAed: v })} class={INPUT} />
			</td>
			<td class="px-2 py-[3px] text-right text-[10px] text-slate-400">
				{s.inputs.plotAreaSqm > 0 ? fmt(s.inputs.masterCommunityFeesAed / toSqft(s.inputs.plotAreaSqm), 0) : '—'}
			</td>
			<td class={PCT_COL}>{fmtPct(pct(s.inputs.masterCommunityFeesAed))}</td>
			<td class={UNIT}>AED / sqft plot</td>
		</tr>

		{#if s.inputs.ffeOsePreopeningCostAed > 0}
		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">13</td>
			<td class={LABEL}>FF&amp;E / Pre-Opening</td>
			<td class="px-2 py-[3px] text-center text-[10px] text-slate-400">Pre-HO</td>
			<td class="p-0">
				<AmountInput value={s.inputs.ffeOsePreopeningCostAed}
					oncommit={(v) => s.updateInputs({ ffeOsePreopeningCostAed: v })} class={INPUT} />
			</td>
			<td class={PCT_COL}></td>
			<td class={PCT_COL}>{fmtPct(pct(s.inputs.ffeOsePreopeningCostAed))}</td>
			<td class={UNIT}>fixed AED</td>
		</tr>
		{/if}

		<!-- Pre-finance sub-total -->
		<tr class={ROW_TOTAL}>
			<td></td>
			<td class="px-2 py-[3px] font-semibold text-slate-700">Pre-Finance Cost Sub-Total</td>
			<td></td>
			<td class={VALUE_BOLD}>{fmtAed(preFinanceCosts)}</td>
			<td></td>
			<td class="px-2 py-[3px] text-right tabular-nums text-slate-500 text-[10px] font-semibold">{fmtPct(pct(preFinanceCosts))}</td>
			<td class={UNIT}>AED</td>
		</tr>

		<!-- ═══════════════════════════════════════════════════════════
		     SECTION E — FINANCE COSTS
		     ═══════════════════════════════════════════════════════════ -->
		<tr class="bg-[#1F3864]">
			<td colspan="7" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">E. &nbsp; FINANCE COSTS</td>
		</tr>

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">14</td>
			<td class={LABEL}>Arrangement Fee</td>
			<td class="px-2 py-[3px] text-center text-[10px] text-slate-400">Financial close</td>
			<td class={VALUE_BLACK}>{fmtAed(arrangementFee)}</td>
			<td class="p-0">
				<input type="number" step="0.1" min="0" class={INPUT}
					value={s.inputs.arrangementFeePct}
					oninput={(e) => setNumber('arrangementFeePct', e.currentTarget.value)} />
			</td>
			<td class={PCT_COL}>{fmtPct(pct(arrangementFee))}</td>
			<td class={UNIT}>% of debt</td>
		</tr>

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">15</td>
			<td class={LABEL}>Undrawn Commitment Fee</td>
			<td class="px-2 py-[3px] text-center text-[10px] text-slate-400">Pre-draw</td>
			<td class={VALUE_BLACK}>{totalCommitmentFees > 0 ? fmtAed(totalCommitmentFees) : '—'}</td>
			<td class="p-0">
				<input type="number" step="0.1" min="0" class={INPUT}
					value={s.inputs.commitmentFeePct}
					oninput={(e) => setNumber('commitmentFeePct', e.currentTarget.value)} />
			</td>
			<td class={PCT_COL}>{totalCommitmentFees > 0 ? fmtPct(pct(totalCommitmentFees)) : '—'}</td>
			<td class={UNIT}>% p.a. on undrawn</td>
		</tr>

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">16</td>
			<td class={LABEL}>
				Interest Carry
				{#if !s.workbook}
					<span class="text-amber-600 text-[9px] font-normal italic ml-1">(run model for accurate figure)</span>
				{/if}
			</td>
			<td class="px-2 py-[3px] text-center text-[10px] text-slate-400">Con→HO</td>
			<td class={VALUE_BLACK}>{totalInterestPaid > 0 ? fmtAed(totalInterestPaid) : '—'}</td>
			<td class="px-2 py-[3px] relative">
				<!-- Land and construction rates — derived from EIBOR sheet -->
				<div class="flex flex-col gap-0 text-right tabular-nums text-[10px]">
					<span class="text-emerald-700 border-b border-[#EBEBEB] pb-[1px]" title="Land loan rate (EIBOR + spread)">{fmtPct(s.landLoanRatePct, 2)}</span>
					<span class="text-emerald-700 pt-[1px]" title="Construction loan rate (EIBOR + spread)">{fmtPct(s.constructionLoanRatePct, 2)}</span>
				</div>
			</td>
			<td class={PCT_COL}>{totalInterestPaid > 0 ? fmtPct(pct(totalInterestPaid)) : '—'}</td>
			<td class="px-2 py-[3px] text-slate-400 text-[10px] whitespace-nowrap">↗ EIBOR sheet</td>
		</tr>

		<tr class={ROW_TOTAL}>
			<td></td>
			<td class="px-2 py-[3px] font-semibold text-slate-700">Total Finance Costs</td>
			<td></td>
			<td class={VALUE_BOLD}>{totalFinanceCosts > 0 ? fmtAed(totalFinanceCosts) : '—'}</td>
			<td></td>
			<td class="px-2 py-[3px] text-right tabular-nums text-slate-500 text-[10px] font-semibold">{totalFinanceCosts > 0 ? fmtPct(pct(totalFinanceCosts)) : '—'}</td>
			<td class={UNIT}>AED</td>
		</tr>

		<!-- ═══════════════════════════════════════════════════════════
		     SECTION F — VAT
		     ═══════════════════════════════════════════════════════════ -->
		<tr class="bg-[#D6DCE4]">
			<td colspan="7" class="px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase">F. &nbsp; VAT</td>
		</tr>

		<tr class={ROW_STD}>
			<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">17</td>
			<td class={LABEL}>VAT <span class="text-slate-400 font-normal italic">(refundable at handover)</span></td>
			<td class="px-2 py-[3px] text-center text-[10px] text-slate-400">Con→HO</td>
			<td class={VALUE_BLACK}>{fmtAed(s.vatAmount)}</td>
			<td class="p-0">
				<input type="number" step="0.5" min="0" class={INPUT}
					value={s.inputs.vatPct}
					oninput={(e) => setNumber('vatPct', e.currentTarget.value)} />
			</td>
			<td class={PCT_COL}>{fmtPct(pct(s.vatAmount))}</td>
			<td class={UNIT}>% of pre-finance</td>
		</tr>

		</tbody>
	</table>

	<!-- Grand Total -->
	<div class="border-t-2 border-[#1F3864] bg-[#1F3864]">
		<div class="grid grid-cols-3 gap-0">
			<div class="px-3 py-2 border-r border-[#2D4D7A]">
				<div class="text-[9px] uppercase tracking-wider text-blue-200 font-semibold">Total Cost excl. VAT</div>
				<div class="text-[12px] font-bold text-white tabular-nums mt-0.5">{fmtAed(s.totalCostsExclVat)}</div>
			</div>
			<div class="px-3 py-2 border-r border-[#2D4D7A]">
				<div class="text-[9px] uppercase tracking-wider text-blue-200 font-semibold">VAT</div>
				<div class="text-[12px] font-bold text-white tabular-nums mt-0.5">{fmtAed(s.vatAmount)}</div>
			</div>
			<div class="px-3 py-2">
				<div class="text-[9px] uppercase tracking-wider text-blue-200 font-semibold">TOTAL BUDGET (incl. VAT)</div>
				<div class="text-[14px] font-bold text-white tabular-nums mt-0.5">{fmtAed(s.modelTotalCostsInclVat)}</div>
			</div>
		</div>
	</div>

	<!-- Per-unit metrics -->
	<div class="bg-[#EEF2F7] border-b border-[#B8C4CE]">
		<div class="px-3 py-1.5 text-[10px] font-semibold text-slate-600 uppercase tracking-wider border-b border-[#D9D9D9]">Per-Unit &amp; Per-sqft Metrics</div>
		<div class="grid grid-cols-5 divide-x divide-[#D9D9D9]">
			<div class="px-3 py-2">
				<div class="text-[9px] text-slate-500 uppercase tracking-wider">Cost / Unit</div>
				<div class="text-[12px] font-bold text-slate-900 tabular-nums mt-0.5">{s.totalUnits > 0 ? fmtAed(costPerUnitAed) : '—'}</div>
				<div class="text-[9px] text-slate-400">AED</div>
			</div>
			<div class="px-3 py-2">
				<div class="text-[9px] text-slate-500 uppercase tracking-wider">Revenue / Unit</div>
				<div class="text-[12px] font-bold text-slate-900 tabular-nums mt-0.5">{s.totalUnits > 0 ? fmtAed(revenuePerUnitAed) : '—'}</div>
				<div class="text-[9px] text-slate-400">AED</div>
			</div>
			<div class="px-3 py-2">
				<div class="text-[9px] text-slate-500 uppercase tracking-wider">Profit / Unit</div>
				<div class="text-[12px] font-bold {profitPerUnitAed < 0 ? 'text-rose-600' : 'text-emerald-700'} tabular-nums mt-0.5">{s.totalUnits > 0 ? fmtAed(profitPerUnitAed) : '—'}</div>
				<div class="text-[9px] text-slate-400">AED</div>
			</div>
			<div class="px-3 py-2">
				<div class="text-[9px] text-slate-500 uppercase tracking-wider">All-in Cost / sqft BUA</div>
				<div class="text-[12px] font-bold text-slate-900 tabular-nums mt-0.5">{s.totalBuaSqm > 0 ? fmt(costPerSqftBua, 0) : '—'}</div>
				<div class="text-[9px] text-slate-400">AED / sqft</div>
			</div>
			<div class="px-3 py-2">
				<div class="text-[9px] text-slate-500 uppercase tracking-wider">Budget / Revenue</div>
				<div class="text-[12px] font-bold text-slate-900 tabular-nums mt-0.5">{s.totalConfiguredRevenue > 0 ? fmt(s.modelTotalCostsInclVat / s.totalConfiguredRevenue * 100, 1) + '%' : '—'}</div>
				<div class="text-[9px] text-slate-400">cost-to-revenue</div>
			</div>
		</div>
	</div>

	<!-- Returns summary (linked from Returns sheet) -->
	<div class="bg-white border-b border-[#B8C4CE]">
		<div class="px-3 py-1.5 text-[10px] font-semibold text-slate-600 uppercase tracking-wider border-b border-[#D9D9D9] bg-[#EEF2F7]">Returns Summary <span class="text-slate-400 font-normal normal-case italic">(linked from model)</span></div>
		<table class="w-full border-collapse" style="border-spacing:0">
			<colgroup>
				<col style="width:2.5%">
				<col style="width:44%">
				<col style="width:28%">
				<col style="width:25%">
			</colgroup>
			<tbody>

			<tr class="border-b border-[#D9D9D9]">
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">a</td>
				<td class="px-2 py-[3px] text-slate-800">Gross Revenue</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 font-semibold">{fmtAed(s.totalConfiguredRevenue)}</td>
				<td class="px-2 py-[3px] text-right text-slate-400 text-[10px]">AED</td>
			</tr>
			<tr class="border-b border-[#D9D9D9]">
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">b</td>
				<td class="px-2 py-[3px] text-slate-800">Total Cost (incl. VAT)</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900">{fmtAed(s.modelTotalCostsInclVat)}</td>
				<td class="px-2 py-[3px] text-right text-slate-400 text-[10px]">AED</td>
			</tr>
			<tr class="border-b border-[#D9D9D9]">
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">c</td>
				<td class="px-2 py-[3px] text-slate-800">Finance Costs <span class="text-slate-400 font-normal italic">(interest + fees)</span></td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900">{totalFinanceCosts > 0 ? fmtAed(totalFinanceCosts) : s.workbook ? '0' : '—'}</td>
				<td class="px-2 py-[3px] text-right text-slate-400 text-[10px]">AED</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] border-t border-[#1F3864]">
				<td class="px-1 py-[3px]"></td>
				<td class="px-2 py-[3px] text-slate-900 font-semibold">All-in Profit</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 font-semibold">{fmtAed(allInProfit)}</td>
				<td class="px-2 py-[3px] text-right text-slate-400 text-[10px]">AED</td>
			</tr>
			<tr class="border-b border-[#D9D9D9]">
				<td class="px-1 py-[3px]"></td>
				<td class="px-2 py-[3px] text-slate-700">All-in Margin</td>
				<td class="px-2 py-[3px] text-right tabular-nums font-semibold {allInMarginPct < 10 ? 'text-rose-600' : allInMarginPct < 15 ? 'text-amber-600' : 'text-emerald-700'}">{fmtPct(allInMarginPct)}</td>
				<td class="px-2 py-[3px] text-right text-slate-400 text-[10px]">of gross revenue</td>
			</tr>

			<!-- IRR section with explanation -->
			<tr class="bg-[#F9F9F9] border-b border-[#E8E8E8]">
				<td colspan="4" class="px-3 py-1.5 text-[9px] text-slate-500 italic">
					IRR measures time-weighted return on invested capital. <strong class="text-slate-600">Project IRR</strong> is unlevered (ignores financing — independent of interest rate). <strong class="text-slate-600">Equity IRR</strong> is levered (higher interest rate → larger debt balance at handover → less escrow released → lower equity return).
				</td>
			</tr>
			<tr class="border-b border-[#D9D9D9]">
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">d</td>
				<td class="px-2 py-[3px] text-slate-800">
					Project IRR
					<span class="ml-1 text-[9px] text-slate-400 font-normal italic">unlevered — excl. financing</span>
				</td>
				<td class="px-2 py-[3px] text-right tabular-nums font-bold text-[13px] {projectIrrPct != null && projectIrrPct < 10 ? 'text-rose-600' : projectIrrPct != null && projectIrrPct < 15 ? 'text-amber-600' : 'text-emerald-700'}">
					{projectIrrPct != null ? fmt(projectIrrPct, 1) + '%' : '—'}
				</td>
				<td class="px-2 py-[3px] text-right text-slate-400 text-[10px]">% p.a.</td>
			</tr>
			<tr class="border-b border-[#D9D9D9]">
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">e</td>
				<td class="px-2 py-[3px] text-slate-800">
					Equity IRR
					<span class="ml-1 text-[9px] text-slate-400 font-normal italic">levered — incl. interest carry</span>
				</td>
				<td class="px-2 py-[3px] text-right tabular-nums font-bold text-[13px] {equityIrrPct === null ? 'text-slate-400' : equityIrrPct < 12 ? 'text-rose-600' : equityIrrPct < 18 ? 'text-amber-600' : 'text-emerald-700'}">
					{equityIrrPct != null ? fmt(equityIrrPct, 1) + '%' : s.workbook ? '—' : 'Run model'}
				</td>
				<td class="px-2 py-[3px] text-right text-slate-400 text-[10px]">{!s.workbook ? '(requires model run)' : '% p.a.'}</td>
			</tr>
			<tr class="border-b border-[#D9D9D9]">
				<td class="px-1 py-[3px] text-slate-400 text-[10px] text-center">f</td>
				<td class="px-2 py-[3px] text-slate-800">MoIC</td>
				<td class="px-2 py-[3px] text-right tabular-nums font-bold text-[12px] text-slate-900">
					{fmt(s.workbook?.returns?.projectMoic ?? s.revenueMultiple, 2)}x
				</td>
				<td class="px-2 py-[3px] text-right text-slate-400 text-[10px]">revenue / cost</td>
			</tr>

			<tr>
				<td colspan="4" class="py-4"></td>
			</tr>

			</tbody>
		</table>
	</div>

</div>
