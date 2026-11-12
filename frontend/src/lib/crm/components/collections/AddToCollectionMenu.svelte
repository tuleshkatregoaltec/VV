<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Plus from 'lucide-svelte/icons/folder-plus'
import { crmQueries } from '$lib/crm/queries'
import MenuRow from './CollectionMenuRow.svelte'
import { addListing, createCollection } from './collectionActions'
import { addButtonClick } from './collectionRules'

/** Lives beside the card's clickable element, never inside it. */
let { listingKey }: { listingKey: string } = $props()

let open = $state(false)
let naming = $state(false)
let name = $state('')
const list = createQuery(() => ({ ...crmQueries.collections(), enabled: open }))

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
				<MenuRow collection={c} {listingKey} onpick={add} />
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
</style>
