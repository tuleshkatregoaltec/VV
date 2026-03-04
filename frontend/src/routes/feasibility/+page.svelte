<script lang="ts">
	import AppShell from '$lib/components/layout/AppShell.svelte';
	import StepProgress from '$lib/components/feasibility/StepProgress.svelte';
	import StepArea from '$lib/components/feasibility/StepArea.svelte';
	import StepPlot from '$lib/components/feasibility/StepPlot.svelte';
	import StepComparables from '$lib/components/feasibility/StepComparables.svelte';
	import ResearchPanel from '$lib/components/feasibility/ResearchPanel.svelte';
	import SpreadsheetPanel from '$lib/components/feasibility/SpreadsheetPanel.svelte';
	import FeasibilityChat from '$lib/components/feasibility/FeasibilityChat.svelte';
	import { feasibilityStore } from '$lib/stores/feasibility.svelte';
	import type { LandPlot, ComparableData } from '$lib/stores/feasibility.svelte';

	let leftWidth = $state(300);
	let rightWidth = $state(320);
	let isResizing = $state(false);
	let showConfigurator = $state(true);

	function startResize(side: 'left' | 'right', e: MouseEvent) {
		e.preventDefault();
		isResizing = true;
		const startX = e.clientX;
		const startWidth = side === 'left' ? leftWidth : rightWidth;
		function onMove(e: MouseEvent) {
			const delta = e.clientX - startX;
			if (side === 'left') leftWidth = Math.max(200, Math.min(480, startWidth + delta));
			else rightWidth = Math.max(240, Math.min(560, startWidth - delta));
		}
		function onUp() {
			isResizing = false;
			document.removeEventListener('mousemove', onMove);
			document.removeEventListener('mouseup', onUp);
		}
		document.addEventListener('mousemove', onMove);
		document.addEventListener('mouseup', onUp);
	}
</script>

<AppShell>
	<div class="flex h-full min-h-0 overflow-hidden">

		{#if feasibilityStore.step === 4}

			<!-- Left: ProjectConfigurator sidebar -->
			<div
				class="flex-shrink-0 overflow-hidden h-full {isResizing ? '' : 'transition-[width] duration-300 ease-in-out'}"
				style="width: {showConfigurator ? leftWidth : 0}px;"
			>
				<div class="h-full flex flex-col bg-white border-r border-slate-200 overflow-hidden" style="width: {leftWidth}px; min-width: {leftWidth}px;">
					<div class="px-3 pt-3 pb-2 border-b border-slate-200 flex-shrink-0">
						<div class="flex items-center justify-between gap-2">
							<p class="text-xs font-medium text-slate-700 truncate">
								{feasibilityStore.area} ·
								{feasibilityStore.plot
									? `${feasibilityStore.plot.actual_area.toLocaleString('en-AE', { maximumFractionDigits: 0 })} sqm`
									: 'Custom plot'}
							</p>
							{#if import.meta.env.DEV}
								<button
									onclick={() => feasibilityStore.devJump()}
									class="text-[10px] text-slate-400 hover:text-teal-600 border border-dashed border-slate-300 hover:border-teal-400 rounded px-1.5 py-0.5 transition-colors shrink-0"
								>dev</button>
							{/if}
						</div>
					</div>
					<div class="flex-1 min-h-0 overflow-hidden">
						<ResearchPanel />
					</div>
				</div>
			</div>

			<!-- Divider: resize + collapse toggle -->
			<div class="relative flex-shrink-0 h-full flex items-stretch">
				<button
					type="button"
					aria-label="Resize configurator panel"
					tabindex="-1"
					class="w-1.5 cursor-col-resize bg-slate-200 hover:bg-teal-400 active:bg-teal-500 transition-colors p-0 border-0"
					onmousedown={(e) => startResize('left', e)}
				></button>
				<button
					type="button"
					aria-label="{showConfigurator ? 'Hide' : 'Show'} configurator"
					class="absolute top-1/2 -translate-y-1/2 left-full flex items-center justify-center w-4 h-8 rounded-r-md bg-slate-200 hover:bg-teal-400 hover:text-white text-slate-500 transition-colors z-10 border-y border-r border-slate-300"
					onclick={() => (showConfigurator = !showConfigurator)}
				>
					{#if showConfigurator}
						<svg class="w-2.5 h-2.5" viewBox="0 0 8 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
							<path d="M6 1L2 6l4 5" />
						</svg>
					{:else}
						<svg class="w-2.5 h-2.5" viewBox="0 0 8 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
							<path d="M2 1l4 5-4 5" />
						</svg>
					{/if}
				</button>
			</div>

			<!-- Center: SpreadsheetPanel -->
			<div class="flex-1 min-w-0 h-full overflow-hidden">
				<SpreadsheetPanel />
			</div>

			<!-- Right divider + Chat -->
			<button
				type="button"
				aria-label="Resize chat panel"
				tabindex="-1"
				class="w-1 flex-shrink-0 cursor-col-resize bg-slate-200 hover:bg-teal-400 active:bg-teal-500 transition-colors p-0 border-0"
				onmousedown={(e) => startResize('right', e)}
			></button>
			<div class="flex-shrink-0 overflow-hidden h-full" style="width: {rightWidth}px;">
				<FeasibilityChat />
			</div>

		{:else}

			<!-- Steps 1–3: centered content -->
			<div class="flex-1 min-w-0 overflow-y-auto scrollbar-hide">
				<div class="max-w-3xl mx-auto px-6 py-8">
					<div class="flex items-start justify-between">
						<StepProgress
							currentStep={feasibilityStore.step}
							onGoToStep={(s) => feasibilityStore.goToStep(s)}
						/>
						{#if import.meta.env.DEV}
							<button
								onclick={() => feasibilityStore.devJump()}
								class="text-xs text-slate-400 hover:text-teal-600 border border-dashed border-slate-300 hover:border-teal-400 rounded px-2 py-1 transition-colors shrink-0 mt-1"
							>dev: skip to config</button>
						{/if}
					</div>

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
					{/if}
				</div>
			</div>

		{/if}

	</div>
</AppShell>
