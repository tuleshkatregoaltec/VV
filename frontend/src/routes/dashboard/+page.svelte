<script lang="ts">
	import CompactChatInput from '$lib/components/dashboard/CompactChatInput.svelte';
	import FullWidthMarketChart from '$lib/components/dashboard/FullWidthMarketChart.svelte';
	import AppShell from '$lib/components/layout/AppShell.svelte';
	import NewsFeed from '$lib/components/news/NewsFeed.svelte';
	import NewsCard from '$lib/components/news/NewsCard.svelte';
	import { goto } from '$app/navigation';
	import { chat } from '$lib/api/chat';
	import { news } from '$lib/api/news';
	import { createInfiniteQuery } from '@tanstack/svelte-query';
	import { onMount } from 'svelte';
	import { currentUser } from '$lib/stores/user.svelte';

	let username = $derived(currentUser.data?.first_name ?? '');
	let newsSection = $state<HTMLElement>();
	let newsSectionVisible = $state(false);
	let sentinel = $state<HTMLDivElement>();

	const LIMIT = 2;

	// Fetch news articles with infinite scrolling
	const newsQuery = createInfiniteQuery(() => ({
		queryKey: ['news', 'dashboard'],
		queryFn: ({ pageParam = 0 }) => news.list({ limit: LIMIT, offset: pageParam }),
		getNextPageParam: (lastPage) => {
			const nextOffset = lastPage.offset + lastPage.articles.length;
			return nextOffset < lastPage.total ? nextOffset : undefined;
		},
		initialPageParam: 0
	}));

	const newsArticles = $derived(newsQuery.data?.pages.flatMap((page) => page.articles) ?? []);

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

	// Intersection observer to detect when news section is visible
	$effect(() => {
		if (!newsSection) return;

		const observer = new IntersectionObserver(
			(entries) => {
				entries.forEach((entry) => {
					if (entry.isIntersecting) {
						newsSectionVisible = true;
					}
				});
			},
			{ threshold: 0.1 }
		);

		observer.observe(newsSection);

		return () => observer.disconnect();
	});

	// Infinite scroll observer
	onMount(() => {
		const observer = new IntersectionObserver((entries) => {
			if (
				entries[0].isIntersecting &&
				newsQuery.hasNextPage &&
				!newsQuery.isFetchingNextPage
			) {
				newsQuery.fetchNextPage();
			}
		});

		if (sentinel) observer.observe(sentinel);
		return () => observer.disconnect();
	});

	// Mock stats data - 3 KPIs in one row
	const stats = [
		{
			label: 'Avg. Price/sqft',
			value: 'AED 1,284',
			change: '+2.4%',
			positive: true,
			icon: 'chart'
		},
		{
			label: 'Total Transactions',
			value: '142,340',
			change: '+8.1%',
			positive: true,
			icon: 'transactions'
		},
		{
			label: 'Market Growth',
			value: '12.3%',
			change: 'YoY',
			positive: true,
			icon: 'growth'
		}
	];
</script>

<AppShell showFilters={false}>
	<!-- Unified offwhite background -->
	<div class="min-h-screen bg-slate-50">
		<!-- Hero Section -->
		<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-12 pb-8">
			<!-- Hero + Chat on Left, KPIs on Right -->
			<div class="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-12 lg:items-center">
				<!-- Left: Hero + Chat (2 columns) -->
				<div class="lg:col-span-2 space-y-8">
					<!-- Hero Text -->
					<div class="text-center">
						<h1 class="text-5xl sm:text-6xl font-bold text-slate-900 mb-4">
							Welcome, <span class="bg-gradient-to-r from-teal-600 to-cyan-600 bg-clip-text text-transparent">{username}</span>
						</h1>
						<p class="text-xl text-slate-600">Your Dubai real-estate dashboard</p>
					</div>

					<!-- Chat Input -->
					<CompactChatInput
						placeholder="Ask me anything about Dubai real estate..."
						onSubmit={handleChatSubmit}
					/>
				</div>

				<!-- Right: KPI Cards (1 column) -->
				<div class="lg:col-span-1 flex flex-col gap-4">
					{#each stats as stat}
						<div class="bg-white/80 backdrop-blur-sm rounded-xl p-4 border border-teal-100 shadow-sm hover:shadow-md transition-all duration-300">
							<div class="flex items-center gap-3 mb-3">
								<div class="p-2.5 bg-gradient-to-br from-teal-600 to-cyan-600 rounded-lg flex-shrink-0">
									{#if stat.icon === 'chart'}
										<svg class="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
										</svg>
									{:else if stat.icon === 'transactions'}
										<svg class="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
										</svg>
									{:else if stat.icon === 'growth'}
										<svg class="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
										</svg>
									{/if}
								</div>
								<div class="flex items-center gap-1 px-2.5 py-1 bg-teal-50 text-teal-700 rounded-full text-xs font-semibold">
									{#if stat.positive}
										<svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
											<path fill-rule="evenodd" d="M5.293 9.707a1 1 0 010-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 01-1.414 1.414L11 7.414V15a1 1 0 11-2 0V7.414L6.707 9.707a1 1 0 01-1.414 0z" clip-rule="evenodd" />
										</svg>
									{/if}
									{stat.change}
								</div>
							</div>
							<h3 class="text-sm font-medium text-slate-600 mb-1">{stat.label}</h3>
							<p class="text-2xl font-bold text-slate-900">{stat.value}</p>
						</div>
					{/each}
				</div>
			</div>

			<!-- Market Chart -->
			<div class="mb-12">
				<h2 class="text-2xl font-bold text-slate-900 mb-6">Market Trends</h2>
				<div class="bg-white/80 backdrop-blur-sm rounded-2xl shadow-lg border border-teal-100 p-8 hover:shadow-xl transition-shadow duration-300">
					<FullWidthMarketChart />
				</div>
			</div>

			<!-- News Section Header -->
			<div class="text-center mb-12">
				<div class="inline-block px-4 py-2 bg-teal-100 text-teal-700 rounded-full text-sm font-semibold mb-4">
					Stay Informed
				</div>
				<h2 class="text-4xl sm:text-5xl font-bold text-slate-900 mb-4">Latest News</h2>
				<p class="text-lg text-slate-600">Stay updated with the latest Dubai real estate news</p>
			</div>
		</div>

		<!-- News Feed Section with Fade Transition -->
		<section
			bind:this={newsSection}
			class="pb-16 bg-slate-50 transition-opacity duration-1000 {newsSectionVisible
				? 'opacity-100'
				: 'opacity-0'}"
		>
			<div class="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
				<div class="space-y-4">
					{#if newsQuery.isPending}
						<div class="text-center text-slate-500 py-8">Loading news...</div>
					{:else if newsQuery.isError}
						<div class="text-center text-red-500 py-8">Error loading news</div>
					{:else if newsArticles.length === 0}
						<div class="text-center text-slate-500 py-8">No news articles available</div>
					{:else}
						{#each newsArticles as article (article.id)}
							<NewsCard {article} />
						{/each}

						<!-- Infinite scroll sentinel -->
						<div bind:this={sentinel} class="h-4"></div>

						{#if newsQuery.isFetchingNextPage}
							<div class="text-center text-slate-500 py-4">Loading more...</div>
						{/if}
					{/if}
				</div>
			</div>
		</section>
	</div>
</AppShell>