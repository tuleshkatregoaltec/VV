<script lang="ts">
	import { onMount } from 'svelte';
	import {
		Chart,
		Title,
		Tooltip,
		Legend,
		LineElement,
		CategoryScale,
		LinearScale,
		PointElement
	} from 'chart.js';
	import ChatBox from '$lib/components/dashboard/ChatBox.svelte';
	import DashboardCard from '$lib/components/dashboard/DashboardCard.svelte';
	import PageHeader from '$lib/components/dashboard/PageHeader.svelte';
	import AppShell from '$lib/components/layout/AppShell.svelte';
	import Grid from '$lib/components/layout/Grid.svelte';

	let Line: any;
	let chartReady = false;

	onMount(async () => {
		const module = await import('svelte-chartjs');
		Line = module.Line;
		Chart.register(Title, Tooltip, Legend, LineElement, CategoryScale, LinearScale, PointElement);
		chartReady = true;
	});

	let username = 'Kian';

	function handleChatSubmit(value: string) {
		console.log('Submitted:', value);
	}

	const marketTrendData = {
		labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
		datasets: [
			{
				label: 'Market Trend',
				data: [65, 59, 80, 81, 56, 55],
				fill: true,
				backgroundColor: 'rgba(24, 24, 24, 0.08)', // --color-primary: #181818
				borderColor: '#181818',
				tension: 0.4,
				pointBackgroundColor: '#181818',
				pointBorderColor: '#fff',
				pointHoverBackgroundColor: '#fff',
				pointHoverBorderColor: '#181818'
			}
		]
	};

	const chartOptions = {
		responsive: true,
		maintainAspectRatio: false,
		scales: {
			x: {
				grid: {
					display: false
				},
				ticks: {
					color: '#232323'
				}
			},
			y: {
				grid: {
					color: '#edeadd' // match new bg-gray
				},
				ticks: {
					color: '#232323'
				}
			}
		},
		plugins: {
			legend: {
				display: false
			}
		}
	};
</script>

<AppShell showFilters={false}>
    <div class="max-w-7xl mx-auto px-4 py-8">

	<PageHeader title="Welcome, {username}!" subtitle="Your property dashboard" />

	<!-- Input Box -->
	<div class="flex justify-center mb-16">
		<ChatBox
			placeholder="Search properties, areas, or ask anything..."
			onSubmit={handleChatSubmit}
			options={['Custom deliverables', 'Valuation']}
		/>
	</div>

	<!-- Dashboard Cards Grid -->
	<Grid cols={1} mdCols={2} lgCols={3} gap={4} className="sm:gap-5">
		<!-- Transactions Card -->
		<DashboardCard
			title="Transactions"
			value={204}
			trend={{ value: '12% from last month', direction: 'up' }}
		>
			<svg slot="icon" xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
		<path stroke-linecap="round" stroke-linejoin="round" d="M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5l-3 3-3-3" />
	  </svg>
		</DashboardCard>
			<!-- Market Trend Card -->
			<DashboardCard
				title="Market Trend"
				value=""
				colSpan="md:col-span-2 lg:col-span-1"
			>
				<svg slot="icon" xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
				</svg>
				<div class="h-32 -mx-5 -mb-5 mt-4">
					{#if chartReady}
						<Line data={marketTrendData} options={chartOptions} />
					{/if}
				</div>
			</DashboardCard>
		<!-- Avg Price/sq.ft Card -->
		<DashboardCard
			title="Avg price/sq.ft"
			value="2300 AED"
			trend={{ value: '2.5% from last month', direction: 'down' }}
		>
				<svg slot="icon" xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v.01" />
				</svg>
			</DashboardCard>
	</Grid>
	</div>
</AppShell>
