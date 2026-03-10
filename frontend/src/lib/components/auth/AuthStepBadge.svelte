<script lang="ts">
export let step = ''
export let total = 0
export let label = ''
</script>

<div
	class="inline-flex items-center gap-3 rounded-full border border-white/70 bg-white/80 px-4 py-2 text-xs font-medium uppercase tracking-[0.24em] text-slate-600 shadow-sm backdrop-blur"
>
	<span
		>Step {step}{#if total}
			/ {total}{/if}</span
	>
	{#if label}
		<span class="h-1 w-1 rounded-full bg-slate-300"></span>
		<span class="tracking-[0.18em]">{label}</span>
	{/if}
</div>
