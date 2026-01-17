<script lang="ts">
	import CompactChatInput from '$lib/components/dashboard/CompactChatInput.svelte';
	import DashboardCard from '$lib/components/dashboard/DashboardCard.svelte';
	import TrendChart from '$lib/components/dashboard/TrendChart.svelte';
	import PageHeader from '$lib/components/dashboard/PageHeader.svelte';
	import AppShell from '$lib/components/layout/AppShell.svelte';
	import NewsFeed from '$lib/components/news/NewsFeed.svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { chat } from '$lib/api/chat';
	import { analytics, type SalesAnalyticsResponse } from '$lib/api/analytics';

	let username = $derived(page.data.user?.first_name ?? '');
	let analyticsData = $state<SalesAnalyticsResponse | null>(null);
	let isLoading = $state(true);

	// Fetch analytics data on mount
	$effect(() => {
		async function loadAnalytics() {
			try {
				const data = await analytics.sales({ timeframe_days: 30 });
				analyticsData = data;
			} catch (error) {
				console.error('Failed to load analytics:', error);
			} finally {
				isLoading = false;
			}
		}
		loadAnalytics();
	});

	// Format number with commas
	function formatNumber(num: number): string {
		return new Intl.NumberFormat('en-US').format(Math.round(num));
	}

	// Format percentage with sign
	function formatPercent(pct: number | null): string | null {
		if (pct === null) return null;
		const sign = pct >= 0 ? '+' : '';
		return `${sign}${pct.toFixed(1)}% from last month`;
	}

	async function handleChatSubmit(message: string) {
		try {
			const conversation = await chat.createConversation({
				title: message.slice(0, 50)
			});

			goto('/dashboard/chat', {
				state: {
					conversationId: conversation.id,
					initialMessage: message
				}
			});
		} catch (error) {
			console.error('Failed to create conversation:', error);
			throw error;
		}
	}
</script>

<AppShell showFilters={false}>
	<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8 bg-background">
		<PageHeader title="Welcome, {username}!" subtitle="Your Dubai property dashboard" />

		<div class="mb-12 sm:mb-16">
			<CompactChatInput
				placeholder="Ask me anything about Dubai real estate..."
				onSubmit={handleChatSubmit}
			/>
		</div>

		{#if isLoading}
			<!-- Loading skeleton -->
			<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
				{#each [1, 2, 3] as _}
					<div
						class="bg-white/80 backdrop-blur-xl rounded-xl shadow-lg border border-primary-pale p-5 animate-pulse"
					>
						<div class="h-6 bg-gray-200 rounded w-1/2 mb-4"></div>
						<div class="h-10 bg-gray-200 rounded w-3/4 mb-4"></div>
						<div class="h-4 bg-gray-200 rounded w-1/2"></div>
					</div>
				{/each}
			</div>
		{:else if analyticsData}
			<!-- Cards with real data -->
			<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
				<!-- Transaction Volume Card -->
				<DashboardCard
					title="Transaction Volume"
					value={formatNumber(analyticsData.summary.transaction_count)}
					trend={analyticsData.summary.count_change_pct !== null
						? {
								value: formatPercent(analyticsData.summary.count_change_pct) ?? '',
								direction: analyticsData.summary.count_change_pct >= 0 ? 'up' : 'down'
							}
						: null}
				>
					<svg
						slot="icon"
						xmlns="http://www.w3.org/2000/svg"
						class="h-6 w-6"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						stroke-width="2"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
						/>
					</svg>
				</DashboardCard>

				<!-- Market Trend Card with Chart -->
				<DashboardCard title="Dubai Market Trend" value="">
					<svg
						slot="icon"
						xmlns="http://www.w3.org/2000/svg"
						class="h-6 w-6"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						stroke-width="2"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"
						/>
					</svg>
				<TrendChart trends={analyticsData.trends} />
				</DashboardCard>

				<!-- Avg Price/sq.m Card -->
				<DashboardCard
					title="Avg Price/sq.m"
					value="{formatNumber(analyticsData.summary.avg_price_sqft)} AED"
					trend={analyticsData.summary.volume_change_pct !== null
						? {
								value: formatPercent(analyticsData.summary.volume_change_pct) ?? '',
								direction: analyticsData.summary.volume_change_pct >= 0 ? 'up' : 'down'
							}
						: null}
				>
					<svg
						slot="icon"
						xmlns="http://www.w3.org/2000/svg"
						class="h-6 w-6"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						stroke-width="2"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
						/>
					</svg>
				</DashboardCard>
			</div>
		{:else}
			<!-- Error state -->
			<div class="text-center py-12">
				<p class="text-gray-500">Failed to load dashboard data. Please refresh the page.</p>
			</div>
		{/if}

		<!-- News Feed -->
		<section class="mt-12 pt-8 border-t border-gray-200">
			<h2 class="text-2xl font-semibold mb-6">Latest News</h2>
			<NewsFeed />
		</section>
	</div>
</AppShell>
