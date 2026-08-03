<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import {
	ArrowLeft,
	Bookmark,
	BookmarkCheck,
	BriefcaseBusiness,
	Building2,
	CheckCircle2,
	CircleAlert,
	Clock3,
	FileUp,
	FolderOpen,
	House,
	KeyRound,
	Mail,
	MessageSquareText,
	Phone,
	Plus,
	RefreshCw,
	Search,
	Sparkles,
	Trash2,
	UserRound,
	UsersRound,
	X
} from 'lucide-svelte'
import type {
	InboundEnquiry,
	InboundEnquiryCreate,
	InboundIntent,
	InboundMatch,
	InboundMatchState,
	InboundStatus
} from '$lib/api/inbound'
import { inbound } from '$lib/api/inbound'
import AppFrame from '$lib/components/layout/AppFrame.svelte'
import PageContainer from '$lib/components/layout/PageContainer.svelte'

type WorkspaceTab = 'demand' | 'instructions' | 'imports'
type MatchLane = 'owners' | 'units' | 'listings' | 'demand'

let tab = $state<WorkspaceTab>('demand')
let search = $state('')
let status = $state('')
let selectedId = $state<number | null>(null)
let showCreate = $state(false)
let createSaving = $state(false)
let createError = $state('')
let noteBody = $state('')
let noteSaving = $state(false)
let matchRefreshing = $state(false)
let expandingUnits = $state(false)
let matchLane = $state<MatchLane>('owners')
let importFile = $state<File | null>(null)
let importName = $state('')
let importRunning = $state(false)
let importError = $state('')
let deletingImportId = $state<number | null>(null)
let form = $state({
	intent: 'buy' as InboundIntent,
	full_name: '',
	phone: '',
	email: '',
	source: 'Manual',
	campaign: '',
	locations: '',
	property_type: 'Apartment',
	bedrooms: '2',
	budget_min: '',
	budget_max: '',
	building: '',
	unit_number: '',
	strict_locations: true,
	strict_bedrooms: false,
	strict_budget: false,
	timeline: '',
	notes: ''
})

const listQuery = createQuery(() => ({
	queryKey: ['crm', 'inbound', tab, status, search],
	queryFn: () => inbound.list({
		intent_group: tab === 'imports' ? undefined : tab,
		status: status || undefined,
		search: search || undefined
	}),
	enabled: tab !== 'imports',
	staleTime: 30_000
}))
const importQuery = createQuery(() => ({
	queryKey: ['crm', 'inbound', 'imports'],
	queryFn: inbound.imports,
	enabled: tab === 'imports',
	staleTime: 30_000
}))
const detailQuery = createQuery(() => ({
	queryKey: ['crm', 'inbound', 'detail', selectedId],
	queryFn: () => inbound.get(selectedId!),
	enabled: selectedId !== null,
	staleTime: 15_000
}))
const matchesQuery = createQuery(() => ({
	queryKey: ['crm', 'inbound', 'matches', selectedId],
	queryFn: () => inbound.matches(selectedId!),
	enabled: selectedId !== null,
	staleTime: 30_000
}))

const detail = $derived(detailQuery.data)
const matches = $derived(matchesQuery.data)
const visibleMatches = $derived(matches?.lanes[matchLane] ?? [])

function number(value: number | undefined | null) {
	return Number(value ?? 0).toLocaleString()
}

function money(value: unknown) {
	const amount = Number(value)
	return Number.isFinite(amount) && amount > 0 ? `AED ${Math.round(amount).toLocaleString()}` : 'Open'
}

function shortDate(value: string | null | undefined) {
	if (!value) return '—'
	const parsed = new Date(value)
	return Number.isNaN(parsed.valueOf()) ? '—' : new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }).format(parsed)
}

function intentLabel(intent: InboundIntent) {
	return ({ buy: 'Buyer', rent: 'Tenant', sell: 'Seller', let: 'Landlord' })[intent]
}

function intentClass(intent: InboundIntent) {
	return intent === 'buy' || intent === 'sell'
		? 'border-info-border bg-info-bg text-info'
		: 'border-success-border bg-success-bg text-success'
}

function statusLabel(value: string) {
	return value.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())
}

function confidenceLabel(value: number) {
	return value >= 0.85 ? 'High confidence' : value >= 0.65 ? 'Review suggested' : 'Needs review'
}

function scoreClass(score: number) {
	if (score >= 80) return 'border-success-border bg-success-bg text-success'
	if (score >= 65) return 'border-info-border bg-info-bg text-info'
	return 'border-warning-border bg-warning-bg text-warning'
}

function criteriaText(enquiry: InboundEnquiry) {
	const criteria = enquiry.criteria
	if ((enquiry.intent === 'sell' || enquiry.intent === 'let') && criteria.building) {
		return `${String(criteria.building)} · Unit ${String(criteria.unit_number ?? 'not supplied')} · ${money(criteria.expected_price_aed ?? criteria.budget_max_aed)}`
	}
	const locations = Array.isArray(criteria.locations) ? criteria.locations.join(', ') : String(criteria.locations ?? 'Any location')
	const bedrooms = criteria.bedrooms_min === 0 ? 'Studio' : criteria.bedrooms_min ? `${criteria.bedrooms_min} bed` : 'Any layout'
	return `${locations} · ${bedrooms} · ${money(criteria.budget_max_aed)}`
}

function openCreate(intent?: InboundIntent) {
	if (intent) form.intent = intent
	showCreate = true
	createError = ''
}

async function createLead() {
	if (!form.full_name.trim() || createSaving) return
	createSaving = true
	createError = ''
	try {
		const bedroom = Number(form.bedrooms)
		const payload: InboundEnquiryCreate = {
			intent: form.intent,
			full_name: form.full_name.trim(),
			phone: form.phone.trim() || undefined,
			email: form.email.trim() || undefined,
			source: form.source.trim() || 'Manual',
			campaign: form.campaign.trim() || undefined,
			notes: form.notes.trim() || undefined,
			criteria: {
				locations: form.locations.split(',').map((item) => item.trim()).filter(Boolean),
				property_type: form.property_type || undefined,
				bedrooms_min: Number.isFinite(bedroom) ? bedroom : undefined,
				bedrooms_max: Number.isFinite(bedroom) ? bedroom : undefined,
				budget_min_aed: Number(form.budget_min) || undefined,
				budget_max_aed: Number(form.budget_max) || undefined,
				expected_price_aed: Number(form.budget_max) || undefined,
				building: form.building.trim() || undefined,
				unit_number: form.unit_number.trim() || undefined,
				timeline: form.timeline || undefined
			},
			strict_fields: [
				...(form.strict_locations ? ['locations'] : []),
				...(form.strict_bedrooms ? ['bedrooms_min'] : []),
				...(form.strict_budget ? ['budget_max_aed'] : [])
			]
		}
		const created = await inbound.create(payload)
		showCreate = false
		selectedId = created.id
		await listQuery.refetch()
	} catch (error) {
		createError = error instanceof Error ? error.message : 'The enquiry could not be created.'
	} finally {
		createSaving = false
	}
}

async function updateStatus(value: InboundStatus) {
	if (!selectedId) return
	await inbound.update(selectedId, { status: value })
	await Promise.all([detailQuery.refetch(), listQuery.refetch()])
}

async function addNote() {
	if (!selectedId || !noteBody.trim() || noteSaving) return
	noteSaving = true
	try {
		await inbound.addNote(selectedId, noteBody.trim())
		noteBody = ''
		await detailQuery.refetch()
	} finally {
		noteSaving = false
	}
}

async function refreshMatches(expandUnits = false) {
	if (!selectedId || matchRefreshing) return
	matchRefreshing = true
	expandingUnits = expandUnits
	try {
		await inbound.refreshMatches(selectedId, expandUnits)
		await Promise.all([matchesQuery.refetch(), detailQuery.refetch(), listQuery.refetch()])
	} finally {
		matchRefreshing = false
		expandingUnits = false
	}
}

async function setMatchState(item: InboundMatch, state: InboundMatchState) {
	await inbound.updateMatch(item.id, state)
	await Promise.all([matchesQuery.refetch(), detailQuery.refetch(), listQuery.refetch()])
}

function chooseImport(event: Event) {
	const input = event.currentTarget as HTMLInputElement
	importFile = input.files?.[0] ?? null
	if (importFile && !importName) importName = importFile.name.replace(/\.(xlsx|csv)$/i, '')
	importError = ''
}

async function runImport() {
	if (!importFile || importRunning) return
	importRunning = true
	importError = ''
	try {
		await inbound.upload(importFile, importName.trim())
		importFile = null
		importName = ''
		await importQuery.refetch()
	} catch (error) {
		importError = error instanceof Error ? error.message : 'The import failed.'
	} finally {
		importRunning = false
	}
}

async function deleteImport(id: number) {
	if (deletingImportId !== null || !confirm('Delete this import and every enquiry created only from it?')) return
	deletingImportId = id
	try {
		await inbound.deleteImport(id)
		await importQuery.refetch()
	} finally {
		deletingImportId = null
	}
}
</script>

<svelte:head><title>Inbound intelligence · Vitevue CRM</title></svelte:head>

<AppFrame stableScrollGutter>
	<PageContainer variant="wide" class="pb-14">
		<header class="flex flex-col gap-5 border-b border-border pb-6 pt-5 lg:flex-row lg:items-end lg:justify-between">
			<div>
				<a href="/crm" class="mb-3 inline-flex items-center gap-1.5 text-xs font-semibold text-fg-4 transition hover:text-info"><ArrowLeft size={13} /> Lease opportunity CRM</a>
				<div class="flex items-center gap-3"><span class="flex h-10 w-10 items-center justify-center rounded-lg bg-navy text-on-navy"><Sparkles size={19} /></span><div><h1 class="text-2xl font-semibold tracking-tight text-fg-1">Inbound intelligence</h1><p class="mt-1 text-sm text-fg-3">Turn campaign enquiries into demand briefs, instructions, and owner pursuit networks.</p></div></div>
			</div>
			<div class="flex flex-wrap gap-2"><button type="button" class="ui-button" data-variant="primary" data-size="sm" onclick={() => openCreate(tab === 'instructions' ? 'sell' : 'buy')}><Plus size={14} /> New inbound</button><button type="button" class="ui-button" data-variant="secondary" data-size="sm" onclick={() => { tab = 'imports'; selectedId = null }}><FileUp size={14} /> Import leads</button></div>
		</header>

		<section class="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
			<div class="ui-surface p-4"><div class="flex items-center justify-between"><span class="font-mono text-[10px] uppercase text-fg-4">All inbound</span><UsersRound size={16} class="text-info" /></div><p class="mt-3 text-2xl font-semibold">{number(listQuery.data?.summary.total)}</p><p class="mt-1 text-xs text-fg-4">Organization-wide enquiries</p></div>
			<div class="ui-surface p-4"><div class="flex items-center justify-between"><span class="font-mono text-[10px] uppercase text-fg-4">Demand</span><Search size={16} class="text-success" /></div><p class="mt-3 text-2xl font-semibold">{number(listQuery.data?.summary.demand)}</p><p class="mt-1 text-xs text-fg-4">Buyers and tenants</p></div>
			<div class="ui-surface p-4"><div class="flex items-center justify-between"><span class="font-mono text-[10px] uppercase text-fg-4">Instructions</span><BriefcaseBusiness size={16} class="text-info" /></div><p class="mt-3 text-2xl font-semibold">{number(listQuery.data?.summary.instructions)}</p><p class="mt-1 text-xs text-fg-4">Sellers and landlords</p></div>
			<div class="ui-surface p-4"><div class="flex items-center justify-between"><span class="font-mono text-[10px] uppercase text-fg-4">Review</span><CircleAlert size={16} class="text-warning" /></div><p class="mt-3 text-2xl font-semibold">{number(listQuery.data?.summary.needs_review)}</p><p class="mt-1 text-xs text-fg-4">Ambiguous extractions</p></div>
		</section>

		<div class="mt-4 flex flex-wrap items-center gap-2 border-b border-border pb-3">
			{#each [{ id: 'demand', label: 'Demand', icon: Search }, { id: 'instructions', label: 'Instructions', icon: BriefcaseBusiness }, { id: 'imports', label: 'Imports', icon: FolderOpen }] as item}
				<button type="button" class="ui-button" data-variant={tab === item.id ? 'primary' : 'ghost'} data-size="sm" onclick={() => { tab = item.id as WorkspaceTab; selectedId = null }}><item.icon size={14} /> {item.label}</button>
			{/each}
		</div>

		{#if tab === 'imports'}
			<div class="mt-4 grid gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
				<section class="ui-surface p-5"><h2 class="text-sm font-semibold text-fg-1">Import campaign leads</h2><p class="mt-1 text-xs leading-5 text-fg-4">CSV or XLSX. Contact details remain private; only redacted notes are used for AI extraction.</p><label class="mt-4 block cursor-pointer rounded-lg border border-dashed border-border bg-panel p-6 text-center"><input class="sr-only" type="file" accept=".csv,.xlsx" onchange={chooseImport} /><FileUp class="mx-auto text-info" size={22} /><p class="mt-2 text-xs font-semibold">{importFile?.name ?? 'Choose lead export'}</p></label><input bind:value={importName} class="mt-3 h-10 w-full rounded-md border border-border bg-card px-3 text-sm outline-none focus:border-focus" placeholder="Campaign or folder name" /><button type="button" class="mt-3 w-full ui-button" data-variant="primary" data-size="sm" disabled={!importFile || importRunning} onclick={runImport}>{#if importRunning}<RefreshCw size={13} class="animate-spin" /> Standardizing{:else}<Sparkles size={13} /> Import and enrich{/if}</button>{#if importError}<p class="mt-3 rounded-md border border-error-border bg-error-bg p-3 text-xs text-error">{importError}</p>{/if}</section>
				<section class="ui-surface overflow-hidden"><div class="border-b border-border px-5 py-4"><h2 class="text-sm font-semibold">Import history</h2><p class="mt-1 text-xs text-fg-4">Every source remains auditable and removable.</p></div>{#if importQuery.isLoading}<div class="p-8 text-center text-sm text-fg-4"><RefreshCw class="mx-auto mb-2 animate-spin" size={18} /> Loading imports</div>{:else if importQuery.data?.length}<div class="divide-y divide-border">{#each importQuery.data as item (item.id)}<div class="flex items-start justify-between gap-4 p-5"><div class="min-w-0"><div class="flex items-center gap-2"><p class="truncate text-sm font-semibold">{item.name}</p><span class="rounded-full border border-success-border bg-success-bg px-2 py-0.5 text-[9px] font-semibold uppercase text-success">{item.status}</span></div><p class="mt-1 text-xs text-fg-4">{item.original_filename} · {shortDate(item.completed_at)}</p><div class="mt-3 flex flex-wrap gap-2 text-[10px]"><span class="rounded border border-border px-2 py-1">{number(item.summary.imported)} enquiries</span><span class="rounded border border-warning-border bg-warning-bg px-2 py-1 text-warning">{number(item.summary.needs_review)} review</span><span class="rounded border border-border px-2 py-1">{number(item.summary.duplicates)} duplicates</span></div></div><button type="button" class="ui-button text-error" data-variant="ghost" data-size="icon" disabled={deletingImportId === item.id} onclick={() => deleteImport(item.id)}><Trash2 size={14} /></button></div>{/each}</div>{:else}<div class="p-10 text-center text-sm text-fg-4">No inbound files imported yet.</div>{/if}</section>
			</div>
		{:else}
			<section class="mt-4 ui-surface p-4"><div class="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]"><label class="relative"><Search class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-4" size={14} /><input bind:value={search} class="h-10 w-full rounded-md border border-border bg-card pl-9 pr-3 text-sm outline-none focus:border-focus" placeholder="Search contact, campaign, area…" /></label><select bind:value={status} class="h-10 rounded-md border border-border bg-card px-3 text-sm"><option value="">All pipeline stages</option>{#each ['new','needs_review','assigned','contacted','qualified','active','won','nurture','closed_lost'] as value}<option {value}>{statusLabel(value)}</option>{/each}</select></div></section>

			<div class="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_460px]">
				<section class="ui-surface overflow-hidden"><div class="flex items-center justify-between border-b border-border px-5 py-4"><div><h2 class="text-sm font-semibold">{tab === 'demand' ? 'Buyer and tenant demand' : 'Seller and landlord instructions'}</h2><p class="mt-1 text-xs text-fg-4">{number(listQuery.data?.total)} enquiries</p></div><button type="button" class="ui-button" data-variant="ghost" data-size="icon" onclick={() => listQuery.refetch()}><RefreshCw size={14} class={listQuery.isFetching ? 'animate-spin' : ''} /></button></div>{#if listQuery.isLoading}<div class="p-10 text-center text-sm text-fg-4"><RefreshCw class="mx-auto mb-2 animate-spin" size={18} /> Loading inbound queue</div>{:else if listQuery.data?.enquiries.length}<div class="divide-y divide-border">{#each listQuery.data.enquiries as enquiry (enquiry.id)}<button type="button" class="grid w-full gap-3 p-4 text-left transition hover:bg-panel md:grid-cols-[minmax(0,1fr)_170px_110px] {selectedId === enquiry.id ? 'bg-info-bg' : ''}" onclick={() => { selectedId = enquiry.id; matchLane = enquiry.intent === 'sell' || enquiry.intent === 'let' ? 'demand' : 'owners' }}><div class="min-w-0"><div class="flex items-center gap-2"><p class="truncate text-sm font-semibold">{enquiry.contact.full_name}</p><span class={`rounded-full border px-2 py-0.5 text-[9px] font-semibold ${intentClass(enquiry.intent)}`}>{intentLabel(enquiry.intent)}</span>{#if enquiry.status === 'needs_review'}<CircleAlert size={13} class="text-warning" />{/if}</div><p class="mt-1 truncate text-xs text-fg-3">{criteriaText(enquiry)}</p><p class="mt-1 text-[10px] text-fg-4">{enquiry.campaign || enquiry.source} · {shortDate(enquiry.enquiry_date)}</p></div><div><p class="text-[10px] uppercase text-fg-4">Pipeline</p><p class="mt-1 text-xs font-semibold text-fg-2">{statusLabel(enquiry.status)}</p><p class="mt-1 text-[10px] text-fg-4">{confidenceLabel(enquiry.extraction_confidence)}</p></div><div class="text-right"><p class="text-lg font-semibold">{number(enquiry.match_count)}</p><p class="text-[10px] text-fg-4">matches</p>{#if enquiry.saved_match_count}<p class="mt-1 text-[10px] font-semibold text-success">{enquiry.saved_match_count} saved</p>{/if}</div></button>{/each}</div>{:else}<div class="p-12 text-center"><UserRound class="mx-auto text-fg-4" size={24} /><p class="mt-3 text-sm font-semibold">No enquiries in this workspace</p><button type="button" class="mt-4 ui-button" data-variant="primary" data-size="sm" onclick={() => openCreate(tab === 'demand' ? 'buy' : 'sell')}><Plus size={13} /> Add the first</button></div>{/if}</section>

				<aside class="ui-surface overflow-hidden xl:sticky xl:top-20 xl:max-h-[calc(100vh-7rem)] xl:overflow-y-auto">{#if !selectedId}<div class="grid min-h-[520px] place-items-center p-8 text-center"><div><Sparkles class="mx-auto text-info" size={25} /><p class="mt-3 text-sm font-semibold">Select an inbound enquiry</p><p class="mt-1 text-xs leading-5 text-fg-4">Its normalized brief, pursuit network, and activity will appear here.</p></div></div>{:else if detailQuery.isLoading}<div class="grid min-h-[520px] place-items-center"><RefreshCw class="animate-spin text-info" size={22} /></div>{:else if detail}<header class="border-b border-border p-5"><div class="flex items-start justify-between gap-3"><div><div class="flex items-center gap-2"><span class={`rounded-full border px-2 py-1 text-[10px] font-semibold ${intentClass(detail.intent)}`}>{intentLabel(detail.intent)}</span><span class="rounded-full border border-border px-2 py-1 text-[10px]">{statusLabel(detail.status)}</span></div><h2 class="mt-3 text-xl font-semibold">{detail.contact.full_name}</h2><p class="mt-1 text-xs text-fg-4">{criteriaText(detail)}</p></div><button type="button" class="ui-button" data-variant="ghost" data-size="icon" onclick={() => (selectedId = null)}><X size={15} /></button></div><div class="mt-4 flex flex-wrap gap-2">{#if detail.contact.phone}<a class="ui-button" data-variant="secondary" data-size="sm" href={`tel:${detail.contact.phone}`}><Phone size={13} /> {detail.contact.phone}</a>{/if}{#if detail.contact.email}<a class="ui-button" data-variant="secondary" data-size="sm" href={`mailto:${detail.contact.email}`}><Mail size={13} /> Email</a>{/if}</div><label class="mt-4 block"><span class="text-[10px] font-semibold uppercase text-fg-4">Pipeline stage</span><select value={detail.status} onchange={(event) => updateStatus((event.currentTarget as HTMLSelectElement).value as InboundStatus)} class="mt-1 h-9 w-full rounded-md border border-border bg-card px-3 text-xs">{#each ['new','needs_review','assigned','contacted','qualified','active','won','nurture','closed_lost'] as value}<option {value}>{statusLabel(value)}</option>{/each}</select></label></header>

				<section class="border-b border-border p-5"><div class="flex items-center justify-between"><div><h3 class="text-sm font-semibold">Match network</h3><p class="mt-1 text-[10px] text-fg-4">Explainable, evidence-ranked pursuits</p></div><button type="button" class="ui-button" data-variant="ghost" data-size="sm" disabled={matchRefreshing} onclick={() => refreshMatches()}><RefreshCw size={13} class={matchRefreshing && !expandingUnits ? 'animate-spin' : ''} /> Refresh</button></div><div class="mt-3 flex flex-wrap gap-1">{#each (detail.intent === 'sell' || detail.intent === 'let' ? [{ id: 'demand', label: 'Reverse demand' }, { id: 'units', label: `Property evidence ${matches?.lanes.units.length ?? 0}` }] : [{ id: 'owners', label: `Owners ${matches?.lanes.owners.length ?? 0}` }, { id: 'units', label: `Units ${matches?.lanes.units.length ?? 0}` }, { id: 'listings', label: `Listings ${matches?.lanes.listings.length ?? 0}` }]) as lane}<button type="button" class="ui-button" data-variant={matchLane === lane.id ? 'primary' : 'ghost'} data-size="sm" onclick={() => (matchLane = lane.id as MatchLane)}>{lane.label}</button>{/each}</div>{#if matchLane === 'units' && (detail.intent === 'buy' || detail.intent === 'rent')}<button type="button" class="mt-3 w-full ui-button" data-variant="secondary" data-size="sm" disabled={matchRefreshing} onclick={() => refreshMatches(true)}>{#if expandingUnits}<RefreshCw size={13} class="animate-spin" /> Expanding market universe{:else}<Building2 size={13} /> Explore all matching units{/if}</button><p class="mt-2 text-[10px] leading-4 text-fg-4">Adds recently transacted units beyond the default lease-opportunity pool. Owner identity may require enrichment.</p>{/if}{#if matchLane === 'listings' && matches && !matches.listing_fresh}<div class="mt-3 rounded-lg border border-warning-border bg-warning-bg p-3 text-xs text-warning"><div class="flex gap-2"><Clock3 size={14} class="flex-none" /><p>Listings are hidden because the feed is older than 48 hours. Owner and unit matching remain live.</p></div></div>{/if}{#if matchesQuery.isLoading}<div class="py-8 text-center text-xs text-fg-4"><RefreshCw class="mx-auto mb-2 animate-spin" size={15} /> Scoring matches</div>{:else if visibleMatches.length}<div class="mt-3 space-y-2">{#each visibleMatches.slice(0, 20) as item (item.id)}<article class="rounded-lg border border-border bg-panel p-3"><div class="flex items-start justify-between gap-3"><div class="min-w-0"><p class="truncate text-xs font-semibold">{item.title}</p><p class="mt-1 truncate text-[10px] text-fg-4">{item.subtitle}</p></div><span class={`rounded-md border px-2 py-1 font-mono text-xs font-bold ${scoreClass(item.score)}`}>{item.score}</span></div><div class="mt-2 flex flex-wrap gap-1">{#each item.reasons.slice(0, 3) as reason}<span class="rounded bg-card px-1.5 py-1 text-[9px] text-fg-3">{reason}</span>{/each}</div><div class="mt-3 flex justify-end gap-1">{#if item.state === 'saved'}<button type="button" class="ui-button text-success" data-variant="ghost" data-size="sm" onclick={() => setMatchState(item, 'suggested')}><BookmarkCheck size={13} /> Saved</button>{:else}<button type="button" class="ui-button" data-variant="ghost" data-size="sm" onclick={() => setMatchState(item, 'saved')}><Bookmark size={13} /> Save</button>{/if}<button type="button" class="ui-button" data-variant="ghost" data-size="sm" onclick={() => setMatchState(item, 'dismissed')}><X size={13} /> Dismiss</button></div></article>{/each}</div>{:else}<div class="py-8 text-center text-xs text-fg-4">No qualifying matches in this lane.</div>{/if}</section>

				<section class="p-5"><div class="flex items-center gap-2"><MessageSquareText size={14} class="text-info" /><h3 class="text-sm font-semibold">Activity and notes</h3></div>{#if detail.review_reasons.length}<div class="mt-3 rounded-lg border border-warning-border bg-warning-bg p-3"><p class="text-[10px] font-semibold uppercase text-warning">Review exceptions</p>{#each detail.review_reasons as reason}<p class="mt-1 text-xs text-fg-2">• {reason}</p>{/each}</div>{/if}<textarea bind:value={noteBody} class="mt-3 min-h-20 w-full rounded-md border border-border bg-card p-3 text-xs outline-none focus:border-focus" placeholder="Add qualification, viewing, or follow-up notes…"></textarea><button type="button" class="mt-2 ui-button" data-variant="secondary" data-size="sm" disabled={!noteBody.trim() || noteSaving} onclick={addNote}>{#if noteSaving}<RefreshCw size={12} class="animate-spin" />{:else}<Plus size={12} />{/if} Add note</button>{#if detail.notes.length}<div class="mt-4 space-y-2">{#each detail.notes as note}<div class="rounded-lg border border-border bg-panel p-3"><p class="whitespace-pre-wrap text-xs leading-5">{note.body}</p><p class="mt-2 text-[9px] text-fg-4">{shortDate(note.created_at)}</p></div>{/each}</div>{/if}</section>{/if}</aside>
			</div>
		{/if}
	</PageContainer>
</AppFrame>

{#if showCreate}
	<button type="button" class="fixed inset-0 z-[90] bg-overlay backdrop-blur-[2px]" aria-label="Close" onclick={() => (showCreate = false)}></button>
	<div class="fixed left-1/2 top-1/2 z-[100] max-h-[92vh] w-[calc(100%-2rem)] max-w-2xl -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl border border-border bg-card shadow-2xl" role="dialog" aria-modal="true" aria-label="New inbound enquiry"><header class="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-card px-6 py-4"><div><h2 class="text-lg font-semibold">New inbound enquiry</h2><p class="mt-1 text-xs text-fg-4">Create a structured demand brief or instruction.</p></div><button type="button" class="ui-button" data-variant="ghost" data-size="icon" onclick={() => (showCreate = false)}><X size={16} /></button></header><form class="grid gap-4 p-6" onsubmit={(event) => { event.preventDefault(); createLead() }}><div class="grid grid-cols-4 gap-2">{#each ['buy','rent','sell','let'] as intent}<button type="button" class={`rounded-lg border p-3 text-xs font-semibold capitalize ${form.intent === intent ? 'border-navy bg-panel text-fg-1' : 'border-border text-fg-3'}`} onclick={() => (form.intent = intent as InboundIntent)}>{intentLabel(intent as InboundIntent)}</button>{/each}</div><div class="grid gap-3 sm:grid-cols-2"><label class="grid gap-1"><span class="text-xs font-semibold">Full name</span><input required bind:value={form.full_name} class="h-10 rounded-md border border-border bg-card px-3 text-sm" /></label><label class="grid gap-1"><span class="text-xs font-semibold">Phone</span><input bind:value={form.phone} class="h-10 rounded-md border border-border bg-card px-3 text-sm" /></label><label class="grid gap-1"><span class="text-xs font-semibold">Email</span><input type="email" bind:value={form.email} class="h-10 rounded-md border border-border bg-card px-3 text-sm" /></label><label class="grid gap-1"><span class="text-xs font-semibold">Campaign</span><input bind:value={form.campaign} class="h-10 rounded-md border border-border bg-card px-3 text-sm" /></label><label class="grid gap-1 sm:col-span-2"><span class="text-xs font-semibold">Locations</span><input bind:value={form.locations} class="h-10 rounded-md border border-border bg-card px-3 text-sm" placeholder="JBR, Dubai Marina" /></label><label class="grid gap-1"><span class="text-xs font-semibold">Property type</span><select bind:value={form.property_type} class="h-10 rounded-md border border-border bg-card px-3 text-sm"><option>Apartment</option><option>Villa</option><option>Office</option><option>Shop</option><option>Commercial</option></select></label><label class="grid gap-1"><span class="text-xs font-semibold">Bedrooms</span><select bind:value={form.bedrooms} class="h-10 rounded-md border border-border bg-card px-3 text-sm"><option value="0">Studio</option>{#each [1,2,3,4,5,6] as bed}<option value={bed}>{bed}</option>{/each}</select></label><label class="grid gap-1"><span class="text-xs font-semibold">Minimum budget</span><input type="number" bind:value={form.budget_min} class="h-10 rounded-md border border-border bg-card px-3 text-sm" /></label><label class="grid gap-1"><span class="text-xs font-semibold">{form.intent === 'sell' || form.intent === 'let' ? 'Expected price / rent' : 'Maximum budget'}</span><input type="number" bind:value={form.budget_max} class="h-10 rounded-md border border-border bg-card px-3 text-sm" /></label>{#if form.intent === 'sell' || form.intent === 'let'}<label class="grid gap-1"><span class="text-xs font-semibold">Building or project</span><input bind:value={form.building} class="h-10 rounded-md border border-border bg-card px-3 text-sm" placeholder="Marina Gate 1" /></label><label class="grid gap-1"><span class="text-xs font-semibold">Unit number</span><input bind:value={form.unit_number} class="h-10 rounded-md border border-border bg-card px-3 text-sm" placeholder="1204" /></label>{/if}<label class="grid gap-1 sm:col-span-2"><span class="text-xs font-semibold">Timeline</span><input bind:value={form.timeline} class="h-10 rounded-md border border-border bg-card px-3 text-sm" placeholder="Within 3 months" /></label><fieldset class="sm:col-span-2"><legend class="text-xs font-semibold">Must-have requirements</legend><p class="mt-1 text-[10px] text-fg-4">Unchecked criteria remain flexible and reduce the score rather than excluding a match.</p><div class="mt-2 flex flex-wrap gap-2"><label class="flex items-center gap-2 rounded-md border border-border bg-panel px-3 py-2 text-xs"><input type="checkbox" bind:checked={form.strict_locations} /> Location</label><label class="flex items-center gap-2 rounded-md border border-border bg-panel px-3 py-2 text-xs"><input type="checkbox" bind:checked={form.strict_bedrooms} /> Bedrooms</label><label class="flex items-center gap-2 rounded-md border border-border bg-panel px-3 py-2 text-xs"><input type="checkbox" bind:checked={form.strict_budget} /> Budget</label></div></fieldset><label class="grid gap-1 sm:col-span-2"><span class="text-xs font-semibold">Original notes</span><textarea bind:value={form.notes} class="min-h-24 rounded-md border border-border bg-card p-3 text-sm" placeholder="Mortgage approved, prefers a sea view…"></textarea></label></div>{#if createError}<p class="rounded-md border border-error-border bg-error-bg p-3 text-xs text-error">{createError}</p>{/if}<div class="flex justify-end gap-2"><button type="button" class="ui-button" data-variant="secondary" onclick={() => (showCreate = false)}>Cancel</button><button type="submit" class="ui-button" data-variant="primary" disabled={createSaving}>{#if createSaving}<RefreshCw size={13} class="animate-spin" /> Creating{:else}<CheckCircle2 size={13} /> Create and match{/if}</button></div></form></div>
{/if}
