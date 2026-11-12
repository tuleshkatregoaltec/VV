<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import QueryView from '$lib/crm/components/ui/QueryView.svelte'
import { fmt, plural, shortDate } from '$lib/crm/format'
import { crmQueries } from '$lib/crm/queries'
import { createCollection } from './collectionActions'

let { onopen }: { onopen: (id: string) => void } = $props()

const list = createQuery(() => crmQueries.collections())
let name = $state('')
let creating = $state(false)

async function create() {
	const value = name.trim()
	if (!value || creating) return
	creating = true
	const made = await createCollection(value)
	creating = false
	if (made) {
		name = ''
		onopen(made.id)
	}
}
</script>

<form
	class="newc"
	onsubmit={(e) => {
		e.preventDefault()
		void create()
	}}
>
	<input
		class="input"
		aria-label="New collection name"
		placeholder="New collection name"
		maxlength="120"
		bind:value={name}
	/>
	<button type="submit" class="btn sm" disabled={!name.trim() || creating}>Create</button>
</form>

<QueryView query={list} rows={3}>
	{#snippet children(data)}
		{#if data.items.length}
			<ul class="rows">
				{#each data.items as c (c.id)}
					<li>
						<button type="button" class="row" onclick={() => onopen(c.id)}>
							<span class="nm">{c.name}</span>
							<span class="meta">{plural(c.item_count, 'property', 'properties')}</span>
							{#if c.sharing_enabled}<span class="chip green">Shared</span>{/if}
							<span class="meta">Updated {shortDate(c.updated_at.slice(0, 10))}</span>
						</button>
					</li>
				{/each}
			</ul>
			<p class="meta">{fmt(data.total)} in total</p>
		{:else}
			<Empty text="No collections yet — add properties from Company listings." />
		{/if}
	{/snippet}
</QueryView>

<style>
	.newc { display: flex; gap: 8px; margin: 12px 0; max-width: 420px; }
	.newc .input { flex: 1; }
	.rows { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
	.row {
		display: flex; align-items: center; gap: 12px; width: 100%; text-align: left;
		padding: 10px 12px; border: 1px solid var(--line, #e5e7eb); border-radius: 8px; background: none;
		cursor: pointer;
	}
	.nm { font-weight: 600; flex: 1; }
	.meta { color: var(--mute, #6b7280); font-size: 12px; }
</style>
