<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { Chart, registerables } from 'chart.js'
import { onMount } from 'svelte'
import type {
	ProjectAnalyticsResponse,
	ProjectConfigurationRow,
	ProjectSearchItem,
	ProjectTrendPoint
} from '$lib/api/analytics'
import { analyticsQueries } from '$lib/queries/analytics'
import { getChartTheme } from '$lib/utils/chartTheme'
import AnalyticsError from './AnalyticsError.svelte'

Chart.register(...registerables)

let {
	projectA,
	projectB
}: {
	projectA: ProjectSearchItem
	projectB: ProjectSearchItem
} = $props()

type TrendMode = 'avg_price' | 'avg_price_sqft'
type DeltaMode = 'pct_change' | 'points'

let trendMode = $state<TrendMode>('avg_price')
let trendCanvas = $state<HTMLCanvasElement>()
let marketSplitCanvas = $state<HTMLCanvasElement>()
let themeVersion = $state(0)

let trendChart: Chart | null = null
let marketSplitChart: Chart | null = null

const paramsA = $derived(toQueryParams(projectA))
const paramsB = $derived(toQueryParams(projectB))

const summaryQueryA = createQuery(() => analyticsQueries.projectSummary(paramsA))
const summaryQueryB = createQuery(() => analyticsQueries.projectSummary(paramsB))
const trendsQueryA = createQuery(() => analyticsQueries.projectTrends(paramsA, 365))
const trendsQueryB = createQuery(() => analyticsQueries.projectTrends(paramsB, 365))
const subProjectsQueryA = createQuery(() =>
	analyticsQueries.subProjects(projectA.name, projectA.filter_type)
)
const subProjectsQueryB = createQuery(() =>
	analyticsQueries.subProjects(projectB.name, projectB.filter_type)
)

const summaryA = $derived(summaryQueryA.data ?? null)
const summaryB = $derived(summaryQueryB.data ?? null)
const loading = $derived(summaryQueryA.isLoading || summaryQueryB.isLoading)
const error = $derived(summaryQueryA.isError || summaryQueryB.isError)

function toQueryParams(selection: ProjectSearchItem) {
	if (selection.filter_type === 'market') return {}
	if (selection.filter_type === 'building') return { buildingId: selection.building_id ?? '' }
	return selection.filter_type === 'project'
		? { project: selection.name }
		: { masterProject: selection.name, filterType: selection.filter_type }
}

function isMarketSelection(selection: ProjectSearchItem): boolean {
	return selection.filter_type === 'market'
}

function isMasterSelection(selection: ProjectSearchItem): boolean {
	return !['project', 'market', 'building'].includes(selection.filter_type)
}

function fmtCurrency(n: number | null | undefined): string {
	if (n == null || !Number.isFinite(n) || n <= 0) return '-'
	return `AED ${n.toLocaleString('en-AE', { maximumFractionDigits: 2 })}`
}

function fmtCompact(n: number | null | undefined): string {
	if (n == null || !Number.isFinite(n)) return '-'
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
	if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`
	return Math.round(n).toLocaleString('en-AE')
}

function fmtNumber(n: number | null | undefined, digits = 0): string {
	if (n == null || !Number.isFinite(n)) return '-'
	return n.toLocaleString('en-AE', {
		minimumFractionDigits: digits,
		maximumFractionDigits: digits
	})
}

function fmtPct(n: number | null | undefined, digits = 1): string {
	if (n == null || !Number.isFinite(n)) return '-'
	return `${fmtNumber(n, digits)}%`
}

function fmtSignedPct(n: number | null | undefined, digits = 1): string {
	if (n == null || !Number.isFinite(n)) return '-'
	const prefix = n > 0 ? '+' : n < 0 ? '-' : ''
	return `${prefix}${fmtNumber(Math.abs(n), digits)}%`
}

function fmtSignedPoints(n: number | null | undefined, digits = 1): string {
	if (n == null || !Number.isFinite(n)) return '-'
	const prefix = n > 0 ? '+' : n < 0 ? '-' : ''
	return `${prefix}${fmtNumber(Math.abs(n), digits)} pp`
}

function deltaTone(value: number | null | undefined): string {
	if (value == null || !Number.isFinite(value)) return 'text-fg-5'
	if (value > 0) return 'text-success'
	if (value < 0) return 'text-error'
	return 'text-fg-4'
}

function statusBadgeClass(status: string | null | undefined): string {
	const s = (status ?? '').toLowerCase()
	if (s.includes('complet') || s.includes('handov') || s.includes('deliver')) {
		return 'bg-success-bg text-success ring-1 ring-border'
	}
	if (
		s.includes('construct') ||
		s.includes('progress') ||
		s.includes('active') ||
		s.includes('plan')
	) {
		return 'bg-warning-bg text-warning ring-1 ring-border'
	}
	if (s.includes('cancel')) return 'bg-error-bg text-error ring-1 ring-border'
	return 'bg-panel text-fg-3 ring-1 ring-border'
}

function getDisplayName(selection: ProjectSearchItem, summary: ProjectAnalyticsResponse): string {
	return isMasterSelection(selection)
		? selection.name
		: (summary.project?.project_name ?? selection.name)
}

function getKnownArea(selection: ProjectSearchItem, summary: ProjectAnalyticsResponse): string {
	const fromProject = summary.project?.area_name
	if (fromProject) return fromProject
	return 'Area unavailable'
}

function getDevelopmentCount(selection: ProjectSearchItem, subProjectCount: number): number | null {
	if (!isMasterSelection(selection)) return null
	return subProjectCount || null
}

function getOffPlanShare(summary: ProjectAnalyticsResponse): number | null {
	const offPlan = summary.by_reg_type.find((row) => row.reg_type === 'Off-Plan Properties')
	if (offPlan?.pct_of_total != null) return offPlan.pct_of_total
	const segments = getMarketSegments(summary)
	return segments.total > 0 ? (segments.offPlan / segments.total) * 100 : null
}

function getMarketSegments(summary: ProjectAnalyticsResponse) {
	const offPlan =
		summary.by_reg_type.find((row) => row.reg_type === 'Off-Plan Properties')?.count ?? 0
	const secondary =
		summary.by_reg_type.find((row) => row.reg_type === 'Existing Properties')?.count ?? 0
	return {
		offPlan,
		secondary,
		total: offPlan + secondary
	}
}

function getKpis(summary: ProjectAnalyticsResponse) {
	return [
		{
			label: 'Total sales',
			value: fmtNumber(summary.sales.transaction_count),
			detail: 'transactions'
		},
		{
			label: 'Avg sale price',
			value: fmtCurrency(summary.sales.avg_price),
			detail: `${fmtCurrency(summary.sales.avg_price_sqft)}/sq ft`
		},
		{
			label: 'Median rent',
			value: fmtCurrency(summary.rentals.median_annual_rent),
			detail: `${fmtNumber(summary.rentals.contract_count)} contracts`
		},
		{
			label: 'Gross yield',
			value: fmtPct(summary.overall_gross_yield_pct),
			detail: ''
		},
		{
			label: 'Off-plan share',
			value: fmtPct(getOffPlanShare(summary)),
			detail: ''
		}
	]
}

function getTopConfigRows(summary: ProjectAnalyticsResponse): ProjectConfigurationRow[] {
	return summary.configuration_analysis
		.filter((row) => row.market_segment === 'all')
		.slice()
		.sort((left, right) => right.sale_count - left.sale_count)
		.slice(0, 5)
}

function getMetricRows(
	summaryLeft: ProjectAnalyticsResponse,
	summaryRight: ProjectAnalyticsResponse
) {
	return [
		{
			label: 'Total sales',
			a: summaryLeft.sales.transaction_count,
			b: summaryRight.sales.transaction_count,
			format: (value: number | null | undefined) => fmtNumber(value),
			deltaMode: 'pct_change' as DeltaMode
		},
		{
			label: 'Avg sale price',
			a: summaryLeft.sales.avg_price,
			b: summaryRight.sales.avg_price,
			format: (value: number | null | undefined) => fmtCurrency(value),
			deltaMode: 'pct_change' as DeltaMode
		},
		{
			label: 'Avg price / sq ft',
			a: summaryLeft.sales.avg_price_sqft,
			b: summaryRight.sales.avg_price_sqft,
			format: (value: number | null | undefined) => `${fmtCurrency(value)}/sq ft`,
			deltaMode: 'pct_change' as DeltaMode
		},
		{
			label: 'Median annual rent',
			a: summaryLeft.rentals.median_annual_rent,
			b: summaryRight.rentals.median_annual_rent,
			format: (value: number | null | undefined) => fmtCurrency(value),
			deltaMode: 'pct_change' as DeltaMode
		},
		{
			label: 'Gross yield',
			a: summaryLeft.overall_gross_yield_pct,
			b: summaryRight.overall_gross_yield_pct,
			format: (value: number | null | undefined) => fmtPct(value),
			deltaMode: 'points' as DeltaMode
		},
		{
			label: 'Off-plan share',
			a: getOffPlanShare(summaryLeft),
			b: getOffPlanShare(summaryRight),
			format: (value: number | null | undefined) => fmtPct(value),
			deltaMode: 'points' as DeltaMode
		}
	]
}

function getDeltaValue(
	a: number | null | undefined,
	b: number | null | undefined,
	mode: DeltaMode
) {
	if (a == null || b == null || !Number.isFinite(a) || !Number.isFinite(b)) return null
	if (mode === 'points') return b - a
	if (a === 0) return null
	return ((b - a) / a) * 100
}

function getDeltaLabel(
	a: number | null | undefined,
	b: number | null | undefined,
	mode: DeltaMode
) {
	const delta = getDeltaValue(a, b, mode)
	return mode === 'points' ? fmtSignedPoints(delta) : fmtSignedPct(delta)
}

function getShortName(
	selection: ProjectSearchItem,
	summary: ProjectAnalyticsResponse | null
): string {
	const name = summary ? getDisplayName(selection, summary) : selection.name
	return name.length > 28 ? `${name.slice(0, 25)}...` : name
}

function trendValue(point: ProjectTrendPoint): number {
	return trendMode === 'avg_price' ? point.avg_price : point.avg_price_sqft
}

function buildTrendChart() {
	const dataA = trendsQueryA.data?.data ?? []
	const dataB = trendsQueryB.data?.data ?? []
	if (!trendCanvas || (dataA.length === 0 && dataB.length === 0)) {
		trendChart?.destroy()
		trendChart = null
		return
	}

	const ctx = trendCanvas.getContext('2d')
	if (!ctx) return

	trendChart?.destroy()
	const theme = getChartTheme()
	const dates = Array.from(
		new Set([...dataA.map((point) => point.date), ...dataB.map((point) => point.date)])
	).sort((left, right) => new Date(left).getTime() - new Date(right).getTime())
	const byDateA = new Map(dataA.map((point) => [point.date, trendValue(point)]))
	const byDateB = new Map(dataB.map((point) => [point.date, trendValue(point)]))

	trendChart = new Chart(ctx, {
		type: 'line',
		data: {
			labels: dates.map((date) =>
				new Date(date).toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
			),
			datasets: [
				{
					label: getShortName(projectA, summaryA),
					data: dates.map((date) => byDateA.get(date) ?? null),
					borderColor: theme.line,
					backgroundColor: theme.line,
					borderWidth: 2.5,
					tension: 0.32,
					pointRadius: 2,
					pointHoverRadius: 4,
					spanGaps: false
				},
				{
					label: getShortName(projectB, summaryB),
					data: dates.map((date) => byDateB.get(date) ?? null),
					borderColor: theme.lineAlt,
					backgroundColor: theme.lineAlt,
					borderWidth: 2.5,
					tension: 0.32,
					pointRadius: 2,
					pointHoverRadius: 4,
					spanGaps: false
				}
			]
		},
		options: {
			responsive: true,
			maintainAspectRatio: false,
			interaction: { mode: 'index', intersect: false },
			plugins: {
				legend: {
					position: 'top',
					align: 'end',
					labels: {
						color: theme.foregroundMuted,
						boxWidth: 10,
						boxHeight: 10,
						usePointStyle: true
					}
				},
				tooltip: {
					backgroundColor: theme.tooltipBackground,
					titleColor: theme.tooltipText,
					bodyColor: theme.tooltipText,
					displayColors: true,
					padding: 10,
					callbacks: {
						label: (context) =>
							trendMode === 'avg_price'
								? ` ${context.dataset.label}: ${fmtCurrency(Number(context.parsed.y ?? 0))}`
								: ` ${context.dataset.label}: AED ${fmtNumber(Number(context.parsed.y ?? 0), 0)}/sq ft`
					}
				}
			},
			scales: {
				x: {
					grid: { display: false },
					border: { color: theme.axis },
					ticks: { color: theme.muted, maxTicksLimit: 8 }
				},
				y: {
					grid: { color: theme.grid },
					border: { display: false },
					ticks: {
						color: theme.muted,
						callback: (value) =>
							trendMode === 'avg_price' ? fmtCompact(Number(value)) : fmtNumber(Number(value), 0)
					}
				}
			}
		}
	})
}

function buildMarketSplitChart() {
	if (!summaryA || !summaryB || !marketSplitCanvas) {
		marketSplitChart?.destroy()
		marketSplitChart = null
		return
	}
	const splitA = getMarketSegments(summaryA)
	const splitB = getMarketSegments(summaryB)
	if (splitA.total <= 0 && splitB.total <= 0) {
		marketSplitChart?.destroy()
		marketSplitChart = null
		return
	}

	const ctx = marketSplitCanvas.getContext('2d')
	if (!ctx) return

	marketSplitChart?.destroy()
	const theme = getChartTheme()

	marketSplitChart = new Chart(ctx, {
		type: 'bar',
		data: {
			labels: ['Off-plan', 'Secondary'],
			datasets: [
				{
					label: getShortName(projectA, summaryA),
					data: [splitA.offPlan, splitA.secondary],
					backgroundColor: theme.line,
					borderRadius: 6,
					borderSkipped: false
				},
				{
					label: getShortName(projectB, summaryB),
					data: [splitB.offPlan, splitB.secondary],
					backgroundColor: theme.lineAlt,
					borderRadius: 6,
					borderSkipped: false
				}
			]
		},
		options: {
			responsive: true,
			maintainAspectRatio: false,
			plugins: {
				legend: {
					position: 'top',
					align: 'end',
					labels: {
						color: theme.foregroundMuted,
						boxWidth: 10,
						boxHeight: 10,
						usePointStyle: true
					}
				},
				tooltip: {
					backgroundColor: theme.tooltipBackground,
					titleColor: theme.tooltipText,
					bodyColor: theme.tooltipText,
					callbacks: {
						label: (context) => ` ${context.dataset.label}: ${fmtNumber(Number(context.parsed.y))}`
					}
				}
			},
			scales: {
				x: {
					grid: { display: false },
					border: { color: theme.axis },
					ticks: { color: theme.foregroundMuted, font: { weight: 600 } }
				},
				y: {
					beginAtZero: true,
					grid: { color: theme.grid },
					border: { display: false },
					ticks: { color: theme.muted, callback: (value) => fmtCompact(Number(value)) }
				}
			}
		}
	})
}

$effect(() => {
	trendsQueryA.data
	trendsQueryB.data
	trendMode
	themeVersion
	buildTrendChart()
})

$effect(() => {
	summaryA
	summaryB
	themeVersion
	buildMarketSplitChart()
})

onMount(() => {
	const observer = new MutationObserver(() => {
		themeVersion += 1
	})
	observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })

	return () => {
		observer.disconnect()
		trendChart?.destroy()
		marketSplitChart?.destroy()
	}
})
</script>

{#if loading}
	<div class="grid gap-5">
		<div class="grid gap-5 xl:grid-cols-2">
			<div class="h-72 animate-pulse rounded-lg border border-border bg-card"></div>
			<div class="h-72 animate-pulse rounded-lg border border-border bg-card"></div>
		</div>
		<div class="h-[360px] animate-pulse rounded-lg border border-border bg-card"></div>
	</div>
{:else if error}
	<AnalyticsError message="Failed to load comparison analytics." retry={() => Promise.all([summaryQueryA.refetch(), summaryQueryB.refetch()])} fetching={summaryQueryA.isFetching || summaryQueryB.isFetching} />
{:else if summaryA && summaryB}
	{@const subCountA = subProjectsQueryA.data?.sub_projects.length ?? 0}
	{@const subCountB = subProjectsQueryB.data?.sub_projects.length ?? 0}
	{@const developmentCountA = getDevelopmentCount(projectA, subCountA)}
	{@const developmentCountB = getDevelopmentCount(projectB, subCountB)}
	{@const metricRows = getMetricRows(summaryA, summaryB)}
	{@const topRowsA = getTopConfigRows(summaryA)}
	{@const topRowsB = getTopConfigRows(summaryB)}

	<div class="space-y-5">
		{#if subProjectsQueryA.isError || subProjectsQueryB.isError}
			<AnalyticsError message="Failed to load development counts for the comparison." retry={() => Promise.all([subProjectsQueryA.refetch(), subProjectsQueryB.refetch()])} fetching={subProjectsQueryA.isFetching || subProjectsQueryB.isFetching} />
		{/if}
		<section class="grid gap-5 xl:grid-cols-2">
			{@render SummaryCard(
				'Project A',
				projectA,
				summaryA,
				developmentCountA,
				subProjectsQueryA.isLoading
			)}
			{@render SummaryCard(
				'Project B',
				projectB,
				summaryB,
				developmentCountB,
				subProjectsQueryB.isLoading
			)}
		</section>

		<section class="ui-surface p-4 sm:p-5">
			<div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
				<div>
					<p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-fg-4">
						Shared price trend
					</p>
					<h2 class="mt-1 text-lg font-semibold text-fg-1">Price trend</h2>
				</div>
				<div class="ui-segmented self-start md:self-auto">
					<button
						type="button"
						class="ui-segmented-item px-3 py-1.5 text-sm"
						data-active={trendMode === 'avg_price'}
						onclick={() => (trendMode = 'avg_price')}
					>
						Avg price
					</button>
					<button
						type="button"
						class="ui-segmented-item px-3 py-1.5 text-sm"
						data-active={trendMode === 'avg_price_sqft'}
						onclick={() => (trendMode = 'avg_price_sqft')}
					>
						AED / sq ft
					</button>
				</div>
			</div>
			<div class="mt-4 h-[340px]">
				{#if trendsQueryA.isError || trendsQueryB.isError}
					<AnalyticsError message="Failed to load comparison trends." retry={() => Promise.all([trendsQueryA.refetch(), trendsQueryB.refetch()])} fetching={trendsQueryA.isFetching || trendsQueryB.isFetching} />
				{:else if trendsQueryA.isLoading || trendsQueryB.isLoading}
					<div class="h-full animate-pulse rounded-lg bg-panel"></div>
				{:else if (trendsQueryA.data?.data.length ?? 0) > 0 || (trendsQueryB.data?.data.length ?? 0) > 0}
					<canvas bind:this={trendCanvas}></canvas>
				{:else}
					<div class="flex h-full items-center justify-center rounded-lg border border-dashed border-border text-sm text-fg-4">
						No trend data available for this comparison.
					</div>
				{/if}
			</div>
		</section>

		<div class="grid gap-5">
			<section class="ui-surface p-5">
				<p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-fg-4">
					Market split
				</p>
				<h2 class="mt-1 text-lg font-semibold text-fg-1">Off-plan vs secondary volume</h2>
				<div class="mt-4 h-[300px]">
					{#if getMarketSegments(summaryA).total > 0 || getMarketSegments(summaryB).total > 0}
						<canvas bind:this={marketSplitCanvas}></canvas>
					{:else}
						<div class="flex h-full items-center justify-center rounded-lg border border-dashed border-border text-sm text-fg-4">
							No sales mix data for this comparison.
						</div>
					{/if}
				</div>
			</section>

			<section class="ui-surface p-5">
				<p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-fg-4">
					Metric table
				</p>
				<h2 class="mt-1 text-lg font-semibold text-fg-1">Delta is Project B minus Project A</h2>

				<div class="mt-4 hidden rounded-lg border border-border md:block">
					<div class="grid grid-cols-[1fr_1fr_1fr_0.8fr] border-b border-border bg-panel px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-fg-4">
						<div>Metric</div>
						<div class="text-right">Project A</div>
						<div class="text-right">Project B</div>
						<div class="text-right">Delta</div>
					</div>
					{#each metricRows as row (row.label)}
						{@const delta = getDeltaValue(row.a, row.b, row.deltaMode)}
						<div class="grid grid-cols-[1fr_1fr_1fr_0.8fr] border-b border-border px-4 py-3 text-sm last:border-b-0">
							<div class="font-medium text-fg-1">{row.label}</div>
							<div class="text-right text-fg-3">{row.format(row.a)}</div>
							<div class="text-right text-fg-3">{row.format(row.b)}</div>
							<div class="text-right font-semibold {deltaTone(delta)}">
								{getDeltaLabel(row.a, row.b, row.deltaMode)}
							</div>
						</div>
					{/each}
				</div>

				<div class="mt-4 grid gap-3 md:hidden">
					{#each metricRows as row (row.label)}
						{@const delta = getDeltaValue(row.a, row.b, row.deltaMode)}
						<div class="rounded-lg border border-border bg-panel p-3">
							<p class="text-sm font-semibold text-fg-1">{row.label}</p>
							<div class="mt-2 grid grid-cols-3 gap-2 text-xs">
								<div>
									<p class="uppercase tracking-[0.12em] text-fg-5">A</p>
									<p class="mt-1 font-semibold text-fg-2">{row.format(row.a)}</p>
								</div>
								<div>
									<p class="uppercase tracking-[0.12em] text-fg-5">B</p>
									<p class="mt-1 font-semibold text-fg-2">{row.format(row.b)}</p>
								</div>
								<div class="text-right">
									<p class="uppercase tracking-[0.12em] text-fg-5">Delta</p>
									<p class="mt-1 font-semibold {deltaTone(delta)}">
										{getDeltaLabel(row.a, row.b, row.deltaMode)}
									</p>
								</div>
							</div>
						</div>
					{/each}
				</div>
			</section>
		</div>

		<section class="ui-surface p-5">
			<div>
				<p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-fg-4">
					Top configurations
				</p>
				<h2 class="mt-1 text-lg font-semibold text-fg-1">Most active bedroom mixes by last 12 months</h2>
			</div>
			<div class="mt-4 grid gap-5 xl:grid-cols-2">
				{@render ConfigList('Project A', projectA, summaryA, topRowsA)}
				{@render ConfigList('Project B', projectB, summaryB, topRowsB)}
			</div>
		</section>
	</div>
{/if}

{#snippet SummaryCard(
	label: string,
	selection: ProjectSearchItem,
	summary: ProjectAnalyticsResponse,
	developmentCount: number | null,
	subProjectsLoading: boolean
)}
	<section class="ui-surface min-w-0 p-5">
		<div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
			<div class="min-w-0">
				<p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-fg-4">{label}</p>
				<h2 class="mt-1.5 break-words text-2xl font-semibold tracking-normal text-fg-1">
					{getDisplayName(selection, summary)}
				</h2>
				<p class="mt-1 text-sm text-fg-3">{getKnownArea(selection, summary)}</p>
				<!-- Each side shows its own usage: an office tower compares as Commercial. -->
				<span
					class="mt-2 inline-flex rounded-sm bg-panel px-2 py-0.5 text-[11px] font-semibold text-fg-3 ring-1 ring-border"
					data-testid="compare-usage"
				>
					{summary.usage === 'Commercial' ? 'Commercial' : 'Residential'} records
				</span>
			</div>
			<span
				class="inline-flex w-fit items-center rounded-sm px-2.5 py-1 text-xs font-semibold {isMarketSelection(
					selection
				) || isMasterSelection(selection)
					? 'bg-info-bg text-info ring-1 ring-border'
					: statusBadgeClass(summary.project?.project_status)}"
			>
				{isMarketSelection(selection)
					? 'Dubai market'
					: isMasterSelection(selection)
					? 'Master community'
					: summary.project?.project_status ?? 'Project'}
			</span>
		</div>

		{#if isMasterSelection(selection) && developmentCount != null}
			<p class="mt-4 border-t border-border pt-3 text-xs text-fg-4">
				{fmtNumber(developmentCount)} developments
			</p>
		{/if}

		<div class="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
			{#each getKpis(summary) as item (item.label)}
				<div class="rounded-md border border-border bg-panel p-3">
					<p class="text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-4">{item.label}</p>
					<p class="mt-1.5 break-words text-lg font-semibold text-fg-1">{item.value}</p>
					{#if item.detail}<p class="mt-1 text-xs text-fg-4">{item.detail}</p>{/if}
				</div>
			{/each}
		</div>
	</section>
{/snippet}

{#snippet ConfigList(
	label: string,
	selection: ProjectSearchItem,
	summary: ProjectAnalyticsResponse,
	rows: ProjectConfigurationRow[]
)}
	<section class="min-w-0 rounded-lg border border-border bg-panel p-4">
		<div class="flex items-start justify-between gap-3">
			<div class="min-w-0">
				<p class="text-[11px] font-semibold uppercase tracking-[0.14em] text-fg-4">{label}</p>
				<h3 class="mt-1 truncate text-base font-semibold text-fg-1">
					{getDisplayName(selection, summary)}
				</h3>
			</div>
			<p class="shrink-0 text-xs font-semibold text-fg-4">Top 5</p>
		</div>
		<div class="mt-4 grid gap-2">
			{#each rows as row (row.market_segment + row.rooms)}
				<div class="rounded-md border border-border bg-card p-3">
					<div class="flex items-start justify-between gap-3">
						<p class="min-w-0 font-semibold text-fg-1">{row.rooms}</p>
						<p class="shrink-0 text-sm font-semibold text-fg-2">
							{fmtNumber(row.sale_count)} sales
						</p>
					</div>
					<div class="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
						<div>
							<p class="uppercase tracking-[0.12em] text-fg-5">Avg price</p>
							<p class="mt-1 font-semibold text-fg-2">{fmtCurrency(row.avg_sale_price)}</p>
						</div>
						<div>
							<p class="uppercase tracking-[0.12em] text-fg-5">Price / sq ft</p>
							<p class="mt-1 font-semibold text-fg-2">{fmtCurrency(row.avg_sale_price_sqft)}</p>
						</div>
						<div>
							<p class="uppercase tracking-[0.12em] text-fg-5">Yield</p>
							<p class="mt-1 font-semibold text-fg-2">{fmtPct(row.gross_yield_pct)}</p>
						</div>
					</div>
				</div>
			{/each}
			{#if rows.length === 0}
				<div class="rounded-md border border-dashed border-border px-4 py-8 text-center text-sm text-fg-4">
					No configuration data available.
				</div>
			{/if}
		</div>
	</section>
{/snippet}
