<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { crm } from '$lib/crm/api'
import type { ListingStatus } from '$lib/crm/api/types'
import Chip from '$lib/crm/components/ui/Chip.svelte'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import QueryView from '$lib/crm/components/ui/QueryView.svelte'
import Seg from '$lib/crm/components/ui/Seg.svelte'
import Tabs from '$lib/crm/components/ui/Tabs.svelte'
import { fmt, price, priceShort, short } from '$lib/crm/format'
import { crmQueries } from '$lib/crm/queries'
import { openListing, panel } from '$lib/crm/stores/panel.svelte'
import { type AssetTab, ui } from '$lib/crm/stores/ui.svelte'
import { write } from '$lib/crm/write'

const me = createQuery(() => crmQueries.me())
const mineAll = createQuery(() => crmQueries.listings('mine'))
const renewals = createQuery(() => crmQueries.renewals())
const scope = $derived(ui.assetTab === 'company' ? 'company' : 'mine')
const listings = createQuery(() => ({
	...crmQueries.listings(scope, ui.assetStatus),
	enabled: ui.assetTab === 'mine' || ui.assetTab === 'company'
}))
const portfolio = createQuery(() => ({
	...crmQueries.portfolio(),
	enabled: ui.assetTab === 'portfolio'
}))
const market = createQuery(() => ({ ...crmQueries.market(), enabled: ui.assetTab === 'market' }))

const facts = $derived.by(() => {
	const c = mineAll.data?.counts
	if (!c) return ''
	return `${c.live} live · ${c.pocket} pocket · ${c.expired} expired · ${renewals.data?.length ?? 0} renewals`
})

const TABS: { id: AssetTab; label: string }[] = [
	{ id: 'mine', label: 'My listings' },
	{ id: 'company', label: 'Company listings' },
	{ id: 'portfolio', label: 'Portfolio' },
	{ id: 'renewals', label: 'Renewals' },
	{ id: 'market', label: 'Market' }
]

const statusItems = $derived.by(() => {
	const c = listings.data?.counts
	const n = (s: ListingStatus) => (c ? ` · ${c[s]}` : '')
	const items: { id: ListingStatus; label: string }[] = [
		{ id: 'live', label: `Live${n('live')}` },
		{ id: 'pocket', label: `${scope === 'company' ? 'Company pocket' : 'Pocket'}${n('pocket')}` }
	]
	if (scope === 'mine') items.push({ id: 'expired', label: `Expired${n('expired')}` })
	return items
})

function selectTab(t: AssetTab) {
	ui.assetTab = t
	if (t === 'company' && ui.assetStatus === 'expired') ui.assetStatus = 'live'
}

function startRenewal(id: number, unit: string) {
	write({
		call: () => crm.renewals.start(id),
		success: `Renewal started — ${unit} · rent deal opened`
	})
}

const statusLabel = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
</script>

<svelte:head><title>Assets · CRM Beta</title></svelte:head>

<PageHeader title="Assets" {facts} />

<Tabs label="Assets" items={TABS} value={ui.assetTab} onselect={selectTab} />

{#if ui.assetTab === 'mine' || ui.assetTab === 'company'}
	<div class="card">
		<div class="filters">
			<Seg label="Status" items={statusItems} value={ui.assetStatus} onselect={(s) => (ui.assetStatus = s)} />
			{#if scope === 'mine'}
				<button type="button" class="btn sm ml-auto" onclick={() => panel.open({ kind: 'new-listing' })}>
					＋ Listing
				</button>
			{/if}
		</div>
		<QueryView query={listings} rows={4}>
			{#snippet children(data)}
				{#if data.items.length}
					<div class="lcards">
						{#each data.items as x (x.id)}
							<button type="button" class="lcard" onclick={() => openListing(x.id)}>
								<div class="img">
									<span class="chip">{x.deal_type === 'sale' ? 'Sale' : 'Rent'}</span>
									<span class="chip">{statusLabel(x.status)}</span>
								</div>
								<div class="body">
									<span class="pr">{priceShort(x.deal_type, x.price_aed)}</span>
									<span class="t">{x.unit}</span>
									<span class="d">
										{x.area} · {x.bedrooms ? `${x.bedrooms} bed` : 'Studio'} · {fmt(x.size_sqft)} sqft{scope ===
										'company'
											? ` · ${x.agent}`
											: ''}
									</span>
									<div class="foot">
										<Chip chip={x.permit_chip} />
										{#if x.status === 'live'}<Chip>{x.days_live} days · {x.enquiries} leads</Chip>{/if}
										<Chip chip={x.form_a_chip} />
									</div>
								</div>
							</button>
						{/each}
					</div>
				{:else}
					<Empty text="No {ui.assetStatus} listings{scope === 'company' ? ' from colleagues' : ''}.">
						{#if scope === 'mine'}
							<button type="button" class="btn ghost sm" onclick={() => panel.open({ kind: 'new-listing' })}>
								＋ Listing
							</button>
						{/if}
					</Empty>
				{/if}
			{/snippet}
		</QueryView>
	</div>
{:else if ui.assetTab === 'portfolio'}
	<QueryView query={portfolio} rows={5}>
		{#snippet children(p)}
			<div class="grid-3">
				<div class="kpi">
					<span class="lbl">Sales handled</span><span class="v">{p.totals.sales}</span>
					<span class="n">{short(p.totals.sales_value_aed)} in value</span>
				</div>
				<div class="kpi">
					<span class="lbl">Lets handled</span><span class="v">{p.totals.lets}</span>
					<span class="n">{fmt(p.totals.lets_value_aed)} a year in rent</span>
				</div>
				<div class="kpi green">
					<span class="lbl">Commission earned</span><span class="v">{short(p.totals.commission_aed)}</span>
					<span class="n">{p.totals.clients} clients</span>
				</div>
			</div>
			<div class="card">
				<div class="tblwrap">
					<table class="tbl">
						<thead>
							<tr><th>Client</th><th>What</th><th>Unit</th><th class="r">Value</th><th>Date</th><th>DLD / Ejari</th><th class="r">Commission</th></tr>
						</thead>
						<tbody>
							{#each p.clients as c (c.client)}
								{#each c.transactions as t, i (i)}
									<tr class="row">
										<td>
											<button type="button" class="rowlink" onclick={() => panel.open({ kind: 'client', client: c.client })}>
												{c.client}
											</button>
										</td>
										<td data-label="What">{t.what}</td>
										<td data-label="Unit">{t.unit}</td>
										<td class="r num" data-label="Value">{t.kind === 'rent' ? `${fmt(t.value_aed)}/yr` : short(t.value_aed)}</td>
										<td class="sub" data-label="Date">{t.date}</td>
										<td class="mono small" data-label="DLD / Ejari">{t.dld_or_ejari}</td>
										<td class="r num" data-label="Commission">{fmt(t.commission_aed)}</td>
									</tr>
								{/each}
							{:else}
								<tr><td colspan="7"><Empty text="No closed deals yet. They land here once transferred." /></td></tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/snippet}
	</QueryView>
{:else if ui.assetTab === 'renewals'}
	<div class="card">
		<QueryView query={renewals} rows={3}>
			{#snippet children(list)}
				<div class="tblwrap">
					<table class="tbl">
						<thead>
							<tr><th>Unit</th><th>Tenant / landlord</th><th class="r">Rent now</th><th class="r">Building median</th><th>Ends</th><th></th></tr>
						</thead>
						<tbody>
							{#each list as r (r.id)}
								<tr class="row">
									<td>
										<button type="button" class="rowlink" onclick={() => panel.open({ kind: 'renewal', id: r.id })}>
											{r.unit}
										</button>
									</td>
									<td data-label="Tenant / landlord">{r.party}</td>
									<td class="r num" data-label="Rent now">{fmt(r.rent_aed)}</td>
									<td class="r num" data-label="Building median">
										{fmt(r.building_median_aed)} <Chip chip={r.gap_chip} />
									</td>
									<td data-label="Ends"><Chip chip={r.end_chip} /></td>
									<td class="r" data-label="">
										{#if r.started}
											<Chip tone="green">Started</Chip>
										{:else}
											<button type="button" class="btn ghost sm" onclick={() => startRenewal(r.id, r.unit)}>
												Start renewal
											</button>
										{/if}
									</td>
								</tr>
							{:else}
								<tr><td colspan="6"><Empty text="No leases ending in the next 90 days." /></td></tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/snippet}
		</QueryView>
	</div>
{:else}
	<section class="card" aria-labelledby="market-h">
		<div class="ch"><h2 id="market-h">Other agencies' listings in your areas</h2></div>
		<QueryView query={market} rows={5}>
			{#snippet children(list)}
				<div class="tblwrap">
					<table class="tbl">
						<thead><tr><th>Unit</th><th class="r">Price</th><th>Portal</th><th>Against matching sales</th></tr></thead>
						<tbody>
							{#each list as m (m.id)}
								<tr class="row">
									<td>
										<button type="button" class="rowlink" onclick={() => panel.open({ kind: 'market', id: m.id })}>
											{m.watch ? '★ ' : ''}{m.unit}
										</button>
										<div class="sub">{m.area} · {m.days_listed} days listed</div>
									</td>
									<td class="r num" data-label="Price">{price(m.deal_type, m.price_aed).replace('AED ', '')}</td>
									<td data-label="Portal">{m.portal}</td>
									<td data-label="Against matching sales"><Chip chip={m.discount_chip} /></td>
								</tr>
							{:else}
								<tr><td colspan="4"><Empty text="No portal listings in your areas right now." /></td></tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/snippet}
		</QueryView>
	</section>
{/if}
