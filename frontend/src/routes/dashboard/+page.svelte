<script lang="ts">
	import CompactChatInput from '$lib/components/dashboard/CompactChatInput.svelte';
	import DashboardCard from '$lib/components/dashboard/DashboardCard.svelte';
	import PageHeader from '$lib/components/dashboard/PageHeader.svelte';
	import AppShell from '$lib/components/layout/AppShell.svelte';
	import Grid from '$lib/components/layout/Grid.svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { goto } from '$app/navigation';
	import { chat } from '$lib/api/chat';

	let username = $derived(authStore.user?.first_name ?? '');

	async function handleChatSubmit(message: string) {
		try {
			// Create new conversation with title from first message
			const conversation = await chat.createConversation({
				title: message.slice(0, 50)
			});

			// Navigate to chat route with conversation and initial message
			goto('/dashboard/chat', {
				state: {
					conversationId: conversation.id,
					initialMessage: message
				}
			});
		} catch (error) {
			console.error('Failed to create conversation:', error);
			// Re-throw to let CompactChatInput handle the error display
			throw error;
		}
	}
</script>

<AppShell showFilters={false}>
    <div class="max-w-7xl mx-auto px-4 py-8 bg-background">

	<PageHeader title="Welcome, {username}!" subtitle="Your property dashboard" />

	<div class="mb-16">
		<CompactChatInput
			placeholder="Ask me anything about Dubai real estate..."
			onSubmit={handleChatSubmit}
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
					<svg class="w-full h-full" viewBox="0 0 200 64" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
						<defs>
							<linearGradient id="g1" x1="0" x2="0" y1="0" y2="1">
								<stop offset="0%" stop-color="#60a5fa" stop-opacity="0.45" />
								<stop offset="100%" stop-color="#60a5fa" stop-opacity="0.05" />
							</linearGradient>
						</defs>
						<!-- Smooth trendline and matching filled area (no plotted points) -->
						<path d="M0 44 C40 36, 70 28, 100 30 C130 32, 160 22, 200 12 L200 64 L0 64 Z" fill="url(#g1)" />
						<path d="M0 44 C40 36, 70 28, 100 30 C130 32, 160 22, 200 12" fill="none" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.95" />
					</svg>
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
