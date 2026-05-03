<script lang="ts">
import { createInfiniteQuery, createQuery } from '@tanstack/svelte-query'
import { goto } from '$app/navigation'
import { chat } from '$lib/api/chat'
import CompactChatInput from '$lib/components/dashboard/CompactChatInput.svelte'
import CompleteProfileModal from '$lib/components/dashboard/CompleteProfileModal.svelte'
import FullWidthMarketChart from '$lib/components/dashboard/FullWidthMarketChart.svelte'
import AppFrame from '$lib/components/layout/AppFrame.svelte'
import PageContainer from '$lib/components/layout/PageContainer.svelte'
import NewsCard from '$lib/components/news/NewsCard.svelte'
import { analyticsQueries } from '$lib/queries/analytics'
import { newsQueries } from '$lib/queries/news'
import { currentUser } from '$lib/stores/user.svelte'

let username = $derived(currentUser.data?.first_name ?? '')
let newsSection = $state<HTMLElement>()
let newsSectionVisible = $state(false)
let sentinel = $state<HTMLDivElement>()

const LIMIT = 10

const newsQuery = createInfiniteQuery(() => newsQueries.listInfinite('dashboard', LIMIT))
const newsArticles = $derived(newsQuery.data?.pages.flatMap((page) => page.articles) ?? [])

async function handleChatSubmit(message: string) {
	try {
		const conversation = await chat.createConversation({ title: message.slice(0, 50) })
		goto('/chat', {
			state: { conversationId: conversation.id, initialMessage: message }
		})
	} catch (error) {
		console.error('Failed to create conversation:', error)
		throw error
	}
}

$effect(() => {
	if (!newsSection) return
	const observer = new IntersectionObserver(
		(entries) => {
			entries.forEach((entry) => {
				if (entry.isIntersecting) newsSectionVisible = true
			})
		},
		{ threshold: 0.1 }
	)
	observer.observe(newsSection)
	return () => observer.disconnect()
})

$effect(() => {
	if (!sentinel) return
	const observer = new IntersectionObserver(
		(entries) => {
			if (entries[0].isIntersecting && newsQuery.hasNextPage && !newsQuery.isFetchingNextPage) {
				newsQuery.fetchNextPage()
			}
		},
		{ threshold: 0.1, rootMargin: '200px' }
	)
	observer.observe(sentinel)
	return () => observer.disconnect()
})

const kpiQuery = createQuery(() => analyticsQueries.marketTrend(365))

function formatPriceSqm(n: number): string {
	return new Intl.NumberFormat('en-US').format(Math.round(n))
}

function formatPrice(n: number): string {
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
	if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`
	return Math.round(n).toLocaleString()
}

function fmtPct(n: number | null | undefined): string | null {
	if (n == null) return null
	return `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`
}

const lastPoint = $derived(
	kpiQuery.data?.data?.length ? kpiQuery.data.data[kpiQuery.data.data.length - 1] : null
)

const SUGGESTIONS = [
	'What are 2BR yields in Dubai Marina this quarter?',
	'Compare JBR vs Palm Jumeirah price trends',
	'Which sub-markets have the highest YoY growth?'
]
</script>

<AppFrame stableScrollGutter>
	<PageContainer variant="standard">
			<!-- Page Header -->
			<div class="py-8 pb-6">
				<p class="font-mono text-[11px] uppercase tracking-[0.06em] text-fg-4 mb-2">
					Workspace / <span class="text-fg-1">Dubai market</span>
				</p>
				<h1 class="text-2xl font-semibold tracking-normal text-fg-1">
					{username ? `${username}'s workspace` : 'Market overview'}
				</h1>
				<p class="mt-1.5 text-sm text-fg-3">
					Live market data · ask anything below or browse the latest transactions.
				</p>
			</div>

			<!-- KPI Grid -->
			<div class="grid grid-cols-1 gap-3 mb-3 sm:grid-cols-3">

				<!-- Avg Price / sqm -->
				<div class="ui-metric-card">
					<div class="flex items-center justify-between mb-4">
						<span class="font-mono text-[11px] uppercase tracking-[0.08em] text-fg-4">Avg. Price / sqm</span>
						<svg class="h-[14px] w-[14px] text-fg-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z"/>
						</svg>
					</div>
					{#if kpiQuery.isLoading}
						<div class="h-9 w-32 animate-pulse rounded bg-panel"></div>
						<div class="mt-2 h-4 w-20 animate-pulse rounded bg-panel"></div>
					{:else}
						<div class="font-display text-4xl font-normal leading-none tracking-normal text-fg-1 tabular-nums">
							{lastPoint ? formatPriceSqm(lastPoint.avg_price_sqm) : '—'}
						</div>
						<p class="mt-1 text-[11px] text-fg-4">AED / sq.m</p>
						{@const pct = fmtPct(kpiQuery.data?.avg_price_sqm_change_pct)}
						{@const pos = (kpiQuery.data?.avg_price_sqm_change_pct ?? 0) >= 0}
						{#if pct}
							<p class="mt-2 font-mono text-xs {pos ? 'text-trend-up' : 'text-trend-down'}">
								{pos ? '▲' : '▼'} {pct} YoY
							</p>
						{/if}
					{/if}
				</div>

				<!-- Total Transactions -->
				<div class="ui-metric-card">
					<div class="flex items-center justify-between mb-4">
						<span class="font-mono text-[11px] uppercase tracking-[0.08em] text-fg-4">Transactions</span>
						<svg class="h-[14px] w-[14px] text-fg-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z"/>
						</svg>
					</div>
					{#if kpiQuery.isLoading}
						<div class="h-9 w-28 animate-pulse rounded bg-panel"></div>
					{:else}
						<div class="font-display text-4xl font-normal leading-none tracking-normal text-fg-1 tabular-nums">
							{kpiQuery.data ? kpiQuery.data.total_transactions.toLocaleString() : '—'}
						</div>
						<p class="mt-1 font-mono text-[10px] uppercase tracking-[0.06em] text-fg-4">Last 12 months</p>
					{/if}
				</div>

				<!-- Avg Sale Price -->
				<div class="ui-metric-card">
					<div class="flex items-center justify-between mb-4">
						<span class="font-mono text-[11px] uppercase tracking-[0.08em] text-fg-4">Avg. Sale Price</span>
						<svg class="h-[14px] w-[14px] text-fg-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/>
						</svg>
					</div>
					{#if kpiQuery.isLoading}
						<div class="h-9 w-32 animate-pulse rounded bg-panel"></div>
						<div class="mt-2 h-4 w-20 animate-pulse rounded bg-panel"></div>
					{:else}
						<div class="font-display text-4xl font-normal leading-none tracking-normal text-fg-1 tabular-nums">
							<span class="text-2xl font-normal text-fg-3 mr-1">AED</span>{lastPoint ? formatPrice(lastPoint.avg_price) : '—'}
						</div>
						{@const pct = fmtPct(kpiQuery.data?.avg_price_change_pct)}
						{@const pos = (kpiQuery.data?.avg_price_change_pct ?? 0) >= 0}
						{#if pct}
							<p class="mt-2 font-mono text-xs {pos ? 'text-trend-up' : 'text-trend-down'}">
								{pos ? '▲' : '▼'} {pct} YoY
							</p>
						{/if}
					{/if}
				</div>
			</div>

			<!-- Two-col: Chart + AI -->
			<div class="grid grid-cols-1 gap-3 mb-3 lg:grid-cols-[1.6fr_1fr]">

				<!-- Market Chart Card -->
				<div class="ui-surface p-6">
					<FullWidthMarketChart />
				</div>

				<!-- Vitevue AI Card -->
				<div class="ui-surface flex flex-col p-6">
					<div class="flex items-center justify-between mb-4">
						<h3 class="text-sm font-semibold text-fg-1">Vitevue AI</h3>
						<span class="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.08em] text-success">
							<span class="inline-block h-1.5 w-1.5 rounded-full bg-success shadow-[0_0_0_3px_rgba(17,122,72,0.18)]"></span>
							Live
						</span>
					</div>

					<CompactChatInput
						placeholder="Ask anything about Dubai real estate…"
						onSubmit={handleChatSubmit}
					/>

					<div class="mt-4 flex flex-col gap-2">
						{#each SUGGESTIONS as s (s)}
							<button
								type="button"
								onclick={() => handleChatSubmit(s)}
								class="w-full rounded-md border border-border bg-card px-3 py-2 text-left text-xs text-fg-2 transition-colors hover:border-strong hover:bg-elevated"
							>
								→ {s}
							</button>
						{/each}
					</div>
				</div>
			</div>

			<!-- News Section -->
			<div class="mb-12" bind:this={newsSection}>
				<div class="mb-4 flex items-center justify-between border-b border-border pb-4">
					<div>
						<p class="font-mono text-[11px] uppercase tracking-[0.08em] text-fg-4">Latest news</p>
						<h2 class="mt-1 text-2xl font-semibold text-fg-1">Dubai real estate</h2>
					</div>
				</div>

				<div
					class="transition-opacity duration-700 {newsSectionVisible ? 'opacity-100' : 'opacity-0'}"
				>
					{#if newsQuery.isPending}
						<div class="py-8 text-center text-sm text-fg-4">Loading…</div>
					{:else if newsQuery.isError}
						<div class="py-8 text-center text-sm text-error">Error loading news</div>
					{:else if newsArticles.length === 0}
						<div class="py-8 text-center text-sm text-fg-4">No articles available</div>
					{:else}
						<div class="space-y-3">
							{#each newsArticles as article (article.id)}
								<NewsCard {article} />
							{/each}
							{#if newsQuery.isFetchingNextPage}
								<div class="py-4 text-center text-sm text-fg-4">Loading more…</div>
							{/if}
							<div bind:this={sentinel} class="h-4"></div>
						</div>
					{/if}
				</div>
			</div>

	</PageContainer>

	{#if currentUser.data && (!currentUser.data.first_name || !currentUser.data.last_name)}
		<CompleteProfileModal />
	{/if}
</AppFrame>
