<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { Chart, registerables } from 'chart.js'
import { onMount } from 'svelte'
import type {
	PriceDistributionBucket,
	ProjectAnalyticsResponse,
	ProjectConfigurationRow,
	ProjectForecastPoint,
	ProjectPipelinePoint,
	ProjectSearchItem,
	ProjectTrendPoint,
	SubProjectItem
} from '$lib/api/analytics'
import { analyticsQueries } from '$lib/queries/analytics'

Chart.register(...registerables)

let { selection }: { selection: ProjectSearchItem } = $props()

type AnalysisMode = 'sales' | 'rentals'
type ConfigSegment = 'all' | 'off_plan' | 'secondary'

let subProject = $state<string | null>(null)
let mode = $state<AnalysisMode>('sales')
let configMode = $state<AnalysisMode>('sales')
let configSegment = $state<ConfigSegment>('all')
let distroRooms = $state<string>('All')
let distroOffplan = $state(false)
let pipelineRooms = $state<string | null>(null)
let subDropdownOpen = $state(false)
let subSearch = $state('')

$effect(() => {
	selection
	subProject = null
	mode = 'sales'
	configMode = 'sales'
	configSegment = 'all'
	distroRooms = 'All'
	distroOffplan = false
	pipelineRooms = null
	subDropdownOpen = false
	subSearch = ''
})

const queryParams = $derived.by(() =>
	subProject
		? { project: subProject, masterProject: selection.name }
		: selection.filter_type === 'project'
			? { project: selection.name }
			: { masterProject: selection.name, filterType: selection.filter_type }
)

const subProjectsQuery = createQuery(() =>
	analyticsQueries.subProjects(selection.name, selection.filter_type)
)

const summaryQuery = createQuery(() => analyticsQueries.projectSummary(queryParams))

const trendsQuery = createQuery(() => analyticsQueries.projectTrends(queryParams, 365))

const forecastQuery = createQuery(() => analyticsQueries.projectForecast(queryParams, 365))

const pipelineQuery = createQuery(() => analyticsQueries.projectPipeline(queryParams))

const distroQuery = createQuery(() =>
	analyticsQueries.projectPriceDistribution(
		queryParams,
		distroOffplan ? 'Off-Plan Properties' : undefined
	)
)

function getSubProjects(): SubProjectItem[] {
	return subProjectsQuery.data?.sub_projects ?? []
}

function getFilteredSubProjects(): SubProjectItem[] {
	const subProjects = getSubProjects()
	return subSearch.trim()
		? subProjects.filter((sp: SubProjectItem) =>
				sp.name.toLowerCase().includes(subSearch.toLowerCase())
			)
		: subProjects
}

function getSummary(): ProjectAnalyticsResponse | null {
	return summaryQuery.data ?? null
}

function getTrends(): ProjectTrendPoint[] {
	return trendsQuery.data?.data ?? []
}

function getForecast() {
	return forecastQuery.data ?? null
}

function getPipeline() {
	return pipelineQuery.data ?? null
}

function getConfigurationRows(summary: ProjectAnalyticsResponse | null): ProjectConfigurationRow[] {
	return summary?.configuration_analysis.filter((row) => row.market_segment === configSegment) ?? []
}

function getAvailableRooms(): string[] {
	const summary = getSummary()
	if (!summary) return []
	return summary.unit_composition.filter((c) => c.count > 0).map((c) => c.rooms)
}

function getDistroRooms(): string[] {
	return distroQuery.data?.by_rooms.map((b) => b.rooms) ?? []
}

function getDistroBucket(): PriceDistributionBucket | null {
	const distro = distroQuery.data
	if (!distro) return null
	if (distroRooms === 'All') return distro.all ?? null
	return distro.by_rooms.find((b) => b.rooms === distroRooms) ?? null
}

function getFilteredPipelineData(): ProjectPipelinePoint[] {
	const data = getPipeline()?.data ?? []
	if (!pipelineRooms) return data
	const summary = getSummary()
	const comp = summary?.unit_composition.find((c) => c.rooms === pipelineRooms)
	if (!comp) return []
	const ratio = comp.pct_of_total / 100
	return data.map((p) => ({
		...p,
		existing_stock_units: Math.round(p.existing_stock_units * ratio),
		carried_stock_units: Math.round(p.carried_stock_units * ratio),
		new_pipeline_units: Math.round(p.new_pipeline_units * ratio)
	}))
}

function getMarketSplit(summary: ProjectAnalyticsResponse | null) {
	const breakdown = summary?.by_reg_type ?? []
	const offPlan = breakdown.find((row) => row.reg_type === 'Off-Plan Properties')?.count ?? 0
	const secondary = breakdown.find((row) => row.reg_type === 'Existing Properties')?.count ?? 0
	const total = offPlan + secondary
	return {
		total,
		segments: [
			{
				key: 'off_plan',
				label: 'Off-Plan',
				count: offPlan,
				pct: total > 0 ? (offPlan / total) * 100 : 0,
				color: '#14b8a6'
			},
			{
				key: 'secondary',
				label: 'Secondary',
				count: secondary,
				pct: total > 0 ? (secondary / total) * 100 : 0,
				color: '#0f172a'
			}
		]
	}
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
	if (e.key === 'Escape') closeSubDropdown()
	if (e.key === 'Enter') {
		e.preventDefault()
		const filteredSubProjects = getFilteredSubProjects()
		if (filteredSubProjects.length > 0) {
			subProject = filteredSubProjects[0].name
			closeSubDropdown()
		}
	}
}

function stripPrefix(name: string): string {
	return name.replace(selection.name, '').replace(/^[\s\-–]+/, '') || name
}

function statusBadgeClass(status: string): string {
	const s = (status ?? '').toLowerCase()
	if (s.includes('complet') || s.includes('handov') || s.includes('deliver'))
		return 'bg-teal-50 text-teal-700 ring-1 ring-teal-200'
	if (
		s.includes('construct') ||
		s.includes('progress') ||
		s.includes('active') ||
		s.includes('plan')
	)
		return 'bg-amber-50 text-amber-700 ring-1 ring-amber-200'
	if (s.includes('cancel')) return 'bg-rose-50 text-rose-700 ring-1 ring-rose-200'
	return 'bg-slate-100 text-slate-600 ring-1 ring-slate-200'
}

function fmtCurrency(n: number | null | undefined): string {
	if (n == null || !Number.isFinite(n) || n <= 0) return '—'
	if (n >= 1_000_000_000) return `AED ${(n / 1_000_000_000).toFixed(2)}B`
	if (n >= 1_000_000) return `AED ${(n / 1_000_000).toFixed(2)}M`
	if (n >= 1_000) return `AED ${(n / 1_000).toFixed(0)}K`
	return `AED ${Math.round(n).toLocaleString()}`
}

function fmtCompact(n: number | null | undefined): string {
	if (n == null || !Number.isFinite(n)) return '—'
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
	if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`
	return Math.round(n).toLocaleString()
}

function fmtNumber(n: number | null | undefined, digits = 0): string {
	if (n == null || !Number.isFinite(n)) return '—'
	return n.toLocaleString('en-AE', {
		minimumFractionDigits: digits,
		maximumFractionDigits: digits
	})
}

function fmtPct(n: number | null | undefined, digits = 1): string {
	if (n == null || !Number.isFinite(n)) return '—'
	return `${fmtNumber(n, digits)}%`
}

function fmtSignedPct(n: number | null | undefined, digits = 1): string {
	if (n == null || !Number.isFinite(n)) return '—'
	const value = fmtNumber(Math.abs(n), digits)
	return `${n > 0 ? '+' : n < 0 ? '−' : ''}${value}%`
}

function fmtPsf(pricePerSqm: number | null | undefined): string {
	if (!pricePerSqm || !Number.isFinite(pricePerSqm)) return ''
	return `AED ${fmtNumber(pricePerSqm / 10.764, 0)} psf`
}

function pctTone(value: number | null | undefined) {
	if (value == null || !Number.isFinite(value)) return 'text-slate-400'
	if (value >= 7) return 'text-teal-600'
	if (value >= 5) return 'text-amber-600'
	return 'text-rose-600'
}

function deltaTone(value: number | null | undefined) {
	if (value == null || !Number.isFinite(value)) return 'text-slate-400'
	if (value > 0) return 'text-teal-600'
	if (value < 0) return 'text-rose-600'
	return 'text-slate-500'
}

function fmtQuarterLabel(value: string | Date): string {
	const dt = new Date(value)
	const quarter = Math.floor(dt.getMonth() / 3) + 1
	return `Q${quarter} '${String(dt.getFullYear()).slice(-2)}`
}

function getWeightedAbsorption(rows: ProjectConfigurationRow[]): number | null {
	const totalStock = rows.reduce((sum, row) => sum + row.stock_units, 0)
	if (totalStock <= 0) return null
	return (rows.reduce((sum, row) => sum + row.sales_last_12m, 0) / totalStock) * 100
}

// ─── Chart canvas refs ───────────────────────────────────────────────────
let trendCanvas = $state<HTMLCanvasElement>()
let bellCanvas = $state<HTMLCanvasElement>()
let pipelineCanvas = $state<HTMLCanvasElement>()
let marketSplitCanvas = $state<HTMLCanvasElement>()

let trendChart: Chart | null = null
let bellChart: Chart | null = null
let pipelineChart: Chart | null = null
let marketSplitChart: Chart | null = null

// ─── Trend chart ─────────────────────────────────────────────────────────
function buildTrendChart() {
	const forecast = getForecast()
	const forecastSeries = forecast?.data ?? []
	const trends = getTrends()
	const historicalSeries =
		forecastSeries.filter((point: ProjectForecastPoint) => point.series === 'historical') || []
	const chartSeries: Array<Pick<ProjectTrendPoint, 'date' | 'avg_price' | 'avg_price_sqm'>> =
		historicalSeries.length > 0 ? historicalSeries : trends
	if (!trendCanvas || chartSeries.length === 0) return
	trendChart?.destroy()
	const ctx = trendCanvas.getContext('2d')
	if (!ctx) return

	const gradient = ctx.createLinearGradient(0, 0, 0, 280)
	gradient.addColorStop(0, 'rgba(0,189,165,0.18)')
	gradient.addColorStop(1, 'rgba(0,189,165,0)')

	const labels = forecastSeries.length > 0 ? forecastSeries : chartSeries
	const historicalValues =
		forecastSeries.length > 0
			? forecastSeries.map((point: ProjectForecastPoint) =>
					point.series === 'historical'
						? mode === 'sales'
							? point.avg_price
							: point.avg_price_sqm
						: null
				)
			: chartSeries.map((point) => (mode === 'sales' ? point.avg_price : point.avg_price_sqm))
	const forecastValues =
		forecastSeries.length > 0
			? forecastSeries.map((point: ProjectForecastPoint) =>
					point.series === 'forecast'
						? mode === 'sales'
							? point.avg_price
							: point.avg_price_sqm
						: null
				)
			: []
	const fallbackHistoricalValues = chartSeries.map((point) =>
		mode === 'sales' ? point.avg_price : point.avg_price_sqm
	)

	trendChart = new Chart(ctx, {
		type: 'line',
		data: {
			labels: labels.map((point) =>
				new Date(point.date).toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
			),
			datasets: [
				{
					label: 'Historical',
					data: forecastSeries.length > 0 ? historicalValues : fallbackHistoricalValues,
					borderColor: '#00BDA5',
					backgroundColor: gradient,
					fill: true,
					tension: 0.34,
					borderWidth: 2.5,
					pointRadius: 0,
					pointHoverRadius: 4
				},
				...(forecastValues.length > 0
					? [
							{
								label: 'Forecast',
								data: forecastValues,
								borderColor: '#00BDA5',
								backgroundColor: 'transparent',
								fill: false,
								tension: 0.34,
								borderWidth: 2,
								borderDash: [7, 5],
								pointRadius: 0,
								pointHoverRadius: 4
							}
						]
					: [])
			]
		},
		options: {
			responsive: true,
			maintainAspectRatio: false,
			plugins: {
				legend: { display: false },
				tooltip: {
					backgroundColor: '#0f172a',
					titleColor: '#cbd5e1',
					bodyColor: '#f8fafc',
					padding: 10,
					displayColors: false,
					callbacks: {
						label: (context) =>
							mode === 'sales'
								? ` ${fmtCurrency(Number(context.parsed.y ?? 0))}`
								: ` AED ${fmtNumber(Number(context.parsed.y ?? 0), 0)}/sqm`
					}
				}
			},
			scales: {
				x: {
					grid: { display: false },
					border: { display: false },
					ticks: { color: '#94a3b8', maxTicksLimit: 8 }
				},
				y: {
					grid: { color: 'rgba(148,163,184,0.12)' },
					border: { display: false },
					ticks: {
						color: '#94a3b8',
						callback: (value) =>
							mode === 'sales' ? fmtCompact(Number(value)) : fmtNumber(Number(value), 0)
					}
				}
			}
		}
	})
}

// ─── Bell curve chart ─────────────────────────────────────────────────────
function buildBellChart() {
	const bucket = getDistroBucket()
	if (
		!bellCanvas ||
		!bucket ||
		bucket.log_mean_price == null ||
		bucket.log_std_price == null ||
		bucket.log_std_price <= 0 ||
		bucket.p05_price == null ||
		bucket.p95_price == null ||
		bucket.p25_price == null ||
		bucket.p50_price == null ||
		bucket.p75_price == null
	) {
		bellChart?.destroy()
		bellChart = null
		return
	}
	bellChart?.destroy()
	const ctx = bellCanvas.getContext('2d')
	if (!ctx) return

	const mu = bucket.log_mean_price
	const sigma = bucket.log_std_price
	const p05_price = bucket.p05_price
	const p95_price = bucket.p95_price
	const p25_price = bucket.p25_price
	const p50_price = bucket.p50_price
	const p75_price = bucket.p75_price
	const nPoints = 300
	const xMin = Math.max(1, p05_price)
	const xMax = p95_price
	const step = (xMax - xMin) / nPoints

	const curvePoints: Array<{ x: number; y: number }> = []

	for (let i = 0; i <= nPoints; i++) {
		const x = xMin + i * step
		const pdf =
			(1 / (x * sigma * Math.sqrt(2 * Math.PI))) *
			Math.exp(-0.5 * ((Math.log(x) - mu) / sigma) ** 2)
		curvePoints.push({ x, y: pdf })
	}

	const gradient = ctx.createLinearGradient(0, 0, 0, 240)
	gradient.addColorStop(0, 'rgba(0,189,165,0.20)')
	gradient.addColorStop(1, 'rgba(0,189,165,0.01)')

	// Decile lookup for hover tooltip
	const decileMap: [number, string][] = [
		[p25_price, 'P25'],
		[p50_price, 'Median'],
		[p75_price, 'P75']
	]
	function nearestDecileLabel(price: number): string {
		let closest = decileMap[0]
		for (const d of decileMap) {
			if (Math.abs(d[0] - price) < Math.abs(closest[0] - price)) closest = d
		}
		const pct = Math.round(((price - xMin) / (xMax - xMin)) * 90 + 5)
		return `~P${pct}`
	}

	bellChart = new Chart(ctx, {
		type: 'line',
		data: {
			datasets: [
				{
					data: curvePoints,
					borderColor: '#00BDA5',
					backgroundColor: gradient,
					fill: true,
					tension: 0.3,
					borderWidth: 2.5,
					pointRadius: 0
				}
			]
		},
		options: {
			responsive: true,
			maintainAspectRatio: false,
			animation: false,
			interaction: { mode: 'index', intersect: false },
			plugins: {
				legend: { display: false },
				tooltip: {
					enabled: true,
					backgroundColor: 'rgba(15,23,42,0.85)',
					titleColor: '#94a3b8',
					bodyColor: '#f8fafc',
					padding: 10,
					displayColors: false,
					callbacks: {
						title: (items) => {
							const price = Number(items[0]?.parsed?.x ?? 0)
							return nearestDecileLabel(price)
						},
						label: (item) => {
							const price = Number(item.parsed?.x ?? 0)
							if (price >= 1_000_000) return ` AED ${(price / 1_000_000).toFixed(2)}M`
							if (price >= 1_000) return ` AED ${(price / 1_000).toFixed(0)}K`
							return ` AED ${Math.round(price).toLocaleString()}`
						}
					}
				}
			},
			scales: {
				x: {
					type: 'linear',
					min: xMin,
					max: xMax,
					grid: { display: false },
					border: { display: false },
					ticks: {
						color: '#94a3b8',
						maxTicksLimit: 9,
						callback: (val) => {
							const n = Number(val)
							if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(0)}M`
							if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`
							return String(Math.round(n))
						}
					}
				},
				y: { display: false }
			}
		},
		plugins: [
			{
				id: 'bellVLines',
				afterDraw(chart: any) {
					const { ctx: c, scales } = chart
					const xScale = scales.x
					const yScale = scales.y
					const drawLine = (value: number, alpha: number, dash: number[]) => {
						if (value < xMin || value > xMax) return
						const px = xScale.getPixelForValue(value)
						c.save()
						c.beginPath()
						c.setLineDash(dash)
						c.strokeStyle = `rgba(0,189,165,${alpha})`
						c.lineWidth = 1.5
						c.moveTo(px, yScale.top)
						c.lineTo(px, yScale.bottom)
						c.stroke()
						c.restore()
					}
					drawLine(p50_price, 0.9, [5, 4])
					drawLine(p25_price, 0.4, [3, 4])
					drawLine(p75_price, 0.4, [3, 4])
				}
			}
		]
	})
}

// ─── Pipeline chart ───────────────────────────────────────────────────────
function buildPipelineChart() {
	const pipelineData = getFilteredPipelineData()
	if (!pipelineCanvas || pipelineData.length === 0) return
	pipelineChart?.destroy()
	const ctx = pipelineCanvas.getContext('2d')
	if (!ctx) return

	const todayMs = Date.now()

	pipelineChart = new Chart(ctx, {
		type: 'bar',
		data: {
			labels: pipelineData.map((p) => fmtQuarterLabel(p.period)),
			datasets: [
				{
					label: 'Existing Stock',
					data: pipelineData.map((p) =>
						new Date(p.period).getTime() < todayMs ? p.existing_stock_units : null
					),
					backgroundColor: '#00BDA5',
					borderRadius: 3,
					stack: 'a'
				},
				{
					label: 'Carried Stock',
					data: pipelineData.map((p) =>
						new Date(p.period).getTime() >= todayMs ? p.carried_stock_units : null
					),
					backgroundColor: 'rgba(0,189,165,0.22)',
					borderRadius: 0,
					stack: 'b'
				},
				{
					label: 'New Pipeline',
					data: pipelineData.map((p) =>
						new Date(p.period).getTime() >= todayMs ? p.new_pipeline_units : null
					),
					backgroundColor: '#f59e0b',
					borderRadius: 3,
					stack: 'b'
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
						color: '#64748b',
						boxWidth: 10,
						boxHeight: 10,
						usePointStyle: true
					}
				},
				tooltip: {
					backgroundColor: '#0f172a',
					titleColor: '#cbd5e1',
					bodyColor: '#f8fafc',
					callbacks: {
						label: (c) => ` ${c.dataset.label}: ${fmtCompact(Number(c.parsed.y))}`
					}
				}
			},
			scales: {
				x: {
					stacked: true,
					grid: { display: false },
					border: { display: false },
					ticks: { color: '#94a3b8', maxTicksLimit: 12 }
				},
				y: {
					stacked: true,
					grid: { color: 'rgba(148,163,184,0.12)' },
					border: { display: false },
					ticks: { color: '#94a3b8', callback: (v) => fmtCompact(Number(v)) }
				}
			}
		},
		plugins: [
			{
				id: 'pipelineSeparator',
				afterDraw(chart: any) {
					const todayIdx = pipelineData.findIndex((p) => new Date(p.period).getTime() >= todayMs)
					if (todayIdx < 1) return
					const { ctx: c, scales } = chart
					const xScale = scales.x
					const yScale = scales.y
					const px = (xScale.getPixelForTick(todayIdx - 1) + xScale.getPixelForTick(todayIdx)) / 2
					c.save()
					c.beginPath()
					c.setLineDash([5, 4])
					c.strokeStyle = '#94a3b8'
					c.lineWidth = 1.5
					c.moveTo(px, yScale.top)
					c.lineTo(px, yScale.bottom)
					c.stroke()
					c.fillStyle = '#94a3b8'
					c.font = '11px system-ui, -apple-system, sans-serif'
					c.fillText('Pipeline →', px + 6, yScale.top + 16)
					c.restore()
				}
			}
		]
	})
}

function buildMarketSplitChart() {
	const summary = getSummary()
	const marketSplit = getMarketSplit(summary)
	if (!marketSplitCanvas || marketSplit.total <= 0) {
		marketSplitChart?.destroy()
		marketSplitChart = null
		return
	}

	marketSplitChart?.destroy()
	const ctx = marketSplitCanvas.getContext('2d')
	if (!ctx) return

	marketSplitChart = new Chart(ctx, {
		type: 'bar',
		data: {
			labels: marketSplit.segments.map((segment) => segment.label),
			datasets: [
				{
					data: marketSplit.segments.map((segment) => segment.count),
					backgroundColor: marketSplit.segments.map((segment) => segment.color),
					borderRadius: 10,
					borderSkipped: false,
					barThickness: 36
				}
			]
		},
		options: {
			responsive: true,
			maintainAspectRatio: false,
			indexAxis: 'y',
			plugins: {
				legend: { display: false },
				tooltip: {
					backgroundColor: '#0f172a',
					titleColor: '#cbd5e1',
					bodyColor: '#f8fafc',
					displayColors: false,
					callbacks: {
						label: (context) => {
							const segment = marketSplit.segments[context.dataIndex]
							return ` ${segment.label}: ${fmtNumber(segment.count)} sales (${fmtPct(segment.pct)})`
						}
					}
				}
			},
			scales: {
				x: {
					beginAtZero: true,
					grid: { color: 'rgba(148,163,184,0.12)' },
					border: { display: false },
					ticks: {
						color: '#94a3b8',
						callback: (value) => fmtCompact(Number(value))
					}
				},
				y: {
					grid: { display: false },
					border: { display: false },
					ticks: { color: '#475569', font: { weight: 600 } }
				}
			}
		}
	})
}

// ─── Effects ──────────────────────────────────────────────────────────────
$effect(() => {
	mode
	getForecast()
	buildTrendChart()
})

$effect(() => {
	const _d = distroQuery.data
	const _r = distroRooms
	buildBellChart()
})

$effect(() => {
	const _r = pipelineRooms
	getPipeline()
	getSummary()
	buildPipelineChart()
})

$effect(() => {
	getSummary()
	buildMarketSplitChart()
})

onMount(() => {
	return () => {
		trendChart?.destroy()
		bellChart?.destroy()
		pipelineChart?.destroy()
		marketSplitChart?.destroy()
	}
})
</script>

{#if summaryQuery.isLoading}
	<div class="grid gap-6">
		<div class="h-36 animate-pulse rounded-2xl border border-slate-200 bg-white"></div>
		<div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
			{#each [0, 1, 2, 3] as item (item)}
				<div class="h-28 animate-pulse rounded-2xl border border-slate-200 bg-white"></div>
			{/each}
		</div>
		<div class="h-[480px] animate-pulse rounded-2xl border border-slate-200 bg-white"></div>
	</div>
{:else if getSummary()}
	{@const summary = getSummary()!}
	{@const subProjects = getSubProjects()}
	{@const filteredSubProjects = getFilteredSubProjects()}
	{@const trends = getTrends()}
	{@const forecast = getForecast()}
	{@const pipeline = getPipeline()}
	{@const configRows = getConfigurationRows(summary)}
	{@const weightedAbsorption = getWeightedAbsorption(configRows)}
	{@const distroBucket = getDistroBucket()}
	{@const distroRoomList = getDistroRooms()}
	{@const pipelineRoomList = getAvailableRooms()}
	{@const marketSplit = getMarketSplit(summary)}
	<div class="space-y-5">

		<!-- ── Project header ────────────────────────────────────────── -->
		<section class="rounded-2xl border border-slate-200 bg-white p-5">
			<div class="flex flex-wrap items-start justify-between gap-4">
				<div class="min-w-0">
					<p class="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">
						{summary.project?.area_name ?? 'Project analytics'}
					</p>
					<h2 class="mt-1.5 truncate text-2xl font-semibold tracking-tight text-slate-900">
						{subProject
							? stripPrefix(subProject)
							: summary.project?.project_name ?? selection.name}
					</h2>
					{#if summary.project?.developer_name}
						<p class="mt-1 text-sm text-slate-500">{summary.project.developer_name}</p>
					{/if}
				</div>

				<div class="flex items-center gap-3">
					{#if summary.project?.project_status}
						<span
							class="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold {statusBadgeClass(summary.project.project_status)}"
						>
							{summary.project.project_status}
						</span>
					{/if}

					{#if subProjects.length > 1}
						<div class="relative" use:clickOutside={closeSubDropdown}>
							<button
								type="button"
								onclick={() => {
									subDropdownOpen = !subDropdownOpen;
									subSearch = '';
								}}
								class="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:border-teal-400 hover:text-teal-700"
							>
								<span
									>{subProject
										? stripPrefix(subProject)
										: `All development (${subProjects.length})`}</span
								>
								<svg class="h-4 w-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
								</svg>
							</button>
							{#if subDropdownOpen}
								<div
									class="absolute right-0 z-50 mt-2 w-72 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl"
								>
									<div class="border-b border-slate-100 p-2">
										<input
											type="text"
											class="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-500/20"
											placeholder="Filter sub-projects..."
											bind:value={subSearch}
											onkeydown={handleSubKeydown}
										/>
									</div>
									<div class="max-h-64 overflow-y-auto p-2">
										<button
											type="button"
											class="w-full rounded-lg px-3 py-2 text-left text-sm transition-colors {subProject === null ? 'bg-teal-50 text-teal-700' : 'text-slate-700 hover:bg-slate-50'}"
											onmousedown={() => {
												subProject = null;
												closeSubDropdown();
											}}
										>
											All development
										</button>
										{#each filteredSubProjects as sp (sp.name)}
											<button
												type="button"
												class="mt-0.5 w-full rounded-lg px-3 py-2 text-left text-sm transition-colors {subProject === sp.name ? 'bg-teal-50 text-teal-700' : 'text-slate-700 hover:bg-slate-50'}"
												onmousedown={() => {
													subProject = sp.name;
													closeSubDropdown();
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
				</div>
			</div>

			<!-- Metadata strip -->
			<div class="mt-4 flex flex-wrap gap-4 border-t border-slate-100 pt-4">
				<div class="min-w-[120px] max-w-[320px]">
					<p class="text-[11px] uppercase tracking-[0.16em] text-slate-400">
						{(summary.project?.developer_names?.length ?? 0) > 1 ? 'Developers' : 'Developer'}
					</p>
					{#if (summary.project?.developer_names?.length ?? 0) > 1}
						<p class="mt-1 text-sm font-medium text-slate-800">
							{summary.project?.developer_names?.slice(0, 3).join(', ')}{(summary.project?.developer_names?.length ?? 0) > 3 ? ` +${(summary.project?.developer_names?.length ?? 0) - 3} more` : ''}
						</p>
					{:else}
						<p class="mt-1 text-sm font-medium text-slate-800">
							{summary.project?.developer_name ?? '—'}
						</p>
					{/if}
				</div>
				<div class="min-w-[100px]">
					<p class="text-[11px] uppercase tracking-[0.16em] text-slate-400">Units</p>
					<p class="mt-1 text-sm font-medium text-slate-800">
						{fmtNumber(summary.project?.no_of_units)}
					</p>
				</div>
				<div class="min-w-[160px]">
					<p class="text-[11px] uppercase tracking-[0.16em] text-slate-400">Handover</p>
					{#if summary.project?.completion_date}
						<p class="mt-1 text-sm font-medium text-slate-800">
							{new Date(summary.project.completion_date).toLocaleDateString('en-GB', {
								month: 'short',
								year: 'numeric'
							})}
						</p>
					{:else}
						<p class="mt-1 text-sm font-medium text-slate-800">—</p>
					{/if}
					{#if summary.project?.percent_completed != null}
						<div class="mt-1.5 h-1.5 w-full max-w-[140px] rounded-full bg-slate-100">
							<div
								class="h-1.5 rounded-full bg-teal-500"
								style="width: {Math.min(100, summary.project.percent_completed)}%"
							></div>
						</div>
						<p class="mt-1 text-[11px] text-slate-400">
							{fmtPct(summary.project.percent_completed, 0)} complete
						</p>
					{/if}
				</div>
				{#if summary.project?.no_of_buildings}
					<div class="min-w-[100px]">
						<p class="text-[11px] uppercase tracking-[0.16em] text-slate-400">Buildings</p>
						<p class="mt-1 text-sm font-medium text-slate-800">
							{fmtNumber(summary.project.no_of_buildings)}
						</p>
					</div>
				{/if}
			</div>
		</section>

		<!-- ── KPI cards ──────────────────────────────────────────────── -->
		<section class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
			<div class="rounded-2xl border border-slate-200 bg-white px-5 py-4">
				<p class="text-[11px] uppercase tracking-[0.18em] text-slate-400">Total Sales</p>
				<p class="mt-2.5 text-3xl font-semibold text-slate-900">
					{fmtNumber(summary.sales.transaction_count)}
				</p>
				<p class="mt-1.5 text-sm text-slate-400">transactions</p>
			</div>
			<div class="rounded-2xl border border-slate-200 bg-white px-5 py-4">
				<p class="text-[11px] uppercase tracking-[0.18em] text-slate-400">Avg Sale Price</p>
				<p class="mt-2.5 text-3xl font-semibold text-slate-900">
					{fmtCurrency(summary.sales.avg_price)}
				</p>
				<p class="mt-1.5 text-sm text-slate-400">{fmtCurrency(summary.sales.avg_price_sqm)}/sqm</p>
			</div>
			<div class="rounded-2xl border border-slate-200 bg-white px-5 py-4">
				<p class="text-[11px] uppercase tracking-[0.18em] text-slate-400">Median Annual Rent</p>
				<p class="mt-2.5 text-3xl font-semibold text-slate-900">
					{fmtCurrency(summary.rentals.median_annual_rent)}
				</p>
				<p class="mt-1.5 text-sm text-slate-400">
					{fmtNumber(summary.rentals.contract_count)} contracts
				</p>
			</div>
			<div class="rounded-2xl border border-teal-200 bg-white px-5 py-4">
				<p class="text-[11px] uppercase tracking-[0.18em] text-teal-600">Gross Yield</p>
				<p class="mt-2.5 text-3xl font-semibold text-teal-600">
					{fmtPct(summary.overall_gross_yield_pct)}
				</p>
				<p class="mt-1.5 text-sm text-teal-500">median rent ÷ median sale</p>
			</div>
		</section>

		<section class="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_360px]">
			<section class="rounded-2xl border border-slate-200 bg-white p-5">
				<div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
					<div>
						<p class="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">
							Price Trend
						</p>
						<h3 class="mt-1 text-base font-semibold text-slate-900">
							Recorded pricing with delivery-aware forecast
						</h3>
					</div>
					<div class="inline-flex rounded-xl border border-slate-200 bg-slate-50 p-0.5">
						<button
							type="button"
							class="rounded-lg px-4 py-1.5 text-sm font-medium transition-colors {mode === 'sales' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}"
							onclick={() => (mode = 'sales')}
						>
							Sales
						</button>
						<button
							type="button"
							class="rounded-lg px-4 py-1.5 text-sm font-medium transition-colors {mode === 'rentals' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}"
							onclick={() => (mode = 'rentals')}
						>
							Price / sqm
						</button>
					</div>
				</div>
				<div class="mt-4 h-[280px]">
					{#if trendsQuery.isLoading || forecastQuery.isLoading}
						<div class="h-full animate-pulse rounded-xl bg-slate-100"></div>
					{:else if trends.length > 0 || (forecast?.data.length ?? 0) > 0}
						<canvas bind:this={trendCanvas}></canvas>
					{:else}
						<div class="flex h-full items-center justify-center rounded-xl border border-dashed border-slate-200 text-sm text-slate-400">
							No trend data available.
						</div>
					{/if}
				</div>
				{#if forecast?.delivery_date}
					<div class="mt-3 flex items-center gap-2 text-xs text-slate-500">
						<span class="inline-block h-1.5 w-1.5 rounded-full bg-teal-400"></span>
						Delivery anchor:
						<span class="font-medium text-slate-700">
							{new Date(forecast.delivery_date).toLocaleDateString('en-GB', {
								month: 'short',
								year: 'numeric'
							})}
						</span>
					</div>
				{/if}
			</section>

			<section class="rounded-2xl border border-slate-200 bg-white p-5">
				<p class="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">
					Market Split
				</p>
				<h3 class="mt-1 text-base font-semibold text-slate-900">
					Off-plan vs secondary sales
				</h3>
				<div class="mt-4 rounded-xl border border-slate-100 bg-slate-50/50 p-4">
					<div class="flex items-end justify-between gap-4">
						<div>
							<p class="text-[11px] uppercase tracking-[0.18em] text-slate-400">Total sales</p>
							<p class="mt-1 text-3xl font-semibold text-slate-900">{fmtNumber(marketSplit.total)}</p>
						</div>
						<p class="text-xs text-slate-400">transaction count</p>
					</div>
					<div class="mt-4 h-[220px]">
						{#if marketSplit.total > 0}
							<canvas bind:this={marketSplitCanvas}></canvas>
						{:else}
							<div class="flex h-full items-center justify-center rounded-xl border border-dashed border-slate-200 text-sm text-slate-400">
								No sales mix data
							</div>
						{/if}
					</div>
				</div>
				<div class="mt-5 grid gap-3">
					{#each marketSplit.segments as segment (segment.key)}
						<div class="flex items-center justify-between rounded-xl border border-slate-100 bg-slate-50/70 px-3.5 py-3">
							<div class="flex items-center gap-3">
								<span
									class="h-3 w-3 rounded-full"
									style={`background-color: ${segment.color};`}
								></span>
								<div>
									<p class="text-sm font-medium text-slate-800">{segment.label}</p>
									<p class="text-xs text-slate-400">{fmtNumber(segment.count)} sales</p>
								</div>
							</div>
							<p class="text-sm font-semibold text-slate-900">{fmtPct(segment.pct)}</p>
						</div>
					{/each}
				</div>
			</section>
		</section>

		<!-- ── Configuration Analysis ─────────────────────────────────── -->
		<section class="rounded-2xl border border-slate-200 bg-white p-5">
			<div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
				<div class="flex items-center gap-3">
					<h3 class="text-base font-semibold text-slate-900">Configuration Analysis</h3>
					<div class="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5">
						<button
							type="button"
							class="inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors {configMode === 'sales' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}"
							onclick={() => (configMode = 'sales')}
						>
							<svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
							</svg>
							Sales
						</button>
						<button
							type="button"
							class="inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors {configMode === 'rentals' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}"
							onclick={() => (configMode = 'rentals')}
						>
							<svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<rect x="3" y="3" width="7" height="7" rx="1" />
								<rect x="14" y="3" width="7" height="7" rx="1" />
								<rect x="3" y="14" width="7" height="7" rx="1" />
								<rect x="14" y="14" width="7" height="7" rx="1" />
							</svg>
							Rental
						</button>
					</div>
				</div>

				{#if configMode === 'sales'}
					<div class="inline-flex rounded-xl border border-slate-200 bg-slate-50 p-0.5">
						<button
							type="button"
							class="rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors {configSegment === 'all' ? 'bg-teal-500 text-white shadow-sm' : 'text-slate-500 hover:text-slate-700'}"
							onclick={() => (configSegment = 'all')}
						>
							All
						</button>
						<button
							type="button"
							class="rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors {configSegment === 'off_plan' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}"
							onclick={() => (configSegment = 'off_plan')}
						>
							Off-Plan
						</button>
						<button
							type="button"
							class="rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors {configSegment === 'secondary' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}"
							onclick={() => (configSegment = 'secondary')}
						>
							Secondary
						</button>
					</div>
				{/if}
			</div>

			{#if configMode === 'sales'}
				<div class="mt-4 overflow-x-auto">
					<table class="min-w-full border-separate border-spacing-0 text-sm">
						<thead>
							<tr class="text-left">
								<th class="border-b border-slate-100 pb-2.5 pr-6 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">Config</th>
								<th class="border-b border-slate-100 pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">Sales</th>
								<th class="border-b border-slate-100 pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">Avg Price</th>
								<th class="border-b border-slate-100 pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-300">Size sqm</th>
								<th class="border-b border-slate-100 pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
									Momentum<br /><span class="font-normal normal-case tracking-normal text-slate-300">QoQ δ</span>
								</th>
								<th class="border-b border-slate-100 pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-300">
									Days on Market<br /><span class="font-normal normal-case tracking-normal">median</span>
								</th>
								<th class="border-b border-slate-100 pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-300">
									Sale / List<br /><span class="font-normal normal-case tracking-normal">ratio</span>
								</th>
								<th class="border-b border-slate-100 pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
									Price Δ YoY<br /><span class="font-normal normal-case tracking-normal text-slate-300">% change</span>
								</th>
								<th class="border-b border-slate-100 pb-2.5 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-teal-500">
									Absorption<br /><span class="font-normal normal-case tracking-normal text-teal-400">% / year</span>
								</th>
							</tr>
						</thead>
						<tbody>
							{#each configRows as row (row.market_segment + row.rooms)}
								<tr class="group">
									<td class="border-b border-slate-50 py-3 pr-6 font-medium text-slate-900 group-hover:bg-slate-50/50">
										{row.rooms}
									</td>
									<td class="border-b border-slate-50 py-3 pr-6 text-right text-slate-700 group-hover:bg-slate-50/50">
										{fmtNumber(row.sales_last_12m)}
									</td>
									<td class="border-b border-slate-50 py-3 pr-6 text-right group-hover:bg-slate-50/50">
										<span class="font-medium text-slate-900">{fmtCurrency(row.avg_sale_price)}</span>
										{#if row.avg_sale_price_sqm > 0}
											<br /><span class="text-[11px] text-slate-400">{fmtPsf(row.avg_sale_price_sqm)}</span>
										{/if}
									</td>
									<td class="border-b border-slate-50 py-3 pr-6 text-right text-slate-300 group-hover:bg-slate-50/50">
										{row.avg_unit_size_sqm > 0 ? fmtNumber(row.avg_unit_size_sqm, 0) : '—'}
									</td>
									<td class="border-b border-slate-50 py-3 pr-6 text-right group-hover:bg-slate-50/50">
										{#if row.sales_momentum_pct == null || !Number.isFinite(row.sales_momentum_pct)}
											<span class="text-slate-300">—</span>
										{:else if Math.abs(row.sales_momentum_pct) < 0.5}
											<span class="inline-flex items-center gap-0.5 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-400">
												— {fmtSignedPct(row.sales_momentum_pct)}
											</span>
										{:else if row.sales_momentum_pct > 0}
											<span class="inline-flex items-center gap-0.5 rounded-full bg-teal-50 px-2 py-0.5 text-xs font-semibold text-teal-700 ring-1 ring-teal-200">
												▲ {fmtPct(row.sales_momentum_pct)}
											</span>
										{:else}
											<span class="inline-flex items-center gap-0.5 rounded-full bg-rose-50 px-2 py-0.5 text-xs font-semibold text-rose-600 ring-1 ring-rose-200">
												▼ {fmtPct(Math.abs(row.sales_momentum_pct))}
											</span>
										{/if}
									</td>
									<!-- Listing data — not available -->
									<td class="border-b border-slate-50 py-3 pr-6 text-right text-slate-200 group-hover:bg-slate-50/50">—</td>
									<td class="border-b border-slate-50 py-3 pr-6 text-right text-slate-200 group-hover:bg-slate-50/50">—</td>
									<td class="border-b border-slate-50 py-3 pr-6 text-right group-hover:bg-slate-50/50">
										{#if row.price_change_yoy_pct != null && Number.isFinite(row.price_change_yoy_pct)}
											<span class="font-medium {deltaTone(row.price_change_yoy_pct)}">
												{row.price_change_yoy_pct > 0 ? '▲' : row.price_change_yoy_pct < 0 ? '▼' : ''}
												{fmtPct(Math.abs(row.price_change_yoy_pct))}
											</span>
										{:else}
											<span class="text-slate-300">—</span>
										{/if}
									</td>
									<td class="border-b border-slate-50 py-3 text-right font-medium group-hover:bg-slate-50/50">
										<span class="{pctTone(row.absorption_rate_pct)}">
											{fmtPct(row.absorption_rate_pct)}
										</span>
									</td>
								</tr>
							{/each}
							{#if configRows.length === 0}
								<tr>
									<td colspan="9" class="py-8 text-center text-sm text-slate-400">
										No data available for this segment.
									</td>
								</tr>
							{/if}
						</tbody>
					</table>
				</div>
			{:else}
				<!-- Rental view -->
				<div class="mt-4 overflow-x-auto">
					<table class="min-w-full border-separate border-spacing-0 text-sm">
						<thead>
							<tr class="text-left">
								<th class="border-b border-slate-100 pb-2.5 pr-6 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">Config</th>
								<th class="border-b border-slate-100 pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">Contracts</th>
								<th class="border-b border-slate-100 pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">Median Rent</th>
								<th class="border-b border-slate-100 pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">Rent / sqm</th>
								<th class="border-b border-slate-100 pb-2.5 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-teal-500">Gross Yield</th>
							</tr>
						</thead>
						<tbody>
							{#each summary.by_rooms as row (row.rooms)}
								<tr class="group">
									<td class="border-b border-slate-50 py-3 pr-6 font-medium text-slate-900 group-hover:bg-slate-50/50">{row.rooms}</td>
									<td class="border-b border-slate-50 py-3 pr-6 text-right text-slate-600 group-hover:bg-slate-50/50">{fmtNumber(row.rental_count)}</td>
									<td class="border-b border-slate-50 py-3 pr-6 text-right font-medium text-slate-900 group-hover:bg-slate-50/50">{fmtCurrency(row.median_annual_rent)}</td>
									<td class="border-b border-slate-50 py-3 pr-6 text-right text-slate-500 group-hover:bg-slate-50/50">
										{row.median_rent_sqm > 0 ? `AED ${fmtNumber(row.median_rent_sqm, 0)}/sqm` : '—'}
									</td>
									<td class="border-b border-slate-50 py-3 text-right font-semibold {pctTone(row.gross_yield_pct)} group-hover:bg-slate-50/50">
										{fmtPct(row.gross_yield_pct)}
									</td>
								</tr>
							{/each}
							{#if summary.by_rooms.length === 0}
								<tr>
									<td colspan="5" class="py-8 text-center text-sm text-slate-400">No rental data available.</td>
								</tr>
							{/if}
						</tbody>
					</table>
				</div>
			{/if}
		</section>

		<!-- ── Price Distribution ─────────────────────────────────────── -->
		<section class="rounded-2xl border border-slate-200 bg-white p-5">
			<div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
				<h3 class="text-base font-semibold text-slate-900">Price Distribution</h3>
				<div class="inline-flex rounded-xl border border-slate-200 bg-slate-50 p-0.5">
					<button
						type="button"
						class="rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors {!distroOffplan ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}"
						onclick={() => { distroOffplan = false; distroRooms = 'All'; }}
					>
						All
					</button>
					<button
						type="button"
						class="rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors {distroOffplan ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}"
						onclick={() => { distroOffplan = true; distroRooms = 'All'; }}
					>
						Off-Plan Only
					</button>
				</div>
			</div>

			<!-- Room tabs -->
			{#if distroRoomList.length > 0}
				<div class="mt-3 flex flex-wrap gap-1.5">
					<button
						type="button"
						onclick={() => (distroRooms = 'All')}
						class="rounded-full px-3 py-1 text-xs font-medium transition-colors {distroRooms === 'All' ? 'bg-teal-500 text-white' : 'border border-slate-200 bg-white text-slate-600 hover:border-teal-300 hover:text-teal-600'}"
					>
						All
					</button>
					{#each distroRoomList as room (room)}
						<button
							type="button"
							onclick={() => (distroRooms = room)}
							class="rounded-full px-3 py-1 text-xs font-medium transition-colors {distroRooms === room ? 'bg-teal-500 text-white' : 'border border-slate-200 bg-white text-slate-600 hover:border-teal-300 hover:text-teal-600'}"
						>
							{room}
						</button>
					{/each}
				</div>
			{/if}

			<!-- Stats row -->
			{#if distroBucket}
				<div class="mt-4 grid grid-cols-3 gap-4 rounded-xl border border-slate-100 bg-slate-50/60 p-4">
					<div>
						<p class="flex items-center gap-1 text-[11px] font-medium uppercase tracking-[0.14em] text-slate-400">
							<span class="font-serif text-base text-slate-500">μ</span> Mean Price
						</p>
						<p class="mt-1 text-lg font-semibold text-teal-600">{fmtCurrency(distroBucket.mean_price)}</p>
					</div>
					<div>
						<p class="flex items-center gap-1 text-[11px] font-medium uppercase tracking-[0.14em] text-slate-400">
							<span class="font-serif text-base text-slate-500">σ</span> Std Deviation
						</p>
						<p class="mt-1 text-lg font-semibold text-slate-800">{fmtCurrency(distroBucket.std_price)}</p>
					</div>
					<div>
						<p class="text-[11px] font-medium uppercase tracking-[0.14em] text-slate-400">68% of Sales Between</p>
						<p class="mt-1 text-sm font-semibold text-slate-800">
							{fmtCurrency(Math.max(0, distroBucket.mean_price - distroBucket.std_price))}
							<span class="font-normal text-slate-400">–</span>
							{fmtCurrency(distroBucket.mean_price + distroBucket.std_price)}
						</p>
					</div>
				</div>
			{/if}

			<!-- Bell curve -->
			<div class="mt-4 h-[220px]">
				{#if distroQuery.isLoading}
					<div class="h-full animate-pulse rounded-xl bg-slate-100"></div>
				{:else if distroBucket && distroBucket.std_price > 0}
					<canvas bind:this={bellCanvas}></canvas>
				{:else}
					<div class="flex h-full items-center justify-center rounded-xl border border-dashed border-slate-200 text-sm text-slate-400">
						{distroQuery.data && !distroBucket
							? 'No data for this bedroom type.'
							: 'No distribution data available.'}
					</div>
				{/if}
			</div>
		</section>

		<!-- ── Stock Timeline ─────────────────────────────────────────── -->
		<section class="rounded-2xl border border-slate-200 bg-white p-5">
			<div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
				<h3 class="text-base font-semibold text-slate-900">
					Stock Timeline
					{#if pipeline?.area_name}
						<span class="ml-1 text-sm font-normal text-slate-400">· {pipeline.area_name}</span>
					{/if}
				</h3>
			</div>

			<!-- Room filter tabs -->
			{#if pipelineRoomList.length > 0}
				<div class="mt-3 flex flex-wrap gap-1.5">
					<button
						type="button"
						onclick={() => (pipelineRooms = null)}
						class="rounded-full px-3 py-1 text-xs font-medium transition-colors {pipelineRooms === null ? 'bg-teal-500 text-white' : 'border border-slate-200 bg-white text-slate-600 hover:border-teal-300 hover:text-teal-600'}"
					>
						All
					</button>
					{#each pipelineRoomList as room (room)}
						<button
							type="button"
							onclick={() => (pipelineRooms = room)}
							class="rounded-full px-3 py-1 text-xs font-medium transition-colors {pipelineRooms === room ? 'bg-teal-500 text-white' : 'border border-slate-200 bg-white text-slate-600 hover:border-teal-300 hover:text-teal-600'}"
						>
							{room}
						</button>
					{/each}
				</div>
			{/if}

			<div class="mt-4 h-[340px]">
				{#if pipelineQuery.isLoading}
					<div class="h-full animate-pulse rounded-xl bg-slate-100"></div>
				{:else if pipeline && pipeline.data.length > 0}
					<canvas bind:this={pipelineCanvas}></canvas>
				{:else}
					<div class="flex h-full items-center justify-center rounded-xl border border-dashed border-slate-200 text-sm text-slate-400">
						No pipeline data available for this area.
					</div>
				{/if}
			</div>
		</section>

	</div>
{:else if summaryQuery.isError}
	<div class="rounded-2xl border border-rose-200 bg-rose-50 px-8 py-16 text-center text-sm text-rose-700">
		Failed to load analytics for this project.
	</div>
{/if}
