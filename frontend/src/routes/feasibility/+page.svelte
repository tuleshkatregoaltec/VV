<script lang="ts">
	import AppShell from '$lib/components/layout/AppShell.svelte';
	import StepProgress from '$lib/components/feasibility/StepProgress.svelte';
	import StepArea from '$lib/components/feasibility/StepArea.svelte';
	import StepPlot from '$lib/components/feasibility/StepPlot.svelte';
	import StepComparables from '$lib/components/feasibility/StepComparables.svelte';
	import ProjectConfigurator from '$lib/components/feasibility/ProjectConfigurator.svelte';
	import SpreadsheetPanel from '$lib/components/feasibility/SpreadsheetPanel.svelte';
	import FeasibilityChat from '$lib/components/feasibility/FeasibilityChat.svelte';
	import { feasibilityStore } from '$lib/stores/feasibility.svelte';
	import type { LandPlot, ComparableData } from '$lib/stores/feasibility.svelte';
</script>

<AppShell>
	<div class="flex h-full">
		<!-- Spreadsheet panel (slides in at step 4) -->
		<div
			class="flex-shrink-0 overflow-hidden transition-all duration-400 ease-in-out"
			style="width: {feasibilityStore.showSpreadsheet ? '320px' : '0px'};"
		>
			<SpreadsheetPanel />
		</div>

		<!-- Main content -->
		<div class="flex-1 overflow-y-auto">
			<div class="max-w-4xl mx-auto px-4 py-8">
				<!-- Step progress -->
				<StepProgress
					currentStep={feasibilityStore.step}
					onGoToStep={(s) => feasibilityStore.goToStep(s)}
				/>

				<!-- Step content -->
				<div class="transition-all">
					{#if feasibilityStore.step === 1}
						<StepArea onSelect={(a) => feasibilityStore.setArea(a)} />
					{:else if feasibilityStore.step === 2}
						<StepPlot
							area={feasibilityStore.area ?? ''}
							onSelect={(p: LandPlot) => feasibilityStore.setPlot(p)}
						/>
					{:else if feasibilityStore.step === 3}
						<StepComparables
							onApply={(data: ComparableData) => feasibilityStore.applyComparableData(data)}
						/>
					{:else if feasibilityStore.step === 4}
						<div>
							<!-- Spreadsheet toggle -->
							<div class="flex items-center justify-between mb-6">
								<div>
									<h2 class="text-xl font-semibold text-slate-800">Configure your project</h2>
									<p class="text-sm text-slate-500 mt-0.5">
										{feasibilityStore.area} ·
										{feasibilityStore.plot
											? `${feasibilityStore.plot.actual_area.toLocaleString('en-AE', { maximumFractionDigits: 0 })} sqm`
											: 'Custom plot'}
									</p>
								</div>
								<button
									type="button"
									class="flex items-center gap-1.5 px-3 py-2 rounded-lg border text-sm font-medium transition-colors
										{feasibilityStore.showSpreadsheet
											? 'bg-teal-600 border-teal-600 text-white'
											: 'bg-white border-slate-200 text-slate-600 hover:border-teal-400'}"
									onclick={() => feasibilityStore.toggleSpreadsheet()}
								>
									<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 0v10" />
									</svg>
									{feasibilityStore.showSpreadsheet ? 'Hide' : 'Show'} Spreadsheet
								</button>
							</div>

							<ProjectConfigurator />
						</div>
					{/if}
				</div>
			</div>
		</div>
	</div>

	<!-- Floating chat (step 3+) -->
	{#if feasibilityStore.step >= 3}
		<FeasibilityChat />
	{/if}
</AppShell>
