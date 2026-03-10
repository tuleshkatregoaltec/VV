<script lang="ts">
import { feasibilityStore } from '$lib/stores/feasibility.svelte'
import { exportFeasibility } from '$lib/utils/exportFeasibility'
import AssumptionsSheet from './sheets/AssumptionsSheet.svelte'
import CashFlowSheet from './sheets/CashFlowSheet.svelte'
import DevBudgetSheet from './sheets/DevBudgetSheet.svelte'
import ReturnsSheet from './sheets/ReturnsSheet.svelte'
import RevenueSheet from './sheets/RevenueSheet.svelte'
import ScheduleSheet from './sheets/ScheduleSheet.svelte'
import SummarySheet from './sheets/SummaryS2heet.svelte'

type Sheet =
	| 'summary'
	| 'assumptions'
	| 'devbudget'
	| 'revenue'
	| 'schedule'
	| 'cashflow'
	| 'returns'
let activeSheet = $state<Sheet>('summary')

function switchTab(id: Sheet) {
	activeSheet = id
	feasibilityStore.clearAffectedTab(id)
}

// Never show a dot on the currently visible tab
$effect(() => {
	if (feasibilityStore.affectedTabs.has(activeSheet)) {
		feasibilityStore.clearAffectedTab(activeSheet)
	}
})

const SHEETS: { id: Sheet; label: string }[] = [
	{ id: 'summary', label: 'Summary' },
	{ id: 'assumptions', label: 'Assumptions' },
	{ id: 'devbudget', label: 'Dev Budget' },
	{ id: 'revenue', label: 'Revenue' },
	{ id: 'schedule', label: 'Schedule' },
	{ id: 'cashflow', label: 'Cash Flow' },
	{ id: 'returns', label: 'Returns' }
]
</script>

<div class="h-full flex flex-col overflow-hidden bg-white border-r border-slate-200">
	<!-- Toolbar -->
	<div
		class="flex items-center justify-between px-3 py-2 border-b border-slate-300 flex-shrink-0 bg-slate-50"
	>
		<span class="text-xs font-semibold text-slate-700">Feasibility Model</span>
		<button
			type="button"
			class="flex items-center gap-1 px-2 py-0.5 rounded border border-slate-300 bg-white text-slate-600 text-[10px] font-medium hover:bg-slate-50 transition-colors"
			onclick={() => exportFeasibility(feasibilityStore)}
		>
			<svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
				/>
			</svg>
			Export Excel
		</button>
	</div>

	<!-- Sheet content -->
	<div class="flex-1 overflow-hidden flex flex-col min-h-0">
		{#if activeSheet === 'summary'}
			<SummarySheet {switchTab} />
		{:else if activeSheet === 'revenue'}
			<RevenueSheet />
		{:else if activeSheet === 'devbudget'}
			<DevBudgetSheet />
		{:else if activeSheet === 'schedule'}
			<ScheduleSheet />
		{:else if activeSheet === 'cashflow'}
			<CashFlowSheet />
		{:else if activeSheet === 'returns'}
			<ReturnsSheet />
		{:else}
			<AssumptionsSheet />
		{/if}
	</div>

	<!-- Sheet tabs (Excel-style at bottom) -->
	<div
		class="flex-shrink-0 flex items-end gap-0.5 px-2 pt-1 border-t border-slate-300 bg-slate-200/60 overflow-x-auto"
	>
		{#each SHEETS as sheet (sheet.id)}
			{@const hasDot = feasibilityStore.affectedTabs.has(sheet.id)}
			<button
				type="button"
				onclick={() => switchTab(sheet.id)}
				class="relative px-3 py-1 text-[11px] font-medium rounded-t transition-colors select-none whitespace-nowrap
					{activeSheet === sheet.id
					? 'bg-white border border-b-0 border-slate-300 text-teal-700 border-t-2 border-t-teal-500 -mb-px'
					: 'bg-slate-100 border border-slate-300 text-slate-500 hover:bg-slate-50 hover:text-slate-700'}"
			>
				{sheet.label}
				{#if hasDot && activeSheet !== sheet.id}
					<span class="absolute top-0.5 right-0.5 w-1.5 h-1.5 rounded-full bg-teal-500 dot-appear"
					></span>
				{/if}
			</button>
		{/each}
	</div>
</div>
