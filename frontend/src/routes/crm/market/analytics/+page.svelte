<script lang="ts">
import Star from 'lucide-svelte/icons/star'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Seg from '$lib/crm/components/ui/Seg.svelte'
import Badges from '$lib/crm/market/Badges.svelte'
import { LEVELS, type LevelId, num, QUARTERS, screen } from '$lib/crm/market/data'
import Lab from '$lib/crm/market/Lab.svelte'
import { market } from '$lib/crm/market/state.svelte'
import { toast } from '$lib/crm/stores/toast.svelte'

/** Analytics (UI only): one level's figures, an optional comparison and 8 quarters of AED/sqft. */
const s = screen('an')
let level = $state<LevelId>('area')
let compare = $state<LevelId | null>(null)
let cmpOpen = $state(false)

const cur = $derived(LEVELS.find((l) => l.id === level) ?? LEVELS[0])
const cmp = $derived(compare ? LEVELS.find((l) => l.id === compare) : undefined)
const watching = $derived(!!market.watched.abs)

function series(psf: number, id: LevelId) {
	const f = psf / QUARTERS.base
	return QUARTERS.area.map((v) => (id === 'area' ? v : Math.round((v * f) / 10) * 10))
}
const sets = $derived([
	{ name: cur.level, vals: series(cur.psf, cur.id), sel: true },
	...(cmp ? [{ name: cmp.level, vals: series(cmp.psf, cmp.id), sel: false }] : [])
])
const max = $derived(Math.max(...sets.flatMap((x) => x.vals)) * 1.08)
const signed = (n: number) => `${n > 0 ? '+' : n < 0 ? '−' : ''}${num(Math.abs(n))}`
const signed1 = (n: number) =>
	`${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(Math.round(n * 10) / 10).toFixed(1)}`

function pickLevel(id: LevelId) {
	level = id
	if (compare === id) compare = null
}
function watch() {
	const on = market.toggleWatch('abs')
	toast.show(`${on ? 'Watching' : 'Stopped watching'} Al Barsha South 4`, {
		undo: () => market.toggleWatch('abs')
	})
}
</script>

<svelte:head><title>Analytics · Market</title></svelte:head>

<PageHeader title={s.label} facts="{cur.name} · {cur.level} · {num(cur.tx)} transactions in 12 months">
	{#snippet note()}<Badges status={s.status} tier={s.tier} />{/snippet}
	{#snippet right()}
		<button type="button" class="btn ghost mk-watch" aria-pressed={watching} onclick={watch}>
			<Star size={15} aria-hidden="true" />{watching ? 'Watching' : 'Watch zone'}
		</button>
	{/snippet}
</PageHeader>

{#snippet statsCard(L: (typeof LEVELS)[number])}
	<section class="card">
		<div class="ch"><h2>{L.name} <span class="facts">{L.level}</span></h2><Lab src={L.src} /></div>
		<div class="cb">
			<div class="mk-stats">
				<div class="mk-stat"><span>Sale, AED per sqft</span><b>{num(L.psf)}</b></div>
				<div class="mk-stat"><span>Rent, AED a year</span><b>{num(L.rent)}</b></div>
				<div class="mk-stat"><span>Gross yield</span><b>{L.yld.toFixed(1)}%</b></div>
				<div class="mk-stat"><span>Transactions, 12 months</span><b>{num(L.tx)}</b></div>
			</div>
		</div>
	</section>
{/snippet}

<div class="mk-root">
	<div class="mk-fbar">
		<Seg label="Level" items={LEVELS.map((l) => ({ id: l.id, label: l.level }))} value={level} onselect={pickLevel} />
		<span class="mk-pick">
			<button type="button" class="btn ghost" aria-haspopup="menu" aria-expanded={cmpOpen} onclick={() => (cmpOpen = !cmpOpen)}>
				Compare: {cmp ? cmp.level : 'None'} ▾
			</button>
			{#if cmpOpen}
				<div class="mk-menu left" role="menu" aria-label="Compare with">
					<button type="button" class="mk-mi" role="menuitemradio" aria-checked={!compare} onclick={() => ((compare = null), (cmpOpen = false))}>None</button>
					{#each LEVELS.filter((l) => l.id !== level) as l (l.id)}
						<button type="button" class="mk-mi" role="menuitemradio" aria-checked={compare === l.id} onclick={() => ((compare = l.id), (cmpOpen = false))}>{l.level}</button>
					{/each}
				</div>
			{/if}
		</span>
		<span class="count">Al Barsha South 4 and the levels inside it</span>
	</div>

	{#if cmp}
		<div class="mk-gcmp">{@render statsCard(cur)}{@render statsCard(cmp)}</div>
		<section class="card">
			<div class="ch"><h2>Difference</h2><Lab src="ex" /></div>
			<div class="cb">
				<b>{cmp.level} vs {cur.level}:</b>
				{signed(cmp.psf - cur.psf)} AED per sqft ({signed1(((cmp.psf - cur.psf) / cur.psf) * 100)}%) ·
				{signed(cmp.rent - cur.rent)} rent · {signed1(cmp.yld - cur.yld)} points yield · {signed(cmp.tx - cur.tx)} transactions
			</div>
		</section>
	{:else}
		{@render statsCard(cur)}
	{/if}

	<section class="card">
		<div class="ch">
			<h2>{QUARTERS.title}</h2>
			<span class="mk-row">
				<Lab src="ex" />
				<button type="button" class="btn ghost sm" onclick={() => toast.show('Saved as an image (example)')}>PNG</button>
				<button type="button" class="btn ghost sm" onclick={() => toast.show('Saved as a CSV (example)')}>CSV</button>
			</span>
		</div>
		<div class="cb">
			<div class="mk-bars" role="img" aria-label="{QUARTERS.title}. {QUARTERS.labels.map((q, i) => `${q}: ${sets.map((x) => num(x.vals[i])).join(' and ')}`).join(', ')}">
				{#each QUARTERS.labels as q, i (q)}
					<div class="mk-bcol">
						<div class="mk-bstack">
							{#each sets as x (x.name)}<i class={['mk-b', x.sel && 'sel']} style:height="{(x.vals[i] / max) * 100}%"></i>{/each}
						</div>
						<span class="mk-bv">{sets.map((x) => num(x.vals[i])).join(' · ')}</span>
						<span class="mk-bq">{q}</span>
					</div>
				{/each}
			</div>
			{#if sets.length > 1}
				<div class="mk-legend">
					{#each sets as x (x.name)}<span><i class={['mk-sw', x.sel && 'sel']}></i>{x.name}</span>{/each}
				</div>
			{/if}
			<p class="mk-note" style:margin-top="8px">Each bar is one quarter. Levels other than the area are the area series scaled to their own price.</p>
		</div>
	</section>
</div>
