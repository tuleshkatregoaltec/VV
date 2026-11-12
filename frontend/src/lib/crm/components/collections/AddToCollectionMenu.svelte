<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Plus from 'lucide-svelte/icons/folder-plus'
import type { CollectionDetailResponse } from '$lib/api/generated/hey-api/types.gen'
import { crmKeys, crmQueries } from '$lib/crm/queries'
import { getQueryClient } from '$lib/queries/client'
import { addListing, createCollection } from './collectionActions'
import { addButtonClick, menuItemState } from './collectionRules'

/** Lives beside the card's clickable element, never inside it. */
let { listingKey }: { listingKey: string } = $props()

let open = $state(false)
let naming = $state(false)
let name = $state('')
const list = createQuery(() => ({ ...crmQueries.collections(), enabled: open }))

/** Whether this listing is already in a collection, read from that collection's cached detail. */
const contains = (collectionId: string) =>
	getQueryClient()
		.getQueryData<CollectionDetailResponse>(crmKeys.collection(collectionId))
		?.items.some((i) => i.listing_key === listingKey) ?? false

$effect(() => {
	for (const c of open ? (list.data?.items ?? []) : [])
		void getQueryClient().prefetchQuery(crmQueries.collection(c.id))
})

async function add(collectionId: string) {
	open = false
	await addListing(collectionId, listingKey)
}

async function createAndAdd() {
	const value = name.trim()
	if (!value) return
	const made = await createCollection(value)
	name = ''
	naming = false
	if (made) await add(made.id)
}
</script>

<div class="atc">
	<button
		type="button"
		class="btn ghost sm"
		aria-haspopup="menu"
		aria-expanded={open}
		onclick={(e) => addButtonClick(e, () => (open = !open))}
	>
		<Plus size={14} /> Add to collection
	</button>
	{#if open}
		<div class="menu" role="menu" tabindex="-1" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.key === 'Escape' && (open = false)}>
			{#each list.data?.items ?? [] as c (c.id)}
				{@const s = menuItemState(c, contains(c.id))}
				<button type="button" role="menuitem" class="mi" disabled={s.disabled} onclick={() => add(c.id)}>
					<span class="ck">{s.checked ? '✓' : ''}</span>
					<span class="nm">{c.name}</span>
					{#if s.hint}<span class="hint">{s.hint}</span>{/if}
				</button>
			{/each}
			{#if naming}
				<form
					class="mi"
					onsubmit={(e) => {
						e.preventDefault()
						void createAndAdd()
					}}
				>
					<input class="input" aria-label="New collection name" placeholder="Name" maxlength="120" bind:value={name} />
				</form>
			{:else}
				<button type="button" role="menuitem" class="mi" onclick={() => (naming = true)}>New collection…</button>
			{/if}
		</div>
	{/if}
</div>

<style>
	.atc { position: relative; }
	.menu {
		position: absolute; z-index: 20; right: 0; bottom: 100%; min-width: 220px; padding: 4px;
		background: var(--card, #fff); border: 1px solid var(--line, #e5e7eb); border-radius: 8px;
		box-shadow: 0 6px 20px rgb(0 0 0 / 0.12);
	}
	.mi { display: flex; align-items: center; gap: 8px; width: 100%; padding: 6px 8px; background: none; border: 0; text-align: left; cursor: pointer; }
	.mi:disabled { opacity: 0.55; cursor: not-allowed; }
	.ck { width: 14px; }
	.nm { flex: 1; }
	.hint { font-size: 12px; color: var(--mute, #6b7280); }
</style>
