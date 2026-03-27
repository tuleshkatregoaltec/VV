<script lang="ts">
import type { CashFlowPeriod } from '$lib/feasibility/workbook/engine'
import { workbookStore } from '$lib/feasibility/workbook/store.svelte'

const periods = $derived(workbookStore.workbook?.cashFlow?.periods ?? ([] as CashFlowPeriod[]))

type NumericPeriodField =
	| 'revenueInflowsAed'
	| 'operatingOutflowsAed'
	| 'debtDrawAed'
	| 'debtRepaymentAed'
	| 'interestPaidAed'
	| 'commitmentFeePaidAed'
	| 'equityContributionAed'
	| 'equityDistributionAed'
	| 'debtBalanceAed'
	| 'landLoanBalanceAed'
	| 'constructionLoanBalanceAed'
	| 'escrowBalanceAed'
	| 'unleveredNetCashFlowAed'
	| 'leveredNetCashFlowAed'
	| 'depositInflowsAed'
	| 'preHandoverInflowsAed'
	| 'handoverInflowsAed'
	| 'costLandAed'
	| 'costConstructionAed'
	| 'costProfessionalFeesAed'
	| 'costMarketingAed'
	| 'costSalesAgentAed'
	| 'costInfrastructureAed'
	| 'costAuthorityFeesAed'
	| 'costCommunityFeesAed'
	| 'costContingencyAed'
	| 'costVatAed'
	| 'vatRefundInflowsAed'

type CostBreakdownRow = { field: NumericPeriodField; label: string }
type FinancingRow = { field: NumericPeriodField; label: string; isOut: boolean }
type BalanceRow = { field: NumericPeriodField; label: string }

function fmt(v: number): string {
	if (v === 0) return '—'
	return Math.abs(Math.round(v)).toLocaleString('en-AE')
}

function fmtOut(v: number): string {
	if (v === 0) return '—'
	return '(' + Math.round(v).toLocaleString('en-AE') + ')'
}

function periodValue(period: CashFlowPeriod, field: NumericPeriodField): number {
	return Number(period[field] ?? 0)
}

function sum(field: NumericPeriodField): number {
	return periods.reduce((s, p) => s + periodValue(p, field), 0)
}

function hasPositive(field: NumericPeriodField): boolean {
	return periods.some((p) => periodValue(p, field) > 0)
}

const TH =
	'px-2 py-[4px] text-right text-[9px] font-semibold text-slate-500 whitespace-nowrap min-w-[70px]'
const TH_L =
	'px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 sticky left-0 bg-white z-20 min-w-[160px] whitespace-nowrap border-r border-slate-200'
const TD = 'px-2 py-[3px] text-right text-[10px] tabular-nums text-slate-600 whitespace-nowrap'
const TD_OUT = 'px-2 py-[3px] text-right text-[10px] tabular-nums text-amber-700 whitespace-nowrap'
const TD_NET = 'px-2 py-[3px] text-right text-[10px] tabular-nums font-semibold whitespace-nowrap'
const TD_TOT =
	'px-2 py-[3px] text-right text-[10px] tabular-nums font-semibold text-slate-800 bg-slate-50 whitespace-nowrap'
const TD_L =
	'px-2 py-[3px] text-left text-[10px] text-slate-700 sticky left-0 bg-white z-10 border-r border-slate-200 whitespace-nowrap'
const TD_L_SUB =
	'pl-5 pr-2 py-[2px] text-left text-[9px] text-slate-400 sticky left-0 bg-white z-10 border-r border-slate-200 whitespace-nowrap italic'
const TD_L_HDR =
	'px-2 py-[4px] text-left text-[10px] font-bold text-white sticky left-0 z-10 border-r border-slate-200 whitespace-nowrap'
const HDR_ROW = 'bg-[#1F3864]'
const SUB_ROW = 'border-t border-slate-100 bg-slate-50/40'
const DATA_ROW = 'border-t border-slate-100 hover:bg-slate-50/60'
const TOTAL_ROW = 'border-t-2 border-[#1F3864] border-b border-slate-200'

const totUnlevered = $derived(sum('unleveredNetCashFlowAed'))
const totLevered = $derived(sum('leveredNetCashFlowAed'))
const costBreakdownRows: CostBreakdownRow[] = [
	{ field: 'costLandAed', label: 'Land' },
	{ field: 'costConstructionAed', label: 'Construction' },
	{ field: 'costProfessionalFeesAed', label: 'Design & supervision' },
	{ field: 'costMarketingAed', label: 'Marketing' },
	{ field: 'costSalesAgentAed', label: 'Sales agent fees' },
	{ field: 'costInfrastructureAed', label: 'Infrastructure' },
	{ field: 'costAuthorityFeesAed', label: 'Authority fees' },
	{ field: 'costCommunityFeesAed', label: 'Community fees' },
	{ field: 'costContingencyAed', label: 'Contingency' },
	{ field: 'costVatAed', label: 'VAT' }
]
const financingRows: FinancingRow[] = [
	{ field: 'debtDrawAed', label: 'Debt draw', isOut: false },
	{ field: 'debtRepaymentAed', label: 'Debt repayment', isOut: true },
	{ field: 'interestPaidAed', label: 'Interest', isOut: true },
	{ field: 'commitmentFeePaidAed', label: 'Commitment fee', isOut: true },
	{ field: 'equityContributionAed', label: 'Equity contribution', isOut: true },
	{ field: 'equityDistributionAed', label: 'Equity distribution', isOut: false }
]
const balanceRows: BalanceRow[] = [
	{ field: 'debtBalanceAed', label: 'Total debt balance' },
	{ field: 'landLoanBalanceAed', label: 'Land loan balance' },
	{ field: 'constructionLoanBalanceAed', label: 'Construction loan balance' },
	{ field: 'escrowBalanceAed', label: 'Escrow balance' }
]
</script>

{#if periods.length === 0}
	<div class="h-full flex items-center justify-center text-sm text-slate-400">
		Run the model to generate monthly cash flows.
	</div>
{:else}
	<div class="h-full overflow-auto text-[10px] font-[Calibri,'Segoe_UI',Arial,sans-serif]">
		<table class="border-collapse" style="border-spacing:0">
			<thead class="sticky top-0 z-30">
				<tr class="border-b-2 border-slate-300 bg-white shadow-sm">
					<th class="{TH_L} bg-slate-50">Line Item</th>
					{#each periods as p}
						<th class={TH}>{p.periodLabel}</th>
					{/each}
					<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-700 bg-slate-100 whitespace-nowrap sticky right-0 z-20 border-l border-slate-300">Total</th>
				</tr>
			</thead>
			<tbody>

			<!-- REVENUE -->
			<tr class={HDR_ROW}>
				<td class="{TD_L_HDR} bg-[#1F3864]">REVENUE INFLOWS</td>
				{#each periods as _}<td class="bg-[#1F3864] min-w-[70px]"></td>{/each}
				<td class="bg-[#1F3864] sticky right-0 border-l border-[#2D4D7A] min-w-[80px]"></td>
			</tr>
			<tr class={DATA_ROW}>
				<td class={TD_L}>Gross sales receipts</td>
				{#each periods as p}<td class={TD}>{fmt(p.revenueInflowsAed)}</td>{/each}
				<td class="{TD_TOT} sticky right-0 border-l border-slate-300">{fmt(sum('revenueInflowsAed'))}</td>
			</tr>
			{#if periods.some(p => p.depositInflowsAed > 0)}
			<tr class={SUB_ROW}>
				<td class={TD_L_SUB}>↳ Deposits</td>
				{#each periods as p}<td class="{TD} text-slate-400">{fmt(p.depositInflowsAed)}</td>{/each}
				<td class="px-2 py-[3px] text-right text-[9px] tabular-nums text-slate-400 bg-slate-50 sticky right-0 border-l border-slate-300">{fmt(sum('depositInflowsAed'))}</td>
			</tr>
			{/if}
			{#if periods.some(p => p.preHandoverInflowsAed > 0)}
			<tr class={SUB_ROW}>
				<td class={TD_L_SUB}>↳ Pre-handover</td>
				{#each periods as p}<td class="{TD} text-slate-400">{fmt(p.preHandoverInflowsAed)}</td>{/each}
				<td class="px-2 py-[3px] text-right text-[9px] tabular-nums text-slate-400 bg-slate-50 sticky right-0 border-l border-slate-300">{fmt(sum('preHandoverInflowsAed'))}</td>
			</tr>
			{/if}
			{#if periods.some(p => p.handoverInflowsAed > 0)}
			<tr class={SUB_ROW}>
				<td class={TD_L_SUB}>↳ At handover</td>
				{#each periods as p}<td class="{TD} text-slate-400">{fmt(p.handoverInflowsAed)}</td>{/each}
				<td class="px-2 py-[3px] text-right text-[9px] tabular-nums text-slate-400 bg-slate-50 sticky right-0 border-l border-slate-300">{fmt(sum('handoverInflowsAed'))}</td>
			</tr>
			{/if}
			{#if periods.some(p => (p.vatRefundInflowsAed ?? 0) > 0)}
			<tr class={DATA_ROW}>
				<td class={TD_L}>VAT refund</td>
				{#each periods as p}<td class={TD}>{fmt(p.vatRefundInflowsAed ?? 0)}</td>{/each}
				<td class="{TD_TOT} sticky right-0 border-l border-slate-300">{fmt(sum('vatRefundInflowsAed'))}</td>
			</tr>
			{/if}

			<!-- OPERATING OUTFLOWS -->
			<tr class={HDR_ROW}>
				<td class="{TD_L_HDR} bg-[#1F3864]">OPERATING OUTFLOWS</td>
				{#each periods as _}<td class="bg-[#1F3864] min-w-[70px]"></td>{/each}
				<td class="bg-[#1F3864] sticky right-0 border-l border-[#2D4D7A] min-w-[80px]"></td>
			</tr>
			<tr class={TOTAL_ROW}>
				<td class={TD_L}>Total operating outflows</td>
				{#each periods as p}<td class={TD_OUT}>{p.operatingOutflowsAed > 0 ? fmtOut(p.operatingOutflowsAed) : '—'}</td>{/each}
				<td class="px-2 py-[3px] text-right text-[10px] tabular-nums font-semibold text-amber-700 bg-slate-50 sticky right-0 border-l border-slate-300">{fmtOut(sum('operatingOutflowsAed'))}</td>
			</tr>
			{#each costBreakdownRows as row (row.field)}
				{#if hasPositive(row.field)}
				<tr class={SUB_ROW}>
					<td class={TD_L_SUB}>↳ {row.label}</td>
					{#each periods as p}<td class="{TD} text-slate-400">{periodValue(p, row.field) > 0 ? fmtOut(periodValue(p, row.field)) : '—'}</td>{/each}
					<td class="px-2 py-[3px] text-right text-[9px] tabular-nums text-slate-400 bg-slate-50 sticky right-0 border-l border-slate-300">{fmtOut(sum(row.field))}</td>
				</tr>
				{/if}
			{/each}

			<!-- UNLEVERED NET CF -->
			<tr class="border-t-2 border-[#1F3864] bg-[#E8F0FE]">
				<td class="px-2 py-[4px] text-left text-[10px] font-bold text-slate-900 sticky left-0 bg-[#E8F0FE] z-10 border-r border-slate-200 whitespace-nowrap">UNLEVERED NET CASH FLOW</td>
				{#each periods as p}
					<td class="px-2 py-[4px] text-right text-[10px] tabular-nums font-semibold whitespace-nowrap {p.unleveredNetCashFlowAed < 0 ? 'text-rose-600' : 'text-emerald-700'}">
						{p.unleveredNetCashFlowAed < 0 ? fmtOut(Math.abs(p.unleveredNetCashFlowAed)) : fmt(p.unleveredNetCashFlowAed)}
					</td>
				{/each}
			<td class="px-2 py-[4px] text-right text-[10px] tabular-nums font-bold sticky right-0 border-l border-slate-300 bg-slate-100 {totUnlevered < 0 ? 'text-rose-600' : 'text-emerald-700'}">
				{totUnlevered < 0 ? fmtOut(Math.abs(totUnlevered)) : fmt(totUnlevered)}
				</td>
			</tr>

			<!-- FINANCING -->
			<tr class={HDR_ROW}>
				<td class="{TD_L_HDR} bg-[#1F3864]">FINANCING</td>
				{#each periods as _}<td class="bg-[#1F3864] min-w-[70px]"></td>{/each}
				<td class="bg-[#1F3864] sticky right-0 border-l border-[#2D4D7A] min-w-[80px]"></td>
			</tr>
			{#each financingRows as row (row.field)}
				{#if hasPositive(row.field)}
				<tr class={DATA_ROW}>
					<td class={TD_L}>{row.label}</td>
					{#each periods as p}
						<td class={row.isOut ? TD_OUT : TD}>{periodValue(p, row.field) > 0 ? (row.isOut ? fmtOut(periodValue(p, row.field)) : fmt(periodValue(p, row.field))) : '—'}</td>
					{/each}
					<td class="{TD_TOT} sticky right-0 border-l border-slate-300 {row.isOut ? 'text-amber-700' : ''}">
						{sum(row.field) > 0 ? (row.isOut ? fmtOut(sum(row.field)) : fmt(sum(row.field))) : '—'}
					</td>
				</tr>
				{/if}
			{/each}
			<!-- Levered net CF -->
			<tr class="border-t-2 border-[#1F3864] bg-[#E8F0FE]">
				<td class="px-2 py-[4px] text-left text-[10px] font-bold text-slate-900 sticky left-0 bg-[#E8F0FE] z-10 border-r border-slate-200 whitespace-nowrap">LEVERED (EQUITY) NET CASH FLOW</td>
				{#each periods as p}
					<td class="px-2 py-[4px] text-right text-[10px] tabular-nums font-semibold whitespace-nowrap {p.leveredNetCashFlowAed < 0 ? 'text-rose-600' : p.leveredNetCashFlowAed > 0 ? 'text-emerald-700' : 'text-slate-400'}">
						{p.leveredNetCashFlowAed < 0 ? fmtOut(Math.abs(p.leveredNetCashFlowAed)) : fmt(p.leveredNetCashFlowAed)}
					</td>
				{/each}
			<td class="px-2 py-[4px] text-right text-[10px] tabular-nums font-bold sticky right-0 border-l border-slate-300 bg-slate-100 {totLevered < 0 ? 'text-rose-600' : 'text-emerald-700'}">
				{totLevered < 0 ? fmtOut(Math.abs(totLevered)) : fmt(totLevered)}
				</td>
			</tr>

			<!-- CLOSING BALANCES -->
			<tr class={HDR_ROW}>
				<td class="{TD_L_HDR} bg-[#1F3864]">CLOSING BALANCES</td>
				{#each periods as _}<td class="bg-[#1F3864] min-w-[70px]"></td>{/each}
				<td class="bg-[#1F3864] sticky right-0 border-l border-[#2D4D7A] min-w-[80px]"></td>
			</tr>
			{#each balanceRows as row (row.field)}
			<tr class={DATA_ROW}>
				<td class={TD_L}>{row.label}</td>
				{#each periods as p}<td class={TD}>{fmt(periodValue(p, row.field))}</td>{/each}
				<td class="{TD_TOT} sticky right-0 border-l border-slate-300 text-slate-400 text-[9px] italic">closing</td>
			</tr>
			{/each}

			<tr><td colspan={periods.length + 2} class="py-3"></td></tr>
			</tbody>
		</table>
	</div>
{/if}
