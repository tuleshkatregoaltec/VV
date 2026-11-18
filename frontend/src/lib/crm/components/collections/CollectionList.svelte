<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import QueryView from '$lib/crm/components/ui/QueryView.svelte'
import { plural, shortDate } from '$lib/crm/format'
import { crmQueries } from '$lib/crm/queries'
import { createCollection } from './collectionActions'
import { MAX_COLLECTION_ITEMS as MAX_ITEMS } from './collectionRules'

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

// Property Finder sometimes stops serving a photo: on error, try the next property's photo.
let skipped = $state<Record<string, number>>({})
const skip = (id: string) => (skipped = { ...skipped, [id]: (skipped[id] ?? 0) + 1 })

const fill = (n: number) => `${Math.min(100, Math.round((n / MAX_ITEMS) * 100))}%`
</script>

<section class="intro">
	<div>
		<h2>Collections</h2>
		<p>Share a live shortlist with a client. One link, always showing your latest picks.</p>
	</div>
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
</section>

<QueryView query={list} rows={3}>
	{#snippet children(data)}
		{#if data.items.length}
			<ul class="grid">
				{#each data.items as c (c.id)}
					{@const cover = (c.cover_photos ?? [])[skipped[c.id] ?? 0]}
					<li>
						<button type="button" class="card" onclick={() => onopen(c.id)}>
							<span class="cover">
								{#if cover}
									<img
										src={cover}
										alt=""
										loading="lazy"
										referrerpolicy="no-referrer"
										onerror={() => skip(c.id)}
									/>
								{:else}
									<span class="badge" aria-hidden="true">{c.name.trim().charAt(0).toUpperCase()}</span>
								{/if}
							</span>
							<span class="head">
								<span class="nm">{c.name}</span>
								{#if c.sharing_enabled}
									<span class="pill live"><span class="dot"></span>Link live</span>
								{:else}
									<span class="pill">Private</span>
								{/if}
							</span>
							<span class="bar"><span style:width={fill(c.item_count)}></span></span>
							<span class="foot">
								<span>{plural(c.item_count, 'property', 'properties')}</span>
								<span>Updated {shortDate(c.updated_at.slice(0, 10))}</span>
							</span>
						</button>
					</li>
				{/each}
			</ul>
		{:else}
			<div class="empty">
				<span class="badge big" aria-hidden="true">＋</span>
				<p>No collections yet — add properties from Company listings.</p>
			</div>
		{/if}
	{/snippet}
</QueryView>

<style>
	.intro {
		display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; flex-wrap: wrap;
		margin: 16px 0 20px;
	}
	.intro h2 { margin: 0; font-size: 18px; font-weight: 650; color: var(--text); }
	.intro p { margin: 4px 0 0; color: var(--text2); font-size: 13px; }
	.newc { display: flex; gap: 8px; width: min(420px, 100%); }
	.newc .input { flex: 1; }

	.grid {
		list-style: none; margin: 0; padding: 0;
		display: grid; gap: 14px; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
	}
	.card {
		display: flex; flex-direction: column; gap: 12px; width: 100%; height: 100%; text-align: left;
		padding: 0 0 16px; overflow: hidden; border: 1px solid var(--sep); border-radius: 14px; background: var(--card);
		color: var(--text); cursor: pointer; box-shadow: var(--shadow);
		transition: border-color 0.15s, transform 0.15s;
	}
	.card:hover { border-color: var(--sep-strong); transform: translateY(-1px); }
	.card:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
	.card > :not(.cover) { margin: 0 16px; }
	.cover {
		display: grid; place-items: center; height: 140px; overflow: hidden;
		background:
			radial-gradient(120% 120% at 0% 0%, color-mix(in srgb, var(--accent) 22%, transparent), transparent 70%),
			var(--sunk);
	}
	.cover img { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform 0.3s; }
	.card:hover .cover img { transform: scale(1.03); }
	.cover .badge { width: 48px; height: 48px; font-size: 20px; }
	.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
	.head .pill { flex: none; margin-top: 1px; }
	.badge {
		display: grid; place-items: center; width: 36px; height: 36px; border-radius: 10px;
		background: var(--blue-bg); color: var(--blue); font-weight: 700; font-size: 15px;
	}
	.badge.big { width: 48px; height: 48px; font-size: 22px; }
	.pill {
		display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px;
		font-size: 12px; font-weight: 600; background: var(--grey-bg); color: var(--text2);
	}
	.pill.live { background: var(--green-bg); color: var(--green); }
	.dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
	.nm {
		font-size: 15px; font-weight: 650; line-height: 1.35;
		display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
	}
	.bar { height: 4px; border-radius: 999px; background: var(--sunk); overflow: hidden; }
	.bar span { display: block; height: 100%; background: var(--accent); border-radius: inherit; }
	.foot { display: flex; justify-content: space-between; color: var(--text3); font-size: 12px; }

	.empty {
		display: grid; justify-items: center; gap: 6px; padding: 48px 16px; text-align: center;
		border: 1px dashed var(--sep-strong); border-radius: 14px; color: var(--text2); font-size: 13px;
	}
	.empty p { margin: 0; }
</style>
