<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { page } from '$app/state'
import PublicPropertyCard from '$lib/collections/PublicPropertyCard.svelte'
import { fetchPublicCollection, PublicCollectionError } from '$lib/collections/publicApi'
import { relativeTime } from '$lib/collections/publicFormat'

const token = $derived(page.params.token ?? '')

// Never cached or persisted: availability and prices must be current every time.
const query = createQuery(() => ({
	queryKey: ['public-collection', token],
	queryFn: () => fetchPublicCollection(token),
	staleTime: 0,
	gcTime: 0,
	refetchOnWindowFocus: true,
	refetchOnMount: 'always' as const,
	retry: false
}))

// Anything that is not an explicit "unavailable" (including a malformed body) is retryable.
const unavailable = $derived(
	query.isError &&
		query.error instanceof PublicCollectionError &&
		query.error.kind === 'unavailable'
)
const latestUpdate = $derived(
	query.data?.items
		.map((i) => i.updated_at)
		.filter((v): v is string => Boolean(v))
		.sort()
		.at(-1) ?? query.data?.fetched_at
)
</script>

<svelte:head>
	<title>Property collection</title>
	<meta name="robots" content="noindex,nofollow" />
	<meta name="referrer" content="no-referrer" />
</svelte:head>

<main class="mx-auto max-w-3xl space-y-6 px-4 py-8">
	{#if query.isPending}
		<p class="text-neutral-500">Loading…</p>
	{:else if unavailable}
		<p class="text-neutral-700">This collection is no longer available.</p>
	{:else if query.isError}
		<div class="space-y-3">
			<p class="text-neutral-700">We couldn't load these properties right now.</p>
			<button
				type="button"
				class="rounded-lg bg-neutral-900 px-4 py-2 text-white"
				onclick={() => query.refetch()}
			>
				Retry
			</button>
		</div>
	{:else if query.data}
		{@const collection = query.data}
		<header class="space-y-3">
			<h1 class="text-2xl font-semibold text-neutral-900">{collection.name}</h1>
			<div class="rounded-xl bg-neutral-100 p-4 text-sm text-neutral-700">
				<p class="font-medium text-neutral-900">{collection.agent.name}</p>
				{#if collection.agent.email}
					<p><a class="underline" href={`mailto:${collection.agent.email}`}>{collection.agent.email}</a></p>
				{/if}
				{#if collection.agent.phone}
					<p><a class="underline" href={`tel:${collection.agent.phone}`}>{collection.agent.phone}</a></p>
				{/if}
			</div>
		</header>

		{#if collection.items.length === 0}
			<p class="text-neutral-600">No properties in this collection yet.</p>
		{:else}
			<ul class="space-y-4">
				{#each collection.items as item}
					<PublicPropertyCard {item} />
				{/each}
			</ul>
			<footer class="text-xs text-neutral-500">
				Listing details from Property Finder, updated {latestUpdate ? relativeTime(latestUpdate) : 'recently'}.
			</footer>
		{/if}
	{/if}
</main>
