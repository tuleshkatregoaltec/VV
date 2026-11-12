<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Building from 'lucide-svelte/icons/building-2'
import Mail from 'lucide-svelte/icons/mail'
import Phone from 'lucide-svelte/icons/phone'
import Search from 'lucide-svelte/icons/search'
import UserRound from 'lucide-svelte/icons/user-round'
import Users from 'lucide-svelte/icons/users'
import X from 'lucide-svelte/icons/x'
import PhotoSlider from '$lib/collections/PhotoSlider.svelte'
import { crm } from '$lib/crm/api'
import { listingKeyOf } from '$lib/crm/api/backend'
import type {
	CompanyListingAgentInventory,
	ListingCard,
	ListingStatus,
	RenewalOwnerFilter,
	RenewalWindow
} from '$lib/crm/api/types'
import AddToCollectionMenu from '$lib/crm/components/collections/AddToCollectionMenu.svelte'
import CollectionEditor from '$lib/crm/components/collections/CollectionEditor.svelte'
import CollectionList from '$lib/crm/components/collections/CollectionList.svelte'
import { canAddToCollection } from '$lib/crm/components/collections/collectionRules'
import Chip from '$lib/crm/components/ui/Chip.svelte'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import FilterMenu from '$lib/crm/components/ui/FilterMenu.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import QueryView from '$lib/crm/components/ui/QueryView.svelte'
import SearchPicker from '$lib/crm/components/ui/SearchPicker.svelte'
import Seg from '$lib/crm/components/ui/Seg.svelte'
import Tabs from '$lib/crm/components/ui/Tabs.svelte'
import { fmt, fullDate, price, priceShort, short } from '$lib/crm/format'
import { crmQueries } from '$lib/crm/queries'
import { openListing, panel } from '$lib/crm/stores/panel.svelte'
import { type AssetTab, ui } from '$lib/crm/stores/ui.svelte'
import { write } from '$lib/crm/write'

const me = createQuery(() => crmQueries.me())
const mineAll = createQuery(() => crmQueries.listings('mine'))
let companyOffset = $state(0)
let companyItems = $state<ListingCard[]>([])
let companyFilter = $state('')
/** Property name search: what is typed, and what is searched once typing pauses. */
let listingTyped = $state('')
let listingSearch = $state('')
$effect(() => {
	const value = listingTyped.trim()
	const timer = setTimeout(() => {
		if (value === listingSearch) return
		listingSearch = value
		companyOffset = 0
		companyItems = []
	}, 300)
	return () => clearTimeout(timer)
})
/** The chosen company's agents, kept while one agent's listings are shown. */
let companyAgents = $state<CompanyListingAgentInventory[]>([])
let selectedAgent = $state<CompanyListingAgentInventory | null>(null)
/**
 * Renewals (client, 3 Nov): a toggle between leases on units with a current owner in the
 * agency's owner imports (with that owner's contact) and every other lease, whose owner is still
 * to be found. 50 at a time up to the 200 the endpoint serves.
 */
let renewalLimit = $state(50)
const OWNER_ITEMS: { id: RenewalOwnerFilter; label: string }[] = [
	{ id: 'known', label: 'Owner known' },
	{ id: 'unknown', label: 'Owner unknown' }
]
/** Area options: every area in the lease data (the list My areas uses), fetched once. */
const renewalAreas = createQuery(() => ({
	...crmQueries.feedAreas(),
	enabled: ui.assetTab === 'renewals'
}))
const renewals = createQuery(() => ({
	...crmQueries.renewals({
		area: ui.renewalArea,
		window: ui.renewalWindow,
		property_type: ui.renewalPtype,
		project: ui.renewalProject,
		building: ui.renewalBuilding,
		limit: renewalLimit,
		owner: ui.renewalOwner
	}),
	enabled: ui.assetTab === 'renewals'
}))
const scope = $derived(ui.assetTab === 'company' ? 'company' : 'mine')
const companyAgentFilter = $derived({
	allCompanies: true,
	...(companyFilter ? { brokerId: companyFilter } : {}),
	...(selectedAgent
		? selectedAgent.agent_id
			? { agentId: selectedAgent.agent_id }
			: { agentName: selectedAgent.agent_name }
		: {}),
	...(listingSearch ? { search: listingSearch } : {})
})
const listings = createQuery(() => ({
	...crmQueries.listings(
		scope,
		ui.assetStatus,
		100,
		scope === 'company' ? companyOffset : 0,
		scope === 'company' ? companyAgentFilter : undefined
	),
	enabled: ui.assetTab === 'mine' || ui.assetTab === 'company'
}))
const agentKey = (a: CompanyListingAgentInventory) => a.agent_id ?? `name:${a.agent_name}`
const companyOptions = $derived(
	(listings.data?.companies ?? []).map((c) => ({
		id: c.broker_id,
		label: c.broker_name,
		meta: `${fmt(c.listings)} · ${fmt(c.agents)} agents`
	}))
)
/** Agents across every company (each company counts its own agents). */
const allAgents = $derived(
	(listings.data?.companies ?? []).reduce((total, c) => total + c.agents, 0)
)
const initials = (name: string) =>
	name
		.split(/\s+/)
		.map((w) => w[0] ?? '')
		.join('')
		.slice(0, 2)
		.toUpperCase()
const agentOptions = $derived(
	companyAgents.map((a) => ({ id: agentKey(a), label: a.agent_name, meta: fmt(a.listings) }))
)
/** A new company or agent is loading: the cards on screen belong to the previous choice. */
const companyLoading = $derived(
	scope === 'company' &&
		listings.isFetching &&
		(listings.isPlaceholderData || (companyOffset === 0 && companyItems.length === 0))
)
/** "Show more" is fetching the next page. */
const companyLoadingMore = $derived(scope === 'company' && listings.isFetching && companyOffset > 0)
$effect(() => {
	if (scope !== 'company' || !listings.data || listings.isPlaceholderData) return
	const page = listings.data
	if (!selectedAgent) companyAgents = page.agent_inventory ?? []
	if (page.offset === 0) companyItems = page.items
	else if (page.offset === companyItems.length) companyItems = [...companyItems, ...page.items]
})
const portfolio = createQuery(() => ({
	...crmQueries.portfolio(),
	enabled: ui.assetTab === 'portfolio'
}))
const market = createQuery(() => ({ ...crmQueries.market(), enabled: ui.assetTab === 'market' }))

const facts = $derived.by(() => {
	const c = mineAll.data?.counts
	if (!c) return ''
	const leases =
		renewals.data && !renewals.isPlaceholderData ? ` · ${fmt(renewals.data.total)} leases` : ''
	return `${c.live} live · ${c.pocket} pocket · ${c.expired} expired${leases}`
})

const TABS: { id: AssetTab; label: string }[] = [
	{ id: 'mine', label: 'My listings' },
	{ id: 'company', label: 'Company listings' },
	{ id: 'collections', label: 'Collections' },
	{ id: 'portfolio', label: 'Portfolio' },
	{ id: 'renewals', label: 'Renewals' },
	{ id: 'market', label: 'Market' }
]

const statusItems = $derived.by(() => {
	const c = listings.data?.counts
	const n = (s: ListingStatus) => (c ? ` · ${c[s]}` : '')
	if (scope === 'company') return [{ id: 'live' as const, label: `Live${n('live')}` }]
	const items: { id: ListingStatus; label: string }[] = [
		{ id: 'live', label: `Live${n('live')}` },
		{ id: 'pocket', label: `Pocket${n('pocket')}` }
	]
	if (scope === 'mine') items.push({ id: 'expired', label: `Expired${n('expired')}` })
	return items
})

function selectTab(t: AssetTab) {
	ui.assetTab = t
	if (t === 'company') {
		companyOffset = 0
		companyItems = []
		companyFilter = ''
		selectedAgent = null
	}
	if (t === 'company' && ui.assetStatus !== 'live') ui.assetStatus = 'live'
}

function selectCompany(brokerId: string) {
	companyFilter = brokerId
	companyOffset = 0
	companyItems = []
	selectedAgent = null
	companyAgents = []
}

async function useCompanyForMatching() {
	if (!companyFilter || !me.data?.is_owner) return
	const result = await write({
		call: () => crm.companyListings.selectSource(companyFilter),
		success: 'Property Finder company connected'
	})
	if (!result) await listings.refetch()
}

async function stopCompanyMatching() {
	const name = listings.data?.matching_company?.broker_name
	if (!name || !me.data?.is_owner) return
	await write({
		call: () => crm.companyListings.clearSource(),
		success: `Buyer matching no longer uses ${name}`
	})
}

function loadMoreCompanyListings() {
	companyOffset = companyItems.length
}

function selectAgent(key: string) {
	selectedAgent = companyAgents.find((a) => agentKey(a) === key) ?? null
	companyOffset = 0
	companyItems = []
}

const WINDOWS: { id: Exclude<RenewalWindow, ''>; label: string }[] = [
	{ id: 'vacant', label: 'Vacant · 60 days' },
	{ id: 'expired', label: 'Ended · 12 months' },
	{ id: 'expiring_30', label: 'Ends in 30 days' },
	{ id: 'expiring_60', label: 'Ends in 31–60 days' },
	{ id: 'expiring_90', label: 'Ends in 61–90 days' }
]

function filterRenewals(change: () => void) {
	change()
	renewalLimit = 50
}

/** Projects are listed for the picked area, buildings for the picked project. */
function pickRenewalArea(area: string) {
	filterRenewals(() => {
		ui.renewalArea = area
		ui.renewalProject = ''
		ui.renewalBuilding = ''
	})
}

function pickRenewalProject(project: string) {
	filterRenewals(() => {
		ui.renewalProject = project
		ui.renewalBuilding = ''
	})
}

const options = (list: string[] | undefined) => (list ?? []).map((x) => ({ id: x, label: x }))

function startRenewal(id: string, unit: string) {
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
		{#if scope === 'company'}
			{@const company = listings.data?.company}
			{@const matching = listings.data?.matching_company}
			<div class="ctool">
				<div class="cpickers">
					<SearchPicker
						label="Property Finder company"
						icon={Building}
						options={companyOptions}
						value={companyFilter}
						onselect={selectCompany}
						allLabel="All companies"
						allMeta="{fmt(companyOptions.length)} companies"
						noun="companies"
					/>
					{#if companyFilter}
						<SearchPicker
							label="Agent"
							icon={Users}
							options={agentOptions}
							value={selectedAgent ? agentKey(selectedAgent) : ''}
							onselect={selectAgent}
							allLabel="All agents"
							allMeta={company ? fmt(company.listings) : undefined}
							noun="agents"
							disabled={!companyAgents.length}
						/>
					{/if}
				</div>
				<label class="lsearch">
					<Search size={15} />
					<input
						bind:value={listingTyped}
						aria-label="Search property name"
						placeholder="Search property name"
						type="search"
					/>
					{#if listingSearch && listings.data && !companyLoading}
						<span class="lsearch-n">{fmt(listings.data.total ?? 0)} found</span>
					{/if}
				</label>
				<dl class="cstats" class:dim={companyLoading}>
					<div>
						<dt>Active listings</dt>
						<dd>
							{fmt(
								selectedAgent
									? selectedAgent.listings
									: company
										? company.listings
										: (listings.data?.counts.live ?? 0)
							)}
						</dd>
					</div>
					{#if companyFilter && company}
						<div>
							<dt>Agents</dt>
							<dd>{fmt(company.agents)}</dd>
						</div>
						{#if company.last_scraped_at}
							<div>
								<dt>Source updated</dt>
								<dd>{fullDate(company.last_scraped_at.slice(0, 10))}</dd>
							</div>
						{/if}
					{:else}
						<div>
							<dt>Companies</dt>
							<dd>{fmt(companyOptions.length)}</dd>
						</div>
						<div>
							<dt>Agents</dt>
							<dd>{fmt(allAgents)}</dd>
						</div>
					{/if}
				</dl>
				<div class="cmatch">
					<span class="cmatch-label">Buyer matching</span>
					{#if matching}
						<span class="chip green" title="Buyers and tenants are matched against this company's listings">
							{matching.broker_name}
						</span>
						{#if me.data?.is_owner}
							<button
								type="button"
								class="btn ghost sm"
								aria-label="Stop using {matching.broker_name} for buyer matching"
								title="Stop using this company for buyer matching"
								onclick={stopCompanyMatching}
							>
								<X size={14} />Remove
							</button>
						{/if}
					{:else}
						<span class="chip outline">No company set</span>
					{/if}
					{#if companyFilter && me.data?.is_owner && companyFilter !== matching?.broker_id}
						<button type="button" class="btn sm" onclick={useCompanyForMatching}>
							Use this company
						</button>
					{/if}
				</div>
			</div>
			<!-- A thin bar while listings load: a new company or agent, or the next page. -->
			<div class="loadtrack" aria-hidden="true">
				{#if listings.isFetching}<span></span>{/if}
			</div>
			{#if companyFilter && selectedAgent}
				<!-- The chosen agent's contact details, as published on their Property Finder listings. -->
				<div class="agent-card">
					<span class="avatar" aria-hidden="true">{initials(selectedAgent.agent_name)}</span>
					<div class="who">
						<strong>{selectedAgent.agent_name}</strong>
						<span>
							{listings.data?.company?.broker_name ?? 'Property Finder'} · {fmt(selectedAgent.listings)} active
							listings
						</span>
					</div>
					<div class="contact">
						{#if selectedAgent.phone}
							<a class="btn ghost sm" href="tel:{selectedAgent.phone}">
								<Phone size={14} />{selectedAgent.phone}
							</a>
						{/if}
						{#if selectedAgent.email}
							<a class="btn ghost sm" href="mailto:{selectedAgent.email}">
								<Mail size={14} />{selectedAgent.email}
							</a>
						{/if}
						{#if !selectedAgent.phone && !selectedAgent.email}
							<span class="muted small">No phone or email on their listings</span>
						{/if}
					</div>
				</div>
			{/if}
		{:else}
			<div class="filters">
				<Seg label="Status" items={statusItems} value={ui.assetStatus} onselect={(s) => (ui.assetStatus = s)} />
				<button type="button" class="btn sm ml-auto" onclick={() => panel.open({ kind: 'new-listing' })}>
					＋ Listing
				</button>
			</div>
		{/if}
		<QueryView query={listings} rows={4}>
			{#snippet children(data)}
				{@const visibleItems = scope === 'company' ? companyItems : data.items}
				{#if companyLoading}
					<div class="lcards" aria-busy="true" aria-label="Loading listings">
						{#each Array.from({ length: 10 }, (_, i) => i) as i (i)}
							<div class="lcard skel-card">
								<div class="img"></div>
								<div class="body"><i></i><i></i><i></i><i></i></div>
							</div>
						{/each}
					</div>
				{:else if visibleItems.length}
					<div class="lcards">
						{#each visibleItems as x (x.id)}
							{@const addKey = scope === 'company' && canAddToCollection(data) ? listingKeyOf(x.id) : null}
							<div class="lcell">
							<button type="button" class="lcard" onclick={() => openListing(x.id)}>
								<div class="img" class:has-ph={x.photos?.length}>
									{#if x.photos?.length}<PhotoSlider photos={x.photos} controls={false} />{/if}
									<span class="chip">{x.deal_type === 'sale' ? 'Sale' : 'Rent'}</span>
									<span class="chip">{statusLabel(x.status)}</span>
								</div>
								<div class="body">
									<span class="pr">{priceShort(x.deal_type, x.price_aed)}</span>
									<span class="t">{x.unit}</span>
									<span class="d">
										{x.area} · {x.bedrooms ? `${x.bedrooms} bed` : 'Studio'} · {fmt(x.size_sqft)} sqft
									</span>
									{#if scope === 'company' && x.agent}
										<span class="ag"><UserRound size={13} />{x.agent}</span>
									{/if}
									<div class="foot">
										<Chip chip={x.permit_chip} />
										{#if x.status === 'live'}<Chip>{x.days_live} days · {x.enquiries} leads</Chip>{/if}
										<Chip chip={x.form_a_chip} />
									</div>
								</div>
							</button>
							{#if addKey}
								<div class="addc"><AddToCollectionMenu listingKey={addKey} /></div>
							{/if}
							</div>
						{/each}
					</div>
					{#if scope === 'company' && data.total != null && visibleItems.length < data.total}
						<div class="more">
							<button
								type="button"
								class="btn ghost"
								disabled={companyLoadingMore}
								aria-busy={companyLoadingMore}
								onclick={loadMoreCompanyListings}
							>
								{#if companyLoadingMore}
									<span class="spin" aria-hidden="true"></span> Loading…
								{:else}
									Show more · {fmt(visibleItems.length)} of {fmt(data.total)}
								{/if}
							</button>
						</div>
					{/if}
				{:else}
					<Empty
						text={scope === 'company'
							? listingSearch
								? `No listings match “${listingSearch}”.`
								: data.company
								? 'No active Property Finder listings for this company.'
								: 'Choose a Property Finder company to see its current listings.'
							: `No ${ui.assetStatus} listings.`}
					>
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
{:else if ui.assetTab === 'collections'}
	<div class="wrap">
		{#if ui.openCollectionId}
			<CollectionEditor id={ui.openCollectionId} onback={() => (ui.openCollectionId = null)} />
		{:else}
			<CollectionList onopen={(id) => (ui.openCollectionId = id)} />
		{/if}
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
	<div class="filters">
		<Seg
			label="Owner"
			items={OWNER_ITEMS}
			value={ui.renewalOwner}
			onselect={(v) => filterRenewals(() => (ui.renewalOwner = v))}
		/>
		<FilterMenu
			label="Lease end"
			allLabel="All lease ends"
			value={ui.renewalWindow}
			options={WINDOWS}
			onselect={(v) => filterRenewals(() => (ui.renewalWindow = v))}
		/>
		<FilterMenu
			label="Area"
			allLabel="All areas"
			value={ui.renewalArea}
			options={options(renewalAreas.data?.map((a) => a.area))}
			onselect={pickRenewalArea}
		/>
		<FilterMenu
			label="Type"
			allLabel="Any type"
			value={ui.renewalPtype}
			options={options(renewals.data?.property_types)}
			onselect={(v) => filterRenewals(() => (ui.renewalPtype = v))}
		/>
		{#if ui.renewalArea}
			<FilterMenu
				label="Project"
				allLabel="All projects"
				value={ui.renewalProject}
				options={options(renewals.data?.projects)}
				onselect={pickRenewalProject}
			/>
		{/if}
		{#if ui.renewalProject}
			<FilterMenu
				label="Building"
				allLabel="All buildings"
				value={ui.renewalBuilding}
				options={options(renewals.data?.buildings)}
				onselect={(v) => filterRenewals(() => (ui.renewalBuilding = v))}
			/>
		{/if}
		<span class="count" aria-live="polite">
			{renewals.isPlaceholderData
				? 'Updating…'
				: renewals.data
					? `${fmt(renewals.data.total)} lease${renewals.data.total === 1 ? '' : 's'}`
					: ''}
		</span>
	</div>
	<!-- Old rows stay dimmed while a new filter loads, so they never read as its answer. -->
	<div class="card" aria-busy={renewals.isPlaceholderData} style:opacity={renewals.isPlaceholderData ? 0.5 : undefined}>
		<QueryView query={renewals} rows={3}>
			{#snippet children(res)}
				<div class="tblwrap">
					<table class="tbl">
						<thead>
							<tr>
								<th>Unit</th>
								<th>Owner</th>
								<th>Property</th>
								<th class="r">Rent a year</th>
								<th>Ends</th>
								<th></th>
							</tr>
						</thead>
						<tbody>
							{#each res.items as r (r.id)}
								<tr class="row">
									<td>
										<button type="button" class="rowlink" onclick={() => panel.open({ kind: 'renewal', id: r.id })}>
											{r.unit}
										</button>
										<div class="sub">{r.area}</div>
									</td>
									<td data-label="Owner">
										{ui.renewalOwner === 'unknown' ? 'Not on file' : (r.owner?.name ?? 'Name not imported')}
										{#if r.owner?.phone}
											<div class="sub"><a href="tel:{r.owner.phone}">{r.owner.phone}</a></div>
										{/if}
									</td>
									<td data-label="Property">{r.property}</td>
									<td class="r num" data-label="Rent a year">{r.rent_aed ? fmt(r.rent_aed) : ''}</td>
									<td data-label="Ends"><Chip chip={r.end_chip} /></td>
									<td class="r" data-label="">
										<button type="button" class="btn ghost sm" onclick={() => startRenewal(r.id, r.unit)}>
											Start renewal
										</button>
									</td>
								</tr>
							{:else}
								<tr>
									<td colspan="6">
										<Empty
											text={ui.renewalOwner === 'unknown'
												? 'No leases match these filters.'
												: 'No leases on units with an owner on file match these filters.'}
										/>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				{#if res.items.length < res.total && renewalLimit < 200}
					<div class="cb">
						<button type="button" class="btn ghost sm" onclick={() => (renewalLimit += 50)}>
							Show more · {fmt(res.items.length)} of {fmt(res.total)}
						</button>
					</div>
				{:else if res.items.length < res.total}
					<div class="cb small muted">
						Showing the first {fmt(res.items.length)} of {fmt(res.total)}. Pick an area or a lease end to see the rest.
					</div>
				{/if}
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

<style>
	/* Card + Add to collection: the button is the card's sibling, never inside it */
	.lcell { display: flex; flex-direction: column; gap: 4px; }
	.lcell > .lcard { flex: 1; }
	.lcard .img { position: relative; overflow: hidden; }
	.lcard .img.has-ph { height: 160px; }
	.lcard .img .chip { position: relative; z-index: 3; }
	.addc { display: flex; justify-content: flex-end; }
	/* Company listings toolbar: company picker · key figures · buyer matching */
	.ctool {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 12px 24px;
		padding: 12px 14px;
		border-bottom: 1px solid var(--sep);
	}
	.cstats {
		display: flex;
		gap: 24px;
		margin: 0;
	}
	.cstats div {
		display: grid;
		gap: 1px;
	}
	.cstats dt {
		font-size: 11px;
		color: var(--text3);
	}
	.cstats dd {
		margin: 0;
		font-size: 15px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.cmatch {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
		margin-left: auto;
		min-width: 0;
	}
	.cmatch-label {
		font-size: 12px;
		color: var(--text3);
	}
	.cmatch .chip {
		max-width: 260px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.cpickers {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		min-width: 0;
	}
	.lsearch {
		display: flex;
		align-items: center;
		gap: 8px;
		width: min(280px, 100%);
		height: 44px;
		padding: 0 12px;
		border: 1px solid var(--sep-strong);
		border-radius: 10px;
		background: var(--card);
		color: var(--text3);
	}
	.lsearch:focus-within {
		border-color: var(--accent);
		box-shadow: 0 0 0 3px var(--sel);
	}
	.lsearch input {
		flex: 1;
		min-width: 0;
		border: 0;
		background: transparent;
		color: var(--text);
		font-size: 14px;
		outline: none;
	}
	.lsearch-n {
		flex: none;
		font-size: 12px;
		color: var(--text3);
		font-variant-numeric: tabular-nums;
	}
	.cstats.dim {
		opacity: 0.5;
		transition: opacity 0.15s;
	}
	/* Loading: a thin indeterminate bar under the toolbar, skeleton cards, a spinner on Show more */
	.loadtrack {
		position: relative;
		height: 2px;
		margin-top: -1px;
		overflow: hidden;
	}
	.loadtrack span {
		position: absolute;
		inset: 0 auto 0 0;
		width: 35%;
		background: var(--accent);
		border-radius: 2px;
		animation: loadbar 1.1s ease-in-out infinite;
	}
	@keyframes loadbar {
		0% {
			transform: translateX(-100%);
		}
		100% {
			transform: translateX(300%);
		}
	}
	.skel-card {
		pointer-events: none;
	}
	.skel-card .img,
	.skel-card i {
		background: var(--skeleton);
		background-size: 200% 100%;
		animation: crm-shimmer 1.3s linear infinite;
	}
	.skel-card .body {
		gap: 0.5rem;
	}
	.skel-card i {
		display: block;
		height: 0.7rem;
		border-radius: 4px;
	}
	.skel-card i:nth-child(1) {
		width: 40%;
		height: 0.9rem;
	}
	.skel-card i:nth-child(2) {
		width: 85%;
	}
	.skel-card i:nth-child(3) {
		width: 65%;
	}
	.skel-card i:nth-child(4) {
		width: 50%;
	}
	.more {
		display: flex;
		justify-content: center;
		padding: 0 1rem 1.2rem;
	}
	.spin {
		width: 14px;
		height: 14px;
		border: 2px solid var(--sep-strong);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.7s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	/* The selected agent's contact card, above their listings */
	.agent-card {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 12px 16px;
		margin: 1rem 1rem 0;
		padding: 12px 14px;
		border: 1px solid var(--sep);
		border-radius: 12px;
		background: var(--card-2);
	}
	.avatar {
		display: grid;
		place-items: center;
		width: 40px;
		height: 40px;
		flex: none;
		border-radius: 50%;
		background: var(--sel);
		color: var(--accent);
		font-size: 14px;
		font-weight: 600;
	}
	.who {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	.who strong {
		font-size: 15px;
	}
	.who span {
		font-size: 12.5px;
		color: var(--text2);
	}
	.contact {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-left: auto;
	}
	.contact :global(svg) {
		color: var(--text3);
	}
	/* Listing card: the agent who holds a company listing */
	.ag {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		min-width: 0;
		font-size: 0.76rem;
		color: var(--text2);
	}
	.ag :global(svg) {
		flex: none;
		color: var(--text3);
	}
</style>
