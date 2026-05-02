<script lang="ts">
import { workbookStore } from '$lib/feasibility/workbook/store.svelte'

function fmt(value: number | null | undefined, digits = 0) {
	if (value === null || value === undefined || !Number.isFinite(value)) return '—'
	return value.toLocaleString('en-AE', {
		minimumFractionDigits: digits,
		maximumFractionDigits: digits
	})
}

function fmtPct(value: number | null | undefined, digits = 1) {
	if (value === null || value === undefined || !Number.isFinite(value)) return '—'
	return `${fmt(value, digits)}%`
}

const outputs = $derived(workbookStore.outputs)
const assumptions = $derived(workbookStore.assumptions)
const isBtr = $derived(assumptions?.developmentModel === 'build_to_rent_residential')
const btr = $derived(outputs?.btr)

const XREF = 'text-emerald-700'

type KpiRow = { label: string; value: string; color?: string }

// ── BTS KPIs ──
const btsKpiRows = $derived<KpiRow[]>(
	!isBtr && outputs
		? [
				{
					label: 'GDV (Revenue)',
					value: `AED ${fmt(outputs.program.grossRevenueAed)}`,
					color: XREF
				},
				{
					label: 'Total Dev Cost (excl. VAT)',
					value: `AED ${fmt(outputs.costs.totalDevCostExclVatAed)}`,
					color: XREF
				},
				{
					label: 'Total Project Cost (incl. VAT)',
					value: `AED ${fmt(outputs.costs.totalDevCostInclVatAed)}`,
					color: XREF
				},
				{ label: 'Gross Profit', value: `AED ${fmt(outputs.returns.grossProfitAed)}`, color: XREF },
				{
					label: 'Gross Margin on GDV',
					value: fmtPct(outputs.returns.grossMarginPct),
					color: XREF
				},
				{
					label: 'Unlevered IRR',
					value:
						outputs.returns.projectIrrPct != null ? fmtPct(outputs.returns.projectIrrPct) : 'N/A',
					color: XREF
				},
				{
					label: 'Levered IRR (Equity)',
					value:
						outputs.returns.equityIrrPct != null ? fmtPct(outputs.returns.equityIrrPct) : 'N/A',
					color: XREF
				},
				{
					label: 'Equity Multiple (MOIC)',
					value: `${fmt(outputs.returns.equityMoic, 2)}x`,
					color: XREF
				},
				{ label: 'Peak Debt', value: `AED ${fmt(outputs.returns.peakDebtAed)}`, color: XREF },
				{ label: 'Peak Equity', value: `AED ${fmt(outputs.returns.peakEquityAed)}`, color: XREF },
				{ label: 'Debt as % of Cost', value: fmtPct(outputs.returns.debtAsPctOfCost), color: XREF },
				{
					label: 'Levered Margin on Equity',
					value: fmtPct(outputs.returns.leveredMarginOnEquityPct),
					color: XREF
				},
				{
					label: 'Break-even Sale Rate',
					value: `AED ${fmt(outputs.returns.breakEvenSaleRateAedSqft)} /sqft`,
					color: XREF
				},
				{ label: 'Total Units', value: fmt(outputs.program.totalUnits), color: XREF },
				{ label: 'Sellable Area (sqm)', value: fmt(outputs.area.sellableArea), color: XREF },
				{ label: 'Costable BUA (sqm)', value: fmt(outputs.area.totalCostableBua), color: XREF }
			]
		: []
)

// ── BTR KPIs ──
const btrKpiRows = $derived<KpiRow[]>(
	isBtr && btr
		? [
				{ label: 'Stabilized NOI', value: `AED ${fmt(btr.returns.stabilizedNoiAed)}`, color: XREF },
				{ label: 'Dev Yield (NOI / Cost)', value: fmtPct(btr.exit.devYieldPct), color: XREF },
				{ label: 'Gross Yield', value: fmtPct(btr.exit.grossYieldPct), color: XREF },
				{ label: 'Net Yield', value: fmtPct(btr.exit.netYieldPct), color: XREF },
				{
					label: 'Unlevered IRR',
					value: btr.returns.unleveredIrrPct != null ? fmtPct(btr.returns.unleveredIrrPct) : 'N/A',
					color: XREF
				},
				{
					label: 'Levered IRR',
					value: btr.returns.leveredIrrPct != null ? fmtPct(btr.returns.leveredIrrPct) : 'N/A',
					color: XREF
				},
				{
					label: 'Equity Multiple (MOIC)',
					value: `${fmt(btr.returns.leveredMoic, 2)}x`,
					color: XREF
				},
				{
					label: 'Unlevered Multiple',
					value: `${fmt(btr.returns.unleveredMoic, 2)}x`,
					color: XREF
				},
				{
					label: 'Total Dev Cost',
					value: `AED ${fmt(btr.devCosts.totalDevCostInclVatAed)}`,
					color: XREF
				},
				{
					label: 'Total Project Cost',
					value: `AED ${fmt(btr.returns.totalProjectCostAed)}`,
					color: XREF
				},
				{
					label: 'Dev Debt Funded',
					value: `AED ${fmt(btr.returns.devDebtFundedAed)}`,
					color: XREF
				},
				{
					label: 'Dev Equity Required',
					value: `AED ${fmt(btr.returns.devEquityFundedAed)}`,
					color: XREF
				},
				{
					label: 'Perm Debt (Refi)',
					value: `AED ${fmt(btr.permDebt.actualPermDebtAed)}`,
					color: XREF
				},
				{
					label: 'DSCR at Origination',
					value: `${fmt(btr.permDebt.dscrAtOrigination, 2)}x`,
					color: XREF
				},
				{ label: 'Exit Cap Rate', value: fmtPct(btr.exit.exitCapRatePct), color: XREF },
				{
					label: 'Terminal Sale Value',
					value: `AED ${fmt(btr.exit.grossSalePriceAed)}`,
					color: XREF
				},
				{ label: 'Total Profit', value: `AED ${fmt(btr.returns.totalProfitAed)}`, color: XREF },
				{ label: 'Total Units', value: fmt(btr.program.totalUnits), color: XREF },
				{ label: 'Total Leasable Area (sqm)', value: fmt(btr.program.totalAreaSqm), color: XREF },
				{ label: 'Dev Spread (bps)', value: fmt(btr.exit.developmentSpreadBps), color: XREF }
			]
		: []
)

const kpiRows = $derived(isBtr ? btrKpiRows : btsKpiRows)

const projectInfo = $derived([
	{ label: 'Plot Number', value: assumptions?.plotNumber ?? '—' },
	{ label: 'Community', value: assumptions?.communityName ?? '—' },
	{ label: 'Project', value: assumptions?.projectName ?? '—' },
	{ label: 'Usage', value: assumptions?.usage ?? '—' },
	{ label: 'Model', value: isBtr ? 'Build-to-Rent' : 'Build-to-Sell' },
	{ label: 'Land Acquisition', value: assumptions?.landAcquisitionDate ?? '—' },
	{ label: 'Handover', value: assumptions?.handoverDate ?? '—' },
	...(isBtr
		? [{ label: 'Hold Period', value: `${assumptions?.btrHoldPeriodYears ?? 10} years` }]
		: [])
])
</script>

{#if !outputs}
<div class="h-full flex items-center justify-center px-6 text-sm text-slate-400">
	Generate an HBU study to view the summary dashboard.
</div>
{:else}
<div class="overflow-auto flex-1 bg-white text-[11px] font-[Calibri,'Segoe_UI',Arial,sans-serif] select-none">

	<!-- Title bar -->
	<div class="bg-[#1F3864] border-b-2 border-[#1F3864] text-white px-4 py-2.5 flex items-center justify-between gap-4">
		<div class="text-[13px] font-bold tracking-wide">EXECUTIVE SUMMARY</div>
		<div class="text-[10px] text-blue-200 shrink-0">{isBtr ? 'Build-to-Rent' : 'Build-to-Sell'}</div>
	</div>

	<!-- Project info row -->
	<div class="flex border-b border-[#B8C4CE] bg-[#EEF2F7] divide-x divide-[#D9D9D9]">
		{#each projectInfo as item (item.label)}
			<div class="px-2 py-1.5 min-w-0">
				<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold truncate">{item.label}</div>
				<div class="text-[11px] font-medium text-slate-900 tabular-nums truncate">{item.value}</div>
			</div>
		{/each}
	</div>

	<!-- KPI table -->
	<table class="w-full border-collapse" style="border-spacing:0">
		<tbody>
		<tr class="bg-[#1F3864]">
			<td colspan="2" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">KEY PERFORMANCE INDICATORS</td>
		</tr>
		<tr class="bg-[#D6DCE4] border-b border-[#B8C4CE]">
			<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Metric</th>
			<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Value</th>
		</tr>
		{#each kpiRows as kpi (kpi.label)}
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">{kpi.label}</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-[10px] font-medium {kpi.color ?? 'text-slate-900'}">{kpi.value}</td>
			</tr>
		{/each}
		</tbody>
	</table>

	{#if isBtr && btr}
	<!-- BTR Financing Summary -->
	<table class="w-full border-collapse" style="border-spacing:0">
		<tbody>
		<tr class="bg-[#1F3864]">
			<td colspan="2" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">DEVELOPMENT &amp; PERMANENT FINANCING</td>
		</tr>
		{#each [
			{ label: 'Dev Debt (LTC)', value: `AED ${fmt(btr.returns.devDebtFundedAed)}` },
			{ label: 'Dev Equity', value: `AED ${fmt(btr.returns.devEquityFundedAed)}` },
			{ label: 'Dev Interest Reserve', value: `AED ${fmt(btr.returns.devInterestReserveAed)}` },
			{ label: 'Permanent Loan (Refi)', value: `AED ${fmt(btr.permDebt.actualPermDebtAed)}`, bold: true },
			{ label: 'Refi Points/Fees', value: `AED ${fmt(btr.permDebt.refiPointsCostAed)}` },
			{ label: 'Net Refi Proceeds', value: `AED ${fmt(btr.permDebt.refiProceedsAed)}`, neg: btr.permDebt.refiProceedsAed < 0 },
			{ label: 'Annual Debt Service', value: `AED ${fmt(btr.permDebt.annualDebtServiceAed)}` },
			{ label: 'Loan Payoff at Exit', value: `AED ${fmt(btr.permDebt.loanPayoffAed)}` }
		] as row (row.label)}
			<tr class="border-b border-[#D9D9D9] {row.bold ? 'bg-[#EEF2F7] font-semibold' : ''} hover:bg-slate-50/60">
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">{row.label}</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-[10px] font-medium {row.neg ? 'text-rose-600' : 'text-emerald-700'}">{row.value}</td>
			</tr>
		{/each}
		</tbody>
	</table>
	{:else}
	<!-- BTS Financing summary -->
	<table class="w-full border-collapse" style="border-spacing:0">
		<tbody>
		<tr class="bg-[#1F3864]">
			<td colspan="2" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">FINANCING SUMMARY</td>
		</tr>
		{#each [
			{ label: 'Total Financing Costs', value: `AED ${fmt(outputs.returns.totalFinancingCostsAed)}` },
			{ label: 'Financing Fee', value: `AED ${fmt(outputs.returns.financingFeeAed)}` },
			{ label: 'Exit Fee', value: `AED ${fmt(outputs.returns.exitFeeAed)}` },
			{ label: 'Total Interest Paid', value: `AED ${fmt(outputs.returns.totalInterestPaidAed)}` },
			{ label: 'Average Debt Outstanding', value: `AED ${fmt(outputs.returns.averageDebtOutstandingAed)}` }
		] as row (row.label)}
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">{row.label}</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-[10px] font-medium text-emerald-700">{row.value}</td>
			</tr>
		{/each}
		</tbody>
	</table>

	<!-- BTS Waterfall summary -->
	{#if outputs.waterfall}
	<table class="w-full border-collapse" style="border-spacing:0">
		<tbody>
		<tr class="bg-[#1F3864]">
			<td colspan="2" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">EQUITY WATERFALL</td>
		</tr>
		{#each [
			{ label: 'Return of Capital', value: `AED ${fmt(outputs.waterfall.returnOfCapital)}` },
			{ label: 'Preferred Return Paid', value: `AED ${fmt(outputs.waterfall.preferredReturnPaid)}` },
			{ label: 'Residual to Equity', value: `AED ${fmt(outputs.waterfall.residualToEquity)}` },
			{ label: 'Sponsor Promote', value: `AED ${fmt(outputs.waterfall.sponsorPromote)}` }
		] as row (row.label)}
			<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
				<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">{row.label}</td>
				<td class="px-2 py-[3px] text-right tabular-nums text-[10px] font-medium text-emerald-700">{row.value}</td>
			</tr>
		{/each}
		</tbody>
	</table>
	{/if}
	{/if}

	<div class="py-3"></div>
</div>
{/if}
