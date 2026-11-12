<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import QueryView from '$lib/crm/components/ui/QueryView.svelte'
import { price } from '$lib/crm/format'
import { crmQueries } from '$lib/crm/queries'
import {
	copyShareLink,
	deleteCollection,
	removeItem,
	renameCollection,
	rotateShareLink,
	setSharing
} from './collectionActions'
import { countLabel } from './collectionRules'

let { id, onback }: { id: string; onback: () => void } = $props()

const detail = createQuery(() => crmQueries.collection(id))
let draft = $state<string | null>(null)

async function saveName(current: string) {
	const value = (draft ?? current).trim()
	draft = null
	if (value && value !== current) await renameCollection(id, value)
}

async function rotate() {
	if (confirm('Get a new link? The old link will stop working.')) await rotateShareLink(id)
}

async function remove(name: string) {
	if (!confirm(`Delete "${name}"? Its link will stop working.`)) return
	if (await deleteCollection(id)) onback()
}
</script>

<button type="button" class="btn ghost sm" onclick={onback}>← Collections</button>

<QueryView query={detail} rows={3}>
	{#snippet children(c)}
		<div class="head">
			<input
				class="input name"
				aria-label="Collection name"
				maxlength="120"
				value={draft ?? c.name}
				oninput={(e) => (draft = e.currentTarget.value)}
				onblur={() => saveName(c.name)}
				onkeydown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
			/>
			<span class="meta">{countLabel(c.item_count)}</span>
		</div>
		<p class="meta">Anyone with the link can see this collection's name.</p>

		<div class="share">
			<label class="toggle">
				<input
					type="checkbox"
					checked={c.sharing_enabled}
					onchange={(e) => setSharing(id, e.currentTarget.checked)}
				/>
				Sharing {c.sharing_enabled ? 'on' : 'off'}
			</label>
			{#if c.sharing_enabled}
				<button type="button" class="btn sm" onclick={() => copyShareLink(id)}>Copy link</button>
				<button type="button" class="btn ghost sm" onclick={rotate}>Get a new link</button>
				<button type="button" class="btn ghost sm" onclick={() => setSharing(id, false)}>
					Disable link
				</button>
			{/if}
			<button type="button" class="btn ghost sm ml-auto" onclick={() => remove(c.name)}>Delete</button>
		</div>

		<ul class="items">
			{#each c.items as it (it.id)}
				<li>
					<span class="t">{it.listing?.title ?? it.listing_title}</span>
					{#if it.listing}
						<span class="meta">{it.listing.area_name}</span>
						<span class="pr">{price(it.listing.mode === 'rent' ? 'rent' : 'sale', it.listing.price_aed)}</span>
					{:else}
						<span class="meta">No longer available</span>
					{/if}
					<button type="button" class="btn ghost sm" onclick={() => removeItem(id, it.id)}>Remove</button>
				</li>
			{/each}
		</ul>
	{/snippet}
</QueryView>

<style>
	.head { display: flex; align-items: center; gap: 12px; margin: 12px 0 4px; }
	.name { font-size: 18px; font-weight: 600; flex: 1; max-width: 420px; }
	.meta { color: var(--mute, #6b7280); font-size: 12px; }
	.share { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
	.items { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
	.items li { display: flex; align-items: center; gap: 12px; padding: 8px 12px; border: 1px solid var(--line, #e5e7eb); border-radius: 8px; }
	.t { flex: 1; font-weight: 600; }
</style>
