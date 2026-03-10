<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { feasibility } from '$lib/api/feasibility';

	let { onSelect }: { onSelect: (area: string) => void } = $props();

	let search = $state('');
	let isOpen = $state(false);

	const areasQuery = createQuery(() => ({
		queryKey: ['feasibility-areas'],
		queryFn: () => feasibility.getAreas(),
		staleTime: Infinity
	}));

	const filtered = $derived(
		search.trim()
			? (areasQuery.data ?? []).filter((a) => a.toLowerCase().includes(search.toLowerCase()))
			: (areasQuery.data ?? [])
	);

	function clickOutside(node: HTMLElement, cb: () => void) {
		function handle(e: MouseEvent) {
			if (!node.contains(e.target as Node)) cb();
		}
		document.addEventListener('mousedown', handle, true);
		return {
			destroy() {
				document.removeEventListener('mousedown', handle, true);
			}
		};
	}
</script>

<div class="max-w-md mx-auto">
	<h2 class="text-xl font-semibold text-slate-800 mb-2">Select an area</h2>
	<p class="text-sm text-slate-500 mb-6">
		Choose the Dubai area where your project will be located.
	</p>

	<div class="relative" use:clickOutside={() => (isOpen = false)}>
		<div class="relative">
			<div class="pointer-events-none absolute inset-y-0 left-3 flex items-center">
				<svg class="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
					/>
				</svg>
			</div>
			<input
				type="text"
				class="w-full pl-9 pr-4 py-3 rounded-xl border border-slate-200 bg-white text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500 transition-all"
				placeholder="Search area..."
				bind:value={search}
				oninput={() => (isOpen = true)}
				onfocus={() => (isOpen = true)}
			/>
		</div>

		{#if isOpen}
			<div
				class="absolute z-50 mt-1 w-full max-h-72 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-lg"
			>
				{#if areasQuery.isLoading}
					<div class="px-4 py-3 text-sm text-slate-400">Loading areas...</div>
				{:else if filtered.length === 0}
					<div class="px-4 py-3 text-sm text-slate-400">No areas found</div>
				{:else}
					{#each filtered as area}
						<button
							type="button"
							class="w-full text-left px-4 py-2.5 text-sm text-slate-900 hover:bg-teal-50 hover:text-teal-700 transition-colors"
							onmousedown={() => {
								onSelect(area);
								search = area;
								isOpen = false;
							}}
						>
							{area}
						</button>
					{/each}
				{/if}
			</div>
		{/if}
	</div>
</div>
