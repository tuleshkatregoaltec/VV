<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { Chart, registerables } from 'chart.js'
import { onMount } from 'svelte'
import { analytics, type ProjectSearchItem } from '$lib/api/analytics'

Chart.register(...registerables)

let { selection }: { selection: ProjectSearchItem } = $props()

let subProject = $state<string | null>(null)

// Reset sub-project when selection changes
$effect(() => {
	selection
	subProject = null
})

const subProjectsQuery = createQuery(() => ({
	queryKey: ['sub-projects', selection.name],
	queryFn: () => analytics.subProjects(selection.name, selection.filter_type),
	staleTime: 10 * 60_000,
	enabled: selection.filter_type !== 'project'
}))

const queryParams = $derived(
	subProject
		? { project: subProject, masterProject: selection.name }
		: selection.filter_type === 'project'
			? { project: selection.name }
			: { masterProject: selection.name, filterType: selection.filter_type }
)

const summaryQuery = createQuery(() => ({
	queryKey: ['project-summary', selection.name, subProject],
	queryFn: () => analytics.projectSummary(queryParams),
	staleTime: 5 * 60_000
}))

const trendsQuery = createQuery(() => ({
	queryKey: ['project-trends', selection.name, subProject],
	queryFn: () => analytics.projectTrends(queryParams, 365),
	staleTime: 5 * 60_000
}))

const subProjects = $derived(subProjectsQuery.data?.sub_projects ?? [])

// Sub-project dropdown state
let subDropdownOpen = $state(false)
let subSearch = $state('')

const filteredSubProjects = $derived(
	subSearch.trim()
		? subProjects.filter((sp) => sp.name.toLowerCase().includes(subSearch.toLowerCase()))
		: subProjects
)

function stripPrefix(name: string): string {
	return name.replace(selection.name, '').replace(/^[\s\-–]+/, '') || name
}

function clickOutside(node: HTMLElement, callback: () => void) {
	function handle(e: MouseEvent) {
		if (!node.contains(e.target as Node)) callback()
	}
	document.addEventListener('mousedown', handle, true)
	return {
		destroy() {
			document.removeEventListener('mousedown', handle, true)
		}
	}
}

function closeSubDropdown() {
	subDropdownOpen = false
	subSearch = ''
}

function handleSubKeydown(e: KeyboardEvent) {
	if (e.key === 'Escape') {
		closeSubDropdown()
	}
	if (e.key === 'Enter') {
		e.preventDefault()
		if (filteredSubProjects.length > 0) {
			subProject = filteredSubProjects[0].name
			closeSubDropdown()
		}
	}
}

// Chart canvases
let trendCanvas = $state<HTMLCanvasElement>()
let typeCanvas = $state<HTMLCanvasElement>()
let regCanvas = $state<HTMLCanvasElement>()
let trendChart: Chart | null = null
let typeChart: Chart | null = null
let regChart: Chart | null = null

const TEAL_PALETTE = [
	'rgba(13,148,136,0.85)',
	'rgba(20,184,166,0.85)',
	'rgba(94,234,212,0.85)',
	'rgba(153,246,228,0.85)',
	'rgba(6,182,212,0.85)',
	'rgba(8,145,178,0.85)'
]

function fmt(n: number): string {
	if (n >= 1_000_000_000) return `AED ${(n / 1_000_000_000).toFixed(2)}B`
	if (n >= 1_000_000) return `AED ${(n / 1_000_000).toFixed(2)}M`
	if (n >= 1_000) return `AED ${(n / 1_000).toFixed(0)}K`
	return `AED ${Math.round(n).toLocaleString()}`
}

function fmtShort(n: number): string {
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
	if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`
	return Math.round(n).toLocaleString()
}

function buildTrendChart() {
	if (!trendCanvas || !trendsQuery.data?.data?.length) return
	trendChart?.destroy()
	const ctx = trendCanvas.getContext('2d')
	if (!ctx) return
	const pts = trendsQuery.data.data
	trendChart = new Chart(ctx, {
		type: 'line',
		data: {
			labels: pts.map((p) => {
				const d = new Date(p.date)
				return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
			}),
			datasets: [
				{
					label: 'Avg Sale Price (AED)',
					data: pts.map((p) => p.avg_price),
					borderColor: 'rgb(13,148,136)',
					backgroundColor: 'rgba(13,148,136,0.08)',
					borderWidth: 2,
					fill: true,
					tension: 0.3,
					pointRadius: 2,
					pointHoverRadius: 4
				}
			]
		},
		options: {
			responsive: true,
			maintainAspectRatio: false,
			plugins: {
				legend: { display: false },
				tooltip: {
					callbacks: {
						label: (ctx) => ` ${fmt(ctx.parsed.y)}`
					}
				}
			},
			scales: {
				x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } },
				y: {
					beginAtZero: false,
					grid: { color: 'rgba(0,0,0,0.04)' },
					ticks: { callback: (v) => fmtShort(Number(v)) }
				}
			}
		}
	})
}

function buildDonutChart(
	canvas: HTMLCanvasElement,
	labels: string[],
	values: number[],
	existing: Chart | null
): Chart {
	existing?.destroy()
	const ctx = canvas.getContext('2d')
	if (!ctx) {
		throw new Error('Canvas 2D context unavailable')
	}
	return new Chart(ctx, {
		type: 'doughnut',
		data: {
			labels,
			datasets: [
				{
					data: values,
					backgroundColor: TEAL_PALETTE,
					borderWidth: 2,
					borderColor: '#fff'
				}
			]
		},
		options: {
			responsive: true,
			maintainAspectRatio: false,
			cutout: '62%',
			plugins: {
				legend: {
					position: 'right',
					labels: { boxWidth: 12, font: { size: 11 }, padding: 8 }
				},
				tooltip: {
					callbacks: {
						label: (ctx) => ` ${ctx.label}: ${ctx.parsed}%`
					}
				}
			}
		}
	})
}

$effect(() => {
	if (trendsQuery.data) buildTrendChart()
})

$effect(() => {
	const data = summaryQuery.data
	if (!data) return

	if (typeCanvas && data.by_property_type.length) {
		typeChart = buildDonutChart(
			typeCanvas,
			data.by_property_type.map((d) => d.property_type),
			data.by_property_type.map((d) => d.pct_of_total),
			typeChart
		)
	}
	if (regCanvas && data.by_reg_type.length) {
		regChart = buildDonutChart(
			regCanvas,
			data.by_reg_type.map((d) => d.reg_type),
			data.by_reg_type.map((d) => d.pct_of_total),
			regChart
		)
	}
})

onMount(() => {
	return () => {
		trendChart?.destroy()
		typeChart?.destroy()
		regChart?.destroy()
	}
})
</script>

<div class="space-y-6">
	{#if summaryQuery.isLoading}
		<!-- Skeleton -->
		<div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
			{#each [0, 1, 2, 3] as skeleton (skeleton)}
				<div class="bg-white rounded-xl p-4 border border-slate-100 animate-pulse">
					<div class="h-3 w-20 bg-slate-200 rounded mb-3"></div>
					<div class="h-7 w-28 bg-slate-200 rounded"></div>
				</div>
			{/each}
		</div>
	{:else if summaryQuery.data}
		{@const d = summaryQuery.data}

		<!-- Sub-project selector -->
		{#if subProjects.length > 1}
			<div class="relative" use:clickOutside={closeSubDropdown}>
				<button
					type="button"
					onclick={() => {
						subDropdownOpen = !subDropdownOpen;
						subSearch = '';
					}}
					class="flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm text-slate-700 hover:border-teal-400 transition-colors"
				>
					<span class="font-medium">
						{subProject
							? stripPrefix(subProject)
							: `All development (${subProjects.length} sub-projects)`}
					</span>
					<svg
						class="w-4 h-4 text-slate-400 ml-1"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M19 9l-7 7-7-7"
						/>
					</svg>
				</button>

				{#if subDropdownOpen}
					<div
						class="absolute z-50 mt-1 w-80 rounded-lg border border-slate-200 bg-white shadow-lg"
					>
						<div class="p-2 border-b border-slate-100">
							<input
								type="text"
								class="w-full px-3 py-1.5 rounded-md border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
								placeholder="Filter sub-projects..."
								bind:value={subSearch}
								onkeydown={handleSubKeydown}
								autofocus
							/>
						</div>
						<div class="max-h-64 overflow-y-auto">
							<button
								type="button"
								class="w-full text-left px-3 py-2 text-sm transition-colors {subProject === null
									? 'bg-teal-50 text-teal-700 font-medium'
									: 'text-slate-700 hover:bg-slate-50'}"
								onmousedown={() => {
									subProject = null;
									subDropdownOpen = false;
									subSearch = '';
								}}
							>
								All development
							</button>
							{#each filteredSubProjects as sp (sp.project_id ?? sp.name)}
								<button
									type="button"
									class="w-full text-left px-3 py-2 text-sm transition-colors {subProject ===
									sp.name
										? 'bg-teal-50 text-teal-700 font-medium'
										: 'text-slate-700 hover:bg-slate-50'}"
									onmousedown={() => {
										subProject = sp.name;
										subDropdownOpen = false;
										subSearch = '';
									}}
								>
									{stripPrefix(sp.name)}
								</button>
							{/each}
							{#if filteredSubProjects.length === 0}
								<div class="px-3 py-2 text-sm text-slate-400">No matches</div>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		{/if}

		<!-- Project meta bar -->
		{#if d.project}
			<div class="flex flex-wrap gap-4 text-xs text-slate-500">
				{#if d.project.developer_name}
					<span
						><span class="font-medium text-slate-700">Developer:</span>
						{d.project.developer_name}</span
					>
				{/if}
				{#if d.project.area_name}
					<span><span class="font-medium text-slate-700">Area:</span> {d.project.area_name}</span>
				{/if}
				{#if d.project.project_status}
					<span
						><span class="font-medium text-slate-700">Status:</span>
						{d.project.project_status}</span
					>
				{/if}
				{#if d.project.no_of_units}
					<span
						><span class="font-medium text-slate-700">Units:</span>
						{d.project.no_of_units.toLocaleString()}</span
					>
				{/if}
				{#if d.project.percent_completed != null}
					<span
						><span class="font-medium text-slate-700">Completion:</span>
						{d.project.percent_completed}%</span
					>
				{/if}
			</div>
		{/if}

		<!-- KPI strip -->
		<div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
			<div class="bg-white rounded-xl p-4 border border-slate-100">
				<p class="text-xs font-medium text-slate-500 mb-1">Total Sales</p>
				<p class="text-2xl font-bold text-slate-900">
					{d.sales.transaction_count.toLocaleString()}
				</p>
				<p class="text-xs text-slate-400 mt-1">transactions</p>
			</div>
			<div class="bg-white rounded-xl p-4 border border-slate-100">
				<p class="text-xs font-medium text-slate-500 mb-1">Avg Sale Price</p>
				<p class="text-2xl font-bold text-slate-900">{fmt(d.sales.avg_price)}</p>
				<p class="text-xs text-slate-400 mt-1">{fmt(d.sales.avg_price_sqm)}/sqm</p>
			</div>
			<div class="bg-white rounded-xl p-4 border border-slate-100">
				<p class="text-xs font-medium text-slate-500 mb-1">Median Annual Rent</p>
				<p class="text-2xl font-bold text-slate-900">{fmt(d.rentals.median_annual_rent)}</p>
				<p class="text-xs text-slate-400 mt-1">
					{d.rentals.contract_count.toLocaleString()} contracts
				</p>
			</div>
			<div class="bg-white rounded-xl p-4 border border-teal-100 bg-teal-50/40">
				<p class="text-xs font-medium text-teal-600 mb-1">Gross Yield</p>
				<p class="text-2xl font-bold text-teal-700">
					{d.overall_gross_yield_pct != null ? `${d.overall_gross_yield_pct.toFixed(1)}%` : '—'}
				</p>
				<p class="text-xs text-teal-500 mt-1">median rent ÷ median sale</p>
			</div>
		</div>

		<!-- Bedroom analytics table -->
		{#if d.by_rooms.length > 0}
			<div class="bg-white rounded-xl border border-slate-100 overflow-hidden">
				<div class="px-4 py-3 border-b border-slate-100">
					<h3 class="text-sm font-semibold text-slate-700">Sales by Bedroom</h3>
				</div>
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="bg-slate-50 text-xs font-medium text-slate-500 uppercase tracking-wide">
								<th class="text-left px-4 py-2.5">Rooms</th>
								<th class="text-right px-4 py-2.5">Sales</th>
								<th class="text-right px-4 py-2.5">Avg Sale Price</th>
								<th class="text-right px-4 py-2.5">Price/sqm</th>
								<th class="text-right px-4 py-2.5">
									<span class="inline-flex items-center justify-end gap-1">
										Est. Annual Rent
										<span class="group relative cursor-default">
											<svg
												class="w-3.5 h-3.5 text-slate-400"
												fill="none"
												viewBox="0 0 24 24"
												stroke="currentColor"
											>
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													stroke-width="2"
													d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
												/>
											</svg>
											<div
												class="pointer-events-none absolute top-full right-0 mt-2 z-50 w-72 rounded-lg bg-slate-800 px-3 py-2 text-xs font-normal text-slate-200 opacity-0 shadow-lg transition-opacity group-hover:opacity-100 normal-case tracking-normal"
											>
												Median annual rent inferred from Ejari contracts matched by unit area. Shown
												only when enough rental data exists for this bedroom type.
											</div>
										</span>
									</span>
								</th>
								<th class="text-right px-4 py-2.5">
									<span class="inline-flex items-center justify-end gap-1 text-teal-600">
										Gross Yield
										<span class="group relative cursor-default">
											<svg
												class="w-3.5 h-3.5 text-slate-400"
												fill="none"
												viewBox="0 0 24 24"
												stroke="currentColor"
											>
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													stroke-width="2"
													d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
												/>
											</svg>
											<div
												class="pointer-events-none absolute top-full right-0 mt-2 z-50 w-72 rounded-lg bg-slate-800 px-3 py-2 text-xs font-normal text-slate-200 opacity-0 shadow-lg transition-opacity group-hover:opacity-100 normal-case tracking-normal"
											>
												Median annual rent ÷ median existing-market sale price. Off-plan prices
												excluded to avoid inflated yields.
											</div>
										</span>
									</span>
								</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-slate-50">
							{#each d.by_rooms as row (row.rooms)}
								<tr class="hover:bg-slate-50/50 transition-colors">
									<td class="px-4 py-3 font-medium text-slate-800">{row.rooms}</td>
									<td class="px-4 py-3 text-right text-slate-600"
										>{row.sale_count.toLocaleString()}</td
									>
									<td class="px-4 py-3 text-right text-slate-800 font-medium"
										>{fmt(row.avg_sale_price)}</td
									>
									<td class="px-4 py-3 text-right text-slate-500">{fmt(row.avg_sale_price_sqm)}</td>
									<td class="px-4 py-3 text-right text-slate-700">
										{row.median_annual_rent > 0 ? fmt(row.median_annual_rent) : '—'}
									</td>
									<td
										class="px-4 py-3 text-right font-semibold {row.gross_yield_pct != null
											? 'text-teal-600'
											: 'text-slate-400'}"
									>
										{row.gross_yield_pct != null ? `${row.gross_yield_pct.toFixed(1)}%` : '—'}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}

		<!-- Price trend chart -->
		<div class="bg-white rounded-xl border border-slate-100 p-4">
			<h3 class="text-sm font-semibold text-slate-700 mb-4">Sale Price Trend (12 months)</h3>
			{#if trendsQuery.isLoading}
				<div class="h-48 bg-slate-100 rounded animate-pulse"></div>
			{:else if trendsQuery.data?.data?.length}
				<div style="height: 200px">
					<canvas bind:this={trendCanvas}></canvas>
				</div>
			{:else}
				<div class="h-48 flex items-center justify-center text-slate-400 text-sm">
					No trend data
				</div>
			{/if}
		</div>

		<!-- Donut charts row -->
		{#if d.by_property_type.length || d.by_reg_type.length}
			<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
				{#if d.by_property_type.length}
					<div class="bg-white rounded-xl border border-slate-100 p-4">
						<h3 class="text-sm font-semibold text-slate-700 mb-4">Property Type Split</h3>
						<div style="height: 160px">
							<canvas bind:this={typeCanvas}></canvas>
						</div>
					</div>
				{/if}
				{#if d.by_reg_type.length}
					<div class="bg-white rounded-xl border border-slate-100 p-4">
						<h3 class="text-sm font-semibold text-slate-700 mb-4">Ready vs Off-plan</h3>
						<div style="height: 160px">
							<canvas bind:this={regCanvas}></canvas>
						</div>
					</div>
				{/if}
			</div>
		{/if}

		<!-- Unit composition -->
		{#if d.unit_composition.length && !subProject}
			<div class="bg-white rounded-xl border border-slate-100 p-4">
				<h3 class="text-sm font-semibold text-slate-700 mb-3">Unit Supply Composition</h3>
				<div class="space-y-2">
					{#each d.unit_composition as u (u.rooms)}
						<div class="flex items-center gap-3">
							<span class="text-xs text-slate-600 w-16 flex-shrink-0">{u.rooms}</span>
							<div class="flex-1 bg-slate-100 rounded-full h-2">
								<div
									class="bg-teal-500 h-2 rounded-full transition-all duration-500"
									style="width: {u.pct_of_total}%"
								></div>
							</div>
							<span class="text-xs text-slate-500 w-16 text-right"
								>{u.count.toLocaleString()} ({u.pct_of_total}%)</span
							>
						</div>
					{/each}
				</div>
			</div>
		{/if}
	{:else if summaryQuery.isError}
		<div class="bg-red-50 border border-red-200 rounded-xl p-6 text-center text-sm text-red-600">
			Failed to load analytics for this project.
		</div>
	{/if}
</div>
