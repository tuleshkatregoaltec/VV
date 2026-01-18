<script lang="ts">
	type TimeRange = '30d' | '90d' | '6mo' | '1yr';
	type Metric = 'price_sqft' | 'avg_price';
	
	let selectedRange = $state<TimeRange>('6mo');
	let selectedMetric = $state<Metric>('price_sqft');

	// Mock data generator for 6 months of daily data
	function generateMockData(days: number) {
		const data = [];
		const basePriceSqft = 1200;
		const basePriceTotal = 850000;
		const today = new Date();
		
		for (let i = days; i >= 0; i--) {
			const date = new Date(today);
			date.setDate(date.getDate() - i);
			
			// Create realistic fluctuation with overall upward trend
			const trend = (days - i) * 0.5;
			const noise = Math.sin(i / 10) * 50 + Math.random() * 40 - 20;
			const avgPriceSqft = basePriceSqft + trend + noise;
			
			// Average price scales with sqft price
			const trendTotal = (days - i) * 350;
			const noiseTotal = Math.sin(i / 10) * 35000 + Math.random() * 25000 - 12500;
			const avgPriceTotal = basePriceTotal + trendTotal + noiseTotal;
			
			data.push({
				date: date.toISOString().split('T')[0],
				avg_sqft: Math.round(avgPriceSqft),
				avg_price: Math.round(avgPriceTotal),
				transaction_count: Math.floor(800 + Math.random() * 400)
			});
		}
		return data;
	}

	const mockData = {
		'30d': generateMockData(30),
		'90d': generateMockData(90),
		'6mo': generateMockData(180),
		'1yr': generateMockData(365)
	};

	const chartData = $derived(mockData[selectedRange]);
	
	// Calculate statistics based on selected metric
	const values = $derived(chartData.map(d => selectedMetric === 'price_sqft' ? d.avg_sqft : d.avg_price));
	const minValue = $derived(Math.min(...values));
	const maxValue = $derived(Math.max(...values));
	const valueRange = $derived(maxValue - minValue || 1);
	
	const firstValue = $derived(values[0] ?? 0);
	const lastValue = $derived(values[values.length - 1] ?? 0);
	const currentValue = $derived(lastValue);
	const percentChange = $derived(
		firstValue ? (((lastValue - firstValue) / firstValue) * 100).toFixed(1) : '0.0'
	);
	const isPositive = $derived(Number(percentChange) >= 0);

	const metricLabel = $derived(selectedMetric === 'price_sqft' ? 'per sq.ft' : 'average');
	const metricUnit = $derived(selectedMetric === 'price_sqft' ? 'AED/sq.ft' : 'AED');

	// Chart dimensions - reduced for better viewport fit
	const chartWidth = 1000;
	const chartHeight = 200;
	const padding = { top: 15, right: 20, bottom: 30, left: 60 };
	const innerWidth = chartWidth - padding.left - padding.right;
	const innerHeight = chartHeight - padding.top - padding.bottom;

	function generatePath(data: typeof chartData): string {
		if (data.length === 0) return '';

		const points = data.map((point, i) => {
			const x = padding.left + (i / (data.length - 1)) * innerWidth;
			const value = selectedMetric === 'price_sqft' ? point.avg_sqft : point.avg_price;
			const normalizedValue = (value - minValue) / valueRange;
			const y = padding.top + (1 - normalizedValue) * innerHeight;
			return { x, y };
		});

		let path = `M ${points[0].x} ${points[0].y}`;
		for (let i = 1; i < points.length; i++) {
			const prev = points[i - 1];
			const curr = points[i];
			const cp1x = prev.x + (curr.x - prev.x) / 3;
			const cp2x = prev.x + ((curr.x - prev.x) * 2) / 3;
			path += ` C ${cp1x} ${prev.y}, ${cp2x} ${curr.y}, ${curr.x} ${curr.y}`;
		}
		return path;
	}

	const linePath = $derived(generatePath(chartData));
	const areaPath = $derived(
		linePath
			? `${linePath} L ${padding.left + innerWidth} ${padding.top + innerHeight} L ${padding.left} ${padding.top + innerHeight} Z`
			: ''
	);

	// Y-axis labels
	const yAxisTicks = $derived([
		{ value: maxValue, y: padding.top },
		{ value: (maxValue + minValue) / 2, y: padding.top + innerHeight / 2 },
		{ value: minValue, y: padding.top + innerHeight }
	]);

	// X-axis labels - show 5 evenly spaced dates
	const xAxisTicks = $derived(
		[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
			const index = Math.floor(ratio * (chartData.length - 1));
			const point = chartData[index];
			const date = new Date(point.date);
			return {
				label: date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
				x: padding.left + ratio * innerWidth
			};
		})
	);

	function formatNumber(num: number): string {
		return new Intl.NumberFormat('en-US').format(Math.round(num));
	}
</script>

<div class="bg-white/80 backdrop-blur-sm rounded-2xl shadow-lg border border-teal-100 p-4 sm:p-6">
	<!-- Header -->
	<div class="flex flex-col sm:flex-row sm:items-start sm:justify-between mb-6 gap-4">
		<div>
			<h2 class="text-xl font-bold text-slate-900 mb-2">Dubai Market Trend</h2>
			<div class="flex items-baseline gap-2">
				<span class="text-3xl font-bold text-slate-900">{formatNumber(currentValue)}</span>
				<span class="text-sm text-slate-500">{metricUnit}</span>
			</div>
			<div
				class="mt-2 inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold {isPositive
					? 'bg-green-100 text-green-800'
					: 'bg-red-100 text-red-800'}"
			>
				{#if isPositive}
					<svg class="w-3 h-3 mr-1" fill="currentColor" viewBox="0 0 20 20">
						<path
							fill-rule="evenodd"
							d="M5.293 9.707a1 1 0 010-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 01-1.414 1.414L11 7.414V15a1 1 0 11-2 0V7.414L6.707 9.707a1 1 0 01-1.414 0z"
							clip-rule="evenodd"
						/>
					</svg>
				{:else}
					<svg class="w-3 h-3 mr-1" fill="currentColor" viewBox="0 0 20 20">
						<path
							fill-rule="evenodd"
							d="M14.707 10.293a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 111.414-1.414L9 12.586V5a1 1 0 012 0v7.586l2.293-2.293a1 1 0 011.414 0z"
							clip-rule="evenodd"
						/>
					</svg>
				{/if}
				<span>{isPositive ? '+' : ''}{percentChange}%</span>
			</div>
		</div>

		<!-- Controls -->
		<div class="flex flex-col gap-2">
			<!-- Metric Selector -->
			<div class="flex gap-2 bg-slate-100 p-1 rounded-lg">
				<button
					class="px-3 py-1.5 rounded-md text-xs font-medium transition-all {selectedMetric === 'price_sqft'
						? 'bg-white text-primary shadow-sm'
						: 'text-slate-600 hover:text-slate-900'}"
					onclick={() => (selectedMetric = 'price_sqft')}
				>
					Price/sq.ft
				</button>
				<button
					class="px-3 py-1.5 rounded-md text-xs font-medium transition-all {selectedMetric === 'avg_price'
						? 'bg-white text-primary shadow-sm'
						: 'text-slate-600 hover:text-slate-900'}"
					onclick={() => (selectedMetric = 'avg_price')}
				>
					Avg Price
				</button>
			</div>

			<!-- Time Range Selector -->
			<div class="flex gap-2 bg-slate-100 p-1 rounded-lg">
				{#each [{ label: '30D', value: '30d' }, { label: '90D', value: '90d' }, { label: '6M', value: '6mo' }, { label: '1Y', value: '1yr' }] as range}
					<button
						class="px-3 py-1.5 rounded-md text-xs font-medium transition-all {selectedRange ===
						range.value
							? 'bg-white text-primary shadow-sm'
							: 'text-slate-600 hover:text-slate-900'}"
						onclick={() => (selectedRange = range.value as TimeRange)}
					>
						{range.label}
					</button>
				{/each}
			</div>
		</div>
	</div>

	<!-- Chart -->
	<div class="w-full overflow-x-auto">
		<svg
			class="w-full min-w-[600px]"
			viewBox="0 0 {chartWidth} {chartHeight}"
			preserveAspectRatio="xMidYMid meet"
			xmlns="http://www.w3.org/2000/svg"
		>
			<defs>
				<linearGradient id="areaGradient" x1="0" x2="0" y1="0" y2="1">
					<stop
						offset="0%"
						stop-color={isPositive ? '#10b981' : '#ef4444'}
						stop-opacity="0.3"
					/>
					<stop
						offset="100%"
						stop-color={isPositive ? '#10b981' : '#ef4444'}
						stop-opacity="0.05"
					/>
				</linearGradient>
			</defs>

			<!-- Grid lines -->
			{#each yAxisTicks as tick}
				<line
					x1={padding.left}
					y1={tick.y}
					x2={padding.left + innerWidth}
					y2={tick.y}
					stroke="#e5e7eb"
					stroke-width="1"
					stroke-dasharray="4 4"
				/>
			{/each}

			<!-- Area fill -->
			<path d={areaPath} fill="url(#areaGradient)" />

			<!-- Line -->
			<path
				d={linePath}
				fill="none"
				stroke={isPositive ? '#10b981' : '#ef4444'}
				stroke-width="3"
				stroke-linecap="round"
				stroke-linejoin="round"
			/>

			<!-- Y-axis labels -->
			{#each yAxisTicks as tick}
				<text
					x={padding.left - 10}
					y={tick.y}
					text-anchor="end"
					dominant-baseline="middle"
					class="text-xs fill-slate-500"
				>
					{formatNumber(tick.value)}
				</text>
			{/each}

			<!-- X-axis labels -->
			{#each xAxisTicks as tick}
				<text
					x={tick.x}
					y={chartHeight - 10}
					text-anchor="middle"
					class="text-xs fill-slate-500"
				>
					{tick.label}
				</text>
			{/each}
		</svg>
	</div>

	<!-- Legend/Info -->
	<div class="mt-4 pt-3 border-t border-slate-200 flex flex-wrap gap-4 text-xs text-slate-600">
		<div class="flex items-center gap-2">
			<div class="w-2.5 h-2.5 rounded-full bg-green-500"></div>
			<span>{selectedMetric === 'price_sqft' ? 'Price per Square Foot' : 'Average Transaction Price'}</span>
		</div>
		<div class="flex items-center gap-2">
			<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
				/>
			</svg>
			<span>Based on {formatNumber(chartData.reduce((sum, d) => sum + d.transaction_count, 0))} transactions</span>
		</div>
	</div>
</div>

