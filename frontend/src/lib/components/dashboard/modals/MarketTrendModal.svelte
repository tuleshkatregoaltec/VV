<script lang="ts">
	import TrendChart from '$lib/components/charts/TrendChart.svelte';
	import type { SalesAnalyticsResponse } from '$lib/api/analytics';

	let { data }: { data: SalesAnalyticsResponse } = $props();

	function formatCurrency(value: number): string {
		if (value >= 1_000_000_000) return `AED ${(value / 1_000_000_000).toFixed(1)}B`;
		if (value >= 1_000_000) return `AED ${(value / 1_000_000).toFixed(1)}M`;
		if (value >= 1_000) return `AED ${(value / 1_000).toFixed(0)}K`;
		return `AED ${value.toFixed(0)}`;
	}

	// Calculate stats from trends
	const avgPrices = $derived(data.trends.map((t) => t.avg_sqft).filter((p) => p > 0));
	const minPrice = $derived(avgPrices.length > 0 ? Math.min(...avgPrices) : 0);
	const maxPrice = $derived(avgPrices.length > 0 ? Math.max(...avgPrices) : 0);
	const avgPrice = $derived(
		avgPrices.length > 0 ? avgPrices.reduce((a, b) => a + b, 0) / avgPrices.length : 0
	);
</script>

<div class="space-y-6">
	<!-- Summary Stats -->
	<div class="grid grid-cols-3 gap-4">
		<div class="bg-blue-50 rounded-xl p-4">
			<p class="text-sm text-gray-600 mb-1">Average</p>
			<p class="text-2xl font-bold text-gray-900">{formatCurrency(avgPrice)}</p>
			<p class="text-xs text-gray-500 mt-1">per sq.ft</p>
		</div>
		<div class="bg-green-50 rounded-xl p-4">
			<p class="text-sm text-gray-600 mb-1">Highest</p>
			<p class="text-2xl font-bold text-gray-900">{formatCurrency(maxPrice)}</p>
			<p class="text-xs text-gray-500 mt-1">per sq.ft</p>
		</div>
		<div class="bg-orange-50 rounded-xl p-4">
			<p class="text-sm text-gray-600 mb-1">Lowest</p>
			<p class="text-2xl font-bold text-gray-900">{formatCurrency(minPrice)}</p>
			<p class="text-xs text-gray-500 mt-1">per sq.ft</p>
		</div>
	</div>

	<!-- Large Trend Chart -->
	<div>
		<TrendChart
			data={data.trends}
			title="Price per sq.ft Over Time"
			metric="avg_sqft"
			height={450}
		/>
	</div>

	<!-- Additional Info -->
	<div class="bg-gray-50 rounded-xl p-4">
		<div class="grid grid-cols-2 gap-4 text-sm">
			<div>
				<p class="text-gray-600">Time Period</p>
				<p class="font-semibold text-gray-900">Last {data.timeframe_days} days</p>
			</div>
			<div>
				<p class="text-gray-600">Data Points</p>
				<p class="font-semibold text-gray-900">{data.trends.length} days</p>
			</div>
			<div>
				<p class="text-gray-600">Total Transactions</p>
				<p class="font-semibold text-gray-900">{data.summary.transaction_count.toLocaleString()}</p>
			</div>
			<div>
				<p class="text-gray-600">Total Volume</p>
				<p class="font-semibold text-gray-900">{formatCurrency(data.summary.total_volume)}</p>
			</div>
		</div>
	</div>
</div>
