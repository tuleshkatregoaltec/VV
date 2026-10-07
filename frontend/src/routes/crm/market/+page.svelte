<script lang="ts">
import Empty from '$lib/crm/components/ui/Empty.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Badges from '$lib/crm/market/Badges.svelte'
import { AS_OF, fDay, HOME, MARKET_SCREENS, screen, TOOL_LINES, ZONES } from '$lib/crm/market/data'
import Lab from '$lib/crm/market/Lab.svelte'
import { market } from '$lib/crm/market/state.svelte'
import { toast } from '$lib/crm/stores/toast.svelte'

/** Market home (UI only, example data): counters, the tools and the agent's own Market work. */
const s = screen('home')
const watched = $derived(ZONES.rows.filter((z) => market.watched[z.key]))

function unwatch(key: string, name: string) {
	market.toggleWatch(key)
	toast.show(`Stopped watching ${name}`, { undo: () => market.toggleWatch(key) })
}
function unsave(id: number) {
	const item = market.saved.find((x) => x.id === id)
	if (!item) return
	market.unsave(id)
	toast.show(`Removed from ${item.lead} · ${item.kind}, ${item.label}`, {
		undo: () => (market.saved = [...market.saved, item])
	})
}
</script>

<svelte:head><title>Market · CRM</title></svelte:head>

<PageHeader
	title={s.label}
	facts="{fDay(AS_OF)} · {watched.length} zones watched · {market.saved.length} saved to leads"
>
	{#snippet note()}<Badges status={s.status} tier={s.tier} />{/snippet}
</PageHeader>

<div class="mk-root">
	<div class="grid-4 kpis">
		{#each HOME.counters as c (c.k)}
			<a class="kpi" href={c.href}>
				<span class="lbl">{c.k}</span>
				<span class={['v', c.small && 'sm']}>{c.v}</span>
				<span class="n">{c.n}</span>
				<Lab src={c.src} />
			</a>
		{/each}
	</div>

	<div class="mk-g2">
		<section class="card" aria-labelledby="mk-tools">
			<div class="ch"><h2 id="mk-tools">Tools <span class="facts">{MARKET_SCREENS.length - 1} tools</span></h2></div>
			<div class="list">
				{#each MARKET_SCREENS.slice(1) as t (t.id)}
					<a class="mk-tool" href={t.path}>
						<span class="mk-tool-t"><b>{t.label}</b><span>{TOOL_LINES[t.id]}</span></span>
						<Badges status={t.status} tier={t.tier} />
					</a>
				{/each}
			</div>
		</section>

		<section class="card" aria-labelledby="mk-work">
			<div class="ch"><h2 id="mk-work">Your work</h2></div>
			<h3 class="mk-sec">Your areas <Lab src="ex" /></h3>
			<div class="list">
				{#each HOME.areas as a (a.name)}
					<a class="li" href="/crm/market/radar?zone={a.zone}">
						<span></span>
						<span>
							<div class="t">{a.name}</div>
							<div class="d">AED {a.psf} per sqft · rent AED {a.rent} a year · {a.yld} gross · {a.note}</div>
						</span>
						<span></span>
					</a>
				{/each}
			</div>
			<h3 class="mk-sec">Watched zones <span class="muted">{watched.length}</span></h3>
			<div class="list">
				{#each watched as z (z.key)}
					<div class="li">
						<span></span>
						<span>
							<div class="t">{z.name}</div>
							<div class="d">{z.tx ? `${z.tx.v.toLocaleString('en-US')} transactions, 12 months` : 'Not in the example data'}</div>
						</span>
						<button type="button" class="btn ghost sm" onclick={() => unwatch(z.key, z.name)}>Unwatch</button>
					</div>
				{:else}
					<Empty text="No zones watched. Watch a zone on the radar map.">
						<a class="btn ghost sm" href="/crm/market/radar">Open Radar map</a>
					</Empty>
				{/each}
			</div>
			<h3 class="mk-sec">Saved to leads <span class="muted">{market.saved.length}</span></h3>
			<div class="list">
				{#each [...market.saved].reverse() as v (v.id)}
					<div class="li">
						<span></span>
						<span><div class="t">{v.kind} · {v.label}</div><div class="d">{v.lead} · {v.at}</div></span>
						<button type="button" class="btn ghost sm" onclick={() => unsave(v.id)}>Remove</button>
					</div>
				{:else}
					<Empty text="Nothing saved to a lead. Save a unit report, a shortlist, a project or a plot to a lead." />
				{/each}
			</div>
		</section>
	</div>
</div>
