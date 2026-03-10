<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { feasibility } from '$lib/api/feasibility';
	import type { GISPlotSummary } from '$lib/stores/feasibility.svelte';

	let {
		onSelect
	}: {
		onSelect: (plot: GISPlotSummary) => void;
	} = $props();

	type SortKey = 'largest' | 'highest_gfa' | 'verified_first';
	type UsageFilter = 'all' | 'residential' | 'commercial' | 'mixed';

	let communitySearch = $state('');
	let selectedCommunity = $state('');
	let plotSearch = $state('');
	let sizeInput = $state('');
	let verifiedOnly = $state(false);
	let usageFilter = $state<UsageFilter>('all');
	let sortBy = $state<SortKey>('verified_first');
	let plots = $state<GISPlotSummary[]>([]);
	let totalCommunityPlots = $state(0);
	let loading = $state(false);
	let loadError = $state('');
	let fullyLoaded = $state(false);
	const pageSize = 100;

	const communitiesQuery = createQuery(() => ({
		queryKey: ['feasibility-plot-communities'],
		queryFn: () => feasibility.getCommunities(),
		staleTime: Infinity
	}));

	function fmt(n: number) {
		return n.toLocaleString('en-AE', { maximumFractionDigits: 0 });
	}

	function prettyLabel(value: string) {
		return value
			.toLowerCase()
			.split(' ')
			.filter(Boolean)
			.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
			.join(' ');
	}

	function initials(value: string) {
		return prettyLabel(value)
			.split(' ')
			.filter((part) => part.length > 0)
			.map((part) => part[0])
			.join('')
			.toLowerCase();
	}

	function matchesCommunityFilter(value: string, query: string) {
		const q = query.trim().toLowerCase();
		if (!q) return true;
		const label = prettyLabel(value).toLowerCase();
		const compact = label.replace(/[^a-z0-9]/g, '');
		const queryCompact = q.replace(/[^a-z0-9]/g, '');
		return (
			label.includes(q) || compact.includes(queryCompact) || initials(value).includes(queryCompact)
		);
	}

	function inferUsage(plot: GISPlotSummary): UsageFilter {
		const haystack = `${plot.gfa_type} ${plot.land_use_summary.join(' ')}`.toLowerCase();
		const hasRes = ['residential', 'apartment', 'villa', 'townhouse'].some((token) =>
			haystack.includes(token)
		);
		const hasCom = ['commercial', 'office', 'retail', 'shop', 'hotel', 'industrial'].some((token) =>
			haystack.includes(token)
		);
		if (hasRes && hasCom) return 'mixed';
		if (hasRes) return 'residential';
		if (hasCom) return 'commercial';
		return 'all';
	}

	const filteredCommunities = $derived(
		(communitiesQuery.data ?? []).filter((value) => matchesCommunityFilter(value, communitySearch))
	);

	const visiblePlots = $derived.by(() => {
		const q = plotSearch.trim().toLowerCase();
		const targetSize = parseFloat(sizeInput);
		const hasSize = sizeInput.trim() !== '' && !Number.isNaN(targetSize) && targetSize > 0;
		let rows = plots.filter((plot) => {
			if (verifiedOnly && !plot.is_verified) return false;
			if (usageFilter !== 'all') {
				const usage = inferUsage(plot);
				if (usageFilter === 'mixed' ? usage !== 'mixed' : usage !== usageFilter) return false;
			}
			if (hasSize) {
				const min = targetSize * 0.8;
				const max = targetSize * 1.2;
				if (plot.plot_area_sqm < min || plot.plot_area_sqm > max) return false;
			}
			if (!q) return true;
			return (
				plot.plot_number.toLowerCase().includes(q) ||
				plot.project_name.toLowerCase().includes(q) ||
				plot.community_name.toLowerCase().includes(q)
			);
		});

		rows = [...rows].sort((a, b) => {
			if (sortBy === 'largest') return b.plot_area_sqm - a.plot_area_sqm;
			if (sortBy === 'highest_gfa') return b.max_gfa_sqm - a.max_gfa_sqm;
			if (a.is_verified !== b.is_verified) return Number(b.is_verified) - Number(a.is_verified);
			return b.plot_area_sqm - a.plot_area_sqm;
		});
		return rows;
	});

	async function loadCommunityPlots(community: string) {
		if (!community) {
			plots = [];
			totalCommunityPlots = 0;
			fullyLoaded = false;
			loadError = '';
			return;
		}
		loading = true;
		loadError = '';
		try {
			const allRows: GISPlotSummary[] = [];
			let offset = 0;
			while (true) {
				const nextRows = await feasibility.searchPlots({
					community,
					offset,
					limit: pageSize
				});
				allRows.push(...nextRows);
				if (nextRows.length < pageSize) break;
				offset += nextRows.length;
			}
			plots = allRows;
			totalCommunityPlots = allRows.length;
			fullyLoaded = true;
		} catch (err) {
			plots = [];
			totalCommunityPlots = 0;
			fullyLoaded = false;
			loadError = err instanceof Error ? err.message : 'Failed to load plots for this community.';
		} finally {
			loading = false;
		}
	}

	function pickCommunity(value: string) {
		selectedCommunity = value;
		plotSearch = '';
		sizeInput = '';
		verifiedOnly = false;
		usageFilter = 'all';
		sortBy = 'verified_first';
		loadCommunityPlots(value);
	}
</script>

<div class="max-w-6xl mx-auto">
	<h2 class="text-xl font-semibold text-slate-800 mb-1">Select a plot</h2>
	<p class="text-sm text-slate-500 mb-6">
		Browse GIS plots by area, then filter the full community inventory by size, verification, and
		product type. You should not need to know plot IDs.
	</p>

	<div class="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
		<div
			class="rounded-[30px] border border-slate-200/80 bg-white overflow-hidden shadow-[0_24px_70px_-42px_rgba(15,23,42,0.38)]"
		>
			<div
				class="px-5 py-5 border-b border-slate-200 bg-[linear-gradient(180deg,#fbfdff_0%,#eef7f5_100%)]"
			>
				<p class="text-xs font-medium tracking-[0.14em] uppercase text-slate-400 mb-2">Areas</p>
				<p class="text-sm text-slate-500 mb-4">
					Pick a GIS community to load all of its plots before filtering.
				</p>
				<div class="relative">
					<div class="pointer-events-none absolute inset-y-0 left-3 flex items-center">
						<svg
							class="w-4 h-4 text-slate-400"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
						>
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
						class="w-full pl-9 pr-4 py-2.5 rounded-xl border border-slate-200 bg-white text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500 transition-all"
						placeholder="Filter areas..."
						bind:value={communitySearch}
					/>
				</div>
			</div>

			<div class="max-h-[42rem] overflow-y-auto bg-white">
				{#if communitiesQuery.isPending}
					<div class="px-5 py-8 text-sm text-slate-400">Loading GIS communities…</div>
				{:else if filteredCommunities.length === 0}
					<div class="px-5 py-8 text-sm text-slate-400">No GIS communities match that search.</div>
				{:else}
					{#each filteredCommunities as value (value)}
						<button
							type="button"
							class="w-full text-left px-5 py-3.5 border-b border-slate-100 last:border-0 transition-colors {selectedCommunity ===
							value
								? 'bg-teal-50/80 text-teal-700'
								: 'text-slate-700 hover:bg-slate-50'}"
							onclick={() => pickCommunity(value)}
						>
							<div class="flex items-center justify-between gap-3">
								<div>
									<span class="text-sm font-medium">{prettyLabel(value)}</span>
									<p class="text-xs text-slate-400 mt-0.5">GIS plot community</p>
								</div>
								{#if selectedCommunity === value}
									<span class="text-[10px] px-2 py-0.5 rounded-full bg-teal-100 text-teal-700"
										>Selected</span
									>
								{/if}
							</div>
						</button>
					{/each}
				{/if}
			</div>
		</div>

		<div
			class="rounded-[30px] border border-slate-200/80 bg-white overflow-hidden shadow-[0_24px_70px_-42px_rgba(15,23,42,0.38)]"
		>
			<div
				class="px-5 py-5 border-b border-slate-200 bg-[linear-gradient(180deg,#ffffff_0%,#f7fafc_100%)]"
			>
				<div class="flex items-start justify-between gap-4">
					<div>
						<p class="text-xs font-medium tracking-[0.14em] uppercase text-slate-400">
							Plot Inventory
						</p>
						<p class="text-sm text-slate-700 mt-1">
							{#if selectedCommunity}
								Browsing <span class="font-semibold">{prettyLabel(selectedCommunity)}</span>
							{:else}
								Select an area on the left to browse plots
							{/if}
						</p>
					</div>
					<div class="text-right">
						{#if selectedCommunity}
							<p class="text-xs text-slate-400">
								{visiblePlots.length} visible · {totalCommunityPlots} loaded
							</p>
							<p class="text-[11px] text-slate-400 mt-1">
								{fullyLoaded
									? 'Filters are applied against the full loaded community inventory.'
									: 'Loading community inventory…'}
							</p>
						{/if}
					</div>
				</div>

				<div class="grid gap-3 mt-4 md:grid-cols-[1.4fr_0.7fr_0.8fr_0.8fr_auto]">
					<div class="relative">
						<div class="pointer-events-none absolute inset-y-0 left-3 flex items-center">
							<svg
								class="w-4 h-4 text-slate-400"
								fill="none"
								viewBox="0 0 24 24"
								stroke="currentColor"
							>
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
							class="w-full pl-9 pr-4 py-2.5 rounded-xl border border-slate-200 bg-white text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500 transition-all"
							placeholder="Search within area..."
							bind:value={plotSearch}
						/>
					</div>

					<input
						type="number"
						class="w-full px-4 py-2.5 rounded-xl border border-slate-200 bg-white text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500 transition-all"
						placeholder="Size sqm"
						bind:value={sizeInput}
						min="0"
					/>

					<select
						class="w-full px-4 py-2.5 rounded-xl border border-slate-200 bg-white text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500 transition-all"
						bind:value={usageFilter}
					>
						<option value="all">All uses</option>
						<option value="residential">Residential</option>
						<option value="commercial">Commercial</option>
						<option value="mixed">Mixed use</option>
					</select>

					<select
						class="w-full px-4 py-2.5 rounded-xl border border-slate-200 bg-white text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500 transition-all"
						bind:value={sortBy}
					>
						<option value="verified_first">Verified first</option>
						<option value="largest">Largest plots</option>
						<option value="highest_gfa">Highest GFA</option>
					</select>

					<label
						class="inline-flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl border border-slate-200 bg-white text-sm text-slate-700"
					>
						<input
							type="checkbox"
							bind:checked={verifiedOnly}
							class="rounded border-slate-300 text-teal-600 focus:ring-teal-500"
						/>
						Verified
					</label>
				</div>
			</div>

			<div
				class="min-h-[34rem] max-h-[42rem] overflow-y-auto p-5 bg-[radial-gradient(circle_at_top_left,rgba(20,184,166,0.05),transparent_35%)]"
			>
				{#if loading}
					<div class="flex items-center gap-2 text-sm text-slate-400 py-4">
						<div
							class="w-4 h-4 border-2 border-teal-400 border-t-transparent rounded-full animate-spin"
						></div>
						Loading full community inventory…
					</div>
				{:else if loadError}
					<div class="rounded-2xl border border-rose-200 bg-rose-50 px-6 py-8 text-center">
						<p class="text-sm font-medium text-rose-700">Could not load plots.</p>
						<p class="text-sm text-rose-600 mt-1">{loadError}</p>
					</div>
				{:else if !selectedCommunity}
					<div
						class="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-6 py-12 text-center"
					>
						<p class="text-sm font-medium text-slate-600">Choose an area on the left.</p>
						<p class="text-sm text-slate-400 mt-1">
							The plot list will populate immediately so you can browse and filter without a plot
							ID.
						</p>
					</div>
				{:else if visiblePlots.length === 0}
					<div
						class="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-6 py-12 text-center"
					>
						<p class="text-sm font-medium text-slate-600">No plots match the current filters.</p>
						<p class="text-sm text-slate-400 mt-1">
							Try removing the size or usage filter, or choosing a different community.
						</p>
					</div>
				{:else}
					<div class="space-y-3">
						{#each visiblePlots as p (p.plot_number)}
							<button
								type="button"
								class="w-full text-left p-4 rounded-2xl border border-slate-200 bg-white hover:border-teal-400 hover:bg-teal-50 transition-all group shadow-[0_10px_24px_-20px_rgba(15,23,42,0.45)]"
								onclick={() => onSelect(p)}
							>
								<div class="flex items-start justify-between gap-4">
									<div class="min-w-0">
										<div class="flex items-center gap-2 flex-wrap">
											<p
												class="text-sm font-semibold text-slate-800 group-hover:text-teal-700 truncate"
											>
												{p.plot_number}
											</p>
											<span
												class="px-2 py-0.5 rounded-full text-[10px] font-medium {p.is_verified
													? 'bg-emerald-100 text-emerald-700'
													: 'bg-amber-100 text-amber-700'}"
											>
												{p.is_verified ? 'Verified' : 'Unverified'}
											</span>
										</div>
										<p class="text-xs text-slate-500 mt-0.5 truncate">
											{prettyLabel(p.community_name || 'Unknown community')}
										</p>
										{#if p.project_name}
											<p class="text-xs text-slate-400 truncate">{p.project_name}</p>
										{/if}
										{#if p.land_use_summary.length > 0}
											<div class="flex flex-wrap gap-1.5 mt-2">
												{#each p.land_use_summary.slice(0, 3) as tag (tag)}
													<span
														class="px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 text-[10px] font-medium"
													>
														{tag}
													</span>
												{/each}
											</div>
										{/if}
									</div>

									<div class="text-right flex-shrink-0">
										<p class="text-sm font-bold text-slate-800">{fmt(p.plot_area_sqm)} sqm</p>
										<p class="text-[11px] text-slate-500 mt-0.5">
											Max GFA {p.max_gfa_sqm > 0 ? fmt(p.max_gfa_sqm) : '—'} sqm
										</p>
										{#if p.max_height}
											<p class="text-[11px] text-slate-400">Height {p.max_height}</p>
										{/if}
									</div>
								</div>
							</button>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>
