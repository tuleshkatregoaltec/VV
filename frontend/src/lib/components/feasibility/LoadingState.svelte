<script lang="ts">
import { onMount } from 'svelte'

import { feasibilityWorkspace, loadingSteps } from '$lib/stores/feasibilityWorkspace.svelte'

onMount(() => {
	feasibilityWorkspace.resetLoading()
	const timer = setInterval(() => feasibilityWorkspace.advanceLoadingStep(), 1100)
	return () => clearInterval(timer)
})
</script>

<div class="flex h-full min-h-0 items-center justify-center overflow-hidden px-6 py-6">
	<div class="w-full max-w-2xl rounded-[32px] border border-slate-200 bg-white p-8 shadow-sm">
		<p class="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">Generating Study</p>
		<h2 class="mt-3 text-3xl font-semibold text-slate-900">Building the seeded workbook</h2>
		<p class="mt-3 text-sm text-slate-600">
			The backend is researching evidence, setting assumptions, and returning a ready-to-edit first-pass study.
		</p>

		<div class="mt-8 space-y-3">
			{#each loadingSteps as step, index}
				<div class="flex items-center gap-3 rounded-2xl border px-4 py-3 {index <= feasibilityWorkspace.loadingStepIndex ? 'border-teal-200 bg-teal-50 text-teal-700' : 'border-slate-200 bg-slate-50 text-slate-500'}">
					<div class="h-2.5 w-2.5 rounded-full {index <= feasibilityWorkspace.loadingStepIndex ? 'bg-teal-500' : 'bg-slate-300'}"></div>
					<span class="text-sm font-medium">{step}</span>
				</div>
			{/each}
		</div>
	</div>
</div>
