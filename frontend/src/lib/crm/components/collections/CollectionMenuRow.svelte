<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import type { CollectionResponse } from '$lib/api/generated/hey-api/types.gen'
import { crmQueries } from '$lib/crm/queries'
import { menuRowState } from './collectionRules'

/** One collection in the menu; membership comes from its detail query so it updates when loaded. */
let {
	collection,
	listingKey,
	onpick
}: { collection: CollectionResponse; listingKey: string; onpick: (id: string) => void } = $props()

const detail = createQuery(() => crmQueries.collection(collection.id))
const s = $derived(menuRowState(collection, detail.data, listingKey))
</script>

<button
	type="button"
	role="menuitem"
	class="mi"
	disabled={s.disabled}
	aria-busy={s.pending}
	onclick={() => onpick(collection.id)}
>
	<span class="ck">{s.checked ? '✓' : ''}</span>
	<span class="nm">{collection.name}</span>
	{#if s.hint}<span class="hint">{s.hint}</span>{/if}
</button>

<style>
	.mi { display: flex; align-items: center; gap: 8px; width: 100%; padding: 6px 8px; background: none; border: 0; text-align: left; cursor: pointer; }
	.mi:disabled { opacity: 0.55; cursor: not-allowed; }
	.ck { width: 14px; }
	.nm { flex: 1; }
	.hint { font-size: 12px; color: var(--mute, #6b7280); }
</style>
