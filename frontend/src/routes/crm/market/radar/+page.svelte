<script lang="ts">
import Star from 'lucide-svelte/icons/star'
import { page } from '$app/state'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Badges from '$lib/crm/market/Badges.svelte'
import {
	LAYERS,
	type LayerId,
	num,
	OTHER_LAYERS,
	screen,
	ZONES,
	type Zone
} from '$lib/crm/market/data'
import Lab from '$lib/crm/market/Lab.svelte'
import { market } from '$lib/crm/market/state.svelte'
import { toast } from '$lib/crm/stores/toast.svelte'

/**
 * Radar map (UI only, schematic). The "Your owners" layer shows counts per zone from the
 * agency's own file only, after upload (DLD Circular 02-2026): no names, no list.
 */
const s = screen('radar')
const z0 = page.url.searchParams.get('zone')
let layer = $state<LayerId>('act')
let zone = $state(ZONES.rows.some((z) => z.key === z0) ? (z0 as string) : 'abs')
/** Demo switch until the owner-file state is read from the CRM. */
let fileUploaded = $state(false)

const L = $derived(LAYERS.find((x) => x.id === layer) ?? LAYERS[0])
const z = $derived(ZONES.rows.find((x) => x.key === zone) ?? ZONES.rows[0])
const locked = $derived(layer === 'own' && !fileUploaded)

function value(x: Zone): number {
	if (layer === 'act') return x.tx?.v ?? 0
	if (layer === 'prj') return x.prj ? x.prj.a + x.prj.d : 0
	return x.own?.v ?? 0
}
function valueText(x: Zone): string {
	if (layer === 'act') return x.tx ? num(x.tx.v) : '—'
	if (layer === 'prj') return x.prj ? `${x.prj.a} / ${x.prj.d}` : '—'
	return fileUploaded ? String(x.own?.v ?? 0) : '—'
}
const max = $derived(Math.max(1, ...ZONES.rows.map(value)))
const circles = $derived(
	ZONES.rows.map((x) => {
		const v = value(x)
		return { x, v, r: v ? 10 + 34 * Math.sqrt(v / max) : 5 }
	})
)
function watch() {
	const key = z.key
	const on = market.toggleWatch(key)
	toast.show(`${on ? 'Watching' : 'Stopped watching'} ${z.name}`, {
		undo: () => market.toggleWatch(key)
	})
}
</script>

<svelte:head><title>Radar map · Market</title></svelte:head>

<PageHeader title={s.label} facts="{num(ZONES.demo.zones)} zones · {num(ZONES.demo.projects)} projects mapped · layer: {L.label} · map drawn schematically">
	{#snippet note()}<Badges status={s.status} tier={s.tier} />{/snippet}
</PageHeader>

{#snippet fig(o: { v: string | number; src: 'demo' | 'ex' } | null)}
	{#if o}{typeof o.v === 'number' ? num(o.v) : o.v} <Lab src={o.src} />{:else}<span class="muted">Not in the example data</span>{/if}
{/snippet}

<div class="mk-root">
	<div class="mk-gradar">
		<section class="card" aria-label="Map">
			<div class="ch">
				<div class="seg" role="group" aria-label="Layer">
					{#each LAYERS as l (l.id)}
						<button type="button" aria-pressed={layer === l.id} onclick={() => (layer = l.id)}>
							{l.label}{#if l.id === 'own'} <span class="mk-tag mk-bad">{l.status}</span>{/if}
						</button>
					{/each}
				</div>
				<span class="mk-row"><Lab src="demo" /><Lab src="ex" /></span>
			</div>
			<div class="cb mk-stack">
				<div class="mk-mapwrap">
					<svg class={['mk-map', layer === 'own' && 'own']} viewBox="0 0 900 460" aria-hidden="true" focusable="false">
						<path class="mk-sea" d={ZONES.sea}></path>
						<path class="mk-coast" d={ZONES.coast}></path>
						<text class="mk-sealbl" x={ZONES.seaLabel.x} y={ZONES.seaLabel.y}>{ZONES.seaLabel.text}</text>
						{#if !locked}
							{#each circles as c (c.x.key)}
								<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
								<g class={['mk-zone', !c.v && 'nil', c.x.key === zone && 'on']} onclick={() => (zone = c.x.key)}>
									<circle cx={c.x.x} cy={c.x.y} r={Math.round(c.r)}></circle>
								</g>
							{/each}
							{#each circles as c (c.x.key)}
								<text class={['mk-zt', !c.v && 'nil', c.x.key === zone && 'on']} x={c.x.x} y={Math.round(c.x.y + c.r + 14)}>{c.x.name}</text>
							{/each}
						{/if}
					</svg>
					{#if locked}
						<div class="mk-mapover">
							<Empty text="Upload your agency's owner file to see this layer. Only owners from your agency's own file are shown, checked against DLD. Vitevue does not provide owner data.">
								<a class="btn ghost sm" href="/crm/owners">Open Owners in CRM</a>
							</Empty>
						</div>
					{/if}
				</div>
				<p class="mk-note">
					{#if layer === 'own'}
						{fileUploaded
							? 'From your owner file, checked against DLD. Contact only owners you hold a documented prior transaction with (DLD Circular 02-2026). Counts per zone only.'
							: "Counts per zone from your agency's own file, after upload. No names, no list."}
					{:else}
						Circle size: {L.measure}. A small dot means the zone has no figure on this layer in the example data.
					{/if}
				</p>
				<label class="check"><input type="checkbox" bind:checked={fileUploaded} /> Owner file uploaded (demo)</label>
			</div>
		</section>

		<section class="card" aria-labelledby="mk-zones">
			<div class="ch"><h2 id="mk-zones">Zones <span class="facts">{L.label}</span></h2></div>
			<div role="group" aria-label="Zones">
				{#each ZONES.rows as x (x.key)}
					<button type="button" class="mk-zbtn" aria-pressed={x.key === zone} onclick={() => (zone = x.key)}>
						<span>{x.name}</span>
						<span class="mk-zv">{valueText(x)}{#if market.watched[x.key]} <Star size={13} fill="currentColor" aria-label="Watched" />{/if}</span>
					</button>
				{/each}
			</div>
			<p class="mk-note mk-pad">{OTHER_LAYERS}</p>
			<h3 class="mk-sec lg">{z.name}</h3>
			<div class="mk-pad">
				<dl class="mk-kv one">
					<dt>Transactions</dt><dd>{@render fig(z.tx)}</dd>
					<dt>Projects, active / done</dt><dd>{#if z.prj}{z.prj.a} / {z.prj.d} <Lab src={z.prj.src} />{:else}<span class="muted">Not in the example data</span>{/if}</dd>
					<dt>AED per sqft</dt><dd>{@render fig(z.psf)}</dd>
					<dt>Rent, AED a year</dt><dd>{@render fig(z.rent)}</dd>
					<dt>Gross yield</dt><dd>{@render fig(z.yld)}</dd>
					<dt>Your owners with an event</dt><dd>{#if fileUploaded}{z.own?.v ?? 0} <Lab src="ex" />{:else}<span class="muted">Upload your owner file</span>{/if}</dd>
				</dl>
				<div class="mk-row" style:margin-top="10px">
					<button type="button" class="btn ghost sm mk-watch" aria-pressed={!!market.watched[z.key]} onclick={watch}>
						<Star size={14} aria-hidden="true" />{market.watched[z.key] ? 'Watching' : 'Watch zone'}
					</button>
					{#if z.key === 'abs'}<a class="btn plain sm" href="/crm/market/analytics">Open in Analytics</a>{/if}
				</div>
			</div>
		</section>
	</div>
</div>
