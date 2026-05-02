<script lang="ts">
import { workbookStore } from '$lib/feasibility/workbook/store.svelte'

function fmt(value: number, digits = 0) {
	return value.toLocaleString('en-AE', {
		minimumFractionDigits: digits,
		maximumFractionDigits: digits
	})
}

function fmtMaybe(value: number | null | undefined, digits = 1, suffix = '%') {
	if (value === null || value === undefined || !Number.isFinite(value)) return 'N/A'
	return `${fmt(value, digits)}${suffix}`
}

const validationIssueCodes = $derived(
	new Set((workbookStore.validation?.issues ?? []).map((issue) => issue.code))
)

function hasIssue(code: string) {
	if (validationIssueCodes.has(code)) return true
	if (code === 'negative_all_in_margin') return validationIssueCodes.has('negative_margin')
	if (code === 'finance_cost_load_high') return validationIssueCodes.has('funding_gap')
	return false
}

type RangeStatus = 'within range' | 'warning' | 'outlier'

function statusClasses(status: RangeStatus) {
	if (status === 'outlier') return 'bg-rose-100 text-rose-700'
	if (status === 'warning') return 'bg-amber-100 text-amber-700'
	return 'bg-emerald-100 text-emerald-700'
}

const outputs = $derived(workbookStore.outputs)
const assumptions = $derived(workbookStore.assumptions)
const draftSensitivities = $derived(
	[] as Array<{
		code: string
		label: string
		changeNote: string
		projectIrrPct: number | null
		equityIrrPct: number | null
		allInMarginPct: number | null
		peakDebtAed: number | null
		totalFinanceCostsAed: number | null
	}>
)

const grossRevenueAed = $derived(outputs?.program.grossRevenueAed ?? 0)
const totalCostsInclVatAed = $derived(outputs?.costs.totalCostsInclVatAed ?? 0)
const projectIrrPct = $derived(outputs?.returns.projectIrrPct ?? 0)
const projectMoic = $derived(outputs?.returns.projectMoic ?? 0)
const offPlanProceedsAed = $derived(outputs?.funding.offPlanProceedsAed ?? 0)
const debtFundingAed = $derived(outputs?.funding.debtFundingAed ?? 0)
const equityFundingAed = $derived(outputs?.funding.equityFundingAed ?? 0)
const vatRefundsAed = $derived(outputs?.funding.vatRefundsAed ?? 0)
const totalSourcesAed = $derived(outputs?.funding.cashReconSourcesAed ?? 0)
const totalUsesAed = $derived(outputs?.funding.cashReconUsesAed ?? 0)
const peakNetSponsorCapitalAed = $derived(outputs?.returns.peakEquityAed ?? 0)
const returnOnCostPct = $derived(
	totalCostsInclVatAed > 0
		? ((grossRevenueAed - totalCostsInclVatAed) / totalCostsInclVatAed) * 100
		: 0
)
const revenueMultiple = $derived(
	totalCostsInclVatAed > 0 ? grossRevenueAed / totalCostsInclVatAed : 0
)

const draftRevenue = $derived(outputs?.program.grossRevenueAed ?? 0)
const draftCostsInclVat = $derived(outputs?.costs.totalCostsInclVatAed ?? 0)
const draftProfit = $derived(outputs?.returns.grossProfitAed ?? 0)
const draftMarginPct = $derived(outputs?.returns.grossMarginPct ?? 0)
const fundingGap = $derived(outputs?.funding.cashReconGapAed ?? totalSourcesAed - totalUsesAed)
const localProfit = $derived(grossRevenueAed - totalCostsInclVatAed)
const localMarginPct = $derived(grossRevenueAed > 0 ? (localProfit / grossRevenueAed) * 100 : 0)
const profitGap = $derived(localProfit - draftProfit)
const marginGap = $derived(localMarginPct - draftMarginPct)
const returnChecks = $derived([
	{
		label: 'Project IRR',
		value:
			outputs?.returns.projectIrrPct !== null && outputs?.returns.projectIrrPct !== undefined
				? `${fmt(outputs.returns.projectIrrPct, 1)}%`
				: 'N/A',
		status: (hasIssue('project_irr_negative')
			? 'outlier'
			: hasIssue('project_irr_too_high')
				? 'warning'
				: 'within range') as RangeStatus
	},
	{
		label: 'Equity IRR',
		value:
			outputs?.returns.equityIrrPct !== null && outputs?.returns.equityIrrPct !== undefined
				? `${fmt(outputs.returns.equityIrrPct, 1)}%`
				: 'N/A',
		status: (hasIssue('equity_irr_negative')
			? 'outlier'
			: hasIssue('equity_irr_too_high')
				? 'warning'
				: 'within range') as RangeStatus
	},
	{
		label: 'All-in margin',
		value:
			outputs?.returns.allInMarginPct !== null && outputs?.returns.allInMarginPct !== undefined
				? `${fmt(outputs.returns.allInMarginPct, 1)}%`
				: 'N/A',
		status: (hasIssue('negative_all_in_margin')
			? 'outlier'
			: hasIssue('finance_cost_load_high')
				? 'warning'
				: 'within range') as RangeStatus
	}
])

const reconciliationRows = $derived([
	{
		label: 'Revenue',
		draft: draftRevenue,
		local: grossRevenueAed,
		suffix: 'AED'
	},
	{
		label: 'Costs incl. VAT',
		draft: draftCostsInclVat,
		local: totalCostsInclVatAed,
		suffix: 'AED'
	},
	{ label: 'Profit', draft: draftProfit, local: localProfit, suffix: 'AED' },
	{
		label: 'All-in profit',
		draft: outputs?.returns.allInProjectProfitAed ?? 0,
		local: localProfit,
		suffix: 'AED'
	},
	{ label: 'Margin', draft: draftMarginPct, local: localMarginPct, suffix: '%' },
	{
		label: 'All-in margin',
		draft: outputs?.returns.allInMarginPct ?? 0,
		local: localMarginPct,
		suffix: '%'
	},
	{
		label: 'Project IRR',
		draft: outputs?.returns.projectIrrPct ?? 0,
		local: projectIrrPct,
		suffix: '%'
	},
	{
		label: 'Project MOIC',
		draft: outputs?.returns.projectMoic ?? 0,
		local: projectMoic,
		suffix: 'x'
	},
	{ label: 'Equity IRR', draft: outputs?.returns.equityIrrPct ?? 0, local: 0, suffix: '%' },
	{ label: 'Equity MOIC', draft: outputs?.returns.equityMoic ?? 0, local: 0, suffix: 'x' }
])

const sourcesUsesRows = $derived([
	{
		label: 'Off-plan proceeds',
		draft: outputs?.funding.offPlanProceedsAed ?? 0,
		local: offPlanProceedsAed,
		basis: 'Backend modeled collections vs local payment-plan estimate'
	},
	{
		label: 'Debt funding',
		draft: outputs?.funding.debtFundingAed ?? 0,
		local: debtFundingAed,
		basis: 'Backend peak debt support vs local input'
	},
	{
		label: 'Equity funding',
		draft: outputs?.funding.equityFundingAed ?? 0,
		local: equityFundingAed,
		basis: 'Backend actual equity contributions vs local input'
	},
	{
		label: 'VAT refunds',
		draft: outputs?.funding.vatRefundsAed ?? 0,
		local: vatRefundsAed,
		basis: 'Backend modeled VAT refund inflows'
	},
	{
		label: 'Total sources',
		draft: outputs?.funding.cashReconSourcesAed ?? 0,
		local: totalSourcesAed,
		basis: 'Backend sources-and-uses'
	},
	{
		label: 'Total uses',
		draft: outputs?.funding.cashReconUsesAed ?? 0,
		local: totalUsesAed,
		basis: 'Backend sources-and-uses'
	},
	{
		label: 'Funding gap',
		draft: outputs?.funding.cashReconGapAed ?? 0,
		local: fundingGap,
		basis: 'Backend sources-and-uses gap'
	}
])
</script>

{#if !outputs}
	<div class="h-full flex items-center justify-center text-sm text-slate-400">
		Generate an HBU study to build the draft returns view.
	</div>
{:else}
	<div class="overflow-auto flex-1 bg-white text-[11px] font-[Calibri,'Segoe_UI',Arial,sans-serif] select-none">

		<!-- Title bar -->
		<div class="bg-[#1F3864] border-b-2 border-[#1F3864] text-white px-4 py-2.5 flex items-center justify-between gap-4">
			<div class="text-[13px] font-bold tracking-wide">RETURNS &amp; BENCHMARKS</div>
			<div class="text-[10px] text-blue-200 shrink-0">Modeled investment returns — AED unless stated</div>
		</div>

		<!-- Summary bar -->
		<div class="flex border-b border-[#B8C4CE] bg-[#EEF2F7] divide-x divide-[#D9D9D9]">
			<div class="px-2 py-1.5 flex-1">
				<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Local Profit</div>
				<div class="text-[11px] font-bold text-slate-900 tabular-nums">AED {fmt(localProfit)}</div>
			</div>
			<div class="px-2 py-1.5 flex-1">
				<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Equity IRR</div>
				<div class="text-[11px] font-bold text-slate-900 tabular-nums">{outputs?.returns.equityIrrPct != null ? fmt(outputs.returns.equityIrrPct, 1) + '%' : 'N/A'}</div>
			</div>
			<div class="px-2 py-1.5 flex-1">
				<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Equity MOIC</div>
				<div class="text-[11px] font-bold text-slate-900 tabular-nums">{outputs?.returns.equityMoic != null ? fmt(outputs.returns.equityMoic, 2) + 'x' : 'N/A'}</div>
			</div>
			<div class="px-2 py-1.5 flex-1">
				<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Funding Gap</div>
				<div class="text-[11px] font-bold {Math.abs(fundingGap) > 1_000_000 ? 'text-amber-700' : 'text-slate-900'} tabular-nums">AED {fmt(fundingGap)}</div>
			</div>
		</div>

		<!-- Section A: Return Checks -->
		<table class="w-full border-collapse" style="border-spacing:0">
			<tbody>
			<tr class="bg-[#1F3864]">
				<td colspan="4" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">A.&nbsp;&nbsp;RETURN CHECKS</td>
			</tr>
			<tr class="bg-[#D6DCE4] border-b border-[#B8C4CE]">
				<th class="px-1 py-[4px] text-center text-[9px] font-semibold text-slate-500 uppercase tracking-wider">#</th>
				<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Metric</th>
				<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Value</th>
				<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Status</th>
			</tr>
			{#each returnChecks as check, idx (check.label)}
				<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
					<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">{idx + 1}</td>
					<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">{check.label}</td>
					<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px] font-semibold">{check.value}</td>
					<td class="px-2 py-[3px] text-right">
						{#if check.status === 'outlier'}
							<span class="inline-block px-2 py-0.5 text-[9px] font-semibold uppercase rounded-sm bg-[#FCE4D6] text-[#843C0C]">{check.status}</span>
						{:else if check.status === 'warning'}
							<span class="inline-block px-2 py-0.5 text-[9px] font-semibold uppercase rounded-sm bg-[#FFF2CC] text-[#7F6000]">{check.status}</span>
						{:else}
							<span class="inline-block px-2 py-0.5 text-[9px] font-semibold uppercase rounded-sm bg-[#E2F0D9] text-[#375623]">{check.status}</span>
						{/if}
					</td>
				</tr>
			{/each}
			</tbody>
		</table>

		<!-- Section B: Returns Summary -->
		<table class="w-full border-collapse" style="border-spacing:0">
			<tbody>
			<tr class="bg-[#1F3864]">
				<td colspan="4" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">B.&nbsp;&nbsp;RETURNS SUMMARY</td>
			</tr>
			<tr class="bg-[#D6DCE4] border-b border-[#B8C4CE]">
				<th class="px-1 py-[4px] text-center text-[9px] font-semibold text-slate-500 uppercase tracking-wider">#</th>
				<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Metric</th>
				<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Value</th>
				<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Note</th>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">a</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-900 font-semibold">Project IRR</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-[10px] font-bold text-emerald-700">
					{outputs?.returns.projectIrrPct != null ? fmt(outputs.returns.projectIrrPct, 1) + '%' : 'N/A'}
				</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Backend timed cash-flow IRR</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">b</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-900 font-semibold">Equity IRR</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-[10px] font-bold text-emerald-700">
					{outputs?.returns.equityIrrPct != null ? fmt(outputs.returns.equityIrrPct, 1) + '%' : 'N/A'}
				</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Sponsor cash flows after debt cleanup</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">c</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">Return on cost</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{fmt(returnOnCostPct, 1)}%</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Workbook outputs</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">d</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">Revenue multiple</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{fmt(revenueMultiple, 2)}x</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Workbook outputs</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">e</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">Draft project MOIC</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{outputs?.returns.projectMoic != null ? fmt(outputs.returns.projectMoic, 2) + 'x' : 'N/A'}</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Backend timed cash-flow multiple</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">f</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">Draft equity MOIC</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{outputs?.returns.equityMoic != null ? fmt(outputs.returns.equityMoic, 2) + 'x' : 'N/A'}</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Sponsor distributions vs equity contributions</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">g</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">All-in profit</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{outputs?.returns.allInProjectProfitAed != null ? 'AED ' + fmt(outputs.returns.allInProjectProfitAed) : 'N/A'}</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Revenue less total project cost including finance carry</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">h</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">All-in margin</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{outputs?.returns.allInMarginPct != null ? fmt(outputs.returns.allInMarginPct, 1) + '%' : 'N/A'}</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">All-in profit as share of gross revenue</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">i</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">Peak debt</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{outputs?.cashFlow.peakFundingAed != null ? 'AED ' + fmt(outputs.cashFlow.peakFundingAed) : 'N/A'}</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Backend monthly financing path</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">j</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">Peak net sponsor capital</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">AED {fmt(peakNetSponsorCapitalAed)}</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Maximum cumulative equity in less distributions out</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">k</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">Interest carry</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{outputs?.returns.totalInterestPaidAed != null ? 'AED ' + fmt(outputs.returns.totalInterestPaidAed) : 'N/A'}</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Capitalized monthly interest across draft debt path</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">l</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">Financing / exit fees</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">
					{outputs?.returns != null ? 'AED ' + fmt((outputs.returns.financingFeeAed ?? 0) + (outputs.returns.exitFeeAed ?? 0)) : 'N/A'}
				</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Upfront financing fee plus handover exit fee</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">m</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">Off-plan proceeds</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">AED {fmt(offPlanProceedsAed)}</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Deposit + pre-handover collections</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">n</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">Debt / equity funding</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">AED {fmt(debtFundingAed)} / {fmt(equityFundingAed)}</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Workbook funding inputs</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">o</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">Break-even Sale Rate</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{outputs?.returns.breakEvenSaleRateAedSqft != null ? fmt(outputs.returns.breakEvenSaleRateAedSqft) + ' AED/sqft' : 'N/A'}</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Total cost / sellable area</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">p</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">Levered Margin on Equity</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{outputs?.returns.leveredMarginOnEquityPct != null ? fmt(outputs.returns.leveredMarginOnEquityPct, 1) + '%' : 'N/A'}</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Levered profit / total equity</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">q</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">Debt as % of Cost</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-emerald-700 text-[10px]">{outputs?.returns.debtAsPctOfCost != null ? fmt(outputs.returns.debtAsPctOfCost, 1) + '%' : 'N/A'}</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Peak debt / total cost</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">r</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">Average Debt Outstanding</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-emerald-700 text-[10px]">{outputs?.returns.averageDebtOutstandingAed != null ? 'AED ' + fmt(outputs.returns.averageDebtOutstandingAed) : 'N/A'}</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Time-weighted average</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">s</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">Financing Fee</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-emerald-700 text-[10px]">{outputs?.returns.financingFeeAed != null ? 'AED ' + fmt(outputs.returns.financingFeeAed) : 'N/A'}</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">1% of total debt commitment</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">t</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">Exit Fee</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-emerald-700 text-[10px]">{outputs?.returns.exitFeeAed != null ? 'AED ' + fmt(outputs.returns.exitFeeAed) : 'N/A'}</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">1% of opening debt at handover</td>
			</tr>
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">u</td>
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800 font-semibold">Total Financing Costs</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-emerald-700 text-[10px] font-bold">{outputs?.returns.totalFinancingCostsAed != null ? 'AED ' + fmt(outputs.returns.totalFinancingCostsAed) : 'N/A'}</td>
				<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Interest + fees</td>
			</tr>
			</tbody>
		</table>

		<!-- Section C: Draft vs Local Reconciliation -->
		<table class="w-full border-collapse" style="border-spacing:0">
			<tbody>
			<tr class="bg-[#1F3864]">
				<td colspan="4" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">C.&nbsp;&nbsp;DRAFT vs LOCAL RECONCILIATION</td>
			</tr>
			<tr class="bg-[#D6DCE4] border-b border-[#B8C4CE]">
				<th class="px-1 py-[4px] text-center text-[9px] font-semibold text-slate-500 uppercase tracking-wider"></th>
				<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Metric</th>
				<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Draft / Local</th>
				<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Gap</th>
			</tr>
			{#each reconciliationRows as row (row.label)}
				{@const localValue = row.local ?? 0}
				{@const gap = localValue - row.draft}
				{@const isMaterial = Math.abs(gap) > (row.suffix === '%' ? 5 : row.suffix === 'x' ? 0.25 : 1_000_000)}
				<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
					<td></td>
					<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">{row.label}</td>
					<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">
						{#if row.suffix === '%'}{fmt(row.draft, 1)}% / {fmt(localValue, 1)}%{:else if row.suffix === 'x'}{fmt(row.draft, 2)}x / {fmt(localValue, 2)}x{:else}AED {fmt(row.draft)} / {fmt(localValue)}{/if}
					</td>
					<td class="px-2 py-[3px] text-right tabular-nums text-[10px] font-semibold {isMaterial ? 'text-amber-700' : 'text-slate-600'}">
						{#if row.suffix === '%'}{fmt(gap, 1)} pts{:else if row.suffix === 'x'}{fmt(gap, 2)}x{:else}AED {fmt(gap)}{/if}
					</td>
				</tr>
			{/each}
			</tbody>
		</table>

		<!-- Section D: Sensitivity Scenarios (optional) -->
		{#if draftSensitivities.length}
			<table class="w-full border-collapse" style="border-spacing:0">
				<thead>
				<tr class="bg-[#1F3864]">
					<td colspan="7" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">D.&nbsp;&nbsp;SENSITIVITY SCENARIOS</td>
				</tr>
				<tr class="bg-[#D6DCE4] border-b border-[#B8C4CE]">
					<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Scenario</th>
					<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Change</th>
					<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Project IRR</th>
					<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Equity IRR</th>
					<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">All-in Margin</th>
					<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Peak Debt</th>
					<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Finance Carry</th>
				</tr>
				</thead>
				<tbody>
				{#each draftSensitivities as scenario (scenario.code)}
					<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
						<td class="px-2 py-[3px] text-left text-[10px] text-slate-800 font-semibold">{scenario.label}</td>
						<td class="pl-6 pr-2 py-[3px] text-left text-[9px] text-slate-500 italic">{scenario.changeNote}</td>
						<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{scenario.projectIrrPct != null ? fmt(scenario.projectIrrPct, 1) + '%' : 'N/A'}</td>
						<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{scenario.equityIrrPct != null ? fmt(scenario.equityIrrPct, 1) + '%' : 'N/A'}</td>
						<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{scenario.allInMarginPct != null ? fmt(scenario.allInMarginPct, 1) + '%' : 'N/A'}</td>
						<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{scenario.peakDebtAed != null ? 'AED ' + fmt(scenario.peakDebtAed) : 'N/A'}</td>
						<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{scenario.totalFinanceCostsAed != null ? 'AED ' + fmt(scenario.totalFinanceCostsAed) : 'N/A'}</td>
					</tr>
				{/each}
				</tbody>
			</table>
		{/if}

		<!-- Section E: Sources & Uses (optional) -->
		{#if outputs}
			<table class="w-full border-collapse" style="border-spacing:0">
				<thead>
				<tr class="bg-[#1F3864]">
					<td colspan="4" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">{draftSensitivities.length ? 'E.' : 'D.'}&nbsp;&nbsp;SOURCES &amp; USES</td>
				</tr>
				<tr class="bg-[#D6DCE4] border-b border-[#B8C4CE]">
					<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Category</th>
					<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Line Item</th>
					<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Draft / Local</th>
					<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Basis</th>
				</tr>
				</thead>
				<tbody>
				{#each sourcesUsesRows as row (row.label)}
					<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
						<td class="px-2 py-[3px] text-left text-[10px] text-slate-500 italic"></td>
						<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">{row.label}</td>
						<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">AED {fmt(row.draft)} / {fmt(row.local)}</td>
						<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">{row.basis}</td>
					</tr>
				{/each}
				</tbody>
			</table>
		{/if}

		<div class="py-3"></div>
	</div>
{/if}
