<script lang="ts">
import { onMount } from 'svelte'
import { type FeasibilitySheetTab, workbookStore } from '$lib/feasibility/workbook/store.svelte'
import BlankSheet from './sheets/BlankSheet.svelte'
import BudgetSheet from './sheets/BudgetSheet.svelte'
import CashFlowSheet from './sheets/CashFlowSheet.svelte'
import ChecksSheet from './sheets/ChecksSheet.svelte'
import EiborSheet from './sheets/EiborSheet.svelte'
import FinancingSheet from './sheets/FinancingSheet.svelte'
import KeyAssumptionsSheet from './sheets/KeyAssumptionsSheet.svelte'
import MonthlyCashFlowSheet from './sheets/MonthlyCashFlowSheet.svelte'
import PricingEvidenceSheet from './sheets/PricingEvidenceSheet.svelte'
import ReturnsSheet from './sheets/ReturnsSheet.svelte'
import RevenueSheet from './sheets/RevenueSheet.svelte'

const tabs: { id: FeasibilitySheetTab; label: string }[] = [
	{ id: 'key_assumptions', label: 'Key Assumptions' },
	{ id: 'sales_collections', label: 'Sales & Collections' },
	{ id: 'budget', label: 'Budget' },
	{ id: 'financing', label: 'Financing' },
	{ id: 'pricing_evidence', label: 'Pricing Evidence' },
	{ id: 'cashflow', label: 'Cash Flow' },
	{ id: 'monthly_cf', label: 'Monthly CF' },
	{ id: 'returns', label: 'Returns' },
	{ id: 'checks', label: 'Checks' },
	{ id: 'eibor', label: 'EIBOR' }
]

const validation = $derived(workbookStore.validation)
const activeTab = $derived(workbookStore.activeSheet)

onMount(() => {
	workbookStore.clearSheetDirty(activeTab)
})

function isTabDirty(tab: FeasibilitySheetTab) {
	return workbookStore.sheetDirty?.[tab] ?? false
}

function openTab(tab: FeasibilitySheetTab) {
	workbookStore.setActiveSheet(tab)
}
</script>

<div class="h-full flex flex-col overflow-hidden bg-white border-r border-slate-200">
	<div class="flex items-center justify-between px-3 py-2 border-b border-slate-300 flex-shrink-0 bg-slate-50">
		<span class="text-xs font-semibold text-slate-700">Feasibility Model</span>
		<div class="flex items-center gap-2">
			{#if validation}
				<span class="text-[10px] px-2 py-0.5 rounded-full font-medium uppercase tracking-[0.12em] {validation.status === 'invalid'
					? 'bg-rose-100 text-rose-700'
					: validation.status === 'needs_review'
						? 'bg-amber-100 text-amber-700'
						: 'bg-emerald-100 text-emerald-700'}">
					{validation.status.replace('_', ' ')}
				</span>
			{/if}
		</div>
	</div>

	<div class="flex-1 overflow-hidden flex flex-col min-h-0">
		{#if activeTab === 'key_assumptions'}
			<KeyAssumptionsSheet />
		{:else if activeTab === 'sales_collections'}
			<RevenueSheet />
		{:else if activeTab === 'budget'}
			<BudgetSheet />
		{:else if activeTab === 'financing'}
			<FinancingSheet />
		{:else if activeTab === 'pricing_evidence'}
			<PricingEvidenceSheet />
		{:else if activeTab === 'cashflow'}
			<CashFlowSheet />
		{:else if activeTab === 'monthly_cf'}
			<MonthlyCashFlowSheet />
		{:else if activeTab === 'returns'}
			<ReturnsSheet />
		{:else if activeTab === 'checks'}
			<ChecksSheet />
		{:else if activeTab === 'eibor'}
			<EiborSheet />
		{:else}
			<BlankSheet />
		{/if}
	</div>

	<div class="relative z-30 flex-shrink-0 flex items-end gap-0.5 overflow-x-auto border-t border-slate-300 bg-slate-200/60 px-2 pt-1 shadow-[0_-1px_0_rgba(148,163,184,0.18)]">
		{#each tabs as tab (tab.id)}
				<button
					type="button"
					class="relative z-10 px-3 py-1 text-[11px] font-medium rounded-t border border-b-0 border-slate-300 -mb-px whitespace-nowrap transition-colors {activeTab === tab.id
						? 'bg-white text-teal-700 border-t-2 border-t-teal-500'
						: isTabDirty(tab.id)
							? 'bg-teal-50/80 text-teal-600 hover:text-teal-700'
							: 'bg-slate-100/80 text-slate-500 hover:text-slate-700'}"
					onclick={() => openTab(tab.id)}
				>
					{tab.label}
					{#if isTabDirty(tab.id) && activeTab !== tab.id}
						<span class="ml-1 inline-block w-1.5 h-1.5 rounded-full bg-teal-400 align-middle -mt-0.5"></span>
					{/if}
				</button>
		{/each}
	</div>
</div>
