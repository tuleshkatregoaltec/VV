<script lang="ts">
import { Chart, registerables } from 'chart.js'
import { onMount } from 'svelte'
import type { MarketTrendArtifact } from '$lib/chat/artifacts'
import { colorTheme } from '$lib/stores/preferences.svelte'
import { getChartTheme } from '$lib/utils/chartTheme'
import { perSqft } from '$lib/utils/units'

Chart.register(...registerables)

let { artifact }: { artifact: MarketTrendArtifact } = $props()

let canvas = $state<HTMLCanvasElement | undefined>()
let chart: Chart | null = null
const resolvedTheme = $derived(colorTheme.resolved)
const points = $derived(artifact.data?.data ?? [])

// Charts saved in a conversation before the switch to square feet hold per-m² fields.
type SavedPoint = { avg_price_sqft?: number | null; avg_price_sqm?: number | null }
function pricePerSqft(point: SavedPoint | undefined): number | null {
	if (point?.avg_price_sqft != null) return point.avg_price_sqft
	return point?.avg_price_sqm != null ? perSqft(point.avg_price_sqm) : null
}
const changePct = $derived(
	artifact.data?.avg_price_sqft_change_pct ??
		(artifact.data as { avg_price_sqm_change_pct?: number | null } | null | undefined)
			?.avg_price_sqm_change_pct ??
		null
)

function formatMoney(value: number | null | undefined): string {
	const amount = Number(value ?? 0)
	if (!amount) return 'AED 0'
	if (amount >= 1_000_000) return `AED ${(amount / 1_000_000).toFixed(1)}M`
	if (amount >= 1_000) return `AED ${(amount / 1_000).toFixed(0)}K`
	return `AED ${Math.round(amount).toLocaleString()}`
}

function formatNumber(value: number | null | undefined): string {
	return Math.round(Number(value ?? 0)).toLocaleString()
}

function periodLabel(): string | null {
	if (!points.length) return null
	return `${points[0]?.date} to ${points[points.length - 1]?.date}`
}

function createChart() {
	if (!canvas || points.length === 0) return
	chart?.destroy()

	const context = canvas.getContext('2d')
	if (!context) return

	const theme = getChartTheme()
	chart = new Chart(context, {
		type: 'line',
		data: {
			labels: points.map((point) =>
				new Date(point.date).toLocaleDateString(undefined, { month: 'short', year: '2-digit' })
			),
			datasets: [
				{
					label: 'Avg AED / sq ft',
					data: points.map((point) => pricePerSqft(point)),
					borderColor: theme.line,
					backgroundColor: theme.fill,
					borderWidth: 2,
					fill: true,
					tension: 0.35,
					pointRadius: 2,
					pointHoverRadius: 5,
					pointBackgroundColor: theme.line,
					pointBorderColor: theme.panel,
					pointBorderWidth: 2
				}
			]
		},
		options: {
			responsive: true,
			maintainAspectRatio: false,
			plugins: {
				legend: { display: false },
				tooltip: {
					mode: 'index',
					intersect: false,
					backgroundColor: theme.tooltipBackground,
					titleColor: theme.tooltipText,
					bodyColor: theme.tooltipText,
					callbacks: {
						label: (context) => `Avg AED / sq ft: ${formatNumber(Number(context.parsed.y ?? 0))}`
					}
				}
			},
			scales: {
				x: {
					grid: { display: false },
					ticks: { color: theme.muted, maxTicksLimit: 6 }
				},
				y: {
					grid: { color: theme.grid },
					ticks: {
						color: theme.muted,
						callback: (value) => formatNumber(Number(value))
					}
				}
			}
		}
	})
}

onMount(() => {
	createChart()
	return () => chart?.destroy()
})

$effect(() => {
	resolvedTheme
	artifact.id
	points.length
	createChart()
})
</script>

{#if points.length === 0}
	<div class="grid min-h-[240px] place-items-center rounded-md border border-dashed border-border bg-panel p-5 text-center">
		<div>
			<p class="text-sm font-semibold text-fg-1">No trend data</p>
			<p class="mt-1 text-xs leading-5 text-fg-4">Try a broader area or a longer lookback window.</p>
		</div>
	</div>
{:else}
	<div class="grid gap-3">
		<div class="grid grid-cols-3 gap-2">
			<div class="rounded-md border border-border bg-card p-2.5">
				<p class="text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-5">Transactions</p>
				<p class="mt-1 text-sm font-semibold text-fg-1">
					{formatNumber(artifact.data?.total_transactions)}
				</p>
			</div>
			<div class="rounded-md border border-border bg-card p-2.5">
				<p class="text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-5">Latest / sq ft</p>
				<p class="mt-1 text-sm font-semibold text-fg-1">
					{formatNumber(pricePerSqft(points[points.length - 1]))}
				</p>
			</div>
			<div class="rounded-md border border-border bg-card p-2.5">
				<p class="text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-5">Change</p>
				<p
					class="mt-1 text-sm font-semibold {(changePct ?? 0) >= 0
						? 'text-success'
						: 'text-error'}"
				>
					{changePct == null ? '-' : `${changePct > 0 ? '+' : ''}${changePct}%`}
				</p>
			</div>
		</div>

		<div class="h-[260px] rounded-md border border-border bg-card p-3">
			<canvas bind:this={canvas}></canvas>
		</div>

		<div class="rounded-md border border-border bg-panel p-3 text-xs leading-5 text-fg-3">
			{#if periodLabel()}
				<span class="font-semibold text-fg-2">Period:</span>
				{periodLabel()}
			{/if}
			{#if periodLabel()}<span class="mx-1 text-fg-5">/</span>{/if}
			Latest average price:
			<span class="font-semibold text-fg-1">{formatMoney(points[points.length - 1]?.avg_price)}</span>
		</div>
	</div>
{/if}
