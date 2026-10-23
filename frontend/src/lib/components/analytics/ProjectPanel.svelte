<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { Chart, registerables } from 'chart.js'
import { onMount } from 'svelte'
import type {
	AnalyticsUsage,
	PriceDistributionBucket,
	ProjectAnalyticsResponse,
	ProjectConfigurationRow,
	ProjectForecastPoint,
	ProjectPipelinePoint,
	ProjectSearchItem,
	ProjectTrendPoint,
	SubProjectItem
} from '$lib/api/analytics'
import StandardDropdown from '$lib/components/dropdowns/StandardDropdown.svelte'
import { analyticsQueries } from '$lib/queries/analytics'
import { getChartTheme } from '$lib/utils/chartTheme'
import AnalyticsError from './AnalyticsError.svelte'
import UsageToggle from './UsageToggle.svelte'

Chart.register(...registerables)

let {
	selection,
	onSelect
}: { selection: ProjectSearchItem; onSelect?: (next: ProjectSearchItem) => void } = $props()

type AnalysisMode = 'sales' | 'rentals'
type ConfigSegment = 'all' | 'off_plan' | 'secondary'
type TrendChartPoint = Pick<ProjectTrendPoint, 'date' | 'avg_price' | 'avg_price_sqft'>

let subProject = $state<string | null>(null)
let mode = $state<AnalysisMode>('sales')
let configMode = $state<AnalysisMode>('sales')
let configSegment = $state<ConfigSegment>('all')
let distroRooms = $state<string>('All')
let distroOffplan = $state(false)
let subDropdownOpen = $state(false)
let subSearch = $state('')
// Residential or Commercial records; a new selection starts automatic (Commercial for a scope
// with no residential records), a click pins the choice.
let usage = $state<AnalyticsUsage>('auto')
let summaryPeriod = $state('Last Year')
const summaryPeriods: Record<string, number | undefined> = {
	'Last Week': 7,
	'Last Month': 30,
	'Last 3 Months': 90,
	'Last 6 Months': 180,
	'Last Year': 365,
	'All time': undefined
}
const summaryDays = $derived(summaryPeriods[summaryPeriod])

$effect(() => {
	selection
	subProject = null
	usage = 'auto'
	mode = 'sales'
	configMode = 'sales'
	configSegment = 'all'
	distroRooms = 'All'
	distroOffplan = false
	subDropdownOpen = false
	subSearch = ''
})

const queryParams = $derived.by(() =>
	selection.filter_type === 'market'
		? { usage }
		: selection.filter_type === 'building'
			? { buildingId: selection.building_id ?? '', usage }
			: subProject
				? { project: subProject, masterProject: selection.name, usage }
				: selection.filter_type === 'project'
					? { project: selection.name, usage }
					: { masterProject: selection.name, filterType: selection.filter_type, usage }
)

const subProjectsQuery = createQuery(() =>
	analyticsQueries.subProjects(selection.name, selection.filter_type)
)

const summaryQuery = createQuery(() =>
	analyticsQueries.projectSummary({ ...queryParams, summary_days: summaryDays })
)

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
	return (
		summary?.configuration_analysis
			.filter((row) => row.market_segment === configSegment)
			.filter((row) => isReliableConfigRow(row, summary.usage)) ?? []
	)
}

function getConfigurationRentalRows(summary: ProjectAnalyticsResponse | null) {
	return (
		summary?.by_rooms.filter(
			(row) => isConfigRoom(row.rooms, summary.usage) && row.rental_count > 0
		) ?? []
	)
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
				color: 'var(--color-chart-line)'
			},
			{
				key: 'secondary',
				label: 'Secondary',
				count: secondary,
				pct: total > 0 ? (secondary / total) * 100 : 0,
				color: 'var(--color-chart-line-alt)'
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
	if (e.key === 'Escape') {
		;(e.currentTarget as HTMLElement).closest('[role="group"]')?.querySelector('button')?.focus()
		closeSubDropdown()
	}
	if (e.key === 'Enter' && e.target instanceof HTMLInputElement) {
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

function normalizeText(value: string | null | undefined): string | null {
	const normalized = value?.trim().replace(/\s+/g, ' ')
	return normalized || null
}

function uniqueNormalized(values: Array<string | null | undefined>): string[] {
	const seen = new Set<string>()
	const labels: string[] = []
	for (const value of values) {
		const label = normalizeText(value)
		if (!label) continue
		const key = label.toLocaleLowerCase()
		if (seen.has(key)) continue
		seen.add(key)
		labels.push(label)
	}
	return labels
}

function getDeveloperNames(summary: ProjectAnalyticsResponse): string[] {
	const project = summary.project
	return uniqueNormalized([...(project?.developer_names ?? []), project?.developer_name])
}

// Where a header value came from: "Developer, Handover: DXBInteract's building list".
const FIELD_LABELS: Record<string, string> = {
	developer_name: 'Developer',
	completion_date: 'Handover',
	percent_completed: 'Completion',
	no_of_units: 'Units',
	no_of_buildings: 'Buildings',
	area_name: 'Area'
}
const SOURCE_LABELS: Record<string, string> = {
	dxbi_buildings: "DXBInteract's building list",
	dld_units: "DLD's unit register",
	dld_projects: "DLD's project register",
	buildings: 'its buildings added up',
	dld_land_plots: "DLD's land register (villa plots)",
	units_traded: 'units with a recorded sale or lease (no register count)',
	unit_numbers: 'counted from the unit numbers in our records',
	projects_rollup: 'its projects added up',
	dxbi_records: 'DXBI buildings with records'
}

// Registered units as shown: "at least" when only the units that traded are known.
function unitsLabel(project: ProjectAnalyticsResponse['project']): string {
	if (!project?.no_of_units) return '—'
	return project.units_at_least
		? `at least ${fmtNumber(project.no_of_units)}`
		: fmtNumber(project.no_of_units)
}

// The way back up the hierarchy from a building or project.
function selectUp(level: 'master' | 'project', name: string | null | undefined) {
	if (!name || !onSelect) return
	onSelect(
		level === 'master'
			? { name, filter_type: 'master', scope_kind: 'Master' }
			: { name, filter_type: 'project', scope_kind: 'Project' }
	)
}

function selectBuilding(building: { building_id: string; name: string }) {
	const project = getSummary()?.project
	onSelect?.({
		name: building.name,
		filter_type: 'building',
		scope_kind: 'Building',
		building: building.name,
		building_id: building.building_id,
		project: project?.project_name ?? '',
		master: project?.master_name ?? ''
	})
}

function fieldSourceNote(sources: Record<string, string> | undefined): string {
	const bySource = new Map<string, string[]>()
	for (const [field, source] of Object.entries(sources ?? {})) {
		bySource.set(source, [...(bySource.get(source) ?? []), FIELD_LABELS[field] ?? field])
	}
	return [...bySource]
		.map(([source, fields]) => `${fields.join(', ')}: ${SOURCE_LABELS[source] ?? source}`)
		.join(' · ')
}

function getDeveloperLabel(
	summary: ProjectAnalyticsResponse,
	isMasterScope: boolean,
	isMarketScope: boolean
) {
	if (isMarketScope) return 'Developers'
	const developerCount = getDeveloperNames(summary).length
	return isMasterScope && developerCount > 1 ? 'Top developer' : 'Developer'
}

function getDeveloperDisplay(
	summary: ProjectAnalyticsResponse,
	isMasterScope: boolean,
	isMarketScope: boolean
) {
	const names = getDeveloperNames(summary)
	if (isMarketScope) return names[0] ?? 'All developers'
	if (isMasterScope && names.length > 1) return `${names[0]} +${names.length - 1} more`
	return names[0] ?? '—'
}

// A residential configuration is a bedroom count; a commercial one is the property type (Office,
// Shop): the backend groups commercial records by type.
function isConfigRoom(room: string | null | undefined, usage = 'Residential'): boolean {
	const label = normalizeText(room)
	if (!label) return false
	const upper = label.toUpperCase()
	if (['NA', 'N/A', 'NONE', 'NULL'].includes(upper)) return false
	if (usage === 'Commercial') return true
	return upper === 'STUDIO' || /^\d+\s+B\/R$/i.test(label) || upper.includes('PENTHOUSE')
}

function isReliableConfigRow(row: ProjectConfigurationRow, usage = 'Residential'): boolean {
	return (
		isConfigRoom(row.rooms, usage) &&
		(row.stock_units > 0 || row.sale_count > 0 || row.sales_last_12m > 0 || row.rental_count > 0)
	)
}

function statusBadgeClass(status: string): string {
	const s = (status ?? '').toLowerCase()
	if (s.includes('complet') || s.includes('handov') || s.includes('deliver'))
		return 'bg-success-bg text-success ring-1 ring-border'
	if (
		s.includes('construct') ||
		s.includes('progress') ||
		s.includes('active') ||
		s.includes('plan')
	)
		return 'bg-warning-bg text-warning ring-1 ring-border'
	if (s.includes('cancel')) return 'bg-error-bg text-error ring-1 ring-border'
	return 'bg-panel text-fg-3 ring-1 ring-border'
}

function fmtCurrency(n: number | null | undefined): string {
	if (n == null || !Number.isFinite(n) || n <= 0) return '—'
	return `AED ${n.toLocaleString('en-AE', { maximumFractionDigits: 2 })}`
}

function fmtCompact(n: number | null | undefined): string {
	if (n == null || !Number.isFinite(n)) return '—'
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
	if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`
	return Math.round(n).toLocaleString()
}

function fmtAxisCurrency(n: number | null | undefined): string {
	if (n == null || !Number.isFinite(n)) return '—'
	if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
	if (n >= 1_000) return `${(n / 1_000).toFixed(n < 100_000 ? 1 : 0)}K`
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

function fmtPsf(pricePerSqft: number | null | undefined): string {
	if (!pricePerSqft || !Number.isFinite(pricePerSqft)) return ''
	return `AED ${fmtNumber(pricePerSqft, 2)}/sq ft`
}

function pctTone(value: number | null | undefined) {
	if (value == null || !Number.isFinite(value)) return 'text-fg-4'
	if (value >= 7) return 'text-success'
	if (value >= 5) return 'text-warning'
	return 'text-error'
}

function deltaTone(value: number | null | undefined) {
	if (value == null || !Number.isFinite(value)) return 'text-fg-4'
	if (value > 0) return 'text-success'
	if (value < 0) return 'text-error'
	return 'text-fg-3'
}

function fmtQuarterLabel(value: string | Date): string {
	const dt = new Date(value)
	const quarter = Math.floor(dt.getMonth() / 3) + 1
	return `Q${quarter} '${String(dt.getFullYear()).slice(-2)}`
}

function isAggregateSelection(): boolean {
	return selection.filter_type !== 'project' && selection.filter_type !== 'building' && !subProject
}

function isMarketSelection(): boolean {
	return selection.filter_type === 'market' && !subProject
}

function trendDateKey(point: TrendChartPoint | ProjectForecastPoint): string {
	return new Date(point.date).toISOString().slice(0, 10)
}

function trendMetric(point: TrendChartPoint | ProjectForecastPoint): number {
	return mode === 'sales' ? point.avg_price : point.avg_price_sqft
}

function getRecordedTrendSeries(): TrendChartPoint[] {
	const trends = getTrends()
	if (trends.length > 0) return trends
	if (isAggregateSelection()) return []
	return (getForecast()?.data ?? []).filter(
		(point: ProjectForecastPoint) => point.series === 'historical'
	)
}

function getFutureForecastSeries(
	recordedSeries = getRecordedTrendSeries()
): ProjectForecastPoint[] {
	const forecast = getForecast()
	if (isAggregateSelection() || !forecast?.delivery_date || recordedSeries.length === 0) return []

	const lastRecordedMs = new Date(recordedSeries[recordedSeries.length - 1].date).getTime()
	const deliveryMs = new Date(forecast.delivery_date).getTime()
	if (!Number.isFinite(deliveryMs) || deliveryMs <= lastRecordedMs) return []

	return forecast.data.filter(
		(point: ProjectForecastPoint) =>
			point.series === 'forecast' && new Date(point.date).getTime() > lastRecordedMs
	)
}

function shouldShowTrendForecast(recordedSeries = getRecordedTrendSeries()): boolean {
	return getFutureForecastSeries(recordedSeries).length > 0
}

function hasTrendChartData(): boolean {
	return getRecordedTrendSeries().length > 0
}

function getCurrentQuarterStartMs(date = new Date()): number {
	const quarterStartMonth = Math.floor(date.getMonth() / 3) * 3
	return new Date(date.getFullYear(), quarterStartMonth, 1).getTime()
}

function getPipelinePeriodMs(value: string | Date): number {
	const dt = new Date(value)
	return new Date(dt.getFullYear(), dt.getMonth(), 1).getTime()
}

function getPipelineStockUnits(point: ProjectPipelinePoint): number {
	return point.existing_stock_units > 0
		? point.existing_stock_units
		: point.carried_stock_units + point.new_pipeline_units
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
let themeVersion = $state(0)

// ─── Trend chart ─────────────────────────────────────────────────────────
function buildTrendChart() {
	const recordedSeries = getRecordedTrendSeries()
	const forecastSeries = getFutureForecastSeries(recordedSeries)
	if (!trendCanvas || recordedSeries.length === 0) {
		trendChart?.destroy()
		trendChart = null
		return
	}
	trendChart?.destroy()
	const ctx = trendCanvas.getContext('2d')
	if (!ctx) return
	const theme = getChartTheme()

	const gradient = ctx.createLinearGradient(0, 0, 0, 280)
	gradient.addColorStop(0, theme.fill)
	gradient.addColorStop(1, 'transparent')

	const labelKeys = [
		...recordedSeries.map((point) => trendDateKey(point)),
		...forecastSeries.map((point) => trendDateKey(point))
	].filter((key, index, keys) => keys.indexOf(key) === index)
	const recordedValueByDate = new Map(
		recordedSeries.map((point) => [trendDateKey(point), trendMetric(point)])
	)
	const forecastValueByDate = new Map(
		forecastSeries.map((point) => [trendDateKey(point), trendMetric(point)])
	)
	const lastRecorded = recordedSeries[recordedSeries.length - 1]
	const lastRecordedKey = trendDateKey(lastRecorded)
	const recordedValues = labelKeys.map((key) => recordedValueByDate.get(key) ?? null)
	const forecastValues =
		forecastSeries.length > 0
			? labelKeys.map((key) =>
					key === lastRecordedKey
						? trendMetric(lastRecorded)
						: (forecastValueByDate.get(key) ?? null)
				)
			: []

	trendChart = new Chart(ctx, {
		type: 'line',
		data: {
			labels: labelKeys.map((key) =>
				new Date(key).toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
			),
			datasets: [
				{
					label: 'Recorded',
					data: recordedValues,
					borderColor: theme.line,
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
								borderColor: theme.lineAlt,
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
				legend: {
					display: forecastSeries.length > 0,
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
					padding: 10,
					displayColors: false,
					callbacks: {
						label: (context) =>
							mode === 'sales'
								? ` ${fmtCurrency(Number(context.parsed.y ?? 0))}`
								: ` AED ${fmtNumber(Number(context.parsed.y ?? 0), 0)}/sq ft`
					}
				}
			},
			scales: {
				x: {
					grid: { display: false },
					border: { display: false },
					ticks: { color: theme.muted, maxTicksLimit: 8 }
				},
				y: {
					grid: { color: theme.grid },
					border: { display: false },
					ticks: {
						color: theme.muted,
						callback: (value) =>
							mode === 'sales' ? fmtAxisCurrency(Number(value)) : fmtNumber(Number(value), 0)
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
	const theme = getChartTheme()

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
	gradient.addColorStop(0, theme.fill)
	gradient.addColorStop(1, 'transparent')

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
					borderColor: theme.line,
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
					backgroundColor: theme.tooltipBackground,
					titleColor: theme.tooltipText,
					bodyColor: theme.tooltipText,
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
						color: theme.muted,
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
						c.strokeStyle = alpha > 0.5 ? theme.line : theme.axis
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
	const pipelineData = getPipeline()?.data ?? []
	if (!pipelineCanvas || pipelineData.length === 0) {
		pipelineChart?.destroy()
		pipelineChart = null
		return
	}
	pipelineChart?.destroy()
	const ctx = pipelineCanvas.getContext('2d')
	if (!ctx) return
	const theme = getChartTheme()

	const currentQuarterMs = getCurrentQuarterStartMs()
	const firstProjectedIdx = pipelineData.findIndex(
		(point) => getPipelinePeriodMs(point.period) >= currentQuarterMs
	)
	const visiblePipelineData =
		firstProjectedIdx > 0 ? pipelineData.slice(firstProjectedIdx - 1) : pipelineData
	const firstVisibleProjectedIdx =
		firstProjectedIdx > 0 ? 1 : firstProjectedIdx === -1 ? -1 : firstProjectedIdx
	const totalStock = visiblePipelineData.map((point) => getPipelineStockUnits(point))
	const upcomingSupply = visiblePipelineData.map((point, index) =>
		firstVisibleProjectedIdx >= 0 &&
		index >= firstVisibleProjectedIdx &&
		point.new_pipeline_units > 0
			? point.new_pipeline_units
			: null
	)

	pipelineChart = new Chart(ctx, {
		type: 'bar',
		data: {
			labels: visiblePipelineData.map((p) => fmtQuarterLabel(p.period)),
			datasets: [
				{
					type: 'line' as const,
					label: 'Total stock',
					data: totalStock,
					yAxisID: 'stock',
					borderColor: theme.line,
					backgroundColor: 'transparent',
					borderWidth: 2.5,
					pointRadius: 0,
					pointHoverRadius: 4,
					tension: 0.25
				},
				...(upcomingSupply.some((value) => value != null)
					? [
							{
								type: 'bar' as const,
								label: 'Upcoming supply',
								data: upcomingSupply,
								yAxisID: 'deliveries',
								backgroundColor: theme.warning,
								borderRadius: 4,
								barPercentage: 0.58,
								categoryPercentage: 0.72
							}
						]
					: [])
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
					filter: (item) => item.parsed.y != null,
					callbacks: {
						label: (c) => ` ${c.dataset.label}: ${fmtCompact(Number(c.parsed.y))} units`
					}
				}
			},
			scales: {
				x: {
					grid: { display: false },
					border: { display: false },
					ticks: { color: theme.muted, maxTicksLimit: 12 }
				},
				// Each axis is titled in its series' colour: stock (line) left, supply (bars) right.
				stock: {
					type: 'linear',
					position: 'left',
					beginAtZero: true,
					grid: { color: theme.grid },
					border: { display: false },
					title: { display: true, text: 'Total stock (units)', color: theme.line },
					ticks: { color: theme.muted, callback: (v) => fmtCompact(Number(v)) }
				},
				deliveries: {
					type: 'linear',
					position: 'right',
					beginAtZero: true,
					grid: { drawOnChartArea: false },
					border: { display: false },
					title: { display: true, text: 'Upcoming supply (units)', color: theme.warning },
					ticks: { color: theme.muted, callback: (v) => fmtCompact(Number(v)) }
				}
			}
		}
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
	const theme = getChartTheme()

	marketSplitChart = new Chart(ctx, {
		type: 'bar',
		data: {
			labels: marketSplit.segments.map((segment) => segment.label),
			datasets: [
				{
					data: marketSplit.segments.map((segment) => segment.count),
					backgroundColor: [theme.line, theme.lineAlt],
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
					backgroundColor: theme.tooltipBackground,
					titleColor: theme.tooltipText,
					bodyColor: theme.tooltipText,
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
					grid: { color: theme.grid },
					border: { display: false },
					ticks: {
						color: theme.muted,
						callback: (value) => fmtCompact(Number(value))
					}
				},
				y: {
					grid: { display: false },
					border: { display: false },
					ticks: { color: theme.foregroundMuted, font: { weight: 600 } }
				}
			}
		}
	})
}

$effect(() => {
	if (
		distroQuery.data &&
		distroRooms !== 'All' &&
		!distroQuery.data.by_rooms.some((row) => row.rooms === distroRooms)
	)
		distroRooms = 'All'
})

// ─── Effects ──────────────────────────────────────────────────────────────
$effect(() => {
	mode
	themeVersion
	getForecast()
	buildTrendChart()
})

$effect(() => {
	const _d = distroQuery.data
	const _r = distroRooms
	themeVersion
	buildBellChart()
})

$effect(() => {
	themeVersion
	getPipeline()
	getSummary()
	buildPipelineChart()
})

$effect(() => {
	themeVersion
	getSummary()
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
		bellChart?.destroy()
		pipelineChart?.destroy()
		marketSplitChart?.destroy()
	}
})
</script>

{#if summaryQuery.isError}
	<AnalyticsError message="Failed to load analytics for this project." retry={() => summaryQuery.refetch()} fetching={summaryQuery.isFetching} />
{:else if summaryQuery.isLoading}
	<div class="grid gap-6">
		<div class="h-36 animate-pulse rounded-lg border border-border bg-card"></div>
		<div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
			{#each [0, 1, 2, 3] as item (item)}
				<div class="h-28 animate-pulse rounded-lg border border-border bg-card"></div>
			{/each}
		</div>
		<div class="h-[480px] animate-pulse rounded-lg border border-border bg-card"></div>
	</div>
{:else if getSummary()}
	{@const summary = getSummary()!}
	{@const subProjects = getSubProjects()}
	{@const filteredSubProjects = getFilteredSubProjects()}
	{@const trends = getTrends()}
	{@const forecast = getForecast()}
	{@const pipeline = getPipeline()}
	{@const configRows = getConfigurationRows(summary)}
	{@const rentalConfigRows = getConfigurationRentalRows(summary)}
	{@const distroBucket = getDistroBucket()}
	{@const distroRoomList = getDistroRooms()}
	{@const marketSplit = getMarketSplit(summary)}
	{@const isMarketScope = isMarketSelection()}
	<!-- A project's developer, units or handover, from a named source (not its area alone). -->
	{@const hasProjectDetails =
		!isMarketScope &&
		Object.keys(summary.project?.field_sources ?? {}).some((field) => field !== 'area_name')}
	{@const isBuildingScope = selection.filter_type === 'building'}
	{@const isMasterScope = selection.filter_type !== 'project' && selection.filter_type !== 'market' && !isBuildingScope && !subProject}
	<div class="space-y-5">

		{#if subProjectsQuery.isError}
			<AnalyticsError message="Failed to load developments." retry={() => subProjectsQuery.refetch()} fetching={subProjectsQuery.isFetching} />
		{/if}
		<!-- ── Project header ────────────────────────────────────────── -->
		<section class="rounded-lg border border-border bg-card p-5">
			<div class="flex flex-wrap items-start justify-between gap-4">
				<div class="min-w-0">
					{#if !isMasterScope && !isMarketScope && summary.project?.master_name}
						<!-- Master › Project for a building: each level opens its own analytics. -->
						<nav
							aria-label="Location"
							class="flex flex-wrap items-center gap-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-fg-4"
							data-testid="analytics-breadcrumb"
						>
							<button type="button" class="uppercase hover:text-info" onclick={() => selectUp('master', summary.project?.master_name)}>
								{summary.project.master_name}
							</button>
							{#if isBuildingScope && summary.project?.parent_project}
								<span aria-hidden="true">›</span>
								<button type="button" class="uppercase hover:text-info" onclick={() => selectUp('project', summary.project?.parent_project)}>
									{summary.project.parent_project}
								</button>
							{/if}
						</nav>
					{:else}
						<p class="text-[11px] font-semibold uppercase tracking-[0.22em] text-fg-4">
							{summary.project?.area_name ?? `${selection.scope_kind ?? 'Location'} analytics`}
						</p>
					{/if}
					<h2 class="mt-1.5 truncate text-2xl font-semibold tracking-normal text-fg-1">
						{subProject
							? stripPrefix(subProject)
							: summary.project?.project_name ?? selection.name}
					</h2>
					{#if isMarketScope}
						<p class="mt-1 text-sm text-fg-3">
							Citywide {summary.usage === 'Commercial' ? 'commercial' : 'residential'} market aggregate
						</p>
					{:else if isMasterScope}
						<p class="mt-1 text-sm text-fg-3">
							Master community aggregate{subProjects.length > 0
								? ` - ${fmtNumber(subProjects.length)} developments`
								: ''}
						</p>
					{:else if isBuildingScope}
						<p class="mt-1 text-sm text-fg-3">
							Building{summary.project?.developer_name ? ` · ${summary.project.developer_name}` : ''}
						</p>
					{:else if summary.project?.developer_name}
						<p class="mt-1 text-sm text-fg-3">{summary.project.developer_name}</p>
					{/if}
					<UsageToggle
						counts={summary.usage_counts}
						resolved={summary.usage === 'Commercial' ? 'Commercial' : 'Residential'}
						value={usage}
						scope={`${isMarketScope ? 'Dubai' : isMasterScope ? 'this community' : isBuildingScope ? 'this building' : 'this project'}${summaryDays ? ' in the selected window' : ''}`}
						onchange={(choice) => (usage = choice)}
					>
						<div class="flex items-center gap-2">
							<label for="analytics-summary-window-button" class="text-xs font-medium text-fg-3">Summary window</label>
							<div class="w-40">
								<StandardDropdown id="analytics-summary-window" ariaLabel="Summary window" options={Object.keys(summaryPeriods)} bind:value={summaryPeriod} />
							</div>
						</div>
					</UsageToggle>
				</div>

				<div class="flex items-center gap-3">
					{#if isMarketScope}
						<span
							class="inline-flex items-center rounded-sm bg-info-bg px-2.5 py-1 text-xs font-semibold text-info ring-1 ring-border"
						>
							Dubai market
						</span>
					{:else if isMasterScope}
						<span
							class="inline-flex items-center rounded-sm bg-info-bg px-2.5 py-1 text-xs font-semibold text-info ring-1 ring-border"
						>
							Master community
						</span>
					{:else if isBuildingScope}
						<span
							class="inline-flex items-center rounded-sm bg-info-bg px-2.5 py-1 text-xs font-semibold text-info ring-1 ring-border"
						>
							Building
						</span>
					{:else if summary.project?.project_status}
						<span
							class="inline-flex items-center rounded-sm px-2.5 py-1 text-xs font-semibold {statusBadgeClass(summary.project.project_status)}"
						>
							{summary.project.project_status}
						</span>
					{/if}

					{#if subProjects.length > 1}
						<div class="relative" role="group" aria-label="Development selection" use:clickOutside={closeSubDropdown}
							onfocusout={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) closeSubDropdown() }}>
							<button
								type="button"
								onkeydown={handleSubKeydown}
								onclick={() => {
									subDropdownOpen = !subDropdownOpen;
									subSearch = '';
								}}
								class="inline-flex items-center gap-2 rounded-md border border-border bg-panel px-3 py-2 text-sm font-medium text-fg-2 transition-colors hover:border-strong hover:text-info"
							>
								<span
									>{subProject
										? stripPrefix(subProject)
										: `All development (${subProjects.length})`}</span
								>
								<svg class="h-4 w-4 text-fg-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
								</svg>
							</button>
							{#if subDropdownOpen}
								<div
									class="absolute right-0 z-50 mt-2 w-72 overflow-hidden rounded-lg border border-border bg-card shadow-lg"
								>
									<div class="border-b border-border p-2">
										<input
											type="text"
											class="w-full rounded-md border border-border px-3 py-2 text-sm focus:border-focus focus:outline-none focus:ring-2 focus:ring-focus"
											placeholder="Filter sub-projects..."
											bind:value={subSearch}
											onkeydown={handleSubKeydown}
										/>
									</div>
									<div class="max-h-64 overflow-y-auto p-2">
										<button
											type="button"
											onkeydown={handleSubKeydown}
											class="w-full rounded-md px-3 py-2 text-left text-sm transition-colors {subProject === null ? 'bg-info-bg text-info' : 'text-fg-2 hover:bg-panel'}"
											onclick={() => {
												subProject = null;
												closeSubDropdown();
											}}
										>
											All development
										</button>
										{#each filteredSubProjects as sp (sp.name)}
											<button
												type="button"
												onkeydown={handleSubKeydown}
												class="mt-0.5 w-full rounded-md px-3 py-2 text-left text-sm transition-colors {subProject === sp.name ? 'bg-info-bg text-info' : 'text-fg-2 hover:bg-panel'}"
												onclick={() => {
													subProject = sp.name;
													closeSubDropdown();
												}}
											>
												{stripPrefix(sp.name)}
											</button>
										{/each}
										{#if filteredSubProjects.length === 0}
											<div class="px-3 py-2 text-sm text-fg-4">No matches</div>
										{/if}
									</div>
								</div>
							{/if}
						</div>
					{/if}
				</div>
			</div>

			<!-- Metadata strip: a project's details where a source holds them (sources named below). -->
			{#if hasProjectDetails}
			<div class="mt-4 flex flex-wrap gap-4 border-t border-border pt-4">
				<div class="min-w-[150px] max-w-[260px]">
					<p class="text-[11px] uppercase tracking-[0.16em] text-fg-4">{getDeveloperLabel(summary, isMasterScope, isMarketScope)}</p>
					<p class="mt-1 truncate text-sm font-medium text-fg-1" title={getDeveloperDisplay(summary, isMasterScope, isMarketScope)}>
						{getDeveloperDisplay(summary, isMasterScope, isMarketScope)}
					</p>
				</div>
				<div class="min-w-[100px]">
					<p class="text-[11px] uppercase tracking-[0.16em] text-fg-4">Units</p>
					<p class="mt-1 text-sm font-medium text-fg-1" data-testid="analytics-units">
						{unitsLabel(summary.project)}
					</p>
					{#if isMasterScope && summary.project?.no_of_projects}
						<p class="mt-1 text-[11px] text-fg-4">
							{fmtNumber(summary.project.projects_with_units ?? 0)} of {fmtNumber(summary.project.no_of_projects)} projects counted
						</p>
					{:else if summary.project?.units_at_least}
						<p class="mt-1 text-[11px] text-fg-4">No register count; units traded</p>
					{/if}
				</div>
				<div class="min-w-[160px]">
					<p class="text-[11px] uppercase tracking-[0.16em] text-fg-4">Handover</p>
					{#if isMarketScope}
						<p class="mt-1 text-sm font-medium text-fg-1">All completions</p>
					{:else if isMasterScope}
						<p class="mt-1 text-sm font-medium text-fg-1">Multiple phases</p>
					{:else if summary.project?.completion_date}
						<p class="mt-1 text-sm font-medium text-fg-1">
							{new Date(summary.project.completion_date).toLocaleDateString('en-GB', {
								month: 'short',
								year: 'numeric'
							})}
						</p>
					{:else}
						<p class="mt-1 text-sm font-medium text-fg-1">—</p>
					{/if}
					{#if summary.project?.percent_completed != null}
						<div class="mt-1.5 h-1.5 w-full max-w-[140px] rounded-full bg-panel">
							<div
								class="h-1.5 rounded-full bg-primary-light"
								style="width: {Math.min(100, summary.project.percent_completed)}%"
							></div>
						</div>
						<p class="mt-1 text-[11px] text-fg-4">
							{fmtPct(summary.project.percent_completed, 0)}
							{isMasterScope ? 'aggregate completion' : 'complete'}
						</p>
					{/if}
				</div>
				{#if isMasterScope && subProjects.length > 0}
					<div class="min-w-[120px]">
						<p class="text-[11px] uppercase tracking-[0.16em] text-fg-4">Developments</p>
						<p class="mt-1 text-sm font-medium text-fg-1">
							{fmtNumber(subProjects.length)}
						</p>
					</div>
				{:else if summary.project?.no_of_buildings}
					<div class="min-w-[100px]">
						<p class="text-[11px] uppercase tracking-[0.16em] text-fg-4">Buildings</p>
						<p class="mt-1 text-sm font-medium text-fg-1">
							{fmtNumber(summary.project.no_of_buildings)}
						</p>
					</div>
				{/if}
			</div>
			{#if fieldSourceNote(summary.project?.field_sources)}
				<p class="mt-2 text-[11px] text-fg-4" data-testid="analytics-field-sources">
					Sources: {fieldSourceNote(summary.project?.field_sources)}
				</p>
			{/if}
			{/if}
            <p class="mt-4 border-t border-border pt-3 text-xs text-fg-4">
                DXBI transactions · {summary.usage === 'Commercial' ? 'Commercial' : 'Residential'} properties. Summary cards and usage counts: {summaryDays ? `last ${summaryDays} days, including today (Dubai time)` : 'all recorded dates'}. Sales use sale dates; rentals use lease start dates.
                {#if !hasProjectDetails}Registered unit stock and delivery forecasts are unavailable from this source.{/if}
            </p>
		</section>

		<!-- ── A project's buildings ─────────────────────────────────── -->
		{#if !isBuildingScope && !isMasterScope && !isMarketScope && (summary.buildings?.length ?? 0) > 0}
			<section class="rounded-lg border border-border bg-card p-5" data-testid="analytics-buildings">
				<div class="flex items-baseline justify-between gap-3">
					<h3 class="text-sm font-semibold text-fg-1">Buildings</h3>
					<p class="text-xs text-fg-4">Select a building for its own analytics</p>
				</div>
				<div class="mt-3 overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-border text-left text-[11px] uppercase tracking-[0.12em] text-fg-4">
								<th class="py-2 pr-4 font-medium">Building</th>
								<th class="py-2 pr-4 text-right font-medium">Units</th>
								<th class="py-2 pr-4 text-right font-medium">Sales</th>
								<th class="py-2 text-right font-medium">Leases</th>
							</tr>
						</thead>
						<tbody>
							{#each summary.buildings ?? [] as building (building.building_id)}
								<tr class="border-b border-border last:border-0">
									<td class="py-2 pr-4">
										<button type="button" class="text-left font-medium text-fg-1 hover:text-info" onclick={() => selectBuilding(building)}>
											{building.name}
										</button>
									</td>
									<td class="py-2 pr-4 text-right tabular-nums text-fg-2" title={building.units_source ? (SOURCE_LABELS[building.units_source] ?? building.units_source) : ''}>
										{building.units ? (building.units_at_least ? `≥ ${fmtNumber(building.units)}` : fmtNumber(building.units)) : '—'}
									</td>
									<td class="py-2 pr-4 text-right tabular-nums text-fg-2">{fmtNumber(building.sales)}</td>
									<td class="py-2 text-right tabular-nums text-fg-2">{fmtNumber(building.leases)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</section>
		{/if}

		<!-- ── KPI cards ──────────────────────────────────────────────── -->
		<section aria-label="Summary metrics" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
			<div class="rounded-lg border border-border bg-card px-5 py-4">
				<p class="text-[11px] uppercase tracking-[0.18em] text-fg-4">Total Sales</p>
				<p class="mt-2.5 break-words text-3xl font-semibold text-fg-1">
					{fmtNumber(summary.sales.transaction_count)}
				</p>
				<p class="mt-1.5 text-sm text-fg-4">transactions</p>
			</div>
			<div class="rounded-lg border border-border bg-card px-5 py-4">
				<p class="text-[11px] uppercase tracking-[0.18em] text-fg-4">Avg Sale Price</p>
				<p class="mt-2.5 break-words text-3xl font-semibold text-fg-1">
					{fmtCurrency(summary.sales.avg_price)}
				</p>
				<p class="mt-1.5 text-sm text-fg-4">{fmtPsf(summary.sales.avg_price_sqft)}</p>
			</div>
			<div class="rounded-lg border border-border bg-card px-5 py-4">
				<p class="text-[11px] uppercase tracking-[0.18em] text-fg-4">Median Annual Rent</p>
				<p class="mt-2.5 break-words text-3xl font-semibold text-fg-1">
					{fmtCurrency(summary.rentals.median_annual_rent)}
				</p>
				<p class="mt-1.5 text-sm text-fg-4">
					{fmtNumber(summary.rentals.contract_count)} contracts
				</p>
			</div>
			<div class="rounded-lg border border-border bg-card px-5 py-4">
				<p class="text-[11px] uppercase tracking-[0.18em] text-info">Gross Yield</p>
				<p class="mt-2.5 break-words text-3xl font-semibold text-info">
					{fmtPct(summary.overall_gross_yield_pct)}
				</p>
				<p class="mt-1.5 text-sm text-info">median rent ÷ secondary median sale</p>
			</div>
		</section>

		<section class="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_360px]">
			<!-- The chart grows with the Market Split card beside it instead of leaving a gap. -->
			<section class="flex flex-col rounded-lg border border-border bg-card p-5">
				<div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
					<div>
						<p class="text-[11px] font-semibold uppercase tracking-[0.22em] text-fg-4">
							Price Trend
						</p>
						<h3 class="mt-1 text-base font-semibold text-fg-1">
							{shouldShowTrendForecast()
								? 'Recorded pricing with delivery-aware forecast'
								: 'Recorded pricing trend'}
						</h3>
						<p class="mt-1 text-xs text-fg-4">365-day lookback</p>
					</div>
					<div class="inline-flex rounded-lg border border-border bg-panel p-0.5">
						<button
							type="button"
							class="rounded-lg px-4 py-1.5 text-sm font-medium transition-colors {mode === 'sales' ? 'bg-card text-fg-1 shadow-sm' : 'text-fg-3 hover:text-fg-2'}"
							onclick={() => (mode = 'sales')}
						>
							Sales
						</button>
						<button
							type="button"
							class="rounded-lg px-4 py-1.5 text-sm font-medium transition-colors {mode === 'rentals' ? 'bg-card text-fg-1 shadow-sm' : 'text-fg-3 hover:text-fg-2'}"
							onclick={() => (mode = 'rentals')}
						>
							Price / sq ft
						</button>
					</div>
				</div>
				{#if forecastQuery.isError && !isAggregateSelection()}
					<AnalyticsError message="Failed to load forecast." retry={() => forecastQuery.refetch()} fetching={forecastQuery.isFetching} />
				{/if}
				<div class="relative mt-4 h-[280px] xl:h-auto xl:min-h-[280px] xl:flex-1">
					{#if trendsQuery.isError}
						<AnalyticsError message="Failed to load price trends." retry={() => trendsQuery.refetch()} fetching={trendsQuery.isFetching} />
					{:else if trendsQuery.isLoading || (!isAggregateSelection() && forecastQuery.isLoading)}
						<div class="h-full animate-pulse rounded-lg bg-panel"></div>
					{:else if hasTrendChartData()}
						<canvas bind:this={trendCanvas}></canvas>
					{:else}
						<div class="flex h-full items-center justify-center rounded-lg border border-dashed border-border text-sm text-fg-4">
							No trend data available.
						</div>
					{/if}
				</div>
				{#if shouldShowTrendForecast() && forecast?.delivery_date}
					<div class="mt-3 flex items-center gap-2 text-xs text-fg-3">
						<span class="inline-block h-1.5 w-1.5 rounded-full bg-primary-light"></span>
						Delivery anchor:
						<span class="font-medium text-fg-2">
							{new Date(forecast.delivery_date).toLocaleDateString('en-GB', {
								month: 'short',
								year: 'numeric'
							})}
						</span>
					</div>
				{/if}
			</section>

			<section class="rounded-lg border border-border bg-card p-5">
				<p class="text-[11px] font-semibold uppercase tracking-[0.22em] text-fg-4">
					Market Split
				</p>
				<h3 class="mt-1 text-base font-semibold text-fg-1">
					Off-plan vs secondary sales
				</h3>
				<p class="mt-1 text-xs text-fg-4">All recorded dates</p>
				<div class="mt-4 rounded-lg border border-border bg-panel p-4">
					<div class="flex items-end justify-between gap-4">
						<div>
							<p class="text-[11px] uppercase tracking-[0.18em] text-fg-4">Total sales</p>
							<p class="mt-1 text-3xl font-semibold text-fg-1">{fmtNumber(marketSplit.total)}</p>
						</div>
						<p class="text-xs text-fg-4">transaction count</p>
					</div>
					<div class="mt-4 h-[220px]">
						{#if marketSplit.total > 0}
							<canvas bind:this={marketSplitCanvas}></canvas>
						{:else}
							<div class="flex h-full items-center justify-center rounded-lg border border-dashed border-border text-sm text-fg-4">
								No sales mix data
							</div>
						{/if}
					</div>
				</div>
				<div class="mt-5 grid gap-3">
					{#each marketSplit.segments as segment (segment.key)}
						<div class="flex items-center justify-between rounded-lg border border-border bg-panel px-3.5 py-3">
							<div class="flex items-center gap-3">
								<span
									class="h-3 w-3 rounded-full"
									style={`background-color: ${segment.color};`}
								></span>
								<div>
									<p class="text-sm font-medium text-fg-1">{segment.label}</p>
									<p class="text-xs text-fg-4">{fmtNumber(segment.count)} sales</p>
								</div>
							</div>
							<p class="text-sm font-semibold text-fg-1">{fmtPct(segment.pct)}</p>
						</div>
					{/each}
				</div>
			</section>
		</section>

		<!-- ── Configuration Analysis ─────────────────────────────────── -->
		<section class="rounded-lg border border-border bg-card p-5">
			<div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
				<div class="flex items-center gap-3">
					<h3 class="text-base font-semibold text-fg-1">Configuration Analysis</h3>
					<div class="inline-flex rounded-lg border border-border bg-panel p-0.5">
						<button
							type="button"
							class="inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors {configMode === 'sales' ? 'bg-card text-fg-1 shadow-sm' : 'text-fg-3 hover:text-fg-2'}"
							onclick={() => (configMode = 'sales')}
						>
							<svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
							</svg>
							Sales
						</button>
						<button
							type="button"
							class="inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors {configMode === 'rentals' ? 'bg-card text-fg-1 shadow-sm' : 'text-fg-3 hover:text-fg-2'}"
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
					<div class="inline-flex rounded-lg border border-border bg-panel p-0.5">
						<button
							type="button"
							class="rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors {configSegment === 'all' ? 'bg-card text-fg-1 shadow-sm' : 'text-fg-3 hover:text-fg-2'}"
							onclick={() => (configSegment = 'all')}
						>
							All
						</button>
						<button
							type="button"
							class="rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors {configSegment === 'off_plan' ? 'bg-card text-fg-1 shadow-sm' : 'text-fg-3 hover:text-fg-2'}"
							onclick={() => (configSegment = 'off_plan')}
						>
							Off-Plan
						</button>
						<button
							type="button"
							class="rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors {configSegment === 'secondary' ? 'bg-card text-fg-1 shadow-sm' : 'text-fg-3 hover:text-fg-2'}"
							onclick={() => (configSegment = 'secondary')}
						>
							Secondary
						</button>
					</div>
				{/if}
			</div>

			{#if configMode === 'sales'}
                <p class="mt-4 text-xs text-fg-4">Sales, prices and sizes cover all recorded dates. Recent periods end on the newest recorded sale{#if summary.recent_periods_end}, {new Date(summary.recent_periods_end).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })},{/if} for every segment. Low-sample configurations remain visible.</p>
                <p class="mt-1 text-xs text-fg-4">Momentum compares consecutive 90-day counts using their average as the denominator (minimum 20 sales in each). Price change compares consecutive 12-month periods (minimum 3 sales in each).</p>
				<div class="ui-scroll-shadow mt-4 overflow-x-auto">
					<table class="min-w-[640px] w-full border-separate border-spacing-0 text-sm sm:min-w-full">
						<thead>
							<tr class="text-left">
								<th class="sticky left-0 z-10 border-b border-border bg-card pb-2.5 pr-6 text-[11px] font-semibold uppercase tracking-[0.14em] text-fg-4">{summary.usage === 'Commercial' ? 'Type' : 'Config'}</th>
								<th class="border-b border-border pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-fg-4">Sales</th>
								<th class="border-b border-border pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-fg-4">Avg Price</th>
								<th class="border-b border-border pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-fg-4">Median sale size sq ft</th>
								<th class="border-b border-border pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-fg-4">
									Momentum<br /><span class="font-normal normal-case tracking-normal text-fg-4">90d shift</span>
								</th>
								<th class="border-b border-border pb-2.5 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-fg-4">
									Price Δ YoY<br /><span class="font-normal normal-case tracking-normal text-fg-4">% change</span>
								</th>
							</tr>
						</thead>
						<tbody>
							{#each configRows as row (row.market_segment + row.rooms)}
								<tr class="group">
									<td class="sticky left-0 z-10 border-b border-border bg-card py-3 pr-6 font-medium text-fg-1 group-hover:bg-panel">
										{row.rooms}
									</td>
									<td class="border-b border-border py-3 pr-6 text-right text-fg-2 group-hover:bg-panel">
										{fmtNumber(row.sale_count)}
									</td>
									<td class="border-b border-border py-3 pr-6 text-right group-hover:bg-panel">
										<span class="font-medium text-fg-1">{fmtCurrency(row.avg_sale_price)}</span>
										{#if row.avg_sale_price_sqft > 0}
											<br /><span class="text-[11px] text-fg-4">{fmtPsf(row.avg_sale_price_sqft)}</span>
										{/if}
									</td>
									<td class="border-b border-border py-3 pr-6 text-right text-fg-2 group-hover:bg-panel">
										{row.avg_unit_size_sqft > 0 ? fmtNumber(row.avg_unit_size_sqft, 0) : '—'}
									</td>
									<td class="border-b border-border py-3 pr-6 text-right group-hover:bg-panel">
										{#if row.sales_momentum_pct == null || !Number.isFinite(row.sales_momentum_pct)}
											<span class="text-fg-4">—</span>
										{:else if Math.abs(row.sales_momentum_pct) < 0.5}
											<span class="inline-flex items-center gap-0.5 rounded-full bg-panel px-2 py-0.5 text-xs font-medium text-fg-4">
												— {fmtSignedPct(row.sales_momentum_pct)}
											</span>
										{:else if row.sales_momentum_pct > 0}
											<span class="inline-flex items-center gap-0.5 rounded-sm bg-info-bg px-2 py-0.5 text-xs font-semibold text-info ring-1 ring-border">
												▲ {fmtPct(row.sales_momentum_pct)}
											</span>
										{:else}
											<span class="inline-flex items-center gap-0.5 rounded-sm bg-error-bg px-2 py-0.5 text-xs font-semibold text-error ring-1 ring-border">
												▼ {fmtPct(Math.abs(row.sales_momentum_pct))}
											</span>
										{/if}
									</td>
									<td class="border-b border-border py-3 text-right group-hover:bg-panel">
										{#if row.price_change_yoy_pct != null && Number.isFinite(row.price_change_yoy_pct)}
											<span class="font-medium {deltaTone(row.price_change_yoy_pct)}">
												{row.price_change_yoy_pct > 0 ? '▲' : row.price_change_yoy_pct < 0 ? '▼' : ''}
												{fmtPct(Math.abs(row.price_change_yoy_pct))}
											</span>
										{:else}
											<span class="text-fg-4">—</span>
										{/if}
									</td>
								</tr>
							{/each}
							{#if configRows.length === 0}
								<tr>
									<td colspan="6" class="py-8 text-center text-sm text-fg-4">
										No data available for this segment.
									</td>
								</tr>
							{/if}
						</tbody>
					</table>
				</div>
			{:else}
				<!-- Rental view -->
				<div class="ui-scroll-shadow mt-4 overflow-x-auto">
					<table class="min-w-[480px] w-full border-separate border-spacing-0 text-sm sm:min-w-full">
						<thead>
							<tr class="text-left">
								<th class="sticky left-0 z-10 border-b border-border bg-card pb-2.5 pr-6 text-[11px] font-semibold uppercase tracking-[0.14em] text-fg-4">{summary.usage === 'Commercial' ? 'Type' : 'Config'}</th>
								<th class="border-b border-border pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-fg-4">Contracts</th>
								<th class="border-b border-border pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-fg-4">Median Rent</th>
								<th class="border-b border-border pb-2.5 pr-6 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-fg-4">Rent / sq ft</th>
								<th class="border-b border-border pb-2.5 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-fg-4">Gross Yield</th>
							</tr>
						</thead>
						<tbody>
							{#each rentalConfigRows as row (row.rooms)}
								<tr class="group">
									<td class="sticky left-0 z-10 border-b border-border bg-card py-3 pr-6 font-medium text-fg-1 group-hover:bg-panel">{row.rooms}</td>
									<td class="border-b border-border py-3 pr-6 text-right text-fg-3 group-hover:bg-panel">{fmtNumber(row.rental_count)}</td>
									<td class="border-b border-border py-3 pr-6 text-right font-medium text-fg-1 group-hover:bg-panel">{fmtCurrency(row.median_annual_rent)}</td>
									<td class="border-b border-border py-3 pr-6 text-right text-fg-3 group-hover:bg-panel">
										{row.median_rent_sqft > 0 ? `AED ${fmtNumber(row.median_rent_sqft, 0)}/sq ft` : '—'}
									</td>
									<td class="border-b border-border py-3 text-right font-semibold {pctTone(row.gross_yield_pct)} group-hover:bg-panel">
										{fmtPct(row.gross_yield_pct)}
									</td>
								</tr>
							{/each}
							{#if rentalConfigRows.length === 0}
								<tr>
									<td colspan="5" class="py-8 text-center text-sm text-fg-4">No rental data available.</td>
								</tr>
							{/if}
						</tbody>
					</table>
				</div>
			{/if}
		</section>

		<!-- ── Price Distribution ─────────────────────────────────────── -->
		<section class="rounded-lg border border-border bg-card p-5">
			<div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
				<h3 class="text-base font-semibold text-fg-1">Price Distribution</h3>
				<div class="inline-flex rounded-lg border border-border bg-panel p-0.5">
					<button
						type="button"
						class="rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors {!distroOffplan ? 'bg-card text-fg-1 shadow-sm' : 'text-fg-3 hover:text-fg-2'}"
						onclick={() => { distroOffplan = false; distroRooms = 'All'; }}
					>
						All
					</button>
					<button
						type="button"
						class="rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors {distroOffplan ? 'bg-card text-fg-1 shadow-sm' : 'text-fg-3 hover:text-fg-2'}"
						onclick={() => { distroOffplan = true; distroRooms = 'All'; }}
					>
						Off-Plan Only
					</button>
				</div>
			</div>

			<p class="mt-2 text-xs text-fg-4">All recorded dates</p>

			<!-- Room tabs -->
			{#if distroRoomList.length > 0}
				<div class="ui-segmented mt-3">
					<button
						type="button"
						onclick={() => (distroRooms = 'All')}
						class="ui-segmented-item px-3 py-1 text-xs"
						data-active={distroRooms === 'All'}
					>
						All
					</button>
					{#each distroRoomList as room (room)}
						<button
							type="button"
							onclick={() => (distroRooms = room)}
							class="ui-segmented-item px-3 py-1 text-xs"
							data-active={distroRooms === room}
						>
							{room}
						</button>
					{/each}
				</div>
			{/if}

			<!-- Stats row -->
			{#if distroBucket}
				<div class="mt-4 grid grid-cols-3 gap-4 rounded-lg border border-border bg-panel p-4">
					<div>
						<p class="flex items-center gap-1 text-[11px] font-medium uppercase tracking-[0.14em] text-fg-4">
							<span class="font-serif text-base text-fg-3">μ</span> Mean Price
						</p>
						<p class="mt-1 text-lg font-semibold text-accent-text">{fmtCurrency(distroBucket.mean_price)}</p>
					</div>
					<div>
						<p class="flex items-center gap-1 text-[11px] font-medium uppercase tracking-[0.14em] text-fg-4">
							<span class="font-serif text-base text-fg-3">σ</span> Std Deviation
						</p>
						<p class="mt-1 text-lg font-semibold text-fg-1">{fmtCurrency(distroBucket.std_price)}</p>
					</div>
					<div>
						<p class="text-[11px] font-medium uppercase tracking-[0.14em] text-fg-4">68% of Sales Between</p>
						<!-- The 16th to 84th percentile of the sales themselves: mean ± one deviation went
						     below zero for skewed prices ("— – AED 5.75M"). -->
						<p class="mt-1 text-sm font-semibold text-fg-1">
							{fmtCurrency(distroBucket.p16_price)}
							<span class="font-normal text-fg-4">–</span>
							{fmtCurrency(distroBucket.p84_price)}
						</p>
					</div>
				</div>
			{/if}

			<!-- Bell curve -->
			<div class="mt-4 h-[220px]">
				{#if distroQuery.isError}
					<AnalyticsError message="Failed to load price distribution." retry={() => distroQuery.refetch()} fetching={distroQuery.isFetching} />
				{:else if distroQuery.isLoading}
					<div class="h-full animate-pulse rounded-lg bg-panel"></div>
				{:else if distroBucket && distroBucket.std_price > 0}
					<canvas bind:this={bellCanvas}></canvas>
				{:else}
					<div class="flex h-full items-center justify-center rounded-lg border border-dashed border-border text-sm text-fg-4">
						{distroQuery.data && !distroBucket
							? 'No data for this bedroom type.'
							: 'No distribution data available.'}
					</div>
				{/if}
			</div>
		</section>

		<!-- ── Upcoming Supply ────────────────────────────────────────── -->
		<section class="rounded-lg border border-border bg-card p-5">
			<div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
				<h3 class="text-base font-semibold text-fg-1">
					Upcoming Supply
					{#if pipeline?.area_name}
						<span class="ml-1 text-sm font-normal text-fg-4">· {pipeline.area_name}</span>
					{/if}
				</h3>
			</div>

			{#if pipeline}
				<p class="mt-2 text-xs text-fg-3">
					DLD source. Completed stock uses recorded completion dates. Scheduled deliveries are planned.
					{#if pipeline.reference_date}As of {pipeline.reference_date}.{/if}
				</p>
				{#if pipeline.overdue_units || pipeline.undated_units}
					<p class="mt-1 text-xs text-fg-3">
						Excluded from the dated stock projection: {fmtNumber(pipeline.overdue_units)} overdue units
						and {fmtNumber(pipeline.undated_units)} units without a delivery date.
					</p>
				{/if}
			{/if}

			<p class="mt-2 text-xs text-fg-3">Supply is shown for all bedroom types in this area.</p>

			<div class="mt-4 h-[340px]">
				{#if pipelineQuery.isError}
					<AnalyticsError message="Failed to load supply pipeline." retry={() => pipelineQuery.refetch()} fetching={pipelineQuery.isFetching} />
				{:else if pipelineQuery.isLoading}
					<div class="h-full animate-pulse rounded-lg bg-panel"></div>
				{:else if pipeline && pipeline.data.length > 0}
					<canvas bind:this={pipelineCanvas}></canvas>
				{:else}
					<div class="flex h-full items-center justify-center rounded-lg border border-dashed border-border text-sm text-fg-4">
						No pipeline data available for this scope.
					</div>
				{/if}
			</div>
		</section>

	</div>
{/if}
