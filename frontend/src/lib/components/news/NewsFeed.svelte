<script lang="ts">
import { createInfiniteQuery } from '@tanstack/svelte-query'
import { onMount } from 'svelte'
import { news } from '$lib/api/news'
import NewsCard from './NewsCard.svelte'

const LIMIT = 20

const newsQuery = createInfiniteQuery(() => ({
	queryKey: ['news'],
	queryFn: ({ pageParam = 0 }) => news.list({ limit: LIMIT, offset: pageParam }),
	getNextPageParam: (lastPage) => {
		const nextOffset = lastPage.offset + lastPage.articles.length
		return nextOffset < lastPage.total ? nextOffset : undefined
	},
	initialPageParam: 0
}))

let sentinel: HTMLDivElement

onMount(() => {
	const observer = new IntersectionObserver((entries) => {
		if (entries[0].isIntersecting && newsQuery.hasNextPage && !newsQuery.isFetchingNextPage) {
			newsQuery.fetchNextPage()
		}
	})

	if (sentinel) observer.observe(sentinel)
	return () => observer.disconnect()
})

const allArticles = $derived(newsQuery.data?.pages.flatMap((page) => page.articles) ?? [])
</script>

<div class="flex flex-col gap-4">
	{#if newsQuery.isPending}
		<div class="text-gray-500">Loading news...</div>
	{:else if newsQuery.isError}
		<div class="text-red-500">Error loading news</div>
	{:else}
		{#each allArticles as article (article.id)}
			<NewsCard {article} />
		{/each}

		<div bind:this={sentinel}></div>

		{#if newsQuery.isFetchingNextPage}
			<div class="text-gray-500 text-center py-4">Loading more...</div>
		{/if}
	{/if}
</div>
