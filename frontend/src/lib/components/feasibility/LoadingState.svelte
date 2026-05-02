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
	<div class="w-full max-w-2xl rounded-xl border border-[var(--color-border)] bg-white p-8">
		<p class="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">Generating Study</p>
		<h2 class="mt-3 text-3xl font-semibold text-slate-900">Building the seeded workbook</h2>
		<p class="mt-3 text-sm text-slate-600">
			The backend is researching evidence, setting assumptions, and returning a ready-to-edit first-pass study.
		</p>

		<div class="mt-8 space-y-3">
			{#each loadingSteps as step, index}
				<div class="flex items-center gap-3 rounded-lg border px-4 py-3 {index <= feasibilityWorkspace.loadingStepIndex ? 'border-[var(--color-navy-700)] bg-slate-50 text-[var(--color-fg-1)]' : 'border-[var(--color-border)] bg-slate-50 text-[var(--color-fg-4)]'}">
					<div class="h-2.5 w-2.5 rounded-full {index <= feasibilityWorkspace.loadingStepIndex ? 'bg-[var(--color-navy-700)]' : 'bg-slate-300'}"></div>
					<span class="text-sm font-medium">{step}</span>
				</div>
			{/each}
		</div>
	</div>
</div>
