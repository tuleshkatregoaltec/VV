<script lang="ts">
import { workbookStore } from '$lib/feasibility/workbook/store.svelte'

function fmt(value: number, digits = 0): string {
	return value.toLocaleString('en-AE', {
		minimumFractionDigits: digits,
		maximumFractionDigits: digits
	})
}

function fmtPct(value: number | null | undefined): string {
	if (value == null) return '—'
	return value.toFixed(1) + '%'
}

function fmtMoic(value: number | null | undefined): string {
	if (value == null) return '—'
	return value.toFixed(2) + 'x'
}

type AnnualRow = {
	year: number
	revenueInflowsAed: number
	depositInflowsAed: number
	preHandoverInflowsAed: number
	handoverInflowsAed: number
	operatingOutflowsAed: number
	costLandAed: number
	costConstructionAed: number
	costProfessionalFeesAed: number
	costMarketingAed: number
	costSalesAgentAed: number
	costInfrastructureAed: number
	costAuthorityFeesAed: number
	costCommunityFeesAed: number
	costContingencyAed: number
	costVatAed: number
	unleveredNetCashFlowAed: number
	debtDrawAed: number
	debtRepaymentAed: number
	interestPaidAed: number
	commitmentFeePaidAed: number
	equityContributionAed: number
	equityDistributionAed: number
	leveredNetCashFlowAed: number
	// per-period draw breakdown
	landDrawAed: number
	constructionDrawAed: number
	// sales proceeds that funded costs (shows presales coverage of construction)
	costPaidFromEscrowAed: number
	// VAT refund inflow (non-zero in handover year)
	vatRefundInflowsAed: number
	// year-end closing balances (last period of that year)
	debtBalanceAed: number
	landLoanBalanceAed: number
	constructionLoanBalanceAed: number
	escrowBalanceAed: number
}

const draftCashFlow = $derived(workbookStore.workbook?.cashFlow ?? null)
const returns = $derived(workbookStore.workbook?.returns ?? null)

const hasBreakdown = $derived(
	(draftCashFlow?.periods ?? []).some(
		(p) => p.depositInflowsAed !== 0 || p.preHandoverInflowsAed !== 0 || p.handoverInflowsAed !== 0
	)
)

const hasTranche = $derived(
	(draftCashFlow?.periods ?? []).some(
		(p) => p.landLoanBalanceAed !== 0 || p.constructionLoanBalanceAed !== 0
	)
)

const annualRows: AnnualRow[] = $derived(
	(() => {
		if (!draftCashFlow) return []
		const byYear = new Map<number, AnnualRow>()
		for (const p of draftCashFlow.periods) {
			const year = parseInt(p.periodEndDate.slice(0, 4), 10)
			if (!byYear.has(year)) {
				byYear.set(year, {
					year,
					revenueInflowsAed: 0,
					depositInflowsAed: 0,
					preHandoverInflowsAed: 0,
					handoverInflowsAed: 0,
					operatingOutflowsAed: 0,
					costLandAed: 0,
					costConstructionAed: 0,
					costProfessionalFeesAed: 0,
					costMarketingAed: 0,
					costSalesAgentAed: 0,
					costInfrastructureAed: 0,
					costAuthorityFeesAed: 0,
					costCommunityFeesAed: 0,
					costContingencyAed: 0,
					costVatAed: 0,
					unleveredNetCashFlowAed: 0,
					debtDrawAed: 0,
					debtRepaymentAed: 0,
					interestPaidAed: 0,
					commitmentFeePaidAed: 0,
					equityContributionAed: 0,
					equityDistributionAed: 0,
					leveredNetCashFlowAed: 0,
					landDrawAed: 0,
					constructionDrawAed: 0,
					costPaidFromEscrowAed: 0,
					vatRefundInflowsAed: 0,
					// balances overwritten each period (year-end closing = last period's value)
					debtBalanceAed: 0,
					landLoanBalanceAed: 0,
					constructionLoanBalanceAed: 0,
					escrowBalanceAed: 0
				})
			}
			const row = byYear.get(year)!
			// flow rows: sum
			row.revenueInflowsAed += p.revenueInflowsAed
			row.depositInflowsAed += p.depositInflowsAed
			row.preHandoverInflowsAed += p.preHandoverInflowsAed
			row.handoverInflowsAed += p.handoverInflowsAed
			row.operatingOutflowsAed += p.operatingOutflowsAed
			row.costLandAed += p.costLandAed
			row.costConstructionAed += p.costConstructionAed
			row.costProfessionalFeesAed += p.costProfessionalFeesAed
			row.costMarketingAed += p.costMarketingAed
			row.costSalesAgentAed += p.costSalesAgentAed
			row.costInfrastructureAed += p.costInfrastructureAed
			row.costAuthorityFeesAed += p.costAuthorityFeesAed
			row.costCommunityFeesAed += p.costCommunityFeesAed
			row.costContingencyAed += p.costContingencyAed
			row.costVatAed += p.costVatAed
			row.landDrawAed += p.landDrawAed
			row.constructionDrawAed += p.constructionDrawAed
			row.costPaidFromEscrowAed += p.costPaidFromEscrowAed ?? 0
			row.vatRefundInflowsAed += p.vatRefundInflowsAed ?? 0
			row.unleveredNetCashFlowAed += p.unleveredNetCashFlowAed
			row.debtDrawAed += p.debtDrawAed
			row.debtRepaymentAed += p.debtRepaymentAed
			row.interestPaidAed += p.interestPaidAed
			row.commitmentFeePaidAed += p.commitmentFeePaidAed
			row.equityContributionAed += p.equityContributionAed
			row.equityDistributionAed += p.equityDistributionAed
			row.leveredNetCashFlowAed += p.leveredNetCashFlowAed
			// balance rows: year-end closing = last period in year
			row.debtBalanceAed = p.debtBalanceAed
			row.landLoanBalanceAed = p.landLoanBalanceAed
			row.constructionLoanBalanceAed = p.constructionLoanBalanceAed
			row.escrowBalanceAed = p.escrowBalanceAed
		}
		return Array.from(byYear.values()).sort((a, b) => a.year - b.year)
	})()
)

const totals: AnnualRow = $derived(
	(() => {
		const rows = annualRows
		const last = rows.at(-1)
		return {
			year: 0,
			revenueInflowsAed: rows.reduce((s, r) => s + r.revenueInflowsAed, 0),
			depositInflowsAed: rows.reduce((s, r) => s + r.depositInflowsAed, 0),
			preHandoverInflowsAed: rows.reduce((s, r) => s + r.preHandoverInflowsAed, 0),
			handoverInflowsAed: rows.reduce((s, r) => s + r.handoverInflowsAed, 0),
			operatingOutflowsAed: rows.reduce((s, r) => s + r.operatingOutflowsAed, 0),
			costLandAed: rows.reduce((s, r) => s + r.costLandAed, 0),
			costConstructionAed: rows.reduce((s, r) => s + r.costConstructionAed, 0),
			costProfessionalFeesAed: rows.reduce((s, r) => s + r.costProfessionalFeesAed, 0),
			costMarketingAed: rows.reduce((s, r) => s + r.costMarketingAed, 0),
			costSalesAgentAed: rows.reduce((s, r) => s + r.costSalesAgentAed, 0),
			costInfrastructureAed: rows.reduce((s, r) => s + r.costInfrastructureAed, 0),
			costAuthorityFeesAed: rows.reduce((s, r) => s + r.costAuthorityFeesAed, 0),
			costCommunityFeesAed: rows.reduce((s, r) => s + r.costCommunityFeesAed, 0),
			costContingencyAed: rows.reduce((s, r) => s + r.costContingencyAed, 0),
			costVatAed: rows.reduce((s, r) => s + r.costVatAed, 0),
			landDrawAed: rows.reduce((s, r) => s + r.landDrawAed, 0),
			constructionDrawAed: rows.reduce((s, r) => s + r.constructionDrawAed, 0),
			costPaidFromEscrowAed: rows.reduce((s, r) => s + r.costPaidFromEscrowAed, 0),
			vatRefundInflowsAed: rows.reduce((s, r) => s + r.vatRefundInflowsAed, 0),
			unleveredNetCashFlowAed: rows.reduce((s, r) => s + r.unleveredNetCashFlowAed, 0),
			debtDrawAed: rows.reduce((s, r) => s + r.debtDrawAed, 0),
			debtRepaymentAed: rows.reduce((s, r) => s + r.debtRepaymentAed, 0),
			interestPaidAed: rows.reduce((s, r) => s + r.interestPaidAed, 0),
			commitmentFeePaidAed: rows.reduce((s, r) => s + r.commitmentFeePaidAed, 0),
			equityContributionAed: rows.reduce((s, r) => s + r.equityContributionAed, 0),
			equityDistributionAed: rows.reduce((s, r) => s + r.equityDistributionAed, 0),
			leveredNetCashFlowAed: rows.reduce((s, r) => s + r.leveredNetCashFlowAed, 0),
			debtBalanceAed: last?.debtBalanceAed ?? 0,
			landLoanBalanceAed: last?.landLoanBalanceAed ?? 0,
			constructionLoanBalanceAed: last?.constructionLoanBalanceAed ?? 0,
			escrowBalanceAed: last?.escrowBalanceAed ?? 0
		}
	})()
)

// Style helpers
const TH =
	'px-3 py-[5px] text-right text-[10px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap'
const TH_L =
	'px-3 py-[5px] text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wider'
const TD = 'px-3 py-[4px] text-right text-[11px] tabular-nums text-slate-600 whitespace-nowrap'
const TD_TOT =
	'px-3 py-[4px] text-right text-[11px] tabular-nums font-semibold text-slate-800 whitespace-nowrap'
const TD_NEG = 'px-3 py-[4px] text-right text-[11px] tabular-nums text-amber-700 whitespace-nowrap'
const TD_NEG_TOT =
	'px-3 py-[4px] text-right text-[11px] tabular-nums font-semibold text-amber-700 whitespace-nowrap'
const TD_L = 'px-3 py-[4px] text-left text-[11px] text-slate-700 whitespace-nowrap'
const TD_L_SUB = 'pl-7 pr-3 py-[4px] text-left text-[11px] text-slate-400 whitespace-nowrap'
const HDR = 'bg-slate-100 border-t-2 border-slate-300'
const HDR_SUB = 'bg-slate-50 border-t border-slate-200'
const ROW = 'border-t border-slate-100 hover:bg-slate-50/60'
</script>

{#if !draftCashFlow}
	<div class="h-full flex items-center justify-center px-6 text-sm text-slate-400">
		Generate an HBU study to build the cash-flow view.
	</div>
{:else}
	<div class="h-full overflow-auto">
		<table class="w-full border-collapse text-xs min-w-[700px]">
			<!-- Header -->
			<thead class="sticky top-0 z-10 bg-white shadow-sm">
				<tr class="border-b-2 border-slate-300">
					<th class="{TH_L} w-44">Line item</th>
					{#each annualRows as row}
						<th class={TH}>{row.year}</th>
					{/each}
					<th class="{TH} bg-slate-50">Total</th>
				</tr>
			</thead>

			<tbody>
				<!-- ── REVENUE ── -->
				<tr class={HDR}>
					<td class="px-3 py-[5px] text-[10px] font-semibold text-slate-700 uppercase tracking-wider" colspan={annualRows.length + 2}>
						Revenue inflows
					</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L}>Gross sales receipts</td>
					{#each annualRows as row}
						<td class={TD}>{fmt(row.revenueInflowsAed)}</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">{fmt(totals.revenueInflowsAed)}</td>
				</tr>
				{#if hasBreakdown}
					<tr class={ROW}>
						<td class={TD_L_SUB}>↳ Deposits (S-curve)</td>
						{#each annualRows as row}
							<td class="{TD} text-slate-400">{fmt(row.depositInflowsAed)}</td>
						{/each}
						<td class="{TD_TOT} bg-slate-50 text-slate-400">{fmt(totals.depositInflowsAed)}</td>
					</tr>
					<tr class={ROW}>
						<td class={TD_L_SUB}>↳ Pre-handover milestone</td>
						{#each annualRows as row}
							<td class="{TD} text-slate-400">{fmt(row.preHandoverInflowsAed)}</td>
						{/each}
						<td class="{TD_TOT} bg-slate-50 text-slate-400">{fmt(totals.preHandoverInflowsAed)}</td>
					</tr>
					<tr class={ROW}>
						<td class={TD_L_SUB}>↳ Handover proceeds</td>
						{#each annualRows as row}
							<td class="{TD} text-slate-400">{fmt(row.handoverInflowsAed)}</td>
						{/each}
						<td class="{TD_TOT} bg-slate-50 text-slate-400">{fmt(totals.handoverInflowsAed)}</td>
					</tr>
				{/if}

				<!-- ── SALES PROCEEDS FUNDING COSTS ── -->
				{#if annualRows.some(r => r.costPaidFromEscrowAed > 0)}
					<tr class={ROW}>
						<td class="{TD_L} text-teal-700 font-medium">↳ Sales proceeds fund costs (escrow)</td>
						{#each annualRows as row}
							<td class="px-3 py-[4px] text-right text-[11px] tabular-nums text-teal-700 whitespace-nowrap">
								{row.costPaidFromEscrowAed > 0 ? fmt(row.costPaidFromEscrowAed) : '—'}
							</td>
						{/each}
						<td class="px-3 py-[4px] text-right text-[11px] tabular-nums font-semibold text-teal-700 bg-slate-50 whitespace-nowrap">{fmt(totals.costPaidFromEscrowAed)}</td>
					</tr>
				{/if}

				<!-- ── VAT REFUND ── -->
			{#if annualRows.some(r => r.vatRefundInflowsAed > 0)}
				<tr class={ROW}>
					<td class="{TD_L} text-emerald-700 font-medium">↳ VAT refund (recovered at handover)</td>
					{#each annualRows as row}
						<td class="px-3 py-[4px] text-right text-[11px] tabular-nums text-emerald-700 whitespace-nowrap">
							{row.vatRefundInflowsAed > 0 ? fmt(row.vatRefundInflowsAed) : '—'}
						</td>
					{/each}
					<td class="px-3 py-[4px] text-right text-[11px] tabular-nums font-semibold text-emerald-700 bg-slate-50 whitespace-nowrap">{fmt(totals.vatRefundInflowsAed)}</td>
				</tr>
			{/if}

			<!-- ── COSTS ── -->
				<tr class={HDR}>
					<td class="px-3 py-[5px] text-[10px] font-semibold text-slate-700 uppercase tracking-wider" colspan={annualRows.length + 2}>
						Project costs
					</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L_SUB}>Land acquisition</td>
					{#each annualRows as row}
						<td class={TD}>({fmt(row.costLandAed)})</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">({fmt(totals.costLandAed)})</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L_SUB}>Construction</td>
					{#each annualRows as row}
						<td class={TD}>({fmt(row.costConstructionAed)})</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">({fmt(totals.costConstructionAed)})</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L_SUB}>Design &amp; supervision</td>
					{#each annualRows as row}
						<td class={TD}>({fmt(row.costProfessionalFeesAed)})</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">({fmt(totals.costProfessionalFeesAed)})</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L_SUB}>Marketing</td>
					{#each annualRows as row}
						<td class={TD}>({fmt(row.costMarketingAed)})</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">({fmt(totals.costMarketingAed)})</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L_SUB}>Sales agent fees</td>
					{#each annualRows as row}
						<td class={TD}>({fmt(row.costSalesAgentAed)})</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">({fmt(totals.costSalesAgentAed)})</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L_SUB}>Infrastructure &amp; utilities</td>
					{#each annualRows as row}
						<td class={TD}>({fmt(row.costInfrastructureAed)})</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">({fmt(totals.costInfrastructureAed)})</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L_SUB}>Authority &amp; connection fees</td>
					{#each annualRows as row}
						<td class={TD}>({fmt(row.costAuthorityFeesAed)})</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">({fmt(totals.costAuthorityFeesAed)})</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L_SUB}>Master community fees</td>
					{#each annualRows as row}
						<td class={TD}>({fmt(row.costCommunityFeesAed)})</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">({fmt(totals.costCommunityFeesAed)})</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L_SUB}>Contingency</td>
					{#each annualRows as row}
						<td class={TD}>({fmt(row.costContingencyAed)})</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">({fmt(totals.costContingencyAed)})</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L_SUB}>VAT (net)</td>
					{#each annualRows as row}
						<td class={TD}>({fmt(row.costVatAed)})</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">({fmt(totals.costVatAed)})</td>
				</tr>
				<tr class="{ROW} font-semibold border-t border-slate-300">
					<td class={TD_L}>Total project costs</td>
					{#each annualRows as row}
						<td class={TD}>({fmt(row.operatingOutflowsAed)})</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">({fmt(totals.operatingOutflowsAed)})</td>
				</tr>

				<!-- ── UNLEVERED CF ── -->
				<tr class={HDR}>
					<td class="px-3 py-[5px] text-[10px] font-semibold text-slate-700 uppercase tracking-wider" colspan={annualRows.length + 2}>
						Unlevered cash flow
					</td>
				</tr>
				<tr class={ROW}>
					<td class="{TD_L} font-semibold text-slate-800">Unlevered net CF</td>
					{#each annualRows as row}
						<td class={row.unleveredNetCashFlowAed < 0 ? TD_NEG : TD}>
							{row.unleveredNetCashFlowAed < 0 ? '(' : ''}{fmt(Math.abs(row.unleveredNetCashFlowAed))}{row.unleveredNetCashFlowAed < 0 ? ')' : ''}
						</td>
					{/each}
					<td class="{totals.unleveredNetCashFlowAed < 0 ? TD_NEG_TOT : TD_TOT} bg-slate-50">
						{totals.unleveredNetCashFlowAed < 0 ? '(' : ''}{fmt(Math.abs(totals.unleveredNetCashFlowAed))}{totals.unleveredNetCashFlowAed < 0 ? ')' : ''}
					</td>
				</tr>

				<!-- ── DEBT ── -->
				<tr class={HDR}>
					<td class="px-3 py-[5px] text-[10px] font-semibold text-slate-700 uppercase tracking-wider" colspan={annualRows.length + 2}>
						Debt (flows)
					</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L_SUB}>↳ Land loan draws</td>
					{#each annualRows as row}
						<td class="{TD} text-slate-400">{fmt(row.landDrawAed)}</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50 text-slate-400">{fmt(totals.landDrawAed)}</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L_SUB}>↳ Construction loan draws</td>
					{#each annualRows as row}
						<td class="{TD} text-slate-400">{fmt(row.constructionDrawAed)}</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50 text-slate-400">{fmt(totals.constructionDrawAed)}</td>
				</tr>
				<tr class="{ROW} font-semibold">
					<td class={TD_L}>Total debt draws</td>
					{#each annualRows as row}
						<td class={TD}>{fmt(row.debtDrawAed)}</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">{fmt(totals.debtDrawAed)}</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L}>Debt repayments</td>
					{#each annualRows as row}
						<td class={TD}>({fmt(row.debtRepaymentAed)})</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">({fmt(totals.debtRepaymentAed)})</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L}>Interest (capitalised)</td>
					{#each annualRows as row}
						<td class={TD}>({fmt(row.interestPaidAed)})</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">({fmt(totals.interestPaidAed)})</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L}>Commitment fees</td>
					{#each annualRows as row}
						<td class={TD}>({fmt(row.commitmentFeePaidAed)})</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">({fmt(totals.commitmentFeePaidAed)})</td>
				</tr>

				<!-- ── DEBT BALANCES ── -->
				<tr class={HDR_SUB}>
					<td class="px-3 py-[5px] text-[10px] font-semibold text-slate-600 uppercase tracking-wider" colspan={annualRows.length + 2}>
						Debt (year-end closing balances)
					</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L}>Total debt balance</td>
					{#each annualRows as row}
						<td class={TD}>{fmt(row.debtBalanceAed)}</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">{fmt(totals.debtBalanceAed)}</td>
				</tr>
				{#if hasTranche}
					<tr class={ROW}>
						<td class={TD_L_SUB}>↳ Land loan</td>
						{#each annualRows as row}
							<td class="{TD} text-slate-400">{fmt(row.landLoanBalanceAed)}</td>
						{/each}
						<td class="{TD_TOT} bg-slate-50 text-slate-400">{fmt(totals.landLoanBalanceAed)}</td>
					</tr>
					<tr class={ROW}>
						<td class={TD_L_SUB}>↳ Construction loan</td>
						{#each annualRows as row}
							<td class="{TD} text-slate-400">{fmt(row.constructionLoanBalanceAed)}</td>
						{/each}
						<td class="{TD_TOT} bg-slate-50 text-slate-400">{fmt(totals.constructionLoanBalanceAed)}</td>
					</tr>
				{/if}
				<tr class={ROW}>
					<td class={TD_L}>Escrow balance</td>
					{#each annualRows as row}
						<td class={TD}>{fmt(row.escrowBalanceAed)}</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">{fmt(totals.escrowBalanceAed)}</td>
				</tr>

				<!-- ── EQUITY ── -->
				<tr class={HDR}>
					<td class="px-3 py-[5px] text-[10px] font-semibold text-slate-700 uppercase tracking-wider" colspan={annualRows.length + 2}>
						Equity
					</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L}>Equity contributions</td>
					{#each annualRows as row}
						<td class={TD}>({fmt(row.equityContributionAed)})</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">({fmt(totals.equityContributionAed)})</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L}>Equity distributions</td>
					{#each annualRows as row}
						<td class={TD}>{fmt(row.equityDistributionAed)}</td>
					{/each}
					<td class="{TD_TOT} bg-slate-50">{fmt(totals.equityDistributionAed)}</td>
				</tr>

				<!-- ── LEVERED CF ── -->
				<tr class={HDR}>
					<td class="px-3 py-[5px] text-[10px] font-semibold text-slate-700 uppercase tracking-wider" colspan={annualRows.length + 2}>
						Levered (equity) cash flow
					</td>
				</tr>
				<tr class={ROW}>
					<td class="{TD_L} font-semibold text-slate-800">Levered net CF</td>
					{#each annualRows as row}
						<td class={row.leveredNetCashFlowAed < 0 ? TD_NEG : TD}>
							{row.leveredNetCashFlowAed < 0 ? '(' : ''}{fmt(Math.abs(row.leveredNetCashFlowAed))}{row.leveredNetCashFlowAed < 0 ? ')' : ''}
						</td>
					{/each}
					<td class="{totals.leveredNetCashFlowAed < 0 ? TD_NEG_TOT : TD_TOT} bg-slate-50">
						{totals.leveredNetCashFlowAed < 0 ? '(' : ''}{fmt(Math.abs(totals.leveredNetCashFlowAed))}{totals.leveredNetCashFlowAed < 0 ? ')' : ''}
					</td>
				</tr>

				<!-- ── RETURNS ── -->
				<tr class="border-t-2 border-slate-300 bg-slate-100">
					<td class="px-3 py-[5px] text-[10px] font-semibold text-slate-700 uppercase tracking-wider" colspan={annualRows.length + 2}>
						Returns summary
					</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L}>Project IRR</td>
					<td class="px-3 py-[4px] text-[11px] text-slate-600" colspan={annualRows.length}>
						{fmtPct(returns?.projectIrrPct)}
					</td>
					<td class="{TD_TOT} bg-slate-50">{fmtPct(returns?.projectIrrPct)}</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L}>Project MoIC</td>
					<td class="px-3 py-[4px] text-[11px] text-slate-600" colspan={annualRows.length}>
						{fmtMoic(returns?.projectMoic)}
					</td>
					<td class="{TD_TOT} bg-slate-50">{fmtMoic(returns?.projectMoic)}</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L}>Equity IRR</td>
					<td class="px-3 py-[4px] text-[11px] text-slate-600" colspan={annualRows.length}>
						{fmtPct(returns?.equityIrrPct)}
					</td>
					<td class="{TD_TOT} bg-slate-50">{fmtPct(returns?.equityIrrPct)}</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L}>Equity MoIC</td>
					<td class="px-3 py-[4px] text-[11px] text-slate-600" colspan={annualRows.length}>
						{fmtMoic(returns?.equityMoic)}
					</td>
					<td class="{TD_TOT} bg-slate-50">{fmtMoic(returns?.equityMoic)}</td>
				</tr>
				<tr class={ROW}>
					<td class={TD_L}>Gross margin</td>
					<td class="px-3 py-[4px] text-[11px] text-slate-600" colspan={annualRows.length}>
						{fmtPct(returns?.grossMarginPct)}
					</td>
					<td class="{TD_TOT} bg-slate-50">{fmtPct(returns?.grossMarginPct)}</td>
				</tr>
			</tbody>
		</table>
	</div>
{/if}
