<script lang="ts">
import { Chart, registerables } from 'chart.js'
import { onMount } from 'svelte'
import type { DimensionBreakdown, RentalDimensionBreakdown } from '$lib/api/analytics'

interface Props {
	data: DimensionBreakdown[] | RentalDimensionBreakdown[]
	title?: string
	metric?: 'volume' | 'count'
	height?: number
	maxItems?: number
}

let { data, title = 'Breakdown', metric = 'volume', height = 350, maxItems = 10 }: Props = $props()

let canvasElement = $state<HTMLCanvasElement | undefined>()
let chart: Chart | null = null

Chart.register(...registerables)

function formatCurrency(value: number): string {
	if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`
	if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`
	if (value >= 1e3) return `${(value / 1e3).toFixed(1)}K`
	return value.toFixed(0)
}

function formatNumber(value: number): string {
	return value.toLocaleString()
}

function getMetricValue(item: DimensionBreakdown | RentalDimensionBreakdown): number {
	if (metric === 'count') {
		return 'transaction_count' in item ? item.transaction_count : item.contract_count
	}
	return 'total_volume' in item ? item.total_volume : item.total_annual_value
}

function getMetricLabel(): string {
	return metric === 'count' ? 'Count' : 'Volume (AED)'
}

function getFormatter() {
	return metric === 'count' ? formatNumber : formatCurrency
}

function createChart() {
	if (!canvasElement || !data || data.length === 0) return

	if (chart) {
		chart.destroy()
	}

	const ctx = canvasElement.getContext('2d')
	if (!ctx) return

	// Take top N items
	const chartData = data.slice(0, maxItems)
	const labels = chartData.map((d) => d.dimension_value || 'Unknown')
	const values = chartData.map(getMetricValue)
	const formatter = getFormatter()

	chart = new Chart(ctx, {
		type: 'bar',
		data: {
			labels,
			datasets: [
				{
					label: getMetricLabel(),
					data: values,
					backgroundColor: 'rgba(59, 130, 246, 0.8)',
					borderColor: 'rgb(59, 130, 246)',
					borderWidth: 1,
					borderRadius: 4,
					hoverBackgroundColor: 'rgba(59, 130, 246, 0.9)'
				}
			]
		},
		options: {
			responsive: true,
			maintainAspectRatio: false,
			indexAxis: 'y', // Horizontal bars
			plugins: {
				legend: {
					display: false
				},
				title: {
					display: !!title,
					text: title,
					font: {
						size: 16,
						weight: 'bold'
					},
					padding: {
						bottom: 20
					}
				},
				tooltip: {
					callbacks: {
						label: (context) => {
							const item = chartData[context.dataIndex]
							const value = formatter(Number(context.parsed.x ?? 0))
							const pct = item.pct_of_total ? ` (${item.pct_of_total}%)` : ''
							return `${getMetricLabel()}: ${value}${pct}`
						}
					}
				}
			},
			scales: {
				x: {
					beginAtZero: true,
					grid: {
						color: 'rgba(0, 0, 0, 0.05)'
					},
					ticks: {
						callback: (value) => formatter(Number(value))
					}
				},
				y: {
					grid: {
						display: false
					}
				}
			}
		}
	})
}

onMount(() => {
	createChart()
	return () => {
		if (chart) {
			chart.destroy()
		}
	}
})

$effect(() => {
	if (data) {
		createChart()
	}
})
</script>

<div class="chart-container" style="height: {height}px;">
	{#if data && data.length > 0}
		<canvas bind:this={canvasElement}></canvas>
	{:else}
		<div class="empty-state">
			<p>No breakdown data available</p>
		</div>
	{/if}
</div>

<style>
	.chart-container {
		position: relative;
		width: 100%;
		background: var(--bg-primary, white);
		border-radius: 0.5rem;
		padding: 1rem;
	}

	.empty-state {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--text-tertiary, #9ca3af);
	}
</style>
