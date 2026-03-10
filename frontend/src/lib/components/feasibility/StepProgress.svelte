<script lang="ts">
	let {
		currentStep,
		onGoToStep
	}: {
		currentStep: number;
		onGoToStep: (step: 1 | 2 | 3 | 4) => void;
	} = $props();

	const steps = [
		{ n: 1, label: 'Select Plot' },
		{ n: 2, label: 'Plot & HBU' },
		{ n: 4, label: 'Configure' }
	];
</script>

<div class="flex items-center gap-0 mb-8">
	{#each steps as step, i (step.n)}
		<button
			class="flex items-center gap-2 group"
			onclick={() => onGoToStep(step.n as 1 | 2 | 3 | 4)}
			disabled={step.n > currentStep}
		>
			<div
				class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold transition-colors
					{step.n < currentStep
					? 'bg-teal-500 text-white'
					: step.n === currentStep
						? 'bg-teal-600 text-white ring-4 ring-teal-100'
						: 'bg-slate-100 text-slate-400'}"
			>
				{#if step.n < currentStep}
					<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="3"
							d="M5 13l4 4L19 7"
						/>
					</svg>
				{:else}
					{step.n}
				{/if}
			</div>
			<span
				class="text-sm font-medium transition-colors
					{step.n === currentStep
					? 'text-teal-700'
					: step.n < currentStep
						? 'text-slate-600 group-hover:text-teal-600'
						: 'text-slate-400'}"
			>
				{step.label}
			</span>
		</button>
		{#if i < steps.length - 1}
			<div class="flex-1 h-px mx-3 {step.n < currentStep ? 'bg-teal-300' : 'bg-slate-200'}"></div>
		{/if}
	{/each}
</div>
