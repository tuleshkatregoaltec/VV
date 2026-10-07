<script lang="ts">
import Check from 'lucide-svelte/icons/check'
import Search from 'lucide-svelte/icons/search'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Seg from '$lib/crm/components/ui/Seg.svelte'
import Badges from '$lib/crm/market/Badges.svelte'
import { LISTINGS, type MarketListing, num, screen } from '$lib/crm/market/data'
import Lab from '$lib/crm/market/Lab.svelte'
import LeadPicker from '$lib/crm/market/LeadPicker.svelte'
import { market } from '$lib/crm/market/state.svelte'
import { toast } from '$lib/crm/stores/toast.svelte'

/** Listings (UI only): a client's brief searched in the desk's listings, then the portals. */
const s = screen('ls')
type Brief = {
	client: 'buyer' | 'tenant'
	building: string
	beds: string
	sqft: string
	budget: string
	timeline: string
}
const fresh = (): Brief => ({
	client: 'buyer',
	building: 'Burj Vista 1',
	beds: '2',
	sqft: '1,300',
	budget: '3,700,000',
	timeline: '60 days'
})
let brief = $state<Brief>(fresh())
let applied = $state<Brief>(fresh())

const digits = (v: string) => Number(v.replace(/[^0-9]/g, '')) || 0
const family = (v: string) =>
	v
		.toLowerCase()
		.replace(/\s*\d+\s*$/, '')
		.trim()

const results = $derived.by(() => {
	const b = applied
	if (b.client === 'tenant') return []
	const fam = family(b.building)
	const beds = Number(b.beds)
	const sqft = digits(b.sqft)
	const budget = digits(b.budget)
	return LISTINGS.rows.filter(
		(r) =>
			(!fam || family(r.building) === fam) &&
			(beds >= 4 ? r.bed >= 4 : r.bed === beds) &&
			(!sqft || Math.abs(r.sqft - sqft) <= sqft * 0.1) &&
			(!budget || r.price <= budget)
	)
})
const desk = $derived(results.filter((r) => r.desk))
const portal = $derived(results.filter((r) => !r.desk))
const shortCount = $derived(LISTINGS.rows.filter((r) => market.shortlist[r.key]).length)

function evidence(r: MarketListing) {
	const psf = Math.round(r.price / r.sqft)
	const under = ((LISTINGS.evidence.psf - psf) / LISTINGS.evidence.psf) * 100
	return { psf, under, flag: under >= LISTINGS.flagAt }
}
function toggle(r: MarketListing) {
	const on = market.toggleShortlist(r.key)
	toast.show(`${on ? 'Added to' : 'Removed from'} the shortlist · ${r.building} · ${r.unit}`, {
		undo: () => market.toggleShortlist(r.key)
	})
}
function search(e: SubmitEvent) {
	e.preventDefault()
	applied = { ...brief }
}
</script>

<svelte:head><title>Listings · Market</title></svelte:head>

<PageHeader
	title={s.label}
	facts="{applied.client === 'buyer' ? 'Buyer' : 'Tenant'} · {applied.building || 'any building'} · {applied.beds} bed · {applied.budget ? `AED ${applied.budget}` : 'any budget'} · {desk.length} desk, {portal.length} portal listings"
>
	{#snippet note()}<Badges status={s.status} tier={s.tier} />{/snippet}
	{#snippet right()}<LeadPicker kind="Shortlist" label="{shortCount} listings" disabled={!shortCount} />{/snippet}
</PageHeader>

{#snippet group(title: string, rows: MarketListing[], cls: string, none: string)}
	<tr class="mk-grp"><td colspan="7">{title}</td></tr>
	{#each rows as r (r.key)}
		{@const ev = evidence(r)}
		<tr class={cls}>
			<td><div class="nm nowrap">{r.building} · {r.unit}</div><div class="sub">{r.where}</div></td>
			<td class="r">{r.bed}</td>
			<td class="r">{num(r.sqft)}</td>
			<td class="r">{num(r.price)}</td>
			<td class="r">{num(ev.psf)}</td>
			<td>{#if ev.flag}<span class="chip amber">{Math.round(ev.under)}% under the evidence</span>{:else}<span class="chip">In line</span>{/if}</td>
			<td>
				<button type="button" class="btn ghost sm" aria-pressed={!!market.shortlist[r.key]} onclick={() => toggle(r)}>
					{#if market.shortlist[r.key]}<Check size={14} aria-hidden="true" />On the shortlist{:else}Shortlist{/if}
				</button>
			</td>
		</tr>
	{:else}
		<tr><td colspan="7" class="muted">{none}</td></tr>
	{/each}
{/snippet}

<div class="mk-root">
	<div class="mk-gside">
		<form class="card" onsubmit={search} autocomplete="off">
			<div class="ch"><h2>Brief</h2><Lab src="ex" /></div>
			<div class="cb mk-brief">
				<div class="fld mk-full">
					<span class="lbl">Client</span>
					<Seg label="Client" items={[{ id: 'buyer', label: 'Buyer' }, { id: 'tenant', label: 'Tenant' }]} value={brief.client} onselect={(v) => (brief.client = v)} />
				</div>
				<label class="fld mk-full"><span class="lbl">Building</span><input bind:value={brief.building} /></label>
				<div class="fld mk-full">
					<span class="lbl">Bedrooms</span>
					<Seg label="Bedrooms" items={[{ id: '0', label: 'Studio' }, { id: '1', label: '1' }, { id: '2', label: '2' }, { id: '3', label: '3' }, { id: '4', label: '4+' }]} value={brief.beds} onselect={(v) => (brief.beds = v)} />
				</div>
				<label class="fld"><span class="lbl">Size, sqft</span><input inputmode="numeric" bind:value={brief.sqft} /></label>
				<label class="fld"><span class="lbl">Budget, AED</span><input inputmode="numeric" bind:value={brief.budget} /></label>
				<label class="fld mk-full"><span class="lbl">Timeline</span><input bind:value={brief.timeline} /></label>
				<div class="mk-full"><button type="submit" class="btn"><Search size={15} aria-hidden="true" />Search</button></div>
			</div>
		</form>

		<section class="card" aria-labelledby="mk-res">
			<div class="ch"><h2 id="mk-res">Results <span class="facts">Shortlist · {shortCount}</span></h2><Lab src="ex" /></div>
			{#if results.length}
				<div class="tblwrap">
					<table class="tbl">
						<thead>
							<tr><th>Listing</th><th class="r">Bed</th><th class="r">Sqft</th><th class="r">Price AED</th><th class="r">AED per sqft</th><th>Against the evidence</th><th><span class="sr-only">Shortlist</span></th></tr>
						</thead>
						<tbody>
							{@render group('Your desk', desk, 'desk', 'No desk listings match this brief.')}
							{@render group('Portals', portal, 'portal', 'No portal listings match this brief.')}
						</tbody>
					</table>
				</div>
				<p class="mk-note mk-pad">
					Evidence: {LISTINGS.evidence.building} median AED {num(LISTINGS.evidence.psf)} per sqft, {LISTINGS.evidence.period} · Example. Flagged at {LISTINGS.flagAt}% or more under it. Unit numbers here are the lister's, not DLD's.
				</p>
			{:else}
				<Empty text={applied.client === 'tenant' ? 'Example data has sale listings only.' : 'No listings match this brief. Widen the size or the budget.'}>
					<button type="button" class="btn ghost sm" onclick={() => ((brief = fresh()), (applied = fresh()))}>Reset brief</button>
				</Empty>
			{/if}
		</section>
	</div>
</div>
