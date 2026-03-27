<script lang="ts">
import { workbookStore } from '$lib/stores/workbookStore.svelte'

function fmt(value: number, digits = 0) {
	return value.toLocaleString('en-AE', {
		minimumFractionDigits: digits,
		maximumFractionDigits: digits
	})
}

const outputs = $derived(workbookStore.outputs)
const assumptions = $derived(workbookStore.assumptions)
const draftFinancing = $derived(outputs?.financing ?? null)
const sourcesUses = $derived(outputs?.sourcesUses ?? null)
const validation = $derived(workbookStore.validation ?? null)
const cashFlowPeriods = $derived(outputs?.cashFlow?.periods ?? [])

function issuePresent(code: string) {
	return (validation?.issues ?? []).some((issue) => issue.code === code)
}

type TestStatus = 'pass' | 'warning' | 'fail' | 'missing'

function pill(status: TestStatus) {
	if (status === 'fail') return 'bg-rose-100 text-rose-700'
	if (status === 'warning') return 'bg-amber-100 text-amber-700'
	if (status === 'missing') return 'bg-slate-200 text-slate-600'
	return 'bg-emerald-100 text-emerald-700'
}

const peakPeriod = $derived.by(() => {
	if (!cashFlowPeriods.length) return null
	return cashFlowPeriods.reduce((maxPeriod, period) =>
		period.debtBalanceAed > maxPeriod.debtBalanceAed ? period : maxPeriod
	)
})

const peakLandPeriod = $derived.by(() => {
	if (!cashFlowPeriods.length) return null
	return cashFlowPeriods.reduce((maxPeriod, period) =>
		period.landLoanBalanceAed > maxPeriod.landLoanBalanceAed ? period : maxPeriod
	)
})

const peakConstructionPeriod = $derived.by(() => {
	if (!cashFlowPeriods.length) return null
	return cashFlowPeriods.reduce((maxPeriod, period) =>
		period.constructionLoanBalanceAed > maxPeriod.constructionLoanBalanceAed ? period : maxPeriod
	)
})

const firstSweepPeriod = $derived.by(() => {
	return (
		cashFlowPeriods.find((period) => period.debtRepaymentAed > 0 && period.revenueInflowsAed > 0) ??
		null
	)
})

const facilityLines = $derived([
	{
		label: 'Land loan',
		source: sourcesUses?.sources.find((item) => item.code === 'land_loan') ?? null,
		peakBalance: peakLandPeriod?.landLoanBalanceAed ?? 0,
		peakPeriodLabel: peakLandPeriod?.periodLabel ?? 'N/A',
		assumption: null
	},
	{
		label: 'Construction loan',
		source: sourcesUses?.sources.find((item) => item.code === 'construction_loan') ?? null,
		peakBalance: peakConstructionPeriod?.constructionLoanBalanceAed ?? 0,
		peakPeriodLabel: peakConstructionPeriod?.periodLabel ?? 'N/A',
		assumption: null
	}
])

const lenderTests = $derived([
	{
		label: 'Presale threshold',
		value: draftFinancing
			? `${fmt(draftFinancing.presaleCoveragePctAtConstruction, 1)}% covered`
			: 'N/A',
		target: 'No threshold',
		status: !draftFinancing
			? 'missing'
			: draftFinancing.presaleCoveragePctAtConstruction < 100
				? 'warning'
				: 'pass',
		note: 'Presales achieved at construction start versus the modeled threshold.'
	},
	{
		label: 'Debt utilization',
		value: draftFinancing ? `${fmt(draftFinancing.debtCommitmentUtilizationPct, 1)}%` : 'N/A',
		target: draftFinancing ? 'Should remain within committed facilities' : 'N/A',
		status: !draftFinancing
			? 'missing'
			: draftFinancing.debtCommitmentUtilizationPct > 100 ||
					issuePresent('peak_debt_exceeds_facility')
				? 'fail'
				: draftFinancing.debtCommitmentUtilizationPct > 95
					? 'warning'
					: 'pass',
		note: 'Peak debt versus modeled debt commitment envelope.'
	},
	{
		label: 'Minimum debt headroom',
		value: draftFinancing ? `AED ${fmt(draftFinancing.minDebtHeadroomAed)}` : 'N/A',
		target: 'Positive headroom throughout the draw period',
		status: !draftFinancing
			? 'missing'
			: draftFinancing.minDebtHeadroomAed < 0 || issuePresent('peak_debt_exceeds_facility')
				? 'fail'
				: draftFinancing.minDebtHeadroomAed < 5_000_000
					? 'warning'
					: 'pass',
		note: 'Lowest residual facility capacity during the modeled cash flow.'
	},
	{
		label: 'Completion reserve',
		value: draftFinancing ? `${fmt(draftFinancing.completionReserveCoveragePct, 1)}%` : 'N/A',
		target: 'At least 100% covered before sponsor release',
		status: !draftFinancing
			? 'missing'
			: draftFinancing.completionReserveCoveragePct < 100 ||
					issuePresent('completion_reserve_underfunded')
				? 'fail'
				: draftFinancing.completionReserveCoveragePct < 110
					? 'warning'
					: 'pass',
		note: 'Escrow retained at terminal period versus the modeled reserve requirement.'
	},
	{
		label: 'Terminal debt',
		value: draftFinancing ? `AED ${fmt(draftFinancing.closingDebtBalanceAed)}` : 'N/A',
		target: 'Zero or fully explained residual balance',
		status: !draftFinancing
			? 'missing'
			: draftFinancing.closingDebtBalanceAed > 0 || issuePresent('debt_balance_at_exit')
				? 'warning'
				: 'pass',
		note: 'Debt balance remaining after handover and modeled repayment logic.'
	},
	{
		label: 'Debt roll-forward',
		value: peakPeriod ? `Peak in ${peakPeriod.periodLabel}` : 'N/A',
		target: 'Opening + draw + carry - repayment = closing',
		status: !draftFinancing
			? 'missing'
			: issuePresent('debt_rollforward_mismatch')
				? 'fail'
				: 'pass',
		note: 'Balance integrity across draws, interest carry, and repayments.'
	}
] satisfies Array<{
	label: string
	value: string
	target: string
	status: TestStatus
	note: string
}>)
</script>

{#if !draftFinancing}
	<div class="h-full flex items-center justify-center text-sm text-slate-400">
		Generate an HBU study to build the draft financing view.
	</div>
{:else}
	<div class="overflow-auto flex-1 bg-white text-[11px] font-[Calibri,'Segoe_UI',Arial,sans-serif] select-none">

		<!-- Title bar -->
		<div class="bg-[#1F3864] border-b-2 border-[#1F3864] text-white px-4 py-2.5">
			<div class="text-[13px] font-bold tracking-wide">FINANCING &amp; DEBT STRUCTURE</div>
		</div>

		<!-- Summary bar -->
		<div class="grid grid-cols-4 border-b border-[#B8C4CE] bg-[#EEF2F7]">
			<div class="px-3 py-2 border-r border-[#D9D9D9]">
				<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Debt Commitment</div>
				<div class="text-[13px] font-bold text-slate-900 tabular-nums mt-0.5">{fmt(draftFinancing.debtCommitmentAed)}</div>
				<div class="text-[10px] text-slate-500">AED · {fmt(draftFinancing.debtCommitmentUtilizationPct, 1)}% utilized</div>
			</div>
			<div class="px-3 py-2 border-r border-[#D9D9D9]">
				<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Peak Debt</div>
				<div class="text-[13px] font-bold text-slate-900 tabular-nums mt-0.5">{fmt(draftFinancing.peakDebtAed)}</div>
				<div class="text-[10px] text-slate-500">{peakPeriod ? `Peak month ${peakPeriod.periodLabel}` : 'No draw profile'}</div>
			</div>
			<div class="px-3 py-2 border-r border-[#D9D9D9]">
				<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Min Headroom / Terminal Debt</div>
				<div class="text-[13px] font-bold text-slate-900 tabular-nums mt-0.5">{fmt(draftFinancing.minDebtHeadroomAed)} / {fmt(draftFinancing.closingDebtBalanceAed)}</div>
				<div class="text-[10px] text-slate-500">AED</div>
			</div>
			<div class="px-3 py-2">
				<div class="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Completion Reserve</div>
				<div class="text-[13px] font-bold text-slate-900 tabular-nums mt-0.5">{fmt(draftFinancing.completionReserveCoveragePct, 1)}%</div>
				<div class="text-[10px] text-slate-500">Required AED {fmt(draftFinancing.requiredCompletionReserveAed)}</div>
			</div>
		</div>

		<table class="w-full border-collapse" style="border-spacing:0">
			<tbody>

			<!-- Section A: Facility Structure -->
			<tr class="bg-[#1F3864]">
				<td colspan="5" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">A.&nbsp;&nbsp;FACILITY STRUCTURE</td>
			</tr>
			<tr class="bg-[#D6DCE4] border-b border-[#B8C4CE]">
				<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Facility</th>
				<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Commitment (AED)</th>
				<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Peak Balance (AED)</th>
				<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Peak Month</th>
				<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Basis</th>
			</tr>
			{#each facilityLines as row (row.label)}
				<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
					<td class="px-2 py-[3px] text-left text-[10px] text-slate-800 font-semibold">{row.label}</td>
					<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{row.source ? fmt(row.source.amountAed) : 'N/A'}</td>
					<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{fmt(row.peakBalance)}</td>
					<td class="px-2 py-[3px] text-right tabular-nums text-slate-500 text-[10px]">{row.peakPeriodLabel}</td>
					<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">
						{row.source?.basis ?? 'No facility basis returned'}
					</td>
				</tr>
			{/each}

			<!-- Section B: Lender Tests -->
			<tr class="bg-[#1F3864]">
				<td colspan="5" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">B.&nbsp;&nbsp;LENDER TESTS</td>
			</tr>
			<tr class="bg-[#D6DCE4] border-b border-[#B8C4CE]">
				<th class="px-1 py-[4px] text-center text-[9px] font-semibold text-slate-500 uppercase tracking-wider">#</th>
				<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Test</th>
				<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Current / Target</th>
				<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Status</th>
				<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Comment</th>
			</tr>
			{#each lenderTests as test, idx (test.label)}
				<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
					<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">{idx + 1}</td>
					<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">{test.label}</td>
					<td class="px-2 py-[3px] text-right tabular-nums text-[10px] text-slate-900">
						{test.value}<br /><span class="text-slate-400 text-[9px]">{test.target}</span>
					</td>
					<td class="px-2 py-[3px] text-right">
						{#if test.status === 'fail'}
							<span class="inline-block px-2 py-0.5 text-[9px] font-semibold uppercase rounded-sm bg-[#FCE4D6] text-[#843C0C]">{test.status}</span>
						{:else if test.status === 'warning'}
							<span class="inline-block px-2 py-0.5 text-[9px] font-semibold uppercase rounded-sm bg-[#FFF2CC] text-[#7F6000]">{test.status}</span>
						{:else if test.status === 'missing'}
							<span class="inline-block px-2 py-0.5 text-[9px] font-semibold uppercase rounded-sm bg-[#D9D9D9] text-[#595959]">{test.status}</span>
						{:else}
							<span class="inline-block px-2 py-0.5 text-[9px] font-semibold uppercase rounded-sm bg-[#E2F0D9] text-[#375623]">{test.status}</span>
						{/if}
					</td>
					<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">{test.note}</td>
				</tr>
			{/each}

			<!-- Section D: Finance Carry & Reserve -->
			<tr class="bg-[#1F3864]">
				<td colspan="5" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">D.&nbsp;&nbsp;FINANCE CARRY &amp; RESERVE</td>
			</tr>
			<tr class="bg-[#D6DCE4] border-b border-[#B8C4CE]">
				<th class="px-1 py-[4px] text-center text-[9px] font-semibold text-slate-500 uppercase tracking-wider">#</th>
				<th colspan="2" class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Line Item</th>
				<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Amount (AED)</th>
				<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Basis</th>
			</tr>
			{#each [
				{ label: 'Arrangement fee', amount: draftFinancing.arrangementFeeAed, basis: 'Upfront fee on debt commitment' },
				{ label: 'Initial commitment fee', amount: draftFinancing.initialCommitmentFeeAed, basis: 'Facility fee included in cost stack' },
				{ label: 'Capitalized interest', amount: draftFinancing.capitalizedInterestAed, basis: 'Monthly carry on drawn land and construction debt' },
				{ label: 'Commitment fee carry', amount: draftFinancing.commitmentFeeCarryAed, basis: 'Undrawn construction facility carry' },
				{ label: 'Required completion reserve', amount: draftFinancing.requiredCompletionReserveAed, basis: 'Terminal reserve before sponsor release' },
				{ label: 'Sponsor release capacity', amount: draftFinancing.sponsorReleaseCapacityAed, basis: 'Escrow available above required reserve' },
				{ label: 'Closing escrow balance', amount: draftFinancing.closingEscrowBalanceAed, basis: 'Modeled terminal escrow after debt and equity flows' },
			] as row, idx (row.label)}
				<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
					<td class="px-1 py-[3px] text-center text-[9px] text-slate-400">{idx + 1}</td>
					<td colspan="2" class="px-2 py-[3px] text-left text-[10px] text-slate-800">{row.label}</td>
					<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">AED {fmt(row.amount)}</td>
					<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">{row.basis}</td>
				</tr>
			{/each}

			<!-- Section E: Repayment & Sweep -->
			<tr class="bg-[#1F3864]">
				<td colspan="5" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">E.&nbsp;&nbsp;REPAYMENT &amp; SWEEP</td>
			</tr>
			<tr class="bg-[#D6DCE4] border-b border-[#B8C4CE]">
				<th colspan="2" class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Item</th>
				<th colspan="3" class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Value</th>
			</tr>
			{#each [
				{ label: 'Repayment mode', value: assumptions.debtRepaymentMode ?? 'bullet_at_handover' },
				{ label: 'First repayment period', value: firstSweepPeriod ? `${firstSweepPeriod.periodLabel} (AED ${fmt(firstSweepPeriod.debtRepaymentAed)})` : 'No repayment in current draft' },
				{ label: 'Total finance costs', value: 'AED ' + fmt(draftFinancing.totalFinanceCostsAed) },
				{ label: 'Equity in / out', value: `AED ${fmt(draftFinancing.equityContributedAed)} / ${fmt(draftFinancing.equityDistributedAed)}` },
				{ label: 'All-in cost / revenue', value: fmt(draftFinancing.allInCostToRevenuePct, 1) + '%' },
			] as item (item.label)}
				<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
					<td colspan="2" class="px-2 py-[3px] text-left text-[10px] text-slate-800">{item.label}</td>
					<td colspan="3" class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">{item.value}</td>
				</tr>
			{/each}

			</tbody>
		</table>

		<!-- Section F: Sources & Uses (optional) -->
		{#if sourcesUses}
			<table class="w-full border-collapse" style="border-spacing:0">
				<thead>
				<tr class="bg-[#1F3864]">
					<td colspan="4" class="px-2 py-[4px] text-white font-bold text-[11px] tracking-wide">F.&nbsp;&nbsp;SOURCES &amp; USES</td>
				</tr>
				<tr class="bg-[#D6DCE4] border-b border-[#B8C4CE]">
					<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Category</th>
					<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Line Item</th>
					<th class="px-2 py-[4px] text-right text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Amount (AED)</th>
					<th class="px-2 py-[4px] text-left text-[9px] font-semibold text-slate-600 uppercase tracking-wider">Basis</th>
				</tr>
				</thead>
				<tbody>
				{#each sourcesUses.sources as item (item.code)}
					<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
						<td class="px-2 py-[3px] text-left text-[10px] font-semibold text-emerald-700 uppercase tracking-wider text-[9px]">{item.category}</td>
						<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">{item.label}</td>
						<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">AED {fmt(item.amountAed)}</td>
						<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">{item.basis}</td>
					</tr>
				{/each}
				{#each sourcesUses.uses as item (item.code)}
					<tr class="border-b border-[#D9D9D9] hover:bg-slate-50/60">
						<td class="px-2 py-[3px] text-left text-[10px] font-semibold text-amber-700 uppercase tracking-wider text-[9px]">{item.category}</td>
						<td class="px-2 py-[3px] text-left text-[10px] text-slate-800">{item.label}</td>
						<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px]">AED {fmt(item.amountAed)}</td>
						<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">{item.basis}</td>
					</tr>
				{/each}
				<!-- Grand total row -->
				<tr class="border-t-2 border-[#1F3864] border-b border-[#D9D9D9] font-bold bg-[#EEF2F7]">
					<td class="px-2 py-[3px] text-left text-[10px] text-slate-900 font-bold">Totals</td>
					<td class="px-2 py-[3px] text-left text-[9px] text-slate-500">Sources / Uses</td>
					<td class="px-2 py-[3px] text-right tabular-nums text-slate-900 text-[10px] font-bold">
						AED {fmt(sourcesUses.totalSourcesAed)} / {fmt(sourcesUses.totalUsesAed)}
					</td>
					<td class="px-2 py-[3px] text-left text-[10px] font-bold {Math.abs(sourcesUses.gapAed) > 1_000_000 ? 'text-amber-700' : 'text-slate-600'}">
						Gap AED {fmt(sourcesUses.gapAed)}
					</td>
				</tr>
				</tbody>
			</table>
		{/if}

		<div class="py-3"></div>
	</div>
{/if}
