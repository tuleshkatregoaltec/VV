<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import type { CollectionItemResponse } from '$lib/api/generated/hey-api/types.gen'
import PhotoSlider from '$lib/collections/PhotoSlider.svelte'
import QueryView from '$lib/crm/components/ui/QueryView.svelte'
import { fmt, price, priceShort } from '$lib/crm/format'
import { crmQueries } from '$lib/crm/queries'
import {
	copyShareLink,
	deleteCollection,
	openClientView,
	removeItem,
	renameCollection,
	rotateShareLink,
	setSharing
} from './collectionActions'
import { countLabel, MAX_COLLECTION_ITEMS } from './collectionRules'

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
	await deleteCollection(id, onback)
}

const fill = (n: number) => `${Math.min(100, Math.round((n / MAX_COLLECTION_ITEMS) * 100))}%`
const sqft = (n: number) => `${fmt(n)} sqft`

function summary(items: CollectionItemResponse[]) {
	const live = items.flatMap((it) => (it.listing ? [it.listing] : []))
	if (!live.length) return null
	const prices = live.map((l) => l.price_aed)
	const sizes = live.flatMap((l) => (l.size_sqft ? [l.size_sqft] : []))
	const mode = live.every((l) => l.mode === 'rent') ? 'rent' : 'sale'
	const lo = Math.min(...prices)
	const hi = Math.max(...prices)
	return {
		range: lo === hi ? priceShort(mode, lo) : `${priceShort(mode, lo)} – ${priceShort(mode, hi)}`,
		size: sizes.length ? sqft(sizes.reduce((a, b) => a + b, 0) / sizes.length) : null,
		areas: [...new Set(live.map((l) => l.area_name))].join(', '),
		gone: items.length - live.length
	}
}
</script>

<button type="button" class="btn ghost sm" onclick={onback}>← Collections</button>

<QueryView query={detail} rows={3}>
	{#snippet children(c)}
		{@const s = summary(c.items)}
		<section class="hero">
			<div class="title">
				<input
					class="name"
					aria-label="Collection name"
					maxlength="120"
					value={draft ?? c.name}
					oninput={(e) => (draft = e.currentTarget.value)}
					onblur={() => saveName(c.name)}
					onkeydown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
				/>
				<p class="hint">Anyone with the link can see this collection's name. Click it to rename.</p>

				{#if s}
					<dl class="stats">
						<div><dt>Price range</dt><dd>{s.range}</dd></div>
						{#if s.size}<div><dt>Average size</dt><dd>{s.size}</dd></div>{/if}
						<div><dt>Areas</dt><dd>{s.areas}</dd></div>
						{#if s.gone}<div><dt>Off market</dt><dd class="warn">{s.gone}</dd></div>{/if}
					</dl>
				{/if}

				<div class="cap">
					<span class="bar"><span style:width={fill(c.item_count)}></span></span>
					<span class="count">{countLabel(c.item_count)} properties</span>
				</div>
			</div>

			<div class="share" class:live={c.sharing_enabled}>
				<div class="srow">
					<div>
						<p class="st">
							<span class="dot"></span>
							{c.sharing_enabled ? 'Link is live' : 'Sharing is off'}
						</p>
						<p class="hint">
							{c.sharing_enabled
								? 'Your client sees these properties at one link, always up to date.'
								: 'Turn sharing on to get a link for your client.'}
						</p>
					</div>
					<label class="switch">
						<input
							type="checkbox"
							checked={c.sharing_enabled}
							onchange={(e) => setSharing(id, e.currentTarget.checked)}
						/>
						<span class="track" aria-hidden="true"><span class="knob"></span></span>
						<span class="sr">Sharing {c.sharing_enabled ? 'on' : 'off'}</span>
					</label>
				</div>
				{#if c.sharing_enabled}
					<div class="primary">
						<button type="button" class="btn sm" onclick={() => copyShareLink(id)}>Copy link</button>
						<button type="button" class="btn ghost sm" onclick={() => openClientView(id)}>
							Open client view ↗
						</button>
					</div>
					<div class="secondary">
						<button type="button" class="link" onclick={rotate}>Get a new link</button>
						<span aria-hidden="true">·</span>
						<button type="button" class="link" onclick={() => setSharing(id, false)}>Disable link</button>
					</div>
				{/if}
			</div>
		</section>

		{#if c.items.length}
			<ul class="grid">
				{#each c.items as it (it.id)}
					{@const l = it.listing}
					<li class="prop" class:gone={!l}>
						<div class="ph">
							<PhotoSlider photos={l?.photos ?? []} empty={l ? 'No photo' : 'No longer available'} />
							<button
								type="button"
								class="rm"
								aria-label="Remove"
								title="Remove from collection"
								onclick={() => removeItem(id, it.id)}>✕</button
							>
							{#if l}
								<span class="price">{price(l.mode === 'rent' ? 'rent' : 'sale', l.price_aed)}</span>
							{/if}
						</div>
						<div class="body">
							<p class="t">{l?.title ?? it.listing_title}</p>
							{#if l}
								<p class="loc">{[l.building_name, l.area_name].filter(Boolean).join(' · ')}</p>
								<p class="facts">
									<span>{l.property_type}</span>
									{#if l.bedrooms != null}<span>{l.bedrooms === 0 ? 'Studio' : `${l.bedrooms} bed`}</span>{/if}
									{#if l.size_sqft}<span>{sqft(l.size_sqft)}</span>{/if}
								</p>
							{:else}
								<p class="loc">No longer available — removed from the market.</p>
							{/if}
						</div>
					</li>
				{/each}
			</ul>
		{:else}
			<div class="empty">
				<p class="et">No properties yet</p>
				<p>Open Company listings and use “Add to collection” on any card.</p>
			</div>
		{/if}

		<div class="danger">
			<button type="button" class="btn danger sm" onclick={() => remove(c.name)}>Delete collection</button>
		</div>
	{/snippet}
</QueryView>

<style>
	.hero {
		display: grid; grid-template-columns: minmax(0, 1fr) minmax(300px, 380px); gap: 16px;
		margin: 14px 0 22px;
	}
	@media (max-width: 900px) { .hero { grid-template-columns: 1fr; } }
	.title, .share {
		padding: 20px; border: 1px solid var(--sep); border-radius: 16px; background: var(--card);
		display: grid; gap: 10px; align-content: start;
	}
	.title {
		background:
			radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, var(--accent) 12%, transparent), transparent 60%),
			var(--card);
	}
	.name {
		width: 100%; font-size: 24px; font-weight: 700; letter-spacing: -0.01em; color: var(--text);
		background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 4px 6px; margin: -4px -6px;
	}
	.name:hover { border-color: var(--sep); }
	.name:focus { outline: none; border-color: var(--focus); background: var(--sunk); }
	.hint { margin: 0; color: var(--text3); font-size: 12px; line-height: 1.5; }

	.stats {
		margin: 6px 0 0; display: grid; gap: 10px;
		grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
	}
	.stats div { padding: 10px 12px; border-radius: 12px; background: var(--sunk); }
	.stats dt { color: var(--text3); font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
	.stats dd { margin: 2px 0 0; color: var(--text); font-weight: 650; font-size: 14px; }
	.stats dd.warn { color: var(--amber); }

	.cap { display: flex; align-items: center; gap: 10px; }
	.bar { flex: 1; max-width: 260px; height: 5px; border-radius: 999px; background: var(--sunk); overflow: hidden; }
	.bar span { display: block; height: 100%; background: var(--accent); border-radius: inherit; }
	.count { color: var(--text2); font-size: 12px; font-weight: 600; }

	.share.live { border-color: color-mix(in srgb, var(--green) 45%, var(--sep)); }
	.srow { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
	.st { margin: 0 0 2px; display: flex; align-items: center; gap: 8px; font-weight: 650; color: var(--text); }
	.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text3); flex: none; }
	.live .dot { background: var(--green); box-shadow: 0 0 0 3px var(--green-bg); }
	.primary { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 4px; }
	.secondary { display: flex; align-items: center; gap: 8px; color: var(--text3); font-size: 12px; }
	.link {
		border: 0; background: none; padding: 0; color: var(--text2); font-size: 12px; cursor: pointer;
		text-decoration: underline; text-underline-offset: 3px; text-decoration-color: var(--sep-strong);
	}
	.link:hover { color: var(--text); }

	.switch { position: relative; display: inline-flex; cursor: pointer; flex: none; }
	.switch input { position: absolute; inset: 0; opacity: 0; margin: 0; cursor: pointer; }
	.track {
		width: 40px; height: 22px; border-radius: 999px; background: var(--sep-strong); padding: 2px;
		transition: background 0.15s; display: flex;
	}
	.knob { width: 18px; height: 18px; border-radius: 50%; background: #fff; transition: transform 0.15s; }
	.switch input:checked + .track { background: var(--green); }
	.switch input:checked + .track .knob { transform: translateX(18px); }
	.switch input:focus-visible + .track { outline: 2px solid var(--focus); outline-offset: 2px; }
	.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }

	.grid {
		list-style: none; margin: 0; padding: 0; display: grid; gap: 16px;
		grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
	}
	.prop {
		display: flex; flex-direction: column; overflow: hidden;
		border: 1px solid var(--sep); border-radius: 16px; background: var(--card); box-shadow: var(--shadow);
		transition: transform 0.15s, border-color 0.15s;
	}
	.prop:hover { transform: translateY(-2px); border-color: var(--sep-strong); }
	.prop.gone { border-style: dashed; opacity: 0.7; }
	.ph { position: relative; aspect-ratio: 4 / 3; background: var(--sunk); overflow: hidden; }
		.ph::after {
		content: ''; position: absolute; inset: 55% 0 0; pointer-events: none; z-index: 1;
		background: linear-gradient(transparent, rgba(5, 10, 18, 0.55));
	}
	.rm, .price { position: absolute; z-index: 3; }
	.rm {
		right: 10px; top: 10px; width: 30px; height: 30px; border-radius: 50%; border: 0; cursor: pointer;
		display: grid; place-items: center; font-size: 13px;
		background: rgba(5, 10, 18, 0.6); color: #fff; backdrop-filter: blur(4px);
		opacity: 0.85; transition: opacity 0.15s, background 0.15s;
	}
	.rm:hover, .rm:focus-visible { opacity: 1; background: var(--red); }
	.price {
		left: 12px; bottom: 12px; color: #fff; font-weight: 750; font-size: 18px; letter-spacing: -0.01em;
		text-shadow: 0 1px 8px rgba(0, 0, 0, 0.45);
	}
	.body { padding: 14px 16px 16px; display: grid; gap: 6px; align-content: start; flex: 1; }
	.t {
		margin: 0; font-weight: 650; color: var(--text); line-height: 1.35; min-height: 2.7em;
		display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
	}
	.loc { margin: 0; color: var(--text2); font-size: 13px; }
	.facts { margin: 4px 0 0; display: flex; flex-wrap: wrap; gap: 6px; }
	.facts span {
		padding: 3px 9px; border-radius: 999px; background: var(--sunk); color: var(--text2); font-size: 12px;
	}

	.empty {
		display: grid; justify-items: center; gap: 4px; padding: 40px 16px; text-align: center;
		border: 1px dashed var(--sep-strong); border-radius: 16px; color: var(--text2); font-size: 13px;
	}
	.empty p { margin: 0; }
	.empty .et { color: var(--text); font-weight: 650; font-size: 15px; }
	.danger { display: flex; justify-content: flex-end; margin-top: 24px; }
</style>
