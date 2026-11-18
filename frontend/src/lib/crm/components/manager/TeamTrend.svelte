<script lang="ts">
import { Chart, registerables } from 'chart.js'
import { onMount } from 'svelte'
import Seg from '$lib/crm/components/ui/Seg.svelte'
import type { TrendDay, ViewAs } from '$lib/crm/mock/manager'
import { colorTheme } from '$lib/stores/preferences.svelte'

/**
 * Last 30 days as a line chart: leads in vs handled, or median first reply. Same chart.js
 * lifecycle as TrendChart.svelte (that one is typed to market analytics), colours from crm.css
 * vars so it follows the light/dark theme.
 */
let { days, view }: { days: TrendDay[]; view: ViewAs } = $props()

Chart.register(...registerables)

let metric = $state<'volume' | 'response'>('volume')
let canvas = $state<HTMLCanvasElement | undefined>()
let chart: Chart | null = null

function draw() {
	if (!canvas) return
	chart?.destroy()
	const css = getComputedStyle(canvas)
	const v = (name: string) => css.getPropertyValue(name).trim()
	const labels = days.map((d) =>
		new Date(`${d.day}T00:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
	)
	const line = (label: string, data: number[], color: string) => ({
		label,
		data,
		borderColor: color,
		backgroundColor: color,
		borderWidth: 2,
		tension: 0.3,
		pointRadius: 0,
		pointHoverRadius: 4
	})
	chart = new Chart(canvas, {
		type: 'line',
		data: {
			labels,
			datasets:
				metric === 'volume'
					? [
							line(
								'Leads in',
								days.map((d) => d.incoming),
								v('--blue')
							),
							line(
								'Handled',
								days.map((d) => d.handled),
								v('--green')
							)
						]
					: [
							line(
								'Median first reply (min)',
								days.map((d) => d.medianReplyMins),
								v('--amber')
							)
						]
		},
		options: {
			responsive: true,
			maintainAspectRatio: false,
			interaction: { mode: 'index', intersect: false },
			plugins: {
				legend: { position: 'bottom', labels: { color: v('--text2'), boxWidth: 12, boxHeight: 2 } }
			},
			scales: {
				x: {
					grid: { display: false },
					ticks: { color: v('--text2'), maxTicksLimit: 8, maxRotation: 0 }
				},
				y: {
					beginAtZero: true,
					grid: { color: v('--sep') },
					ticks: { color: v('--text2'), precision: 0 }
				}
			}
		}
	})
}

onMount(() => () => chart?.destroy())

// Redraw on new data (View-as switch), metric switch, or theme change.
$effect(() => {
	void [days, metric, colorTheme.resolved]
	draw()
})
</script>

<section class="card" aria-labelledby="tr-h">
	<div class="ch">
		<h2 id="tr-h">{view === 'manager' ? 'Team trends' : 'Your trends'} <span class="ct">· 30 days</span></h2>
		<Seg
			label="Trend"
			items={[
				{ id: 'volume', label: 'Leads' },
				{ id: 'response', label: 'Reply time' }
			]}
			value={metric}
			onselect={(m) => (metric = m)}
		/>
	</div>
	<div class="plot">
		<canvas
			bind:this={canvas}
			aria-label={metric === 'volume'
				? 'Leads in and handled per day, last 30 days'
				: 'Median first reply per day, last 30 days'}
		></canvas>
	</div>
</section>

<style>
	.plot {
		position: relative;
		height: 240px;
		padding: 12px 14px;
	}
</style>
