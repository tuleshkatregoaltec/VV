<script lang="ts">
	import CompactChatInput from '$lib/components/dashboard/CompactChatInput.svelte';
	import FullWidthMarketChart from '$lib/components/dashboard/FullWidthMarketChart.svelte';
	import CompleteProfileModal from '$lib/components/dashboard/CompleteProfileModal.svelte';
	import AppShell from '$lib/components/layout/AppShell.svelte';
	import NewsCard from '$lib/components/news/NewsCard.svelte';
	import { goto } from '$app/navigation';
	import { chat } from '$lib/api/chat';
	import { news } from '$lib/api/news';
	import { analytics } from '$lib/api/analytics';
	import { createQuery, createInfiniteQuery } from '@tanstack/svelte-query';
	import { currentUser } from '$lib/stores/user.svelte';

	let username = $derived(currentUser.data?.first_name ?? '');
	let newsSection = $state<HTMLElement>();
	let newsSectionVisible = $state(false);
	let sentinel = $state<HTMLDivElement>();

	const LIMIT = 10; // Load 10 articles initially and per page

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

	// Infinite scroll observer - trigger when user is 3 articles away from bottom
	$effect(() => {
		if (!sentinel) return;

		const observer = new IntersectionObserver(
			(entries) => {
				if (entries[0].isIntersecting) {
					if (newsQuery.hasNextPage && !newsQuery.isFetchingNextPage) {
						console.log('Sentinel reached, loading next page...');
						newsQuery.fetchNextPage();
					}
				}
			},
			{
				threshold: 0.1,
				rootMargin: '200px' // Start loading 200px before reaching sentinel
			}
		);

		observer.observe(sentinel);

		return () => observer.disconnect();
	});

	const kpiQuery = createQuery(() => ({
		queryKey: ['market-trend', 365],
		queryFn: () => analytics.marketTrend({ days: 365 }),
		staleTime: 5 * 60 * 1000
	}));

	function formatPrice(n: number): string {
		if (n >= 1_000_000) return `AED ${(n / 1_000_000).toFixed(2)}M`;
		if (n >= 1_000) return `AED ${(n / 1_000).toFixed(0)}K`;
		return `AED ${Math.round(n).toLocaleString()}`;
	}

	function formatCount(n: number): string {
		return n.toLocaleString();
	}

	function fmtPct(n: number | null | undefined): string | null {
		if (n == null) return null;
		return `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`;
	}

	const lastPoint = $derived(
		kpiQuery.data?.data?.length ? kpiQuery.data.data[kpiQuery.data.data.length - 1] : null
	);
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
							Welcome, <span
								class="bg-gradient-to-r from-teal-600 to-cyan-600 bg-clip-text text-transparent"
								>{username}</span
							>
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
					<!-- Avg Price/sqm -->
					<div
						class="bg-white/80 backdrop-blur-sm rounded-xl p-4 border border-teal-100 shadow-sm hover:shadow-md transition-all duration-300"
					>
						<div class="flex items-center gap-3 mb-3">
							<div
								class="p-2.5 bg-gradient-to-br from-teal-600 to-cyan-600 rounded-lg flex-shrink-0"
							>
								<svg
									class="w-5 h-5 text-white"
									fill="none"
									viewBox="0 0 24 24"
									stroke="currentColor"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z"
									/>
								</svg>
							</div>
							{#if kpiQuery.isLoading}
								<div class="h-6 w-20 bg-slate-200 rounded-full animate-pulse"></div>
							{:else}
								{@const pct = fmtPct(kpiQuery.data?.avg_price_sqm_change_pct)}
								{@const positive = (kpiQuery.data?.avg_price_sqm_change_pct ?? 0) >= 0}
								{#if pct}
									<div
										class="flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold {positive
											? 'bg-green-50 text-green-700'
											: 'bg-red-50 text-red-700'}"
									>
										<svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
											{#if positive}
												<path
													fill-rule="evenodd"
													d="M5.293 9.707a1 1 0 010-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 01-1.414 1.414L11 7.414V15a1 1 0 11-2 0V7.414L6.707 9.707a1 1 0 01-1.414 0z"
													clip-rule="evenodd"
												/>
											{:else}
												<path
													fill-rule="evenodd"
													d="M14.707 10.293a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 111.414-1.414L9 12.586V5a1 1 0 012 0v7.586l2.293-2.293a1 1 0 011.414 0z"
													clip-rule="evenodd"
												/>
											{/if}
										</svg>
										{pct} YoY
									</div>
								{/if}
							{/if}
						</div>
						<h3 class="text-sm font-medium text-slate-600 mb-1">Avg. Price / sqm</h3>
						{#if kpiQuery.isLoading}
							<div class="h-8 w-32 bg-slate-200 rounded animate-pulse"></div>
						{:else}
							<p class="text-2xl font-bold text-slate-900">
								{lastPoint ? `AED ${Math.round(lastPoint.avg_price_sqm).toLocaleString()}` : '—'}
							</p>
						{/if}
					</div>

					<!-- Total Transactions -->
					<div
						class="bg-white/80 backdrop-blur-sm rounded-xl p-4 border border-teal-100 shadow-sm hover:shadow-md transition-all duration-300"
					>
						<div class="flex items-center gap-3 mb-3">
							<div
								class="p-2.5 bg-gradient-to-br from-teal-600 to-cyan-600 rounded-lg flex-shrink-0"
							>
								<svg
									class="w-5 h-5 text-white"
									fill="none"
									viewBox="0 0 24 24"
									stroke="currentColor"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
									/>
								</svg>
							</div>
							<div
								class="px-2.5 py-1 bg-slate-100 text-slate-600 rounded-full text-xs font-semibold"
							>
								Last 12 months
							</div>
						</div>
						<h3 class="text-sm font-medium text-slate-600 mb-1">Total Transactions</h3>
						{#if kpiQuery.isLoading}
							<div class="h-8 w-28 bg-slate-200 rounded animate-pulse"></div>
						{:else}
							<p class="text-2xl font-bold text-slate-900">
								{kpiQuery.data ? formatCount(kpiQuery.data.total_transactions) : '—'}
							</p>
						{/if}
					</div>

					<!-- Avg Sale Price -->
					<div
						class="bg-white/80 backdrop-blur-sm rounded-xl p-4 border border-teal-100 shadow-sm hover:shadow-md transition-all duration-300"
					>
						<div class="flex items-center gap-3 mb-3">
							<div
								class="p-2.5 bg-gradient-to-br from-teal-600 to-cyan-600 rounded-lg flex-shrink-0"
							>
								<svg
									class="w-5 h-5 text-white"
									fill="none"
									viewBox="0 0 24 24"
									stroke="currentColor"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"
									/>
								</svg>
							</div>
							{#if kpiQuery.isLoading}
								<div class="h-6 w-20 bg-slate-200 rounded-full animate-pulse"></div>
							{:else}
								{@const pct = fmtPct(kpiQuery.data?.avg_price_change_pct)}
								{@const positive = (kpiQuery.data?.avg_price_change_pct ?? 0) >= 0}
								{#if pct}
									<div
										class="flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold {positive
											? 'bg-green-50 text-green-700'
											: 'bg-red-50 text-red-700'}"
									>
										<svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
											{#if positive}
												<path
													fill-rule="evenodd"
													d="M5.293 9.707a1 1 0 010-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 01-1.414 1.414L11 7.414V15a1 1 0 11-2 0V7.414L6.707 9.707a1 1 0 01-1.414 0z"
													clip-rule="evenodd"
												/>
											{:else}
												<path
													fill-rule="evenodd"
													d="M14.707 10.293a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 111.414-1.414L9 12.586V5a1 1 0 012 0v7.586l2.293-2.293a1 1 0 011.414 0z"
													clip-rule="evenodd"
												/>
											{/if}
										</svg>
										{pct} YoY
									</div>
								{/if}
							{/if}
						</div>
						<h3 class="text-sm font-medium text-slate-600 mb-1">Avg. Sale Price</h3>
						{#if kpiQuery.isLoading}
							<div class="h-8 w-32 bg-slate-200 rounded animate-pulse"></div>
						{:else}
							<p class="text-2xl font-bold text-slate-900">
								{lastPoint ? formatPrice(lastPoint.avg_price) : '—'}
							</p>
						{/if}
					</div>
				</div>
			</div>

			<!-- Market Chart -->
			<div class="mb-12">
				<h2 class="text-2xl font-bold text-slate-900 mb-6">Market Trends</h2>
				<div
					class="bg-white/80 backdrop-blur-sm rounded-2xl shadow-lg border border-teal-100 p-8 hover:shadow-xl transition-shadow duration-300"
				>
					<FullWidthMarketChart />
				</div>
			</div>

			<!-- News Section Header -->
			<div class="text-center mb-12">
				<div
					class="inline-block px-4 py-2 bg-teal-100 text-teal-700 rounded-full text-sm font-semibold mb-4"
				>
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

						{#if newsQuery.isFetchingNextPage}
							<div class="text-center text-slate-500 py-4">Loading more...</div>
						{/if}

						<!-- Infinite scroll sentinel - placed after articles for next page trigger -->
						<div bind:this={sentinel} class="h-4"></div>
					{/if}
				</div>
			</div>
		</section>
	</div>

	<!-- Complete Profile Modal - show if user is missing first or last name -->
	{#if currentUser.data && (!currentUser.data.first_name || !currentUser.data.last_name)}
		<CompleteProfileModal />
	{/if}
</AppShell>
