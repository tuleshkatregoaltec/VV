<script lang="ts">
	import ResearchSummary from './research/ResearchSummary.svelte';
	import ResearchTransactions from './research/ResearchTransactions.svelte';
	import ResearchAnalytics from './research/ResearchAnalytics.svelte';
	import ResearchComparables from './research/ResearchComparables.svelte';
	import ResearchMap from './research/ResearchMap.svelte';
	import { researchPanelStore, type ResearchTab } from '$lib/stores/researchPanel.svelte';

	const TABS: { id: ResearchTab; label: string }[] = [
		{ id: 'summary', label: 'Summary' },
		{ id: 'transactions', label: 'Transactions' },
		{ id: 'analytics', label: 'Analytics' },
		{ id: 'comparables', label: 'Comparables' },
		{ id: 'map', label: 'Map' }
	];
</script>

<div class="h-full flex flex-col overflow-hidden">
	<!-- Tab bar -->
	<div
		class="flex items-end gap-0 px-1 pt-1 border-b border-slate-200 flex-shrink-0 bg-white overflow-x-auto scrollbar-hide"
	>
		{#each TABS as tab (tab.id)}
			<button
				type="button"
				class="flex-shrink-0 px-2.5 py-1.5 text-[10px] font-medium border-t-2 transition-colors whitespace-nowrap
					{researchPanelStore.activeTab === tab.id
					? 'border-teal-500 text-teal-700 bg-white'
					: 'border-transparent text-slate-400 hover:text-slate-600 hover:bg-slate-50'}"
				onclick={() => researchPanelStore.setActiveTab(tab.id)}
			>
				{tab.label}
			</button>
		{/each}
	</div>

	<!-- Tab content -->
	<div class="flex-1 min-h-0 overflow-hidden">
		{#if researchPanelStore.activeTab === 'summary'}
			<div class="h-full overflow-y-auto scrollbar-hide px-3 py-3">
				<ResearchSummary />
			</div>
		{:else if researchPanelStore.activeTab === 'transactions'}
			<ResearchTransactions />
		{:else if researchPanelStore.activeTab === 'analytics'}
			<ResearchAnalytics />
		{:else if researchPanelStore.activeTab === 'comparables'}
			<ResearchComparables />
		{:else}
			<ResearchMap />
		{/if}
	</div>
</div>
