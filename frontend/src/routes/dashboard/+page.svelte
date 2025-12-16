<script lang="ts">
	import ChatBox from '$lib/components/dashboard/ChatBox.svelte';
	import DashboardCard from '$lib/components/dashboard/DashboardCard.svelte';
	import PageHeader from '$lib/components/dashboard/PageHeader.svelte';
	import AppShell from '$lib/components/layout/AppShell.svelte';
	import Grid from '$lib/components/layout/Grid.svelte';
	import { authStore } from '$lib/stores/auth.svelte';

	let username = $derived(authStore.user?.first_name ?? '');

	function handleChatSubmit(value: string) {
		console.log('Submitted:', value);
	}
</script>

<AppShell showFilters={false}>
    <div class="max-w-7xl mx-auto px-4 py-8 bg-background">

	<PageHeader title="Welcome, {username}!" subtitle="Your property dashboard" />

	<div class="flex justify-center mb-16">
		<ChatBox
			placeholder="Search properties, areas, or ask anything..."
			onSubmit={handleChatSubmit}
			options={['Custom deliverables', 'Valuation']}
		/>
	</div>

	<Grid cols={1} mdCols={2} lgCols={3} gap={4} className="sm:gap-5">
		<DashboardCard
			title="Transactions"
			value={204}
			trend={{ value: '12% from last month', direction: 'up' }}
		>
			<svg slot="icon" xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
		<path stroke-linecap="round" stroke-linejoin="round" d="M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5l-3 3-3-3" />
	  </svg>
		</DashboardCard>
			<DashboardCard
				title="Market Trend"
				value=""
				colSpan="md:col-span-2 lg:col-span-1"
			>
				<svg slot="icon" xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
				</svg>
				<div class="h-32 -mx-5 -mb-5 mt-4 flex items-center justify-center text-gray-400">
					<span>Chart coming soon</span>
				</div>
			</DashboardCard>
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
