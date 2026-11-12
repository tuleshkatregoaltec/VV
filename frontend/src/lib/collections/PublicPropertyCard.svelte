<script lang="ts">
import type { PublicCollectionItem } from '$lib/api/generated/hey-api/types.gen'
import PhotoSlider from './PhotoSlider.svelte'
import { formatAed } from './publicFormat'

let { item }: { item: PublicCollectionItem } = $props()

const place = $derived([item.building_name, item.area_name].filter(Boolean).join(', '))
const facts = $derived(
	[
		item.property_type,
		item.bedrooms != null ? `${item.bedrooms} bed` : null,
		item.size_sqft != null ? `${new Intl.NumberFormat('en-US').format(item.size_sqft)} sqft` : null
	]
		.filter(Boolean)
		.join(' · ')
)
const price = $derived(formatAed(item.price_aed, item.rent_period))
</script>

{#if item.status === 'unavailable'}
	<li class="rounded-xl border border-dashed border-strong bg-card p-4 text-fg-4">
		No longer available
	</li>
{:else}
	<li class="overflow-hidden rounded-xl border border-border bg-card">
		{#if item.photos?.length}
			<div class="relative h-56 w-full bg-panel">
				<PhotoSlider photos={item.photos} />
			</div>
		{/if}
		<div class="space-y-1 p-4">
			<h2 class="font-semibold text-fg-1">{item.title}</h2>
			{#if place}<p class="text-sm text-fg-3">{place}</p>{/if}
			{#if facts}<p class="text-sm text-fg-3">{facts}</p>{/if}
			{#if price}<p class="pt-1 font-semibold text-fg-1">{price}</p>{/if}
			{#if item.description}
				<p class="pt-2 text-sm whitespace-pre-line text-fg-2">{item.description}</p>
			{/if}
		</div>
	</li>
{/if}
