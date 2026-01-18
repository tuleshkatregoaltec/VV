<script lang="ts">
	import CompactChatInput from '$lib/components/dashboard/CompactChatInput.svelte';
	import FullWidthMarketChart from '$lib/components/dashboard/FullWidthMarketChart.svelte';
	import PageHeader from '$lib/components/dashboard/PageHeader.svelte';
	import AppShell from '$lib/components/layout/AppShell.svelte';
	import NewsFeed from '$lib/components/news/NewsFeed.svelte';
	import { goto } from '$app/navigation';
	import { chat } from '$lib/api/chat';
	import { analytics, type SalesAnalyticsResponse } from '$lib/api/analytics';
	import { currentUser } from '$lib/stores/user.svelte';

	let username = $derived(currentUser.data?.first_name ?? '');
	let analyticsData = $state<SalesAnalyticsResponse | null>(null);
	let isLoading = $state(true);
	let newsSection: HTMLElement;

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
	<!-- Main Dashboard Section -->
	<div class="min-h-screen flex flex-col max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 sm:py-6 bg-slate-50 relative">
		<PageHeader title="Welcome, {username}!" subtitle="Your Dubai property dashboard" />

		<div class="mb-6 sm:mb-8">
			<CompactChatInput
				placeholder="Ask me anything about Dubai real estate..."
				onSubmit={handleChatSubmit}
			/>
		</div>

		<!-- Full-Width Market Trend Chart -->
		<div class="mb-20">
			<FullWidthMarketChart />
		</div>

		<!-- Scroll Indicator -->
		<div class="absolute bottom-16 left-1/2 -translate-x-1/2 animate-hover">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				class="h-8 w-8 text-primary"
				fill="none"
				viewBox="0 0 24 24"
				stroke="currentColor"
				stroke-width="2"
			>
				<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
			</svg>
		</div>
	</div>

	<!-- News Feed Section -->
	<section bind:this={newsSection} class="min-h-screen bg-gradient-to-b from-slate-50 to-slate-100 pt-2 pb-16">
		<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
			<h2 class="text-3xl sm:text-4xl font-bold text-slate-900 text-center mb-12">Latest News</h2>
			<NewsFeed />
		</div>
	</section>
</AppShell>
