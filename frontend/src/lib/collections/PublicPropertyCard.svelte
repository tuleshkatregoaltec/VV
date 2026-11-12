<script lang="ts">
import type { PublicCollectionItem } from '$lib/api/generated/hey-api/types.gen'
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
	<li class="rounded-xl border border-dashed border-neutral-300 p-4 text-neutral-500">
		No longer available
	</li>
{:else}
	<li class="overflow-hidden rounded-xl border border-neutral-200 bg-white">
		{#if item.photos?.[0]}
			<img src={item.photos[0]} alt="" loading="lazy" referrerpolicy="no-referrer" class="h-48 w-full object-cover" />
		{/if}
		<div class="space-y-1 p-4">
			<h2 class="font-semibold text-neutral-900">{item.title}</h2>
			{#if place}<p class="text-sm text-neutral-600">{place}</p>{/if}
			{#if facts}<p class="text-sm text-neutral-600">{facts}</p>{/if}
			{#if price}<p class="pt-1 font-semibold text-neutral-900">{price}</p>{/if}
			{#if item.description}
				<p class="pt-2 text-sm whitespace-pre-line text-neutral-700">{item.description}</p>
			{/if}
		</div>
	</li>
{/if}
