<script lang="ts">
	let {
		options = ['Residential', 'Commercial'],
		selected = $bindable('Residential'),
		onchange
	}: {
		options?: string[];
		selected?: string;
		onchange?: (newValue: string) => void;
	} = $props();

	function toggleOption(option: string) {
		selected = option;
		onchange?.(option);
	}

	// For sliding indicator
	let selectedIdx = $derived(options.findIndex((o) => o === selected));
</script>

<div
	class="relative flex gap-0 bg-white/80 backdrop-blur-xl rounded-full p-0.5 border border-black-pale w-fit min-w-[160px]"
>
	<!-- Sliding indicator -->
	<div
		class="absolute top-0 left-0 h-full rounded-full bg-black transition-transform duration-300 z-0"
		style="width:calc(100% / {options.length}); transform: translateX({selectedIdx * 100}%);"
	></div>
	{#each options as option (option)}
		<button
			onclick={() => toggleOption(option)}
			class="relative z-10 flex-1 px-4 py-1 rounded-full font-semibold transition-all duration-300
                {selected === option ? 'text-white' : 'text-slate-700 hover:text-black'}"
			style="min-width: 80px;"
		>
			{option}
		</button>
	{/each}
</div>
