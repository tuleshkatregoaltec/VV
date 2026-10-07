/**
 * Fixture backend: answers the CRM Beta endpoints (docs/crm/api-contract.md) from the in-memory
 * tables in db.ts, running the business rules in rules.ts. It stands in for FastAPI until the
 * live endpoints exist, and is reached only through the same API functions the live calls use.
 */
import { ApiError } from '$lib/api/client'
import type {
	AnonLead,
	CalendarEvent,
	CalendarSide,
	ChecklistStage,
	Chip,
	CommissionPatch,
	Connection,
	ConversationMessage,
	DealCreate,
	DealDetail,
	DealListResponse,
	DealRow,
	DealStages,
	DealTab,
	DocumentUploadResult,
	EventCreate,
	FeedSummary,
	FormPreview,
	Gap,
	HandoutMode,
	HandoutSettings,
	HomeResponse,
	ImportPreview,
	ImportRequest,
	InboxFilter,
	InboxItem,
	InboxResponse,
	LeadCreate,
	LeadDetail,
	LeadEvent,
	LeadFieldKey,
	LeadFields,
	LeadListResponse,
	LeadMatches,
	LeadPatch,
	LeadRow,
	LeadStage,
	LeadStageMove,
	LeadType,
	ListingCard,
	ListingCreate,
	ListingCreateResult,
	ListingDetail,
	ListingListResponse,
	MarketListing,
	MarketListingDetail,
	MatchClient,
	MatchClients,
	MatchRow,
	MatchTier,
	Me,
	NavCounts,
	Notification,
	OverdueItem,
	OwnerDetail,
	OwnerLeadCreate,
	OwnerListResponse,
	OwnerRecordCreate,
	OwnerReport,
	OwnerRow,
	OwnerTab,
	OwnerUnit,
	PortfolioResponse,
	PursuedMatch,
	PursueResult,
	RelationRow,
	Renewal,
	SearchResults,
	Tone,
	Written
} from '../types'
import { AREA_STATS, areaOfUnit } from './areas'
import {
	type DbDeal,
	type DbEvent,
	type DbLead,
	type DbListing,
	type DbOwner,
	type DbOwnerUnit,
	type DbPrior,
	db,
	ME,
	nextId
} from './db'
import type { DbInboxItem } from './matchdata'
import {
	addDays,
	CONTACT_OUTCOMES,
	CONVEYANCING,
	commission,
	dayLabel,
	daysFrom,
	deadlineChip,
	dealTypeOf,
	defaultCommission,
	detectColumns,
	discountChip,
	docsOf,
	dueChip,
	eventLabel,
	fitsBudget,
	fmt,
	formAChip,
	formAStatus,
	GATE_LINE,
	LEAD_STAGE_DOCS,
	LEAD_STAGES,
	LISTING_DOC_NOTES,
	LISTING_DOCS,
	LOST_REASONS,
	leadSummary,
	MATCH_OVER_BUDGET,
	matchDocument,
	mondayOf,
	normalisePhone,
	nowLabel,
	overBudgetChip,
	ownerActionable,
	ownerLeadType,
	parseCsv,
	permitChip,
	permitStatus,
	permitValid,
	RENT_STAGES,
	renewalChips,
	SALE_STAGES,
	STAGE_GATES,
	scoreLead,
	short,
	shortDate,
	stagesOf,
	TODAY,
	unitActionable
} from './rules'

/* ── plumbing ── */

type Body = Record<string, any>
interface Ctx {
	params: string[]
	query: URLSearchParams
	body: Body
	form: FormData | null
}
type Handler = (ctx: Ctx) => unknown | Promise<unknown>

const routes: { method: string; re: RegExp; handler: Handler }[] = []

function route(method: string, pattern: string, handler: Handler) {
	const re = new RegExp(`^${pattern.replace(/:[a-z_]+/g, '([^/]+)')}$`)
	routes.push({ method, re, handler })
}

export async function handle(method: string, url: string, body?: unknown): Promise<unknown> {
	const u = new URL(url, 'http://fixtures.local')
	const form = typeof FormData !== 'undefined' && body instanceof FormData ? body : null
	for (const r of routes) {
		if (r.method !== method) continue
		const m = u.pathname.match(r.re)
		if (!m) continue
		const params = m.slice(1).map(decodeURIComponent)
		const result = await r.handler({
			params,
			query: u.searchParams,
			body: form ? {} : ((body as Body) ?? {}),
			form
		})
		return result === undefined ? undefined : structuredClone(result)
	}
	throw new ApiError('That page of the CRM does not exist yet.', 404, 'not_found')
}

function notFound(what: string): never {
	throw new ApiError(`${what} not found.`, 404, 'not_found')
}

function invalid(message: string): never {
	throw new ApiError(message, 422, 'invalid')
}

/* ── undo registry ── */

const undoers = new Map<string, () => void>()
let tokenSeq = 0

function remember(revert: () => void): string {
	tokenSeq += 1
	const token = `u${tokenSeq}`
	undoers.set(token, revert)
	return token
}

function written<T>(data: T, revert: (() => void) | null, eventId?: number | null): Written<T> {
	return { data, undo_token: revert ? remember(revert) : null, event_id: eventId ?? null }
}

route('POST', '/undo', ({ body }) => {
	const fn = undoers.get(String(body.token))
	if (!fn) throw new ApiError('Nothing to undo.', 409, 'undo_expired')
	undoers.delete(String(body.token))
	fn()
	return { ok: true }
})

/* ── lookups and views ── */

const STAGE_LABEL: Record<LeadStage, string> = {
	new: 'New',
	contacted: 'Contacted',
	qualified: 'Qualified',
	viewing: 'Viewing',
	listed: 'Listed',
	offer: 'Offer',
	won: 'Won',
	lost: 'Lost'
}
const STAGE_ORDER: LeadStage[] = [
	'new',
	'contacted',
	'qualified',
	'viewing',
	'listed',
	'offer',
	'won',
	'lost'
]
const TYPE_LABEL: Record<LeadType, string> = {
	buyer: 'Buyer',
	seller: 'Seller',
	tenant: 'Tenant',
	landlord: 'Landlord'
}
const LEAD_TYPE_KEYS = Object.keys(TYPE_LABEL) as LeadType[]
const FIELD_LABEL: Record<LeadFieldKey, string> = {
	wants: 'Wants',
	budget_aed: 'Budget',
	finance: 'Finance',
	purpose: 'Buying to',
	timeline: 'Timeline',
	unit: 'Unit',
	target_price_aed: 'Target price',
	occupancy: 'Occupancy',
	mortgage: 'Mortgage',
	cheques: 'Cheques',
	move_in: 'Move-in',
	expected_rent_aed: 'Expected rent',
	available: 'Available',
	furnishing: 'Furnishing',
	areas: 'Areas',
	on_booking_aed: 'Can pay now',
	handover_by: 'Handover by'
}
const MONEY_FIELDS: LeadFieldKey[] = [
	'budget_aed',
	'target_price_aed',
	'expected_rent_aed',
	'on_booking_aed'
]
const OFF_PLAN_FIELDS: LeadFieldKey[] = ['areas', 'on_booking_aed', 'handover_by']
const TYPE_FIELDS: Record<LeadType, LeadFieldKey[]> = {
	buyer: ['wants', 'budget_aed', 'finance', 'purpose', 'timeline', ...OFF_PLAN_FIELDS],
	seller: ['unit', 'target_price_aed', 'occupancy', 'mortgage', 'timeline'],
	tenant: ['wants', 'budget_aed', 'cheques', 'move_in'],
	landlord: ['unit', 'expected_rent_aed', 'available', 'furnishing']
}

/*
 * Agent view only: an agent receives their own leads and deals. A colleague's record is a 404,
 * exactly as if it did not exist; colleagues' leads only ever appear as counts or anonymous rows.
 */
const findLead = (id: number | string) =>
	db.leads.find((l) => l.id === Number(id) && l.agent === ME) ?? notFound('Lead')
const findDeal = (id: string) =>
	db.deals.find((d) => d.id === id && d.agent === ME) ?? notFound('Deal')
const findListing = (id: string) => db.listings.find((x) => x.id === id) ?? notFound('Listing')
const findOwner = (id: string) => db.owners.find((o) => o.id === id) ?? notFound('Owner')
const myLeads = () => db.leads.filter((l) => l.agent === ME)
const myDeals = () => db.deals.filter((d) => d.agent === ME)
const myEvents = () => db.events.filter((e) => e.agent === ME && !e.done)
const isClosed = (d: DbDeal) => d.stage_index >= stagesOf(d.deal_type).length - 1
const isOpenLead = (l: DbLead) => l.stage !== 'won' && l.stage !== 'lost'
const ownerIdByName = (name: string | null) =>
	name ? (db.owners.find((o) => o.name === name)?.id ?? null) : null
const leadMoney = (l: DbLead) =>
	Number(l.fields.budget_aed || l.fields.target_price_aed || l.fields.expected_rent_aed || 0)

/* ── record of relationship (DLD Circular 02-2026) ── */

const PRIOR_KIND: Record<DbPrior['kind'], RelationRow['kind']> = {
	sale: 'Sale',
	tenancy: 'Tenancy',
	listing_agreement: 'Listing agreement'
}

/** The deal counterparty field reads "Mariam Al Falasi (seller)". */
const isParty = (field: string, name: string) => field === name || field.startsWith(`${name} (`)

/**
 * Deals, listings and past transactions with this owner. A listing counts only with a signed
 * Form A on file (not because a typed owner name matches); leads and call logs never count.
 */
function relationRows(o: DbOwner): RelationRow[] {
	const rows: RelationRow[] = []
	for (const d of db.deals) {
		if (!isParty(d.counterparty, o.name) && !isParty(d.client, o.name)) continue
		const role = isParty(d.counterparty, o.name)
			? (d.counterparty.match(/\((\w+)\)/)?.[1] ?? 'party')
			: d.deal_type === 'sale'
				? 'buyer'
				: 'tenant'
		rows.push({
			kind: 'Deal',
			transaction: true,
			text: `${role[0].toUpperCase()}${role.slice(1)} on ${d.id} · ${d.unit.split(' · ')[0]}`,
			date: d.due_date,
			ref: d.agent === ME ? { kind: 'deal', id: d.id } : null,
			added: false
		})
	}
	for (const x of db.listings) {
		if (x.owner !== o.name || !x.documents.some((d) => d.type === 'Form A')) continue
		rows.push({
			kind: 'Listing',
			transaction: true,
			text: `Owner of ${x.id} · ${x.unit} · Form A signed`,
			date: null,
			ref: { kind: 'listing', id: x.id },
			added: false
		})
	}
	for (const p of o.prior) {
		rows.push({
			kind: PRIOR_KIND[p.kind],
			transaction: true,
			text: `${PRIOR_KIND[p.kind]} · ${p.unit} · ${p.reference}`,
			date: p.date,
			ref: null,
			added: p.added
		})
	}
	for (const l of db.leads) {
		if (l.owner_id !== o.id || l.agent !== ME) continue
		rows.push({
			kind: 'Lead',
			transaction: false,
			text: `${TYPE_LABEL[l.lead_type]} lead · ${STAGE_LABEL[l.stage]}`,
			date: null,
			ref: { kind: 'lead', id: String(l.id) },
			added: false
		})
	}
	return rows
}

const hasPriorDeal = (o: DbOwner) => relationRows(o).some((r) => r.transaction)
const onAgencyFile = (o: DbOwner) => o.sources.includes('agency_import')
const ownerOf = (l: DbLead) => (l.owner_id ? db.owners.find((o) => o.id === l.owner_id) : undefined)

/** An owner-file lead whose owner has no documented prior transaction (no contact yet). */
function leadGated(l: DbLead): boolean {
	if (l.source !== 'file') return false
	const o = ownerOf(l)
	return !o || !hasPriorDeal(o)
}

function refuseGated(l: DbLead): void {
	if (leadGated(l))
		throw new ApiError(`${GATE_LINE}. ${l.name} has no prior deal on record.`, 409, 'no_prior_deal')
}

/** First part of the source detail: "Property Finder", "Lease ends in 41 days". */
const sourceShort = (l: DbLead) => l.source_detail.split(' · ')[0]

function anonLead(l: DbLead): AnonLead {
	const money = leadMoney(l)
	const word = l.lead_type === 'seller' ? 'target' : l.lead_type === 'landlord' ? 'rent' : 'budget'
	return {
		lead_type: l.lead_type,
		agent: l.agent ?? 'Unassigned',
		area: l.area,
		price_label: money ? `${word} ${short(money)}` : '',
		stage: l.stage
	}
}

function leadRow(l: DbLead): LeadRow {
	const listing = l.listing_id ? db.listings.find((x) => x.id === l.listing_id) : null
	return {
		id: l.id,
		name: l.name,
		phone: l.phone,
		lead_type: l.lead_type,
		deal_type: dealTypeOf(l.lead_type),
		source: l.source,
		source_detail: l.source_detail,
		received_label: l.received_label,
		stage: l.stage,
		agent: l.agent,
		score: l.score,
		area: l.area,
		language: l.language,
		next_action: l.next_action,
		off_plan: l.off_plan,
		gated: leadGated(l),
		owner_id: l.owner_id,
		fields: l.fields,
		summary: leadSummary(l.lead_type, l.fields),
		known: l.owner_match.summary,
		source_short: sourceShort(l),
		listing: listing ? { id: listing.id, label: listing.unit } : null
	}
}

function stageDocuments(l: DbLead): LeadDetail['stage_documents'] {
	const have = new Map(l.documents.map((d) => [d.type, d]))
	return Object.entries(LEAD_STAGE_DOCS[l.lead_type]).map(([stage, docs]) => ({
		stage: stage as LeadStage,
		docs: (docs ?? []).map((type) => {
			const f = have.get(type)
			return {
				type,
				note: LISTING_DOC_NOTES[type] ?? null,
				file: f ? { name: f.file, size_bytes: f.size_bytes } : null
			}
		})
	}))
}

function leadDetail(l: DbLead): LeadDetail {
	const listing = l.listing_id ? db.listings.find((x) => x.id === l.listing_id) : null
	const own = l.own_listing_id ? db.listings.find((x) => x.id === l.own_listing_id) : null
	const deal =
		db.deals.find((d) => d.lead_id === l.id) ??
		(own ? db.deals.find((d) => d.listing_id === own.id) : undefined)
	return {
		...leadRow(l),
		owner_match: {
			summary: l.owner_match.summary,
			records: l.owner_match.records.map((r) => ({ ...r, owner_id: ownerIdByName(r.owner_name) }))
		},
		pursued: [...(db.pursued[l.id] ?? [])],
		suggested_agent: l.agent ? null : l.suggested_agent,
		listing_card: listing ? listingCard(listing) : null,
		own_listing: own ? { id: own.id, label: own.unit, status: own.status } : null,
		deal: deal
			? { id: deal.id, label: deal.id, stage: stagesOf(deal.deal_type)[deal.stage_index] }
			: null,
		stage_documents: stageDocuments(l),
		can_undo: db.leadEvents.some((e) => e.lead_id === l.id && e.token && !e.reverted)
	}
}

function dealRow(d: DbDeal): DealRow {
	const stages = stagesOf(d.deal_type)
	const required = docsOf(d.deal_type)
	const have = new Set(d.documents.map((x) => x.type))
	const closed = isClosed(d)
	return {
		id: d.id,
		deal_type: d.deal_type,
		unit: d.unit,
		client: d.client,
		counterparty: d.counterparty,
		value_aed: d.value_aed,
		agent: d.agent,
		lead_id: d.lead_id,
		listing_id: d.listing_id,
		due_date: d.due_date,
		next_step: d.next_step,
		approval: d.approval,
		dld_transaction_id: d.dld_transaction_id,
		stages,
		stage_index: d.stage_index,
		stage: stages[d.stage_index],
		next_stage: closed ? null : stages[d.stage_index + 1],
		closed,
		docs_received: required.filter((r) => have.has(r)).length,
		docs_required: required.length,
		missing: required.filter((r) => !have.has(r)),
		due_chip: dueChip(d.due_date, closed),
		commission: { ...d.commission, amounts: commission(d.value_aed, d.commission) }
	}
}

function dealForms(d: DbDeal) {
	if (d.deal_type === 'rent') {
		return [
			{ code: 'tenancy', title: 'Tenancy contract', note: 'Pre-filled from this deal' },
			{ code: 'ejari', title: 'Ejari registration', note: 'Pre-filled from this deal' }
		]
	}
	return [
		{
			code: 'A',
			title: 'Form A — seller appoints the brokerage',
			note: 'Pre-filled from this deal'
		},
		{ code: 'B', title: 'Form B — buyer appoints a brokerage', note: 'Pre-filled from this deal' },
		{ code: 'F', title: 'Form F — contract of sale (MOU)', note: 'Pre-filled from this deal' },
		{
			code: 'I',
			title: 'Form I — agreement between brokerages',
			note: d.commission.cobroker_name
				? 'Pre-filled from this deal'
				: 'Only when another brokerage is involved'
		}
	]
}

/**
 * The conveyancing page: one block per stage with who is involved, its checklist and that
 * stage's documents. Stages before the current one count as done (a missing document still
 * shows); on the current stage the first item is done on arrival and the rest are ticked by hand.
 */
function checklist(d: DbDeal): ChecklistStage[] {
	const stages = stagesOf(d.deal_type)
	const docs = new Map(d.documents.map((x) => [x.type, x]))
	const n = daysFrom(d.due_date)
	const closed = isClosed(d)
	return CONVEYANCING[d.deal_type].map((req, i) => {
		const items = req.items.map((it, j) => {
			const key = `${i}:${j}`
			if (typeof it === 'object') {
				const f = docs.get(it.doc)
				return {
					key,
					label: it.label ?? it.doc,
					doc: it.doc,
					done: Boolean(f),
					file: f ? { name: f.file, uploaded: f.uploaded } : null
				}
			}
			const done =
				i < d.stage_index || (closed && i === d.stage_index)
					? true
					: i > d.stage_index
						? false
						: (d.checks[key] ?? j === 0)
			return { key, label: it, doc: null, done, file: null }
		})
		const missing = items.filter((t) => t.doc && !t.done).length
		const state: ChecklistStage['state'] =
			i < d.stage_index ? 'done' : i === d.stage_index ? 'now' : 'next'
		const chip: Chip =
			state === 'done'
				? missing
					? { tone: 'amber', label: `Done · ${missing} missing` }
					: { tone: 'green', label: 'Done' }
				: state === 'now'
					? closed
						? { tone: 'green', label: 'Closed' }
						: {
								tone: n <= 0 ? 'red' : 'amber',
								label: `Now · ${n === 0 ? 'today' : n < 0 ? `${-n}d late` : `due ${dayLabel(d.due_date)}`}`
							}
					: { tone: 'neutral', label: `${items.filter((t) => t.done).length}/${items.length}` }
		return { index: i, name: stages[i], who: req.who, state, chip, items }
	})
}

function dealDetail(d: DbDeal): DealDetail {
	const listing = d.listing_id ? db.listings.find((x) => x.id === d.listing_id) : null
	const lead = d.lead_id ? db.leads.find((l) => l.id === d.lead_id) : null
	return {
		...dealRow(d),
		documents: { required: docsOf(d.deal_type), received: d.documents },
		compliance: { ...d.compliance, goaml_required: d.compliance.cash_aed >= 55000 },
		listing: listing ? { id: listing.id, label: listing.unit } : null,
		lead: lead ? { id: String(lead.id), label: lead.name } : null,
		forms: dealForms(d),
		checklist: checklist(d)
	}
}

function listingCard(x: DbListing): ListingCard {
	return {
		id: x.id,
		unit: x.unit,
		area: x.area,
		bedrooms: x.bedrooms,
		size_sqft: x.size_sqft,
		price_aed: x.price_aed,
		deal_type: x.deal_type,
		status: x.status,
		scope: x.agent === ME ? 'mine' : 'company',
		agent: x.agent,
		owner: x.owner,
		portals: x.portals,
		days_live: x.days_live,
		enquiries: x.enquiries,
		permit: x.permit,
		permit_chip: permitChip(x.permit),
		form_a_expires: x.form_a_expires,
		form_a_chip: formAChip(x.form_a_expires),
		comparables_note: x.comparables_note,
		from_lead_id: x.from_lead_id
	}
}

/** My buyers/tenants for a listing: same deal type, same area or a budget near the price. */
function listingMatches(x: DbListing, limit = 5): DbLead[] {
	return myLeads()
		.filter(
			(l) =>
				(l.lead_type === 'buyer' || l.lead_type === 'tenant') &&
				dealTypeOf(l.lead_type) === x.deal_type &&
				l.source !== 'file' &&
				isOpenLead(l) &&
				(l.area === x.area ||
					(Number(l.fields.budget_aed) >= x.price_aed * 0.85 &&
						Number(l.fields.budget_aed) <= x.price_aed * 1.3))
		)
		.slice(0, limit)
}

/**
 * A colleague's listing: how many leads and the stage of each, nothing more. Where the sample
 * data has no lead rows for the enquiries, they are spread over the early stages (fixtures only).
 */
function leadStageCounts(x: DbListing): { stage: LeadStage; count: number }[] {
	const on = db.leads.filter((l) => l.listing_id === x.id && isOpenLead(l))
	const mix: Partial<Record<LeadStage, number>> = {}
	if (on.length) for (const l of on) mix[l.stage] = (mix[l.stage] ?? 0) + 1
	else if (x.enquiries) {
		const n = x.enquiries
		mix.new = Math.max(0, n - 2)
		if (n > 1) mix.viewing = 1
		mix.contacted = 1
	}
	return STAGE_ORDER.filter((s) => mix[s]).map((s) => ({ stage: s, count: mix[s] ?? 0 }))
}

function listingDetail(x: DbListing): ListingDetail {
	const from = x.from_lead_id ? db.leads.find((l) => l.id === x.from_lead_id) : null
	const mine = x.agent === ME
	return {
		...listingCard(x),
		documents: { required: LISTING_DOCS, notes: LISTING_DOC_NOTES, received: x.documents },
		form_a_status: formAStatus(
			x.documents.some((d) => d.type === 'Form A'),
			x.form_a_expires
		),
		permit_status: permitStatus(x.permit),
		leads: mine ? db.leads.filter((l) => l.listing_id === x.id && isOpenLead(l)).map(leadRow) : [],
		lead_stages: mine ? null : leadStageCounts(x),
		deals: mine
			? db.deals
					.filter((d) => d.listing_id === x.id)
					.map((d) => ({ id: d.id, client: d.client, stage: stagesOf(d.deal_type)[d.stage_index] }))
			: [],
		matched: listingMatches(x).map(leadRow),
		from_lead:
			from && from.agent === ME
				? { id: from.id, name: from.name, lead_type: from.lead_type }
				: null,
		can_publish: permitValid(x.permit)
	}
}

/** Source names (7 Oct): Own contact · Agency file · DLD/Ejari event. */
const OWNER_SOURCE_NAMES: Record<DbOwner['sources'][number], string> = {
	agent_contact: 'Own contact',
	agency_import: 'Agency file',
	dld_event: 'DLD/Ejari event'
}
const OWNER_SOURCE_LABEL = (o: DbOwner) => o.sources.map((x) => OWNER_SOURCE_NAMES[x]).join(' · ')

const unitKey = (u: DbOwnerUnit) => `${u.building}#${u.number}`
const unitShort = (u: DbOwnerUnit) => `${u.building} #${u.number}`
const unitLabel = (u: DbOwnerUnit) =>
	`${unitShort(u)} · ${u.bedrooms === null ? '—' : u.bedrooms ? `${u.bedrooms}BR` : 'Studio'}`

/** The open lead for this owner (same person), mine or a colleague's, if any. */
function ownerLead(o: DbOwner): DbLead | undefined {
	return db.leads.find(
		(l) =>
			(l.owner_id === o.id || l.name === o.name || (o.phone && l.phone === o.phone)) &&
			l.stage !== 'lost' &&
			l.stage !== 'won'
	)
}

function ownerRow(o: DbOwner): OwnerRow {
	const l = ownerLead(o)
	const lead = l
		? { id: l.agent === ME ? l.id : null, stage: l.stage, agent: l.agent ?? 'Unassigned' }
		: null
	return {
		id: o.id,
		name: o.name,
		sources: o.sources,
		source_label: OWNER_SOURCE_LABEL(o),
		units: o.units.map(unitShort),
		next_event: o.next_event,
		next_event_date: o.next_event_date,
		next_event_label: eventLabel(o.next_event_date),
		last_contact: o.last_contact,
		tag: o.tag,
		market_update_due: o.market_update_due,
		mine: o.sources.includes('agent_contact'),
		on_file: onAgencyFile(o),
		prior_deal: hasPriorDeal(o),
		lead
	}
}

function leaseEnd(u: DbOwnerUnit): string | null {
	return u.rent?.to ?? null
}

function ownerUnit(u: DbOwnerUnit): OwnerUnit {
	const s = u.status
	return {
		key: unitKey(u),
		number: u.number,
		building: u.building,
		area: u.area,
		type: u.type,
		bedrooms: u.bedrooms,
		size_sqft: u.size_sqft,
		bought_aed: u.bought_aed,
		bought_year: u.bought_year,
		status: s,
		status_chip: {
			tone: /Vacant/.test(s) ? 'amber' : /Let/.test(s) ? 'green' : 'neutral',
			label: s.split(' · ')[0]
		},
		rent: u.rent,
		market: u.market,
		rent_history: u.rent_history.map(([year, aed]) => ({ year, aed })),
		transactions: u.transactions.map(([when, what, aed]) => ({ when, what, aed: aed || null }))
	}
}

/** Lead events carry the lead's type and source: "Buyer · Property Finder". */
function eventContext(e: DbEvent): string | null {
	if (!e.lead_id) return null
	const l = db.leads.find((x) => x.id === e.lead_id)
	return l ? `${TYPE_LABEL[l.lead_type]} · ${sourceShort(l)}` : null
}

function eventView(e: DbEvent): CalendarEvent {
	return {
		id: e.id,
		date: e.date,
		time: e.time,
		kind: e.kind,
		title: e.title,
		detail: e.detail,
		agent: e.agent,
		lead_id: e.lead_id,
		deal_id: e.deal_id,
		listing_id: e.listing_id,
		owner_id: e.owner_id,
		context: eventContext(e),
		record: eventRecord(e),
		outcome:
			e.kind === 'viewing' && e.date < TODAY
				? db.leads.find((l) => l.id === e.lead_id)?.viewing_outcome_due === e.date
					? 'No outcome logged'
					: 'Logged on the lead'
				: null
	}
}

function eventRecord(e: DbEvent): CalendarEvent['record'] {
	if (e.lead_id) {
		const l = db.leads.find((x) => x.id === e.lead_id)
		if (l && l.agent === ME)
			return {
				kind: 'lead',
				id: String(l.id),
				label: `${l.name} · ${TYPE_LABEL[l.lead_type]} lead`
			}
	}
	if (e.deal_id && db.deals.some((d) => d.id === e.deal_id && d.agent === ME))
		return { kind: 'deal', id: e.deal_id, label: `Deal ${e.deal_id}` }
	if (e.listing_id) {
		const x = db.listings.find((v) => v.id === e.listing_id)
		if (x) return { kind: 'listing', id: x.id, label: `${x.id} · ${x.unit}` }
	}
	if (e.owner_id) {
		const o = db.owners.find((v) => v.id === e.owner_id)
		if (o) return { kind: 'owner', id: o.id, label: `Owner · ${o.name}` }
	}
	return null
}

const byTime = (a: DbEvent, b: DbEvent) =>
	a.date.localeCompare(b.date) || (a.time ?? '99').localeCompare(b.time ?? '99')

/* ── lead history ── */

function logLead(l: DbLead, text: string, origin: LeadEvent['origin'], token: string | null) {
	const ev = { id: nextId(), lead_id: l.id, at: nowLabel(), text, origin, token, reverted: false }
	db.leadEvents.push(ev)
	return ev
}

/** Snapshot a lead, run a change that logs history under one token, and make it undoable. */
function changeLead<T>(l: DbLead, change: (token: string) => T, extraRevert?: () => void) {
	const before = structuredClone(l)
	tokenSeq += 1
	const token = `u${tokenSeq}`
	const result = change(token)
	l.last_activity = TODAY
	undoers.set(token, () => {
		Object.assign(l, before)
		for (const e of db.leadEvents) if (e.token === token) e.reverted = true
		extraRevert?.()
	})
	const lastEvent = [...db.leadEvents].reverse().find((e) => e.token === token)
	return { result, token, eventId: lastEvent?.id ?? null }
}

/* ── me, counts ── */

route(
	'GET',
	'/me',
	(): Me => ({
		name: ME,
		initials: ME.split(/\s+/)
			.map((p: string) => p[0])
			.join('')
			.replace('.', '')
			.slice(0, 2)
			.toUpperCase(),
		role: 'agent',
		today: TODAY,
		areas: db.areas
	})
)

route(
	'GET',
	'/crm/counts',
	(): NavCounts => ({
		new_leads: myLeads().filter((l) => l.stage === 'new').length,
		inbox:
			db.inbox.filter((x) => x.agent === ME && x.status === 'assigned' && !x.lead_id).length +
			db.inbox.filter((x) => x.agent === ME && (x.status === 'waiting' || x.status === 'requested'))
				.length,
		open_deals: myDeals().filter((d) => !isClosed(d)).length,
		events_today: myEvents().filter((e) => e.date === TODAY).length,
		waiting: db.inbox.filter((x) => x.status === 'waiting' || x.status === 'requested').length,
		unread_notifications: db.notifications.filter((n) => n.unread).length
	})
)

/* ── home ── */

function overdueItems(): OverdueItem[] {
	const out: OverdueItem[] = []
	for (const l of myLeads()) {
		if (l.viewing_outcome_due) {
			out.push({
				text: `Viewing outcome not logged — ${l.name}`,
				detail: `Viewing was ${dayLabel(l.viewing_outcome_due)}`,
				lead_id: l.id
			})
		}
	}
	for (const l of myLeads()) {
		const quiet = -daysFrom(l.last_activity)
		if (isOpenLead(l) && quiet >= 5) {
			out.push({
				text: `No activity in ${quiet} days — ${l.name}`,
				detail: `Last: ${l.last_activity_text || 'no notes'}`,
				lead_id: l.id
			})
		}
	}
	return out
}

function gaps(): Gap[] {
	const out: Gap[] = []
	for (const l of myLeads()) {
		if (l.viewing_outcome_due) {
			out.push({
				text: `What happened at ${l.name}'s viewing?`,
				detail: `Viewing ${dayLabel(l.viewing_outcome_due)} · no outcome`,
				ref_type: 'lead',
				ref_id: String(l.id)
			})
		}
	}
	for (const d of myDeals()) {
		const row = dealRow(d)
		if (!row.closed && row.missing.length) {
			out.push({
				text: `${d.id} is missing ${row.missing.length} document${row.missing.length > 1 ? 's' : ''}`,
				detail: row.missing.join(', '),
				ref_type: 'deal',
				ref_id: d.id
			})
		}
	}
	for (const l of myLeads()) {
		if (l.source === 'agent_to_agent' && !l.form_i_on_file && isOpenLead(l)) {
			out.push({
				text: `Form I not on file — ${l.name}`,
				detail: 'Agent-to-agent · before sharing unit details',
				ref_type: 'lead',
				ref_id: String(l.id)
			})
		}
	}
	for (const l of myLeads()) {
		if (l.source !== 'file' || l.stage !== 'new') continue
		const gated = leadGated(l)
		out.push({
			text: gated ? `No prior deal record — ${l.name}` : `No first call logged — ${l.name}`,
			detail: gated ? `${GATE_LINE.toLowerCase()} · ${sourceShort(l)}` : l.source_detail,
			ref_type: 'lead',
			ref_id: String(l.id)
		})
	}
	return out
}

route('GET', '/crm/home', ({ query }): HomeResponse => {
	const day = query.get('day') || TODAY
	const deals = myDeals()
	const open = deals.filter((d) => !isClosed(d))
	let received = 0
	let due = 0
	for (const d of deals) {
		const agentShare = commission(d.value_aed, d.commission).agent
		if (d.commission.invoice_status === 'received') received += agentShare
		else if (d.commission.invoice_status === 'due' || d.commission.invoice_status === 'overdue')
			due += agentShare
	}
	const events = myEvents()
	const monday = mondayOf(TODAY)
	const week = Array.from({ length: 7 }, (_, i) => {
		const date = addDays(monday, i)
		return { date, kinds: events.filter((e) => e.date === date).map((e) => e.kind) }
	})
	const newLeads = myLeads()
		.filter((l) => l.stage === 'new')
		.sort((a, b) => b.score - a.score)
	const within14 = (date: string | null | undefined) =>
		Boolean(date) && daysFrom(String(date)) >= 0 && daysFrom(String(date)) <= 14
	const mine = db.listings.filter((x) => x.agent === ME)
	const permits = mine.filter((x) => within14(x.permit?.expires)).length
	const formA = mine.filter((x) => within14(x.form_a_expires)).length
	const viewings = events
		.filter((e) => e.kind === 'viewing' && e.date >= monday && e.date < addDays(monday, 7))
		.sort(byTime)
	const nextViewing = viewings.find((e) => e.date >= TODAY)
	const firstArea = db.areas[0]
	const stats = firstArea ? AREA_STATS[firstArea] : undefined
	return {
		date: TODAY,
		facts: {
			events_today: events.filter((e) => e.date === TODAY).length,
			conveyancing: open.length,
			permits_under_14: permits
		},
		counters: {
			viewings_week: {
				count: viewings.length,
				next: nextViewing
					? `next ${dayLabel(nextViewing.date).split(' ')[0]} ${nextViewing.time ?? ''} · ${nextViewing.title.replace(/^.*— /, '')}`.replace(
							/ {2}/,
							' '
						)
					: null
			},
			expiring_14: { count: permits + formA, permits, form_a: formA },
			market:
				firstArea && stats
					? {
							area: firstArea,
							psf_aed: stats.psf,
							rent_median_aed: stats.rent,
							yield_pct: stats.yld
						}
					: null,
			new_leads: newLeads.length,
			overdue: overdueItems().length,
			conveyancing: { count: open.length, value_aed: open.reduce((s, d) => s + d.value_aed, 0) },
			commission: { received_aed: received, due_aed: due }
		},
		week,
		day: events
			.filter((e) => e.date === day)
			.sort(byTime)
			.map(eventView),
		conveyancing: deals.map(dealRow),
		new_leads: newLeads.map(leadRow),
		gaps: gaps(),
		file_leads: myLeads()
			.filter((l) => l.source === 'file' && (l.stage === 'new' || l.stage === 'contacted'))
			.sort((a, b) => b.score - a.score)
			.map(leadRow)
	}
})

/* ── leads ── */

/* "All filters" on Leads: bedrooms, property type and budget band, read from the lead's fields. */
function leadBeds(l: DbLead): string {
	const t = `${l.fields.unit ?? ''} ${l.fields.wants ?? ''}`
	if (/studio/i.test(t)) return '0'
	const m = t.match(/(\d)\s?BR/i)
	return m ? (Number(m[1]) >= 4 ? '4' : m[1]) : ''
}
const leadKind = (l: DbLead) =>
	/villa|townhouse/i.test(`${l.fields.unit ?? ''} ${l.fields.wants ?? ''}`) ? 'villa' : 'apartment'
function leadBand(l: DbLead): string {
	const v = leadMoney(l)
	if (!v) return ''
	if (dealTypeOf(l.lead_type) === 'rent') return v < 100000 ? 'r1' : 'r2'
	return v < 1000000 ? 's1' : v <= 3000000 ? 's2' : 's3'
}

route('GET', '/leads', ({ query }): LeadListResponse => {
	const base = myLeads()
	const type = query.get('lead_type') as LeadType | null
	const lost = query.get('lost') === 'true'
	const source = query.get('source')
	const stage = query.get('stage')
	const area = query.get('area')
	const beds = query.get('beds')
	const ptype = query.get('ptype')
	const budget = query.get('budget')
	const q = (query.get('q') ?? '').trim().toLowerCase()
	const items = base
		// Lost tab: lost leads only. Other tabs leave them out unless the Stage filter asks for Lost.
		.filter((l) => (lost ? l.stage === 'lost' : l.stage !== 'lost' || stage === 'lost'))
		.filter((l) => !type || lost || l.lead_type === type)
		.filter((l) => !source || l.source === source)
		.filter((l) => !stage || l.stage === stage)
		.filter((l) => !area || l.area === area)
		.filter((l) => !beds || leadBeds(l) === beds)
		.filter((l) => !ptype || leadKind(l) === ptype)
		.filter((l) => !budget || leadBand(l) === budget)
		.filter((l) => {
			if (!q) return true
			const hay = [l.name, l.phone, l.area, l.source_detail, l.fields.wants, l.fields.unit]
				.join(' ')
				.toLowerCase()
			return hay.includes(q) || l.phone.replace(/\D/g, '').includes(q.replace(/\D/g, '') || '§')
		})
		.sort((a, b) => b.score - a.score)
	const live = base.filter((l) => l.stage !== 'lost')
	return {
		items: items.map(leadRow),
		total: items.length,
		counts: {
			all: live.length,
			buyer: live.filter((l) => l.lead_type === 'buyer').length,
			seller: live.filter((l) => l.lead_type === 'seller').length,
			tenant: live.filter((l) => l.lead_type === 'tenant').length,
			landlord: live.filter((l) => l.lead_type === 'landlord').length,
			lost: base.length - live.length
		},
		new_count: base.filter((l) => l.stage === 'new').length,
		areas: [...new Set(base.map((l) => l.area))].sort()
	}
})

route('GET', '/leads/:id', ({ params }) => leadDetail(findLead(params[0])))

route('GET', '/leads/:id/events', ({ params }): LeadEvent[] => {
	const l = findLead(params[0])
	return db.leadEvents
		.filter((e) => e.lead_id === l.id && !e.reverted)
		.reverse()
		.map((e) => ({
			id: e.id,
			at: e.at,
			text: e.text,
			origin: e.origin,
			revertible: Boolean(e.token)
		}))
})

function cleanFields(type: LeadType, fields: LeadFields | undefined): LeadFields {
	const out: LeadFields = {}
	for (const k of TYPE_FIELDS[type]) {
		const raw = fields?.[k]
		if (raw === undefined || raw === null || String(raw).trim() === '') continue
		out[k] = MONEY_FIELDS.includes(k) ? Math.round(Number(raw)) || 0 : String(raw).trim()
	}
	return out
}

/** Owner matching: the normalised phone against owner data (agency imports + DLD/Ejari). */
function ownerMatchFor(phone: string, source: LeadCreate['source']): DbLead['owner_match'] {
	if (source === 'agent_to_agent') return { summary: 'Broker — no owner match used', records: [] }
	const hit = db.ownerData[phone]
	return hit ? structuredClone(hit) : { summary: "Not on your agency's file", records: [] }
}

route('POST', '/leads', ({ body }): Written<LeadDetail> => {
	const input = body as LeadCreate
	if (!String(input.name ?? '').trim()) invalid('Enter a name.')
	const phone = normalisePhone(String(input.phone ?? ''))
	if (!phone) invalid('Enter a UAE mobile number, e.g. 050 123 4567.')
	const type = input.lead_type
	const fields = cleanFields(type, input.fields)
	const id = Math.max(...db.leads.map((l) => l.id)) + 1
	const match = ownerMatchFor(phone, input.source)
	const lead: DbLead = {
		id,
		name: input.name.trim(),
		phone,
		lead_type: type,
		source: input.source,
		source_detail: input.source_detail || 'Added by hand',
		received_label: 'just now',
		stage: 'new',
		agent: ME,
		score: scoreLead(input.source, fields),
		area: input.area?.trim() || '—',
		language: '—',
		next_action: 'Call within 5 minutes',
		listing_id: null,
		own_listing_id: null,
		off_plan: false,
		fields,
		owner_match: match,
		suggested_agent: null,
		last_activity: TODAY,
		last_activity_text: 'lead created',
		viewing_outcome_due: null,
		form_i_on_file: false,
		first_call_logged: false,
		documents: [],
		owner_id: db.owners.find((o) => o.phone === phone)?.id ?? null,
		offer: null
	}
	db.leads.push(lead)
	logLead(lead, 'Lead created by hand', 'human', null)
	logLead(lead, `Phone normalised to ${phone}`, 'rule', null)
	logLead(lead, `Owner cross-reference: ${match.summary}`, 'rule', null)
	return written(leadDetail(lead), () => {
		db.leads.splice(db.leads.indexOf(lead), 1)
		db.leadEvents = db.leadEvents.filter((e) => e.lead_id !== lead.id)
	})
})

route('PATCH', '/leads/:id', ({ params, body }): Written<LeadDetail> => {
	const l = findLead(params[0])
	const patch = body as LeadPatch
	const phone = patch.phone === undefined ? undefined : normalisePhone(String(patch.phone))
	if (phone === null) invalid('Enter a UAE mobile number, e.g. 050 123 4567.')
	const { token, eventId } = changeLead(l, (tok) => {
		if (phone && phone !== l.phone) {
			logLead(l, `Phone ${l.phone} → ${phone}`, 'human', tok)
			l.phone = phone
			const match = ownerMatchFor(phone, l.source)
			l.owner_match = match
			l.owner_id = db.owners.find((o) => o.phone === phone)?.id ?? null
			logLead(l, `Owner cross-reference: ${match.summary}`, 'rule', tok)
		}
		if (patch.stage && patch.stage !== l.stage) {
			logLead(l, `Stage ${STAGE_LABEL[l.stage]} → ${STAGE_LABEL[patch.stage]}`, 'human', tok)
			l.stage = patch.stage
			l.last_activity_text = `stage → ${STAGE_LABEL[patch.stage].toLowerCase()}`
		}
		if (patch.off_plan !== undefined && patch.off_plan !== l.off_plan) {
			if (patch.off_plan && l.lead_type !== 'buyer') invalid('Only a buyer can be off-plan.')
			logLead(l, patch.off_plan ? 'Marked off-plan' : 'No longer off-plan', 'human', tok)
			l.off_plan = patch.off_plan
			if (!l.off_plan) for (const k of OFF_PLAN_FIELDS) delete l.fields[k]
		}
		if (patch.lead_type && patch.lead_type !== l.lead_type) {
			logLead(
				l,
				`Lead type ${TYPE_LABEL[l.lead_type]} → ${TYPE_LABEL[patch.lead_type]}`,
				'human',
				tok
			)
			l.lead_type = patch.lead_type
		}
		if (patch.fields) {
			// Only keys sent in the request change; an explicit null clears a field.
			const sent = patch.fields
			const next = cleanFields(l.lead_type, sent)
			for (const k of TYPE_FIELDS[l.lead_type]) {
				if (!(k in sent)) continue
				const was = l.fields[k] ?? null
				const now = next[k] ?? null
				if (String(was ?? '') === String(now ?? '')) continue
				const show = (v: unknown) =>
					v === null || v === '' ? '—' : MONEY_FIELDS.includes(k) ? fmt(Number(v)) : String(v)
				logLead(l, `${FIELD_LABEL[k]}: ${show(was)} → ${show(now)}`, 'human', tok)
				if (now === null) delete l.fields[k]
				else l.fields[k] = now
			}
		}
		if (patch.next_action !== undefined && patch.next_action.trim() !== l.next_action) {
			logLead(l, `Next action: ${patch.next_action.trim() || '—'}`, 'human', tok)
			l.next_action = patch.next_action.trim()
		}
		if (patch.language !== undefined && patch.language.trim() !== l.language) {
			logLead(l, `Language: ${patch.language.trim() || '—'}`, 'human', tok)
			l.language = patch.language.trim()
		}
	})
	const changed = db.leadEvents.some((e) => e.token === token)
	if (!changed) undoers.delete(token)
	return { data: leadDetail(l), undo_token: changed ? token : null, event_id: eventId }
})

route('POST', '/leads/:id/undo', ({ params, body }) => {
	const l = findLead(params[0])
	const candidates = db.leadEvents.filter((e) => e.lead_id === l.id && e.token && !e.reverted)
	const target = body.event_id
		? candidates.find((e) => e.id === Number(body.event_id))
		: candidates[candidates.length - 1]
	if (!target?.token) throw new ApiError('Nothing to undo on this lead.', 409, 'undo_expired')
	const text = target.text
	const fn = undoers.get(target.token)
	if (!fn) throw new ApiError('That change can no longer be undone.', 409, 'undo_expired')
	undoers.delete(target.token)
	fn()
	return { data: leadDetail(l), undone: text }
})

route('POST', '/leads/:id/notes', ({ params, body }) => {
	const l = findLead(params[0])
	const text = String(body.text ?? '').trim()
	if (!text) invalid('Write a note first.')
	const { token, eventId } = changeLead(l, (tok) => {
		logLead(l, `Note: ${text}`, 'human', tok)
		l.last_activity_text = 'note added'
		l.viewing_outcome_due = null
	})
	return { data: leadDetail(l), undo_token: token, event_id: eventId }
})

route('POST', '/leads/:id/calls', ({ params, body }) => {
	const l = findLead(params[0])
	refuseGated(l)
	const { token, eventId } = changeLead(l, (tok) => {
		logLead(l, body.outcome ? `Call logged: ${body.outcome}` : 'Call logged', 'human', tok)
		if (l.stage === 'new') l.stage = 'contacted'
		l.first_call_logged = true
		l.viewing_outcome_due = null
		l.last_activity_text = 'call logged'
	})
	return { data: leadDetail(l), undo_token: token, event_id: eventId }
})

route('POST', '/leads/:id/viewings', ({ params, body }) => {
	const l = findLead(params[0])
	refuseGated(l)
	const listing = body.listing_id ? findListing(String(body.listing_id)) : null
	if (!body.date) invalid('Pick a date.')
	const ev: DbEvent = {
		id: nextId(),
		date: String(body.date),
		time: body.time ? String(body.time) : null,
		kind: 'viewing',
		title: `Viewing — ${l.name}`,
		detail:
			[listing ? `${listing.unit} · ${listing.area}` : null, body.note]
				.filter(Boolean)
				.join(' · ') || 'Unit to confirm',
		agent: l.agent ?? ME,
		lead_id: l.id,
		deal_id: null,
		listing_id: listing?.id ?? null,
		owner_id: null,
		done: false
	}
	const { token, eventId } = changeLead(
		l,
		(tok) => {
			db.events.push(ev)
			// Booking a viewing moves a buyer or tenant to Viewing (a seller never has that stage).
			if (
				LEAD_STAGES[l.lead_type].includes('viewing') &&
				STAGE_ORDER.indexOf(l.stage) < STAGE_ORDER.indexOf('viewing')
			)
				l.stage = 'viewing'
			logLead(l, `Viewing booked ${dayLabel(ev.date)}${ev.time ? ` ${ev.time}` : ''}`, 'human', tok)
			l.last_activity_text = 'viewing booked'
		},
		() => {
			db.events = db.events.filter((e) => e.id !== ev.id)
		}
	)
	return { data: eventView(ev), undo_token: token, event_id: eventId }
})

/**
 * Moving a lead to a stage asks for what that stage needs (business-rules.md, Lead stages):
 * Contacted → how it went + next action · Qualified → the type's fields, money required ·
 * Viewing → date, time, unit (adds a calendar event) · Offer → amount (+ unit, or from whom) ·
 * Lost → reason. Buyer/tenant Won goes through POST /deals. One undo token for the whole move.
 */
route('POST', '/leads/:id/stage', ({ params, body }): Written<LeadDetail> => {
	const l = findLead(params[0])
	const m = body as LeadStageMove
	if (!STAGE_ORDER.includes(m.stage)) invalid('Pick a stage.')
	if (m.stage === l.stage) invalid(`${l.name} is already at ${STAGE_LABEL[m.stage]}.`)
	const buyerSide = l.lead_type === 'buyer' || l.lead_type === 'tenant'
	if (!LEAD_STAGES[l.lead_type].includes(m.stage))
		invalid(
			m.stage === 'viewing'
				? `A ${TYPE_LABEL[l.lead_type].toLowerCase()} has no Viewing stage — use Listed.`
				: `A ${TYPE_LABEL[l.lead_type].toLowerCase()} has no ${STAGE_LABEL[m.stage]} stage.`
		)
	if (m.stage !== 'lost') refuseGated(l)
	const note = String(m.note ?? '').trim()
	let detail = ''
	let fields: LeadFields | null = null
	let ev: DbEvent | null = null
	let offer: DbLead['offer'] = null
	let listed: DbListing | null = null

	if (m.stage === 'contacted') {
		const outcome = String(m.outcome ?? '')
		if (!CONTACT_OUTCOMES.includes(outcome)) invalid('Pick how it went.')
		if (!String(m.next_action ?? '').trim()) invalid('Enter the next action.')
		detail = outcome
	} else if (m.stage === 'qualified') {
		fields = cleanFields(l.lead_type, { ...l.fields, ...m.fields })
		const money = TYPE_FIELDS[l.lead_type].find((k) => MONEY_FIELDS.includes(k))
		if (money && !fields[money]) invalid(`Enter the ${FIELD_LABEL[money].toLowerCase()}.`)
	} else if (m.stage === 'viewing') {
		const v = m.viewing
		if (!v?.date) invalid('Pick a date.')
		if (!v.time) invalid('Pick a time.')
		const listing = v.listing_id ? findListing(v.listing_id) : null
		ev = {
			id: nextId(),
			date: v.date,
			time: v.time,
			kind: 'viewing',
			title: `Viewing — ${l.name}`,
			detail: listing ? `${listing.unit} · ${listing.area}` : 'Unit to confirm',
			agent: l.agent ?? ME,
			lead_id: l.id,
			deal_id: null,
			listing_id: listing?.id ?? null,
			owner_id: null,
			done: false
		}
		detail = `${dayLabel(v.date)} ${v.time}${listing ? ` · ${listing.unit}` : ''}`
	} else if (m.stage === 'listed') {
		// Listed opens the pocket listing form; the listing is linked to the lead (7 Oct).
		if (l.own_listing_id) {
			detail = `listing ${l.own_listing_id}`
		} else {
			if (!m.listing) invalid('Fill in the pocket listing.')
			listed = makeListing({ ...m.listing, status: 'pocket' }, l).listing
			detail = `pocket listing ${listed.id} · ${listed.unit}`
		}
	} else if (m.stage === 'offer') {
		const amount = Math.round(Number(m.offer?.amount_aed))
		if (!(amount > 0)) invalid('Enter the offer amount.')
		const from = String(m.offer?.from ?? '').trim()
		if (!buyerSide && !from) invalid('Enter who the offer is from.')
		const listing = m.offer?.listing_id ? findListing(m.offer.listing_id) : null
		offer = { amount_aed: amount, listing_id: listing?.id ?? null, from }
		detail = `AED ${fmt(amount)}${listing ? ` · ${listing.unit}` : ''}${from ? ` from ${from}` : ''}`
	} else if (m.stage === 'won') {
		if (buyerSide) invalid('A buyer or tenant is won when the deal is created — use Move to deal.')
		detail = 'signed'
	} else if (m.stage === 'lost') {
		const why = String(m.lost_reason ?? '')
		if (!LOST_REASONS.includes(why)) invalid('Pick why the lead was lost.')
		detail = why
	}

	const { token, eventId } = changeLead(
		l,
		(tok) => {
			if (fields) {
				for (const k of TYPE_FIELDS[l.lead_type]) {
					const was = l.fields[k] ?? null
					const now = fields[k] ?? null
					if (String(was ?? '') === String(now ?? '')) continue
					const show = (v: unknown) =>
						v === null || v === '' ? '—' : MONEY_FIELDS.includes(k) ? fmt(Number(v)) : String(v)
					logLead(l, `${FIELD_LABEL[k]}: ${show(was)} → ${show(now)}`, 'human', tok)
				}
				l.fields = fields
			}
			if (m.stage === 'contacted') {
				l.next_action = String(m.next_action).trim()
				l.first_call_logged = true
			}
			if (ev) {
				db.events.push(ev)
				l.viewing_outcome_due = null
			}
			if (offer) l.offer = offer
			if (listed) {
				db.listings.push(listed)
				l.own_listing_id = listed.id
			}
			const text = [`Stage ${STAGE_LABEL[l.stage]} → ${STAGE_LABEL[m.stage]}`, detail, note]
				.filter(Boolean)
				.join(' · ')
			logLead(l, text, 'human', tok)
			l.stage = m.stage
			l.last_activity_text = `stage → ${STAGE_LABEL[m.stage].toLowerCase()}`
		},
		() => {
			if (ev) db.events = db.events.filter((e) => e.id !== ev?.id)
			if (listed) db.listings = db.listings.filter((x) => x.id !== listed?.id)
		}
	)
	return { data: leadDetail(l), undo_token: token, event_id: eventId }
})

/** A document a lead stage asks for (passport, Form B, title deed…). */
route('POST', '/leads/:id/documents', ({ params, form }): Written<LeadDetail> => {
	const l = findLead(params[0])
	const file = form?.get('file')
	const type = form?.get('doc_type')
	if (!(file instanceof File)) invalid('Choose a file.')
	const allowed = Object.values(LEAD_STAGE_DOCS[l.lead_type]).flat()
	if (typeof type !== 'string' || !allowed.includes(type)) invalid('Pick the document type.')
	const { token, eventId } = changeLead(l, (tok) => {
		l.documents = l.documents.filter((d) => d.type !== type)
		l.documents.push({
			id: nextId(),
			type,
			file: file.name,
			size_bytes: file.size,
			uploaded: `uploaded ${nowLabel()}`
		})
		logLead(l, `${type} added`, 'human', tok)
	})
	return { data: leadDetail(l), undo_token: token, event_id: eventId }
})

/* ── Matches (top-level section, 6 Oct) ── */

/**
 * Three client groups (6 Oct, 08:56–09:48): ready buyers and tenants, off-plan buyers, sellers
 * and landlords (reverse matching). Pursue (10:39–11:09) writes "Match pursued" on both linked
 * records and sets the lead's next action; booking a viewing moves the stage.
 */
const MON_IDX: Record<string, number> = {
	jan: 0,
	feb: 1,
	mar: 2,
	apr: 3,
	may: 4,
	jun: 5,
	jul: 6,
	aug: 7,
	sep: 8,
	oct: 9,
	nov: 10,
	dec: 11
}

/** "1 Nov", "November", "Needs 1 November" → the next such date; buyers get 90 days. */
function moveBy(l: DbLead): string {
	const raw = String(l.fields.move_in ?? l.fields.wants ?? '')
	const m = raw.match(/(?:(\d{1,2})\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*/i)
	if (l.lead_type === 'tenant' && m) {
		const month = MON_IDX[m[2].toLowerCase()]
		const day = m[1] ? Number(m[1]) : 1
		let year = Number(TODAY.slice(0, 4))
		const iso = (y: number) =>
			`${y}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
		if (iso(year) < TODAY) year += 1
		return iso(year)
	}
	return addDays(TODAY, 90)
}

/** "30 Jun 2028" */
const dateY = (iso: string) => `${shortDate(iso)} ${iso.slice(0, 4)}`

const bedsIn = (s: unknown): number | null => {
	const t = String(s ?? '')
	if (/studio/i.test(t)) return 0
	const m = t.match(/(\d)\s?(?:BR|bed)/i)
	return m ? Number(m[1]) : null
}

function matchClients(): MatchClients {
	const live = myLeads().filter(isOpenLead)
	const client = (l: DbLead): MatchClient => {
		const money = leadMoney(l)
		const what = l.fields.wants || l.fields.unit || l.area
		return {
			lead: leadRow(l),
			line: [
				what,
				dealTypeOf(l.lead_type) === 'sale' ? 'Sale' : 'Rent',
				money ? short(money) : 'budget not known'
			].join(' · '),
			pursued: db.pursued[l.id]?.length ?? 0
		}
	}
	const byScore = (a: DbLead, b: DbLead) => b.score - a.score
	return {
		ready: live
			.filter((l) => (l.lead_type === 'buyer' || l.lead_type === 'tenant') && !l.off_plan)
			.sort(byScore)
			.map(client),
		offplan: live
			.filter((l) => l.lead_type === 'buyer' && l.off_plan)
			.sort(byScore)
			.map(client),
		sell: live
			.filter((l) => l.lead_type === 'seller' || l.lead_type === 'landlord')
			.sort(byScore)
			.map(client)
	}
}

route('GET', '/matches/clients', () => matchClients())

type RowSeed = Omit<
	MatchRow,
	'pursued' | 'shortlisted' | 'watching' | 'renewal_planned' | 'over_budget' | 'why' | 'chip'
> &
	Partial<Pick<MatchRow, 'over_budget' | 'why' | 'chip'>> & {
		/** The lead's next action when pursued. */
		next: string
	}

const seed = (
	r: Partial<RowSeed> & Pick<RowSeed, 'key' | 'kind' | 'title' | 'sub' | 'line' | 'next'>
): RowSeed => ({
	ref: null,
	lead_stages: null,
	colleague: null,
	owner: null,
	pursuable: true,
	after_move: false,
	can_book: false,
	...r
})

function renewalTitle(unit: string) {
	return `Renewal call · ${unit}`
}

/** Every match row for a lead, with the tier it belongs to. */
function matchSeeds(
	l: DbLead,
	opts: { over: boolean }
): { tier: string; group?: string; row: RowSeed }[] {
	const out: { tier: string; group?: string; row: RowSeed }[] = []
	const factor = opts.over ? 1 + MATCH_OVER_BUDGET : 1
	const budget = Number(l.fields.budget_aed) || null
	const within = (price: number) => !budget || !price || price <= budget * factor

	if (l.lead_type === 'seller' || l.lead_type === 'landlord') {
		const want = l.lead_type === 'seller' ? 'buyer' : 'tenant'
		const price = leadMoney(l)
		const beds = bedsIn(l.fields.unit)
		const fits = (type: string, area: string, b: number | null, money: number | null) =>
			type === want &&
			area === l.area &&
			(beds === null || b === null || b === beds) &&
			(!price || !money || money >= price * 0.9)
		const leads = db.leads
			.filter(
				(x) =>
					x.id !== l.id &&
					!x.off_plan &&
					isOpenLead(x) &&
					fits(x.lead_type, x.area, bedsIn(x.fields.wants), Number(x.fields.budget_aed) || null)
			)
			.sort((a, b) => (a.agent === ME ? 0 : 1) - (b.agent === ME ? 0 : 1) || b.score - a.score)
		for (const x of leads) {
			const mine = x.agent === ME
			const summary = leadSummary(x.lead_type, x.fields)
			out.push({
				tier: 'fit',
				group: 'leads',
				row: seed({
					key: `lead:${x.id}`,
					kind: mine ? 'lead' : 'colleague_lead',
					title: mine ? x.name : `${x.agent ?? 'Unassigned'}'s ${x.lead_type}`,
					sub: [
						summary.line,
						summary.sub,
						x.lead_type === 'tenant' && x.fields.move_in ? `move-in ${x.fields.move_in}` : null,
						STAGE_LABEL[x.stage]
					]
						.filter(Boolean)
						.join(' · '),
					line:
						x.source === 'file'
							? 'vv'
							: x.source === 'inbound'
								? 'in'
								: x.source === 'agent_to_agent'
									? 'a2a'
									: 'own',
					ref: mine ? { kind: 'lead', id: String(x.id) } : null,
					colleague: mine ? null : (x.agent ?? null),
					chip: mine ? null : { tone: 'neutral', label: 'Colleague' },
					can_book: mine,
					next: mine ? `Viewing to arrange · ${x.name}` : `Ask ${x.agent} about a viewing`
				})
			})
		}
		for (const x of db.inbox) {
			if ((x.status !== 'waiting' && x.status !== 'requested') || !x.want) continue
			if (!fits(x.want.type, x.want.area, x.want.beds, x.want.budget)) continue
			out.push({
				tier: 'fit',
				group: 'inbox',
				row: seed({
					key: `inbox:${x.id}`,
					kind: 'inbox',
					title: x.name,
					sub: `${x.source} · ${x.text}`,
					line: x.line,
					ref: { kind: 'inbox', id: x.id },
					chip: { tone: 'amber', label: 'Waiting in the inbox' },
					next: `Ask for ${x.name} in the inbox`
				})
			})
		}
		return out
	}

	if (l.off_plan) {
		const areas = String(l.fields.areas || l.area)
			.split(/,\s*/)
			.filter(Boolean)
		const now = Number(l.fields.on_booking_aed) || null
		const by = String(l.fields.handover_by ?? '') || null
		for (const p of db.projects.filter((x) => areas.includes(x.area))) {
			const why: string[] = []
			if (budget && p.from_aed > budget * factor) why.push('Over budget')
			if (now && p.on_booking_aed > now)
				why.push(`AED ${fmt(p.on_booking_aed)} on booking is more than the client can pay now`)
			if (by && p.handover_date > by) why.push(`Handover ${p.handover} is after ${dateY(by)}`)
			const fit = !why.length
			out.push({
				tier: 'projects',
				row: seed({
					key: `project:${p.id}`,
					kind: 'project',
					title: `${p.name} · ${p.area}`,
					sub: `${p.developer} · ${p.beds} · from AED ${fmt(p.from_aed)} · plan ${p.plan} · AED ${fmt(p.on_booking_aed)} on booking · handover ${p.handover}`,
					line: 'own',
					over_budget: fit ? overBudgetChip(p.from_aed, budget) : null,
					chip: fit ? null : { tone: 'neutral', label: 'Not a fit' },
					why,
					pursuable: fit,
					next: `Send the payment plan · ${p.name}`
				})
			})
		}
		for (const a of db.allocations.filter((x) => areas.includes(x.area) && within(x.price_aed))) {
			const mine = a.agent === ME
			out.push({
				tier: 'allocations',
				row: seed({
					key: `alloc:${a.id}`,
					kind: 'allocation',
					title: `${a.project} · ${a.area}`,
					sub: `${a.unit} · AED ${fmt(a.price_aed)} · ${a.agent} · ${a.left} left`,
					line: 'own',
					over_budget: overBudgetChip(a.price_aed, budget),
					colleague: mine ? null : a.agent,
					next: mine ? `Send the allocation · ${a.project}` : `Ask ${a.agent} · ${a.project}`
				})
			})
		}
		return out
	}

	// Ready buyers and tenants: same area and deal type (Kian, 30 Sep).
	const type = dealTypeOf(l.lead_type)
	const md = moveBy(l)
	for (const x of db.listings) {
		if (x.area !== l.area || x.deal_type !== type || x.status === 'expired' || !within(x.price_aed))
			continue
		const mine = x.agent === ME
		const stages = mine ? null : leadStageCounts(x)
		const n = stages?.reduce((s, v) => s + v.count, 0) ?? 0
		out.push({
			tier: 'company',
			row: seed({
				key: `listing:${x.id}`,
				kind: mine ? 'listing' : 'colleague_listing',
				title: `${x.unit} · ${x.area}`,
				sub: `${x.status === 'pocket' ? 'pocket listing' : x.status} · AED ${fmt(x.price_aed)}${x.deal_type === 'rent' ? ' a year' : ''} · ${x.agent}`,
				line: 'own',
				over_budget: overBudgetChip(x.price_aed, budget),
				ref: { kind: 'listing', id: x.id },
				colleague: mine ? null : x.agent,
				lead_stages:
					stages && n
						? `${n} lead${n === 1 ? '' : 's'} on it · ${stages.map((s) => STAGE_LABEL[s.stage]).join(', ')}`
						: null,
				can_book: mine,
				next: mine ? `Viewing to arrange · ${x.unit}` : `Ask ${x.agent} · ${x.unit}`
			})
		})
	}
	const sellerType = type === 'sale' ? 'seller' : 'landlord'
	for (const x of db.leads) {
		if (x.lead_type !== sellerType || x.area !== l.area || !isOpenLead(x) || x.own_listing_id)
			continue
		if (!within(leadMoney(x))) continue
		const mine = x.agent === ME
		const word = sellerType === 'seller' ? 'Seller' : 'Landlord'
		out.push({
			tier: 'company',
			row: seed({
				key: `lead:${x.id}`,
				kind: mine ? 'seller_lead' : 'colleague_lead',
				title: mine
					? `${String(x.fields.unit || x.area)} · ${x.area}`
					: `${x.agent ?? 'Unassigned'}'s ${word.toLowerCase()}`,
				sub: `${word} lead · ${leadSummary(x.lead_type, x.fields).sub} · ${mine ? x.name : STAGE_LABEL[x.stage]}`,
				line: 'own',
				over_budget: overBudgetChip(leadMoney(x), budget),
				ref: mine ? { kind: 'lead', id: String(x.id) } : null,
				colleague: mine ? null : (x.agent ?? null),
				// A seller from the owner file with no prior deal is not offered.
				pursuable: !leadGated(x),
				next: mine
					? `Viewing to arrange · ${String(x.fields.unit || x.area)}`
					: `Ask ${x.agent} about the unit`
			})
		})
	}
	for (const o of db.owners) {
		if (!onAgencyFile(o) || o.name === l.name) continue
		const prior = hasPriorDeal(o)
		for (const u of o.units) {
			if (u.area !== l.area || !unitActionable(u.status, leaseEnd(u))) continue
			const vacant = /vacant/i.test(u.status)
			const date = leaseEnd(u) ?? TODAY
			out.push({
				tier: 'owners',
				row: seed({
					key: `owner:${o.id}:${unitKey(u)}`,
					kind: 'owner',
					title: `${unitShort(u)} · ${u.area}`,
					sub: `${u.bedrooms ? `${u.bedrooms} bed` : 'Studio'} · ${vacant ? `${u.status[0].toLowerCase()}${u.status.slice(1)}` : `lease ends ${dayLabel(date)}`} · ${o.name}`,
					line: 'vv',
					ref: { kind: 'owner', id: o.id },
					owner: { id: o.id, name: o.name, prior_deal: prior },
					chip: prior
						? { tone: 'green', label: 'Prior deal on file' }
						: { tone: 'amber', label: 'No prior deal on file' },
					pursuable: prior,
					can_book: prior,
					after_move: !vacant && date > md,
					next: `Ask the owner · ${unitShort(u)}`
				})
			})
		}
	}
	for (const m of db.market) {
		if (m.area !== l.area || m.deal_type !== type || !within(m.price_aed)) continue
		out.push({
			tier: 'public',
			row: seed({
				key: `market:${m.id}`,
				kind: 'public',
				title: `${m.portal} · ${m.unit} · ${m.area}`,
				sub: `AED ${fmt(m.price_aed)}${m.deal_type === 'rent' ? ' a year' : ''} · other agency · ${m.days_listed} days listed`,
				line: 'in',
				over_budget: overBudgetChip(m.price_aed, budget),
				chip: { tone: 'pink', label: 'Form I first' },
				ref: { kind: 'market', id: m.id },
				can_book: true,
				next: `Form I, then ask the listing agent · ${m.unit}`
			})
		})
	}
	for (const u of db.unitEvents) {
		if (u.area !== l.area || u.deal_type !== type) continue
		out.push({
			tier: 'events',
			row: seed({
				key: `unit:${u.id}`,
				kind: 'unit_event',
				title: `${u.building} · ${u.number} · ${u.area}`,
				sub: `${u.bedrooms ? `${u.bedrooms} bed` : 'Studio'} · ${u.what} ${dayLabel(u.date)} · owner not on your file`,
				line: 'own',
				pursuable: false,
				after_move: u.date > md,
				next: ''
			})
		})
	}
	return out
}

function finishRow(l: DbLead, r: RowSeed): MatchRow {
	const { next: _next, ...row } = r
	const ownerUnit = r.kind === 'owner' ? r.title.replace(/ · [^·]+$/, '') : ''
	return {
		over_budget: null,
		why: [],
		chip: null,
		...row,
		pursued: db.pursued[l.id]?.find((p) => p.key === r.key) ?? null,
		shortlisted: (db.shortlist[l.id] ?? []).includes(r.key),
		watching: Boolean(db.watched[r.key]),
		renewal_planned:
			r.kind === 'owner' &&
			db.events.some((e) => e.lead_id === l.id && e.title === renewalTitle(ownerUnit))
	}
}

function leadMatches(l: DbLead, opts: { over: boolean; after: boolean }): LeadMatches {
	const seeds = matchSeeds(l, { over: opts.over })
	const rows = (tier: string, group?: string) =>
		seeds
			.filter((s) => s.tier === tier && (!group || s.group === group))
			.map((s) => finishRow(l, s.row))
	const visible = (rs: MatchRow[]) => (opts.after ? rs : rs.filter((r) => !r.after_move))
	const hidden = (rs: MatchRow[]) => (opts.after ? 0 : rs.filter((r) => r.after_move).length)
	const money = leadMoney(l)
	const own = l.own_listing_id ? db.listings.find((x) => x.id === l.own_listing_id) : null
	const base = {
		lead: leadRow(l),
		shortlist: db.shortlist[l.id]?.length ?? 0,
		own_listing: own ? { id: own.id, label: `${own.id} · ${own.status}` } : null
	}
	const tier = (
		t: Partial<MatchTier> & Pick<MatchTier, 'id' | 'title' | 'sub' | 'groups'>
	): MatchTier => ({
		n: null,
		chip: null,
		gate: null,
		hidden_after: 0,
		...t
	})

	if (l.lead_type === 'seller' || l.lead_type === 'landlord') {
		const want = l.lead_type === 'seller' ? 'buyer' : 'tenant'
		const leads = rows('fit', 'leads')
		const inbox = rows('fit', 'inbox')
		const beds = bedsIn(l.fields.unit)
		const gated = leadGated(l)
		const gate = gated && l.owner_id ? { owner_id: l.owner_id } : null
		const strip = (r: MatchRow) => (gated ? { ...r, pursuable: false } : r)
		return {
			...base,
			tab: 'sell',
			move_by: null,
			status: { tone: 'outline', label: 'Planned' },
			brief: [
				{
					k: l.lead_type === 'seller' ? 'Selling' : 'Letting',
					v: `${String(l.fields.unit || l.area)}`
				},
				{
					k: l.lead_type === 'seller' ? 'Target price' : 'Rent a year',
					v: money ? `AED ${fmt(money)}` : 'Not known'
				},
				{
					k: l.lead_type === 'seller' ? 'Occupancy' : 'Available',
					v: String((l.lead_type === 'seller' ? l.fields.occupancy : l.fields.available) || '—')
				},
				{ k: 'Listing', v: own ? `${own.id} · ${own.status}` : 'Not yet' }
			],
			tiers: [
				tier({
					id: 'fit',
					title: `${want === 'buyer' ? 'Buyers' : 'Tenants'} who fit`,
					sub: [
						`${leads.length + inbox.length}`,
						l.area,
						beds === null ? null : beds ? `${beds} bed` : 'studio',
						money
							? `budget from ${want === 'tenant' ? `${fmt(money * 0.9)} a year` : `AED ${short(money * 0.9)}`}`
							: null
					]
						.filter(Boolean)
						.join(' · '),
					chip: { tone: 'outline', label: 'Planned' },
					gate,
					groups: [
						{
							label: `Leads in the agency · ${leads.length}`,
							rows: leads.map(strip),
							empty: `No ${want} leads in the agency fit ${String(l.fields.unit || 'this unit')}.`
						},
						{
							label: `Waiting in the inbox · ${inbox.length}`,
							rows: inbox.map(strip),
							empty: 'No waiting enquiries fit.'
						}
					]
				})
			]
		}
	}

	if (l.off_plan) {
		const projects = rows('projects').sort((a, b) => Number(!a.pursuable) - Number(!b.pursuable))
		const fits = projects.filter((r) => r.pursuable).length
		const allocations = rows('allocations')
		const areas = String(l.fields.areas || l.area)
		return {
			...base,
			tab: 'offplan',
			move_by: null,
			status: { tone: 'outline', label: 'Planned' },
			brief: [
				{ k: 'Wants', v: String(l.fields.wants || '—') },
				{ k: 'Budget', v: money ? `AED ${fmt(money)}` : 'Not known' },
				{
					k: 'Can pay now',
					v: l.fields.on_booking_aed ? `AED ${fmt(Number(l.fields.on_booking_aed))}` : 'Not known'
				},
				{ k: 'Handover by', v: l.fields.handover_by ? dateY(String(l.fields.handover_by)) : '—' }
			],
			tiers: [
				tier({
					id: 'projects',
					n: 1,
					title: 'Launch desk projects that fit',
					sub: `${fits} of ${projects.length} in ${areas} · Example`,
					groups: [{ label: null, rows: projects, empty: `No Launch desk projects in ${areas}.` }]
				}),
				tier({
					id: 'allocations',
					n: 2,
					title: 'Company allocations',
					sub: `${allocations.length} · units the agency holds · Example`,
					groups: [
						{ label: null, rows: allocations, empty: 'No company allocations fit this brief.' }
					]
				})
			]
		}
	}

	const md = moveBy(l)
	const company = rows('company')
	const owners = rows('owners')
	const pub = rows('public')
	const events = rows('events')
	return {
		...base,
		tab: 'ready',
		move_by: md,
		status: null,
		brief: [
			{ k: 'Wants', v: String(l.fields.wants || '—') },
			{
				k: 'Budget',
				v: money ? `AED ${fmt(money)}${l.lead_type === 'tenant' ? ' a year' : ''}` : 'Not known'
			},
			l.lead_type === 'tenant'
				? { k: 'Move-in', v: String(l.fields.move_in || '—') }
				: { k: 'Buying to', v: String(l.fields.purpose || '—') },
			{ k: 'Move by', v: dayLabel(md) }
		],
		tiers: [
			tier({
				id: 'company',
				n: 1,
				title: 'Company listings',
				sub: `${company.length} · same agency`,
				groups: [
					{
						label: null,
						rows: company,
						empty: "No company listings fit. Tier 2 lists owners on your agency's file."
					}
				]
			}),
			tier({
				id: 'owners',
				n: 2,
				title: 'Owners on your file',
				sub: `${visible(owners).length} · vacancy or lease end before ${dayLabel(md)}`,
				hidden_after: hidden(owners),
				groups: [
					{
						label: null,
						rows: visible(owners),
						empty: `No owners on your agency's file in ${l.area} with a vacancy or a lease ending before ${dayLabel(md)}.`
					}
				]
			}),
			tier({
				id: 'public',
				n: 3,
				title: 'Public listings',
				sub: `${pub.length} · other agencies`,
				groups: [{ label: null, rows: pub, empty: 'No portal listings fit this brief.' }]
			}),
			tier({
				id: 'events',
				title: 'Unit events',
				sub: `${visible(events).length} in ${l.area} · owner not on your file`,
				hidden_after: hidden(events),
				groups: [
					{
						label: null,
						rows: visible(events),
						empty: `No other units in ${l.area} with a lease ending before ${dayLabel(md)}.`
					}
				]
			})
		]
	}
}

route(
	'GET',
	'/leads/:id/matches',
	({ params, query }): LeadMatches =>
		leadMatches(findLead(params[0]), {
			over: query.get('over') !== '0',
			after: query.get('after') === '1'
		})
)

const findSeed = (l: DbLead, key: string) =>
	matchSeeds(l, { over: true }).find((s) => s.row.key === key)?.row ?? notFound('Match')

/**
 * Pursue: "Match pursued" on the lead and on the linked record (the other lead, or the owner),
 * the lead's next action set. Pursuing again stops it. One Undo restores both records.
 */
route('POST', '/leads/:id/pursue', ({ params, body }): Written<PursueResult> => {
	const l = findLead(params[0])
	const r = findSeed(l, String(body.key))
	if (!r.pursuable) {
		if (r.owner && !r.owner.prior_deal)
			throw new ApiError(
				`${GATE_LINE}. ${r.owner.name} has no prior deal on record.`,
				409,
				'no_prior_deal'
			)
		invalid('This match cannot be pursued.')
	}
	if (leadGated(l)) refuseGated(l)
	const list = db.pursued[l.id] ?? []
	const was = list.find((p) => p.key === r.key)
	const listBefore = [...list]
	const other =
		r.ref?.kind === 'lead' ? db.leads.find((x) => x.id === Number(r.ref?.id)) : undefined
	const otherBefore = other ? structuredClone(other) : null
	const owner = r.ref?.kind === 'owner' ? db.owners.find((o) => o.id === r.ref?.id) : undefined
	const ownerNotes = owner ? [...owner.notes] : null
	let entry: PursuedMatch | null = null
	const { token, eventId } = changeLead(
		l,
		(tok) => {
			if (was) {
				db.pursued[l.id] = list.filter((p) => p.key !== r.key)
				logLead(l, `Pursue stopped · ${r.title}`, 'human', tok)
				return
			}
			entry = { key: r.key, title: r.title, next: r.next, at: nowLabel() }
			db.pursued[l.id] = [...list, entry]
			logLead(l, `Match pursued · ${r.title} · next: ${r.next}`, 'human', tok)
			l.next_action = r.next
			l.last_activity_text = 'match pursued'
			if (other && other.agent === ME) logLead(other, `Match pursued · ${l.name}`, 'human', tok)
			if (owner)
				owner.notes.push({
					id: nextId(),
					at: nowLabel(),
					text: `Match pursued · ${l.name}`,
					origin: 'human'
				})
		},
		() => {
			db.pursued[l.id] = listBefore
			if (other && otherBefore) Object.assign(other, otherBefore)
			if (owner && ownerNotes) owner.notes = ownerNotes
		}
	)
	return { data: { lead: leadDetail(l), pursued: entry }, undo_token: token, event_id: eventId }
})

route('POST', '/leads/:id/shortlist', ({ params, body }) => {
	const l = findLead(params[0])
	const r = findSeed(l, String(body.key))
	const before = [...(db.shortlist[l.id] ?? [])]
	const on = !before.includes(r.key)
	db.shortlist[l.id] = on ? [...before, r.key] : before.filter((k) => k !== r.key)
	return written({ on, count: db.shortlist[l.id].length }, () => {
		db.shortlist[l.id] = before
	})
})

/** Watch unit: a unit event whose owner is not on the file. Nothing is sent to anyone. */
route('POST', '/units/watch', ({ body }) => {
	const key = String(body.key ?? '')
	if (!db.unitEvents.some((u) => `unit:${u.id}` === key)) notFound('Unit')
	const before = Boolean(db.watched[key])
	db.watched[key] = !before
	return written({ on: !before }, () => {
		db.watched[key] = before
	})
})

/** Plan a renewal call with an owner on the file who has a prior deal on record. */
route('POST', '/leads/:id/renewal-call', ({ params, body }) => {
	const l = findLead(params[0])
	const r = findSeed(l, String(body.key))
	if (r.kind !== 'owner' || !r.owner) invalid('Only an owner on your file can get a renewal call.')
	if (!r.owner.prior_deal)
		throw new ApiError(
			`${GATE_LINE}. ${r.owner.name} has no prior deal on record.`,
			409,
			'no_prior_deal'
		)
	const unit = r.title.replace(/ · [^·]+$/, '')
	if (db.events.some((e) => e.lead_id === l.id && e.title === renewalTitle(unit)))
		throw new ApiError('A renewal call is already planned.', 409, 'exists')
	const ev: DbEvent = {
		id: nextId(),
		date: addDays(TODAY, 1),
		time: '11:00',
		kind: 'call',
		title: renewalTitle(unit),
		detail: `${r.owner.name} · for ${l.name}`,
		agent: ME,
		lead_id: l.id,
		deal_id: null,
		listing_id: null,
		owner_id: r.owner.id,
		done: false
	}
	db.events.push(ev)
	return written(eventView(ev), () => {
		db.events = db.events.filter((e) => e.id !== ev.id)
	})
})

/** Ask a colleague about their listing or lead: logged on the lead; nothing goes to a client. */
route('POST', '/leads/:id/ask', ({ params, body }) => {
	const l = findLead(params[0])
	const r = findSeed(l, String(body.key))
	if (!r.colleague) invalid('That match is yours.')
	const { token, eventId } = changeLead(l, (tok) => {
		logLead(l, `Asked ${r.colleague} · ${r.title}`, 'human', tok)
	})
	return { data: { asked: r.colleague }, undo_token: token, event_id: eventId }
})

/* ── inbox and the lead handout setting (6 Oct, 04:25–06:10) ── */

const HANDOUT: Record<HandoutMode, { label: string; line: string }> = {
	manager: { label: 'Manager assigns', line: 'Agents can ask for a lead. The manager decides.' },
	request: {
		label: 'First to ask gets it',
		line: 'Agents who cover the area ask. The first request assigns the lead.'
	},
	both: {
		label: 'Agents ask, manager confirms',
		line: 'Several agents can ask. The manager confirms one of them.'
	}
}

/** The mockup's clock for "13 min ago" (fixtures: Tue 29 Sep 2026, 10:15 Dubai). */
const NOW = `${TODAY}T10:15`

function atLabel(at: string): string {
	const day = at.slice(0, 10)
	const time = at.slice(11, 16)
	return `${day === TODAY ? 'Today' : dayLabel(day)} · ${time}`
}

function agoLabel(at: string): string {
	const mins = Math.max(0, Math.round((Date.parse(`${NOW}:00Z`) - Date.parse(`${at}:00Z`)) / 60000))
	if (mins < 60) return `${mins} min ago`
	if (mins < 24 * 60) return `${Math.floor(mins / 60)} h ago`
	return `${Math.floor(mins / 1440)} d ago`
}

function wantLine(w: DbInboxItem['want']): string {
	if (!w) return '—'
	const beds = w.beds === null ? '' : w.beds === 0 ? ' · studio' : ` · ${w.beds} bed`
	const money = w.budget
		? w.type === 'tenant' || w.type === 'landlord'
			? ` · ${fmt(w.budget)} a year`
			: ` · AED ${short(w.budget)}`
		: ' · no budget'
	return `${TYPE_LABEL[w.type]} · ${w.area}${beds}${money}`
}

const myRequest = (x: DbInboxItem) => x.requests.find((r) => r.agent === ME)

function inboxChip(x: DbInboxItem): Chip {
	if (x.status === 'assigned')
		return {
			tone: 'green',
			label: x.via_request && x.agent === ME ? 'Yours · asked first' : 'Assigned'
		}
	if (x.status === 'dismissed') return { tone: 'neutral', label: 'Not a real enquiry' }
	if (x.status === 'requested') {
		if (myRequest(x))
			return {
				tone: 'blue',
				label:
					db.settings.handout === 'both'
						? 'You asked · manager confirms'
						: 'You asked · manager decides'
			}
		return { tone: 'blue', label: `Asked for by ${x.requests[0]?.agent}` }
	}
	return {
		tone: 'amber',
		label: db.settings.handout === 'request' ? 'Waiting for a request' : 'Waiting for a manager'
	}
}

function inboxView(x: DbInboxItem): InboxItem {
	const l = x.lead_id ? db.leads.find((v) => v.id === x.lead_id) : undefined
	const waiting = x.status === 'waiting' || x.status === 'requested'
	const mine = myRequest(x)
	const conversation: ConversationMessage[] = [
		{ from: x.line === 'vv' ? 'system' : 'client', who: x.name, at: atLabel(x.at), text: x.text }
	]
	if (l && l.agent === ME && l.stage !== 'new')
		conversation.push({
			from: 'agent',
			who: `${ME} · from the agent's phone`,
			at: atLabel(x.at).replace(/\d\d:\d\d$/, (t) =>
				t.replace(/:(\d\d)/, (_, m) => `:${String(Math.min(59, Number(m) + 6)).padStart(2, '0')}`)
			),
			text: 'Thanks — sending options that fit.'
		})
	return {
		id: x.id,
		name: x.name,
		source: x.source,
		line: x.line,
		at_label: atLabel(x.at),
		ago: agoLabel(x.at),
		text: x.text,
		owner_check: x.owner_check,
		priority: x.priority,
		state: x.status,
		status_chip: inboxChip(x),
		agent: x.agent,
		suggested: x.suggested,
		reason: x.reason,
		requests: x.requests.map((r) => ({ agent: r.agent, at_label: atLabel(r.at) })),
		want_line: wantLine(x.want),
		lead_id: l && l.agent === ME ? l.id : null,
		conversation,
		can: {
			ask: waiting && !mine,
			withdraw: waiting && Boolean(mine),
			release: x.status === 'assigned' && x.via_request && x.agent === ME && l?.stage === 'new',
			dismiss: x.status !== 'dismissed' && !x.lead_id,
			restore: x.status === 'dismissed'
		},
		my_request: mine
			? `Asked ${mine.at.slice(11, 16)} · ${db.settings.handout === 'both' ? 'the manager confirms' : 'a manager decides'}`
			: null
	}
}

function inboxIn(x: DbInboxItem, f: InboxFilter): boolean {
	if (x.status === 'dismissed') return f === 'dismissed'
	if (f === 'mine') return x.agent === ME && x.status === 'assigned'
	if (f === 'waiting') return x.status === 'waiting' || x.status === 'requested'
	return f === 'all'
}

route('GET', '/inbox', ({ query }): InboxResponse => {
	const filter = (query.get('filter') ?? 'all') as InboxFilter
	const filters: InboxFilter[] = ['all', 'mine', 'waiting', 'dismissed']
	return {
		items: db.inbox
			.filter((x) => inboxIn(x, filter))
			.sort((a, b) => b.at.localeCompare(a.at))
			.map(inboxView),
		counts: Object.fromEntries(
			filters.map((f) => [f, db.inbox.filter((x) => inboxIn(x, f)).length])
		) as Record<InboxFilter, number>,
		today: db.inbox.filter((x) => x.at.startsWith(TODAY)).length,
		waiting: db.inbox.filter((x) => x.status === 'waiting' || x.status === 'requested').length,
		handout: db.settings.handout,
		handout_label: HANDOUT[db.settings.handout].label,
		sources: connectionViews().filter((c) => c.kind === 'source')
	}
})

const findInbox = (id: string) => db.inbox.find((x) => x.id === id) ?? notFound('Enquiry')

/** An enquiry assigned to me becomes my lead (New), from what it asks for. */
function leadFromInbox(x: DbInboxItem): DbLead {
	const w = x.want
	const type: LeadType = w?.type ?? 'buyer'
	const fields: LeadFields =
		type === 'tenant'
			? { wants: x.text, budget_aed: w?.budget ?? null }
			: type === 'buyer'
				? { wants: x.text, budget_aed: w?.budget ?? null }
				: { unit: x.text }
	const lead: DbLead = {
		id: Math.max(...db.leads.map((l) => l.id)) + 1,
		name: x.name,
		phone: '—',
		lead_type: type,
		source: x.line === 'vv' ? 'file' : x.line === 'a2a' ? 'agent_to_agent' : 'inbound',
		source_detail: x.source,
		received_label: atLabel(x.at),
		stage: 'new',
		agent: ME,
		score: scoreLead('inbound', cleanFields(type, fields)),
		area: w?.area ?? '—',
		language: '—',
		next_action: 'Call within 5 minutes',
		listing_id: null,
		own_listing_id: null,
		off_plan: false,
		fields: cleanFields(type, fields),
		owner_match: { summary: x.owner_check, records: [] },
		suggested_agent: null,
		last_activity: TODAY,
		last_activity_text: 'assigned from the inbox',
		viewing_outcome_due: null,
		form_i_on_file: false,
		first_call_logged: false,
		documents: [],
		owner_id: null,
		offer: null
	}
	return lead
}

/**
 * Ask for this lead. Manager assigns / Agents ask, manager confirms: the request waits for the
 * manager. First to ask gets it: the first request assigns the lead (Release while it is New).
 */
route('POST', '/inbox/:id/ask', ({ params }) => {
	const x = findInbox(params[0])
	if (x.status !== 'waiting' && x.status !== 'requested')
		invalid('This enquiry already has an agent.')
	if (myRequest(x)) invalid('You already asked for this lead.')
	const before = structuredClone(x)
	let lead: DbLead | null = null
	x.requests.push({ agent: ME, at: NOW })
	if (db.settings.handout === 'request' && x.status === 'waiting') {
		lead = leadFromInbox(x)
		db.leads.push(lead)
		logLead(lead, `Assigned from the inbox · asked first (${HANDOUT.request.label})`, 'rule', null)
		Object.assign(x, { status: 'assigned', agent: ME, via_request: true, lead_id: lead.id })
	} else {
		x.status = 'requested'
	}
	return written(inboxView(x), () => {
		Object.assign(x, before)
		if (lead) {
			db.leads = db.leads.filter((l) => l.id !== lead?.id)
			db.leadEvents = db.leadEvents.filter((e) => e.lead_id !== lead?.id)
		}
	})
})

route('POST', '/inbox/:id/withdraw', ({ params }) => {
	const x = findInbox(params[0])
	if (!myRequest(x)) invalid('You have not asked for this lead.')
	const before = structuredClone(x)
	x.requests = x.requests.filter((r) => r.agent !== ME)
	if (!x.requests.length && x.status === 'requested') x.status = 'waiting'
	return written(inboxView(x), () => Object.assign(x, before))
})

/** Release a lead got by asking, while it is still New: back to waiting, the lead goes. */
route('POST', '/inbox/:id/release', ({ params }) => {
	const x = findInbox(params[0])
	const l = x.lead_id ? db.leads.find((v) => v.id === x.lead_id) : undefined
	if (!(x.status === 'assigned' && x.via_request && x.agent === ME && l?.stage === 'new'))
		invalid('Only a lead you got by asking, still at New, can be released.')
	const before = structuredClone(x)
	const leadBefore = structuredClone(l)
	db.leads = db.leads.filter((v) => v.id !== l.id)
	Object.assign(x, {
		status: 'waiting',
		agent: x.suggested,
		via_request: false,
		lead_id: null,
		requests: x.requests.filter((r) => r.agent !== ME)
	})
	return written(inboxView(x), () => {
		Object.assign(x, before)
		db.leads.push(leadBefore)
	})
})

route('POST', '/inbox/:id/dismiss', ({ params }) => {
	const x = findInbox(params[0])
	if (x.lead_id) invalid('This enquiry is already a lead.')
	const before = x.status
	x.status = 'dismissed'
	return written(inboxView(x), () => {
		x.status = before
	})
})

route('POST', '/inbox/:id/restore', ({ params }) => {
	const x = findInbox(params[0])
	if (x.status !== 'dismissed') invalid('This enquiry is in the inbox.')
	x.status = x.requests.length ? 'requested' : 'waiting'
	return written(inboxView(x), () => {
		x.status = 'dismissed'
	})
})

function handoutView(): HandoutSettings {
	return {
		mode: db.settings.handout,
		options: (Object.keys(HANDOUT) as HandoutMode[]).map((id) => ({ id, ...HANDOUT[id] })),
		log: [...db.settings.log].reverse().map((e) => ({
			...e,
			from: e.from as HandoutMode,
			to: e.to as HandoutMode,
			from_label: HANDOUT[e.from as HandoutMode].label,
			to_label: HANDOUT[e.to as HandoutMode].label
		})),
		stages: [
			{
				types: 'Buyers and tenants',
				stages: LEAD_STAGES.buyer.map((s) => STAGE_LABEL[s]),
				proposal: false
			},
			{
				types: 'Sellers and landlords',
				stages: LEAD_STAGES.seller.map((s) => STAGE_LABEL[s]),
				proposal: true
			}
		]
	}
}

route('GET', '/settings/handout', () => handoutView())

/** Lead handout: one of three modes; every change is logged and can be restored. */
route('PUT', '/settings/handout', ({ body }) => {
	const mode = body.mode as HandoutMode
	if (!HANDOUT[mode]) invalid('Pick how leads are handed out.')
	const from = db.settings.handout
	if (mode === from) invalid(`Already ${HANDOUT[mode].label.toLowerCase()}.`)
	const entry = { id: nextId(), at: `${dayLabel(TODAY)} · ${nowLabel()}`, who: ME, from, to: mode }
	db.settings.handout = mode
	db.settings.log.push(entry)
	return written(handoutView(), () => {
		db.settings.handout = from
		db.settings.log = db.settings.log.filter((e) => e.id !== entry.id)
	})
})

route('GET', '/leads/:id/conversation', ({ params }): ConversationMessage[] => {
	const l = findLead(params[0])
	if (l.source === 'file') {
		return [
			{
				from: 'system',
				who: 'Your owner file',
				at: l.received_label,
				text: `No conversation yet. This owner is on your agency's file · ${l.source_detail}.`
			}
		]
	}
	const wants = l.fields.wants || l.fields.unit || 'a unit'
	const finance = l.fields.finance && l.fields.finance !== '—' ? ` ${l.fields.finance}.` : ''
	const out: ConversationMessage[] = [
		{
			from: 'client',
			who: l.source_detail,
			at: l.received_label,
			text: `Hi, saw the listing. ${wants}.${finance}`
		}
	]
	if (l.stage !== 'new') {
		out.push({
			from: 'agent',
			who: `${l.agent ?? ME} · from the agent's phone`,
			at: '09:10',
			text: 'Thanks — sending options that fit.'
		})
	}
	return out
})

/* ── create a listing from a seller / landlord lead ── */

function makeListing(
	input: ListingCreate,
	fromLead: DbLead | null
): { listing: DbListing; warning: string | null } {
	if (!input.unit?.trim()) invalid('Enter the unit.')
	if (!input.area?.trim()) invalid('Enter the area.')
	if (!(Number(input.price_aed) > 0)) invalid('Enter a price.')
	const permit = input.permit_number?.trim()
	let status: 'live' | 'pocket' = input.status === 'live' ? 'live' : 'pocket'
	let warning: string | null = null
	if (status === 'live' && !permit) {
		status = 'pocket'
		warning = 'A live listing needs a Trakheesi permit — saved as pocket'
	}
	const n = Math.max(...db.listings.map((x) => Number(x.id.slice(1)) || 0)) + 1
	const listing: DbListing = {
		id: `L${n}`,
		unit: input.unit.trim(),
		area: input.area.trim(),
		bedrooms: Number(input.bedrooms) || 0,
		size_sqft: Number(input.size_sqft) || 0,
		price_aed: Math.round(Number(input.price_aed)),
		deal_type: input.deal_type,
		status,
		scope: 'mine',
		agent: ME,
		owner: input.owner?.trim() || '—',
		portals: status === 'live' ? 'PF · Bayut' : 'Not advertised',
		days_live: 0,
		enquiries: 0,
		permit: permit ? { number: `${permit.slice(0, 4)}••`, expires: addDays(TODAY, 91) } : null,
		form_a_expires: null,
		comparables_note: 'Comparables load from Transactions',
		documents: [],
		from_lead_id: fromLead?.id ?? null
	}
	return { listing, warning }
}

route('POST', '/listings', ({ body }): Written<ListingCreateResult> => {
	const { listing, warning } = makeListing(body as ListingCreate, null)
	db.listings.push(listing)
	return written({ listing: listingCard(listing), warning }, () => {
		db.listings = db.listings.filter((x) => x.id !== listing.id)
	})
})

route('POST', '/leads/:id/listing', ({ params, body }): Written<ListingCreateResult> => {
	const l = findLead(params[0])
	if (l.lead_type !== 'seller' && l.lead_type !== 'landlord')
		invalid('Only seller and landlord leads become listings.')
	if (l.own_listing_id) throw new ApiError('This lead already has a listing.', 409, 'exists')
	refuseGated(l)
	const { listing, warning } = makeListing({ ...(body as ListingCreate), status: 'pocket' }, l)
	const { token } = changeLead(
		l,
		(tok) => {
			db.listings.push(listing)
			l.own_listing_id = listing.id
			logLead(l, `Listing created · ${listing.id} · ${listing.unit}`, 'human', tok)
		},
		() => {
			db.listings = db.listings.filter((x) => x.id !== listing.id)
		}
	)
	return { data: { listing: listingCard(listing), warning }, undo_token: token }
})

/* ── feed strip (7 Oct) ── */

const windowOf = (areas: string[]) =>
	areas.reduce(
		(s, a) => s + (db.feedAreas.find((f) => f.area === a)?.owners_in_90_day_window ?? 0),
		0
	)

/**
 * "Lease ends in 90 days · {areas} · N units · N on your agency's file · N entered the inbox
 * today". DLD/Ejari give the units; only owners on the agency's own file become leads (at 30, 60
 * and 90 days to lease end). Vitevue never lists owners by name, so there is no feed to browse.
 */
function feedSummary(): FeedSummary {
	const onFile = db.owners.filter(
		(o) =>
			onAgencyFile(o) &&
			o.units.some((u) => db.areas.includes(u.area) && unitActionable(u.status, leaseEnd(u)))
	)
	return {
		areas: db.areas,
		window_total: windowOf(db.areas),
		on_file: onFile.length,
		entered_today: myLeads().filter(
			(l) => l.source === 'file' && /min|^\d+ ?h$|today|just now/.test(l.received_label)
		).length
	}
}

route('GET', '/feed/summary', () => feedSummary())
route('GET', '/feed/areas', () => db.feedAreas)

route('PUT', '/me/areas', ({ body }) => {
	const areas = (body.areas as string[] | undefined)?.filter((a) =>
		db.feedAreas.some((f) => f.area === a)
	)
	if (!areas?.length) invalid('Pick at least one area.')
	const before = [...db.areas]
	db.areas = areas
	return written(feedSummary(), () => {
		db.areas = before
	})
})

/* ── deals ── */

route('GET', '/deal-stages', (): DealStages => ({ sale: SALE_STAGES, rent: RENT_STAGES }))

route('GET', '/deals', ({ query }): DealListResponse => {
	const tab = (query.get('tab') ?? 'pipeline') as DealTab
	const type = query.get('deal_type')
	const all = myDeals().map(dealRow)
	const open = all.filter((d) => !d.closed)
	// Conveyancing: open deals, soonest due first; All / Sale / Rent.
	const items =
		tab === 'closed'
			? all.filter((d) => d.closed)
			: tab === 'missing_documents'
				? open.filter((d) => d.missing.length)
				: tab === 'commission'
					? all
					: tab === 'conveyancing'
						? open
								.filter((d) => !type || d.deal_type === type)
								.sort((a, b) => a.due_date.localeCompare(b.due_date))
						: open
	return {
		items,
		counts: {
			open: open.length,
			missing_documents: open.filter((d) => d.missing.length).length,
			closed: all.filter((d) => d.closed).length,
			sale: open.filter((d) => d.deal_type === 'sale').length,
			rent: open.filter((d) => d.deal_type === 'rent').length
		},
		open_value_aed: open.reduce((s, d) => s + d.value_aed, 0),
		totals: {
			gross: all.reduce((s, d) => s + d.commission.amounts.gross, 0),
			agent: all.reduce((s, d) => s + d.commission.amounts.agent, 0),
			agency: all.reduce((s, d) => s + d.commission.amounts.agency, 0)
		}
	}
})

route('GET', '/deals/:id', ({ params }) => dealDetail(findDeal(params[0])))

function changeDeal<T>(d: DbDeal, change: () => T): Written<DealDetail> {
	const before = structuredClone(d)
	change()
	return written(dealDetail(d), () => {
		Object.assign(d, before)
	})
}

route('POST', '/deals', ({ body }): Written<DealDetail> => {
	const input = body as DealCreate
	const l = findLead(input.lead_id)
	const listing = input.listing_id
		? findListing(input.listing_id)
		: l.listing_id
			? findListing(l.listing_id)
			: db.listings.find(
					(x) =>
						x.area === l.area && x.status !== 'expired' && x.deal_type === dealTypeOf(l.lead_type)
				)
	const type = listing ? listing.deal_type : dealTypeOf(l.lead_type)
	let n = 201 + db.deals.length
	while (db.deals.some((d) => d.id === `DL-${n}`)) n += 1
	const value = Math.round(
		Number(input.value_aed) || Number(l.fields.budget_aed) || listing?.price_aed || 0
	)
	if (!(value > 0)) invalid('Enter the agreed value.')
	const deal: DbDeal = {
		id: `DL-${n}`,
		deal_type: type,
		unit: listing?.unit ?? String(l.fields.wants || l.fields.unit || 'Unit to confirm'),
		client: l.name,
		counterparty:
			listing && listing.owner !== '—'
				? `${listing.owner} (${type === 'sale' ? 'seller' : 'landlord'})`
				: 'To confirm',
		value_aed: value,
		stage_index: 0,
		agent: l.agent ?? ME,
		lead_id: l.id,
		listing_id: listing?.id ?? null,
		due_date: input.due_date || addDays(TODAY, 21),
		next_step: type === 'sale' ? 'Form F' : 'Tenancy contract',
		approval: 'pending',
		documents: [],
		commission: {
			...defaultCommission(type, l.source),
			invoice_status: 'not_invoiced',
			cobroker_name: l.source === 'agent_to_agent' ? 'Another agency (Form I)' : null,
			referral_name: null
		},
		compliance: { due_diligence: 'pending', screening: 'not_run', cash_aed: 0 },
		dld_transaction_id: null,
		checks: {}
	}
	const { token } = changeLead(
		l,
		(tok) => {
			db.deals.push(deal)
			logLead(l, `Stage ${STAGE_LABEL[l.stage]} → Won · deal ${deal.id}`, 'human', tok)
			l.stage = 'won'
		},
		() => {
			db.deals = db.deals.filter((d) => d.id !== deal.id)
		}
	)
	return { data: dealDetail(deal), undo_token: token }
})

route('PATCH', '/deals/:id/stage', ({ params, body }) => {
	const d = findDeal(params[0])
	const stages = stagesOf(d.deal_type)
	if (body.direction === 'back') {
		if (d.stage_index === 0) invalid('This deal is at its first stage.')
		return changeDeal(d, () => {
			d.stage_index -= 1
			d.next_step = stages[d.stage_index + 1]
		})
	}
	if (isClosed(d)) invalid('This deal is closed.')
	const target = stages[d.stage_index + 1]
	const have = new Set(d.documents.map((x) => x.type))
	const missing = (STAGE_GATES[target] ?? []).filter((doc) => !have.has(doc))
	if (missing.length) {
		throw new ApiError(
			`Upload the ${missing.join(' and ')} before moving to ${target}.`,
			409,
			'stage_blocked'
		)
	}
	return changeDeal(d, () => {
		d.stage_index += 1
		if (isClosed(d)) {
			d.next_step = 'Closed'
			if (d.commission.invoice_status === 'not_invoiced') d.commission.invoice_status = 'due'
		} else {
			d.next_step = stages[d.stage_index + 1]
		}
	})
})

route('PATCH', '/deals/:id', ({ params, body }) => {
	const d = findDeal(params[0])
	return changeDeal(d, () => {
		if (body.dld_transaction_id !== undefined) {
			if (!isClosed(d)) invalid('The DLD transaction number is added once the deal is transferred.')
			const v = String(body.dld_transaction_id).trim()
			if (!v) invalid('Enter the DLD transaction number.')
			d.dld_transaction_id = v
		}
		if (body.due_date) d.due_date = String(body.due_date)
		if (body.next_step) d.next_step = String(body.next_step)
	})
})

/** Tick or untick a conveyancing item on the current stage (documents are ticked by uploading). */
route('PATCH', '/deals/:id/checklist', ({ params, body }) => {
	const d = findDeal(params[0])
	const key = String(body.key ?? '')
	const [stage, item] = key.split(':').map(Number)
	const req = CONVEYANCING[d.deal_type][stage]?.items[item]
	if (req === undefined) notFound('Checklist item')
	if (typeof req === 'object') invalid('Upload the document to tick it.')
	if (stage !== d.stage_index) invalid('Only the current stage can be ticked.')
	return changeDeal(d, () => {
		d.checks = { ...d.checks, [key]: Boolean(body.done) }
	})
})

route(
	'POST',
	'/deals/:id/documents',
	async ({ params, form }): Promise<Written<DocumentUploadResult>> => {
		const d = findDeal(params[0])
		const file = form?.get('file')
		if (!(file instanceof File)) invalid('Choose a file.')
		const required = docsOf(d.deal_type)
		const asked = form?.get('doc_type')
		const guess = typeof asked === 'string' && asked ? asked : matchDocument(file.name)
		const result: DocumentUploadResult = {
			matched: null,
			candidates: [],
			file_name: file.name,
			size_bytes: file.size
		}
		if (!guess || !required.includes(guess)) {
			const have = new Set(d.documents.map((x) => x.type))
			const missing = required.filter((r) => !have.has(r))
			result.candidates = missing.length ? missing : required
			return { data: result, undo_token: null }
		}
		const before = structuredClone(d.documents)
		d.documents = d.documents.filter((x) => x.type !== guess)
		d.documents.push({
			id: nextId(),
			type: guess,
			file: file.name,
			size_bytes: file.size,
			uploaded: `uploaded ${nowLabel()}`
		})
		result.matched = guess
		return written(result, () => {
			d.documents = before
		})
	}
)

route('DELETE', '/deals/:id/documents/:doc', ({ params }) => {
	const d = findDeal(params[0])
	const before = structuredClone(d.documents)
	const doc = d.documents.find((x) => String(x.id) === params[1]) ?? notFound('Document')
	d.documents = d.documents.filter((x) => x.id !== doc.id)
	return written({ removed: doc.type }, () => {
		d.documents = before
	})
})

route('POST', '/deals/:id/document-requests', ({ params, body }) => {
	findDeal(params[0])
	const types = (body.doc_types as string[] | undefined) ?? []
	if (!types.length) invalid('Pick at least one document.')
	return { requested: types.length }
})

const PCT_KEYS = ['rate_pct', 'cobroker_pct', 'referral_pct', 'agent_pct'] as const

/** Each percentage must be a number from 0 to 100; an empty box is not 0. */
function commissionInputs(d: DbDeal, patch: CommissionPatch) {
	const out = { ...d.commission }
	for (const k of PCT_KEYS) {
		const raw = patch[k] as unknown
		if (raw === undefined) continue
		const v = Number(raw)
		if (raw === null || raw === '' || !Number.isFinite(v) || v < 0 || v > 100)
			invalid('Each percentage must be between 0 and 100.')
		out[k] = v
	}
	return out
}

/** Live result while the agent types; nothing is saved. */
route('POST', '/deals/:id/commission/preview', ({ params, body }) =>
	commission(findDeal(params[0]).value_aed, commissionInputs(findDeal(params[0]), body))
)

route('PATCH', '/deals/:id/commission', ({ params, body }) => {
	const d = findDeal(params[0])
	const patch = body as CommissionPatch
	const next = commissionInputs(d, patch)
	return changeDeal(d, () => {
		for (const k of PCT_KEYS) d.commission[k] = next[k]
		if (patch.invoice_status) d.commission.invoice_status = patch.invoice_status
	})
})

route('POST', '/deals/:id/invoice', ({ params }) => {
	const d = findDeal(params[0])
	const a = commission(d.value_aed, d.commission)
	const res = changeDeal(d, () => {
		if (d.commission.invoice_status === 'not_invoiced') d.commission.invoice_status = 'due'
	})
	return { ...res, invoice: { amount_aed: a.gross - a.cobroker, vat_aed: a.vat } }
})

route('GET', '/deals/:id/forms/:code', ({ params }): FormPreview => {
	const d = findDeal(params[0])
	const code = params[1]
	const buyer = d.client
	const seller = d.counterparty.replace(/ \(.*\)$/, '')
	const price = `AED ${fmt(d.value_aed)}`
	const have = new Set(d.documents.map((x) => x.type))
	const c = d.commission
	const sample = 'ORN 12345 (sample)'
	const brn = `BRN 67890 (sample) · ${d.agent}`
	const forms: Record<string, { title: string; fields: [string, string | null][] }> = {
		A: {
			title: 'A — Agreement between seller and broker',
			fields: [
				['Seller', seller],
				['Property', d.unit],
				['Asking price', price],
				['Brokerage', sample],
				['Agent BRN', brn],
				['Commission', `${c.rate_pct}% + VAT`],
				['Term', `90 days from ${shortDate(TODAY)} 2026`]
			]
		},
		B: {
			title: 'B — Agreement between buyer and broker',
			fields: [
				['Buyer', buyer],
				['Budget', price],
				['Brokerage', sample],
				['Agent BRN', brn],
				['Commission', `${c.rate_pct}% + VAT`]
			]
		},
		F: {
			title: 'F — Contract of sale (MOU)',
			fields: [
				['Buyer', buyer],
				['Seller', seller],
				['Property', d.unit],
				['Price', price],
				['Deposit (10%)', `AED ${fmt(d.value_aed * 0.1)}`],
				['Transfer date', dayLabel(d.due_date)],
				['Mortgage', d.stage_index >= 2 ? 'Yes — valuation booked' : 'To confirm'],
				['NOC', have.has('NOC') ? 'Received' : null]
			]
		},
		I: {
			title: 'I — Agreement between brokers',
			fields: [
				['Listing brokerage', sample],
				['Buyer brokerage', c.cobroker_name],
				['Property', d.unit],
				['Split', c.cobroker_name ? `${100 - c.cobroker_pct} / ${c.cobroker_pct}` : null]
			]
		},
		tenancy: {
			title: 'Unified tenancy contract',
			fields: [
				['Tenant', buyer],
				['Landlord', seller],
				['Property', d.unit],
				['Annual rent', price],
				['Cheques', '4'],
				['Start', '1 Oct 2026'],
				['End', '30 Sep 2027']
			]
		},
		ejari: {
			title: 'Ejari registration',
			fields: [
				['Contract', 'Unified tenancy contract'],
				['Tenant', buyer],
				['Landlord', seller],
				['Property', d.unit],
				['Tenant documents', have.has('Emirates ID') ? 'Passport, Emirates ID on file' : null]
			]
		}
	}
	const f = forms[code] ?? notFound('Form')
	return {
		code,
		title: f.title,
		deal_id: d.id,
		fields: f.fields.map(([label, value]) => ({ label, value: value || null }))
	}
})

route('PATCH', '/deals/:id/compliance', ({ params, body }) => {
	const d = findDeal(params[0])
	return changeDeal(d, () => {
		if (body.due_diligence === 'complete' || body.due_diligence === 'pending')
			d.compliance.due_diligence = body.due_diligence
	})
})

route('POST', '/deals/:id/screening', ({ params }) => {
	const d = findDeal(params[0])
	d.compliance.screening = 'running'
	setTimeout(() => {
		d.compliance.screening = 'clear'
	}, 1200)
	return { status: 'running' }
})

route('POST', '/deals/:id/goaml', ({ params }) => {
	const d = findDeal(params[0])
	if (d.compliance.cash_aed < 55000) invalid('No goAML report is needed on this deal.')
	return { status: 'prepared' }
})

/* ── listings ── */

route('GET', '/listings', ({ query }): ListingListResponse => {
	const scope = query.get('scope') === 'company' ? 'company' : 'mine'
	const status = query.get('status')
	const pool = db.listings.filter((x) => (scope === 'mine' ? x.agent === ME : x.agent !== ME))
	return {
		items: pool.filter((x) => !status || x.status === status).map(listingCard),
		counts: {
			live: pool.filter((x) => x.status === 'live').length,
			pocket: pool.filter((x) => x.status === 'pocket').length,
			expired: pool.filter((x) => x.status === 'expired').length
		}
	}
})

route('GET', '/listings/:id', ({ params }) => listingDetail(findListing(params[0])))

function changeListing(x: DbListing, change: () => void, message: string | null = null) {
	const before = structuredClone(x)
	change()
	const w = written(listingDetail(x), () => {
		Object.assign(x, before)
	})
	return { ...w, message }
}

const mineListing = (id: string) => {
	const x = findListing(id)
	if (x.agent !== ME)
		throw new ApiError('Only the listing agent can change this listing.', 403, 'not_yours')
	return x
}

/** Add a permit, or renew an expired one. */
route('POST', '/listings/:id/permit', ({ params, body }) => {
	const x = mineListing(params[0])
	const number = String(body.number ?? '').trim()
	if (number.length < 4) invalid('Enter the Trakheesi permit number.')
	if (!body.expires || daysFrom(String(body.expires)) < 0) invalid('The permit date has passed.')
	return changeListing(x, () => {
		x.permit = { number: `${number.slice(0, 4)}••`, expires: String(body.expires) }
	})
})

route('POST', '/listings/:id/publish', ({ params }) => {
	const x = mineListing(params[0])
	if (!permitValid(x.permit))
		throw new ApiError('Add a valid permit first.', 409, 'permit_required')
	return changeListing(x, () => {
		x.status = 'live'
		x.portals = 'PF · Bayut'
	})
})

route('POST', '/listings/:id/unpublish', ({ params }) => {
	const x = mineListing(params[0])
	return changeListing(x, () => {
		x.status = 'pocket'
		x.portals = 'Not advertised'
	})
})

route('POST', '/listings/:id/relist', ({ params }) => {
	const x = mineListing(params[0])
	const live = permitValid(x.permit)
	return changeListing(
		x,
		() => {
			x.status = live ? 'live' : 'pocket'
			x.portals = live ? 'PF · Bayut' : 'Not advertised'
		},
		live ? null : 'Permit needs renewing — relisted as pocket'
	)
})

route('POST', '/listings/:id/documents', ({ params, form }) => {
	const x = mineListing(params[0])
	const file = form?.get('file')
	const type = form?.get('doc_type')
	if (!(file instanceof File)) invalid('Choose a file.')
	if (typeof type !== 'string' || !LISTING_DOCS.includes(type)) invalid('Pick the document type.')
	return changeListing(x, () => {
		x.documents = x.documents.filter((d) => d.type !== type)
		x.documents.push({
			id: nextId(),
			type,
			file: file.name,
			size_bytes: file.size,
			uploaded: `uploaded ${nowLabel()}`
		})
		if (type === 'Form A') x.form_a_expires = null
	})
})

function sendToLeads(ids: number[], label: string) {
	const picked = ids.map((id) => findLead(id))
	if (!picked.length) invalid('Pick at least one.')
	const events = picked.map((l) => logLead(l, `Sent: ${label}`, 'human', null))
	return written({ sent: picked.length }, () => {
		for (const e of events) e.reverted = true
	})
}

route('POST', '/listings/:id/send', ({ params, body }) => {
	const x = findListing(params[0])
	const price = x.deal_type === 'rent' ? `${fmt(x.price_aed)} a year` : `AED ${short(x.price_aed)}`
	return sendToLeads((body.lead_ids as number[]) ?? [], `${x.unit} · ${price}`)
})

route('POST', '/listings/:id/brochure/send', ({ params }) => {
	findListing(params[0])
	return { sent: true }
})

/* ── portfolio, renewals, market ── */

route('GET', '/portfolio', (): PortfolioResponse => {
	const rows = [...db.portfolio]
	for (const d of myDeals().filter(isClosed)) {
		if (rows.some((r) => r.unit === d.unit && r.client === d.client)) continue
		rows.push({
			client: d.client,
			what: d.deal_type === 'sale' ? 'Bought' : 'Rented',
			unit: d.unit,
			value_aed: d.value_aed,
			date: shortDate(d.due_date),
			dld_or_ejari: d.dld_transaction_id ?? 'DLD number pending',
			commission_aed: commission(d.value_aed, d.commission).gross
		})
	}
	const clients: PortfolioResponse['clients'] = []
	for (const r of rows) {
		let c = clients.find((x) => x.client === r.client)
		if (!c) {
			c = { client: r.client, transactions: [] }
			clients.push(c)
		}
		c.transactions.push({ ...r, kind: /Rent|Let/.test(r.what) ? 'rent' : 'sale' })
	}
	const all = clients.flatMap((c) => c.transactions)
	const sales = all.filter((t) => t.kind === 'sale')
	const lets = all.filter((t) => t.kind === 'rent')
	return {
		clients,
		totals: {
			sales: sales.length,
			sales_value_aed: sales.reduce((s, t) => s + t.value_aed, 0),
			lets: lets.length,
			lets_value_aed: lets.reduce((s, t) => s + t.value_aed, 0),
			commission_aed: all.reduce((s, t) => s + t.commission_aed, 0),
			clients: clients.length
		}
	}
})

route('POST', '/portfolio/check-in', ({ body }) => {
	if (!body.client) invalid('Pick a client.')
	return { sent: true }
})

function renewalView(r: (typeof db.renewals)[number]): Renewal {
	return {
		...r,
		...renewalChips(r.rent_aed, r.building_median_aed, r.lease_end),
		draft: `Hi, your lease on ${r.unit} ends on ${dayLabel(r.lease_end)}. Rent now is AED ${fmt(r.rent_aed)} a year; the building median is AED ${fmt(r.building_median_aed)}. Can we talk this week about renewing?`
	}
}

route('GET', '/renewals', () => db.renewals.map(renewalView))

route('POST', '/renewals/:id/start', ({ params }) => {
	const r = db.renewals.find((x) => x.id === Number(params[0])) ?? notFound('Renewal')
	if (r.started) throw new ApiError('This renewal has already started.', 409, 'exists')
	let n = 201 + db.deals.length
	while (db.deals.some((d) => d.id === `DL-${n}`)) n += 1
	const deal: DbDeal = {
		id: `DL-${n}`,
		deal_type: 'rent',
		unit: r.unit,
		client: r.party.replace(/ \(.*\)$/, ''),
		counterparty: 'Renewal · same tenant',
		value_aed: r.rent_aed,
		stage_index: 0,
		agent: ME,
		lead_id: null,
		listing_id: null,
		due_date: r.lease_end,
		next_step: 'Tenancy contract',
		approval: 'pending',
		documents: [],
		commission: {
			...defaultCommission('rent', null),
			invoice_status: 'not_invoiced',
			cobroker_name: null,
			referral_name: null
		},
		compliance: { due_diligence: 'pending', screening: 'not_run', cash_aed: 0 },
		dld_transaction_id: null,
		checks: {}
	}
	db.deals.push(deal)
	r.started = true
	r.deal_id = deal.id
	return written(renewalView(r), () => {
		db.deals = db.deals.filter((d) => d.id !== deal.id)
		r.started = false
		r.deal_id = null
	})
})

route('POST', '/renewals/:id/send', ({ params }) => {
	db.renewals.find((x) => x.id === Number(params[0])) ?? notFound('Renewal')
	return { sent: true }
})

function marketView(m: (typeof db.market)[number]): MarketListing {
	return { ...m, discount_chip: discountChip(m.discount_pct) }
}

function marketMatches(m: (typeof db.market)[number]) {
	return myLeads()
		.filter(
			(l) =>
				(l.lead_type === 'buyer' || l.lead_type === 'tenant') &&
				dealTypeOf(l.lead_type) === m.deal_type &&
				isOpenLead(l) &&
				l.source !== 'file' &&
				(l.area === m.area ||
					(Number(l.fields.budget_aed) >= m.price_aed * 0.9 &&
						Number(l.fields.budget_aed) <= m.price_aed * 1.3))
		)
		.slice(0, 5)
}

route('GET', '/market-listings', () =>
	db.market
		.filter((m) => m.deal_type === 'sale' && db.marketAreas.includes(m.area))
		.sort((a, b) => b.discount_pct - a.discount_pct)
		.slice(0, 10)
		.map(marketView)
)

route('GET', '/market-listings/:id', ({ params }): MarketListingDetail => {
	const m = db.market.find((x) => x.id === params[0]) ?? notFound('Portal listing')
	return { ...marketView(m), matched: marketMatches(m).map(leadRow) }
})

route('POST', '/market-listings/:id/watch', ({ params, body }) => {
	const m = db.market.find((x) => x.id === params[0]) ?? notFound('Portal listing')
	const before = m.watch
	m.watch = Boolean(body.watch)
	return written(marketView(m), () => {
		m.watch = before
	})
})

route('POST', '/market-listings/:id/send', ({ params, body }) => {
	const m = db.market.find((x) => x.id === params[0]) ?? notFound('Portal listing')
	return sendToLeads((body.lead_ids as number[]) ?? [], `${m.unit} · AED ${short(m.price_aed)}`)
})

/* ── owners ── */

function ownerInTab(o: DbOwner, tab: OwnerTab): boolean {
	const n = daysFrom(o.next_event_date)
	switch (tab) {
		case 'mine':
			return o.sources.includes('agent_contact')
		case 'multi':
			return o.units.length >= 3 || o.tag === '3+ units'
		case 'event':
			return n >= 0 && n <= 90
		case 'sold':
			return o.tag === 'Just sold'
		case 'update':
			// An update is only due to an owner with a prior deal on record (7 Oct).
			return o.market_update_due && hasPriorDeal(o)
		default:
			return true
	}
}

/** Unit-level filters: an owner shows when any unit fits (area, bedrooms, type), plus unit count. */
function ownerFits(o: DbOwner, q: URLSearchParams): boolean {
	const area = q.get('area')
	const beds = q.get('beds')
	const ptype = q.get('ptype')
	const units = q.get('units')
	if (units && !(units === '3' ? o.units.length >= 3 : o.units.length === Number(units)))
		return false
	if (!area && !beds && !ptype) return true
	return o.units.some(
		(u) =>
			(!area || u.area === area) &&
			(!beds || String(Math.min(4, u.bedrooms ?? -1)) === beds) &&
			(!ptype || (ptype === 'villa') === /villa|townhouse/i.test(u.type))
	)
}

route('GET', '/owners', ({ query }): OwnerListResponse => {
	const tab = (query.get('tab') ?? 'all') as OwnerTab
	const source = query.get('source')
	const q = (query.get('q') ?? '').trim().toLowerCase()
	const tabs: OwnerTab[] = ['mine', 'all', 'multi', 'event', 'sold', 'update']
	const counts = Object.fromEntries(
		tabs.map((t) => [t, db.owners.filter((o) => ownerInTab(o, t)).length])
	) as Record<OwnerTab, number>
	const items = db.owners
		.filter((o) => ownerInTab(o, tab))
		.filter((o) => !source || o.sources.includes(source as DbOwner['sources'][number]))
		.filter((o) => ownerFits(o, query))
		.filter(
			(o) =>
				!q ||
				[o.name, ...o.units.map((u) => `${u.building} ${u.number} #${u.number} ${u.area}`)]
					.join(' ')
					.toLowerCase()
					.includes(q)
		)
		.sort((a, b) => Math.abs(daysFrom(a.next_event_date)) - Math.abs(daysFrom(b.next_event_date)))
	return {
		items: items.map(ownerRow),
		counts,
		total: db.owners.length,
		unit_total: db.owners.reduce((s, o) => s + o.units.length, 0),
		with_event_90: counts.event,
		on_file: db.owners.filter(onAgencyFile).length,
		areas: [...new Set(db.owners.flatMap((o) => o.units.map((u) => u.area)))].sort()
	}
})

const NEXT_ACTION: Record<LeadType, string> = {
	buyer: 'Ask about plans for the cash',
	seller: 'Offer a valuation',
	tenant: 'Call about what they need',
	landlord: 'Call about re-let or sale'
}

route('GET', '/owners/:id', ({ params }): OwnerDetail => {
	const o = findOwner(params[0])
	const areas = new Set(o.units.map((u) => u.area))
	const row = ownerRow(o)
	return {
		...row,
		unit_rows: o.units.map(ownerUnit),
		matched: myLeads()
			.filter(
				(l) =>
					(l.lead_type === 'buyer' || l.lead_type === 'tenant') &&
					areas.has(l.area) &&
					isOpenLead(l)
			)
			.slice(0, 3)
			.map(leadRow),
		notes: [...o.notes].reverse(),
		relationship: relationRows(o),
		create_lead:
			!row.lead &&
			row.prior_deal &&
			o.units.length &&
			ownerActionable(o.next_event, o.next_event_date, o.tag)
				? { lead_type: ownerLeadType(o.next_event, o.tag), next_action: NEXT_ACTION }
				: null
	}
})

/**
 * Owner → lead, by hand for now (a workflow later). The owner record stays as it is; the lead
 * carries the owner match and the chosen unit.
 */
route('POST', '/owners/:id/lead', ({ params, body }): Written<LeadDetail> => {
	const o = findOwner(params[0])
	const input = body as OwnerLeadCreate
	if (ownerLead(o)) throw new ApiError(`${o.name} is already a lead.`, 409, 'exists')
	if (!hasPriorDeal(o))
		throw new ApiError(`${GATE_LINE}. ${o.name} has no prior deal on record.`, 409, 'no_prior_deal')
	if (!LEAD_TYPE_KEYS.includes(input.lead_type)) invalid('Pick the lead type.')
	const u = o.units.find((x) => unitKey(x) === input.unit_key) ?? invalid('Pick the unit.')
	const next = String(input.next_action ?? '').trim()
	if (!next) invalid('Enter the next action.')
	const type = input.lead_type
	const source = onAgencyFile(o) && !o.sources.includes('agent_contact') ? 'file' : 'own_contact'
	const fields: LeadFields =
		type === 'landlord'
			? {
					unit: unitLabel(u),
					expected_rent_aed: u.rent?.aed ?? u.market?.rent[0] ?? 0,
					available: u.status,
					furnishing: '—'
				}
			: type === 'seller'
				? {
						unit: unitLabel(u),
						target_price_aed: u.market?.sale[0] ?? 0,
						occupancy: u.status,
						mortgage: '—',
						timeline: '—'
					}
				: { wants: `Owner — ${o.next_event.toLowerCase()}` }
	const lead: DbLead = {
		id: Math.max(...db.leads.map((l) => l.id)) + 1,
		name: o.name,
		phone: o.phone ?? '—',
		lead_type: type,
		source,
		source_detail: `${o.next_event} · ${unitLabel(u)}`,
		received_label: 'just now',
		stage: 'new',
		agent: ME,
		score: scoreLead(source, fields),
		area: u.area,
		language: '—',
		next_action: next,
		listing_id: null,
		own_listing_id: null,
		off_plan: false,
		fields: cleanFields(type, fields),
		owner_match: o.phone
			? ownerMatchFor(o.phone, source)
			: { summary: `Owns ${o.units.length} unit${o.units.length > 1 ? 's' : ''}`, records: [] },
		suggested_agent: null,
		last_activity: TODAY,
		last_activity_text: 'lead created from the owner record',
		viewing_outcome_due: null,
		form_i_on_file: false,
		first_call_logged: false,
		documents: [],
		owner_id: o.id,
		offer: null
	}
	db.leads.push(lead)
	logLead(lead, `Lead created from the owner record · ${o.next_event}`, 'human', null)
	logLead(lead, `Owner match: ${lead.owner_match.summary}`, 'rule', null)
	const note = {
		id: nextId(),
		at: nowLabel(),
		text: `Lead created (${TYPE_LABEL[type]})`,
		origin: 'human' as const
	}
	o.notes.push(note)
	return written(leadDetail(lead), () => {
		db.leads = db.leads.filter((l) => l.id !== lead.id)
		db.leadEvents = db.leadEvents.filter((e) => e.lead_id !== lead.id)
		o.notes = o.notes.filter((n) => n.id !== note.id)
	})
})

/** "Building · unit" lines from the New owner form become unit rows to check against DLD. */
function unitFromLine(line: string, i: number): DbOwnerUnit {
	const [building, rest] = line.split(/\s*·\s*/)
	const number = rest?.match(/\d+/)?.[0] ?? String(i + 1)
	return {
		number,
		building: building || line,
		area: areaOfUnit(line),
		type: /villa/i.test(line) ? 'Villa' : 'Apartment',
		bedrooms: null,
		size_sqft: null,
		bought_aed: null,
		bought_year: null,
		status: 'Checking DLD and Ejari',
		rent: null,
		market: null,
		rent_history: [],
		transactions: []
	}
}

route('POST', '/owners', ({ body }) => {
	const name = String(body.name ?? '').trim()
	if (!name) invalid('Enter the owner’s name.')
	const units = ((body.units as string[] | undefined) ?? []).map((u) => u.trim()).filter(Boolean)
	const o: DbOwner = {
		id: `O${db.owners.length + 1}-${nextId()}`,
		name,
		phone: null,
		sources: ['agent_contact'],
		units: units.map(unitFromLine),
		next_event: 'Checking DLD and Ejari…',
		next_event_date: TODAY,
		last_contact: 'Never',
		tag: '',
		market_update_due: false,
		notes: [],
		prior: []
	}
	db.owners.push(o)
	return written(ownerRow(o), () => {
		db.owners = db.owners.filter((x) => x.id !== o.id)
	})
})

const PRIOR_WORD: Record<DbPrior['kind'], string> = {
	sale: 'sale',
	tenancy: 'tenancy',
	listing_agreement: 'listing agreement'
}

/**
 * Add record (7 Oct): a documented prior transaction with this owner — sale, tenancy or listing
 * agreement; a date not after today; the unit; a reference (DLD or Ejari number, or Form A
 * number). Writes the record on the owner and a history row on the owner-file lead, one Undo.
 */
route('POST', '/owners/:id/records', ({ params, body }) => {
	const o = findOwner(params[0])
	const input = body as OwnerRecordCreate
	if (!PRIOR_WORD[input.kind]) invalid('Pick the deal type.')
	if (!/^\d{4}-\d{2}-\d{2}$/.test(String(input.date ?? ''))) invalid('Pick the date.')
	if (input.date > TODAY) invalid('The date cannot be after today.')
	const unit = String(input.unit ?? '').trim()
	if (!unit) invalid('Enter the unit.')
	const reference = String(input.reference ?? '').trim()
	if (!reference) invalid('Enter the reference: DLD or Ejari number, or the Form A number.')
	const rec: DbPrior = {
		id: nextId(),
		kind: input.kind,
		date: input.date,
		unit,
		reference,
		added: true
	}
	o.prior.push(rec)
	const lead = db.leads.find((l) => l.owner_id === o.id && l.agent === ME && isOpenLead(l))
	const ev = lead
		? logLead(
				lead,
				`Prior deal record added · ${PRIOR_WORD[rec.kind]} · ${unit} · ${reference}`,
				'human',
				null
			)
		: null
	if (lead?.next_action === GATE_LINE) lead.next_action = 'First call'
	const leadBefore = lead ? { next_action: lead.next_action } : null
	return written(ownerRow(o), () => {
		o.prior = o.prior.filter((p) => p.id !== rec.id)
		if (ev) ev.reverted = true
		if (lead && leadBefore && lead.next_action === 'First call') lead.next_action = GATE_LINE
	})
})

route('POST', '/owners/:id/notes', ({ params, body }) => {
	const o = findOwner(params[0])
	const text = String(body.text ?? '').trim()
	if (!text) invalid('Write what was said.')
	const before = structuredClone(o)
	o.notes.push({ id: nextId(), at: nowLabel(), text, origin: 'human' })
	o.last_contact = 'Today'
	return written(ownerRow(o), () => {
		Object.assign(o, before)
	})
})

route('GET', '/owners/:id/report', ({ params }): OwnerReport => {
	const o = findOwner(params[0])
	return {
		owner: o.name,
		period: 'September 2026',
		rows: o.units.map((u) => {
			const area = AREA_STATS[u.area] ? u.area : areaOfUnit(u.building)
			const s = AREA_STATS[area]
			return {
				unit: unitLabel(u),
				line: `${area} · AED ${fmt(s.psf)} per sqft · median rent ${fmt(s.rent)} · yield ${s.yld.toFixed(1)}%`
			}
		}),
		next_event: `${o.next_event} · ${dayLabel(o.next_event_date)}`
	}
})

function clearUpdateDue(o: DbOwner) {
	const before = o.market_update_due
	o.market_update_due = false
	return written(ownerRow(o), () => {
		o.market_update_due = before
	})
}

route('POST', '/owners/:id/report/send', ({ params }) => clearUpdateDue(findOwner(params[0])))
route('POST', '/owners/:id/market-update', ({ params }) => clearUpdateDue(findOwner(params[0])))

/* ── imports ── */

const importTone = (status: string): Tone =>
	status === 'Waiting' ? 'amber' : /Declined/.test(status) ? 'red' : 'green'

route('GET', '/imports', (): ImportRequest[] =>
	db.imports.filter((r) => r.who === ME).map((r) => ({ ...r, tone: importTone(r.status) }))
)

/** Read the CSV the way the import will: a real parser, so quoted commas stay in one field. */
async function readCsv(form: FormData | null): Promise<{ file: File; rows: string[][] }> {
	const file = form?.get('file')
	if (!(file instanceof File)) invalid('Choose a CSV file.')
	let text: string
	try {
		text = await file.text()
	} catch {
		invalid("Couldn't read this file.")
	}
	const rows = parseCsv(text)
	if (rows.length < 2) invalid('That file has no rows under the header.')
	return { file, rows }
}

/** Preview before sending: the columns the import will use and the first five rows. */
route('POST', '/imports/preview', async ({ form }): Promise<ImportPreview> => {
	const { file, rows } = await readCsv(form)
	const [header, ...body] = rows
	const cols = detectColumns(header)
	const cell = (r: string[], i: number) => (i >= 0 ? (r[i] ?? '') : '')
	return {
		file: file.name,
		rows: body.length,
		columns: {
			name: cols.name >= 0 ? header[cols.name] : null,
			phone: cols.phone >= 0 ? header[cols.phone] : null,
			budget: cols.budget >= 0 ? header[cols.budget] : null,
			area: cols.area >= 0 ? header[cols.area] : null
		},
		sample: body.slice(0, 5).map((r) => ({
			name: cell(r, cols.name),
			phone: cell(r, cols.phone),
			budget: cell(r, cols.budget),
			area: cell(r, cols.area)
		})),
		problem:
			cols.name < 0 && cols.phone < 0
				? 'No name or phone column found. Rename a column to "name" or "phone".'
				: null
	}
})

route('POST', '/imports', async ({ form }) => {
	const { file, rows: parsed } = await readCsv(form)
	const cols = detectColumns(parsed[0])
	if (cols.name < 0 && cols.phone < 0)
		invalid('No name or phone column found. Rename a column to "name" or "phone".')
	const rows = parsed.length - 1
	const kind = form?.get('kind') === 'Leads' ? 'Leads' : 'Owners'
	const areas = String(form?.get('areas') ?? '').trim() || '—'
	const r = {
		id: `R${db.imports.length + 1}-${nextId()}`,
		who: ME,
		kind: kind as 'Owners' | 'Leads',
		file: file.name,
		rows,
		areas,
		at: `${shortDate(TODAY)} ${nowLabel()}`,
		status: 'Waiting'
	}
	db.imports.unshift(r)
	return written({ ...r, tone: importTone(r.status) }, () => {
		db.imports = db.imports.filter((x) => x.id !== r.id)
	})
})

/* ── calendar ── */

route('GET', '/events', ({ query }) => {
	const from = query.get('from') ?? '0000-01-01'
	const to = query.get('to') ?? '9999-12-31'
	return myEvents()
		.filter((e) => e.date >= from && e.date <= to)
		.sort(byTime)
		.map(eventView)
})

route('GET', '/events/:id', ({ params }) =>
	eventView(db.events.find((e) => e.id === Number(params[0])) ?? notFound('Event'))
)

route('POST', '/events', ({ body }) => {
	const input = body as EventCreate
	if (!input.title?.trim()) invalid('Enter a title.')
	if (!input.date) invalid('Pick a date.')
	const ev: DbEvent = {
		id: nextId(),
		date: input.date,
		time: input.time || null,
		kind: input.kind,
		title: input.title.trim(),
		detail: 'Added by hand',
		agent: ME,
		lead_id: null,
		deal_id: null,
		listing_id: null,
		owner_id: null,
		done: false
	}
	db.events.push(ev)
	return written(eventView(ev), () => {
		db.events = db.events.filter((e) => e.id !== ev.id)
	})
})

/**
 * Mark done, or Reschedule (7 Oct): a new date and time; a lead's event is logged on the lead
 * and becomes its next action. One Undo puts both back.
 */
route('PATCH', '/events/:id', ({ params, body }) => {
	const ev = db.events.find((e) => e.id === Number(params[0])) ?? notFound('Event')
	const before = { ...ev }
	if (body.done !== undefined) ev.done = Boolean(body.done)
	const moving = body.date !== undefined
	if (moving) {
		if (!/^\d{4}-\d{2}-\d{2}$/.test(String(body.date))) invalid('Pick a date.')
		if (String(body.date) < TODAY) invalid('Pick today or a later date.')
		ev.date = String(body.date)
		ev.time = body.time ? String(body.time) : null
	}
	const l =
		moving && ev.lead_id ? db.leads.find((x) => x.id === ev.lead_id && x.agent === ME) : undefined
	const leadBefore = l ? structuredClone(l) : null
	if (l) {
		const when = `${dayLabel(ev.date)}${ev.time ? ` ${ev.time}` : ''}`
		logLead(l, `Rescheduled · ${ev.title} → ${when}`, 'human', null)
		l.next_action = `${ev.title.replace(/ — .*$/, '')} · ${when}`
	}
	return written(eventView(ev), () => {
		Object.assign(ev, before)
		if (l && leadBefore) {
			Object.assign(l, leadBefore)
			for (const e of db.leadEvents)
				if (e.lead_id === l.id && e.text.startsWith('Rescheduled · ')) e.reverted = true
		}
	})
})

/** Delete an event (7 Oct): logged on its lead; Undo brings it back. */
route('DELETE', '/events/:id', ({ params }) => {
	const ev = db.events.find((e) => e.id === Number(params[0])) ?? notFound('Event')
	if (ev.agent !== ME) throw new ApiError('Only your own events can be deleted.', 403, 'not_yours')
	const at = db.events.indexOf(ev)
	db.events.splice(at, 1)
	const l = ev.lead_id ? db.leads.find((x) => x.id === ev.lead_id && x.agent === ME) : undefined
	const log = l ? logLead(l, `Deleted · ${ev.title} · ${dayLabel(ev.date)}`, 'human', null) : null
	return written({ deleted: ev.title }, () => {
		db.events.splice(at, 0, ev)
		if (log) log.reverted = true
	})
})

route(
	'GET',
	'/calendar/side',
	(): CalendarSide => ({
		overdue: overdueItems(),
		deadlines: myEvents()
			.filter((e) => e.kind === 'deadline' && daysFrom(e.date) >= 0)
			.sort(byTime)
			.slice(0, 6)
			.map((e) => ({ event: eventView(e), chip: deadlineChip(e.date) as Chip }))
	})
)

/* ── search, notifications, connections ── */

route('GET', '/search', ({ query }): SearchResults => {
	const q = (query.get('q') ?? '').trim().toLowerCase()
	if (q.length < 2) return { leads: [], deals: [], listings: [], owners: [], units: [] }
	const hit = (...parts: unknown[]) =>
		parts.some((p) =>
			String(p ?? '')
				.toLowerCase()
				.includes(q)
		)
	return {
		leads: myLeads()
			.filter((l) => hit(l.name, l.phone, l.fields.wants, l.fields.unit, l.area))
			.slice(0, 6)
			.map(leadRow),
		deals: myDeals()
			.filter((d) => hit(d.id, d.unit, d.client))
			.slice(0, 6)
			.map(dealRow),
		listings: db.listings
			.filter((x) => hit(x.unit, x.area, x.id))
			.slice(0, 6)
			.map(listingCard),
		owners: db.owners
			.filter((o) => hit(o.name, o.phone))
			.slice(0, 6)
			.map(ownerRow),
		units: db.owners
			.flatMap((o) =>
				o.units
					.filter((u) => hit(unitLabel(u), u.area, `#${u.number}`))
					.map((u) => ({ owner_id: o.id, owner_name: o.name, unit: unitLabel(u), area: u.area }))
			)
			.slice(0, 6)
	}
})

route('GET', '/notifications', (): Notification[] => db.notifications.map((n) => ({ ...n })))

route('POST', '/notifications/read', ({ body }) => {
	const ids = body.ids as number[] | undefined
	const before = db.notifications.map((n) => n.unread)
	for (const n of db.notifications) if (!ids || ids.includes(n.id)) n.unread = false
	return written(
		{ unread: db.notifications.filter((n) => n.unread).length },
		ids
			? null
			: () => {
					db.notifications.forEach((n, i) => {
						n.unread = before[i]
					})
				}
	)
})

const CONNECTION_TONE: Record<string, Tone> = {
	Connected: 'green',
	Applying: 'blue',
	'Needs a business number': 'amber'
}

function connectionViews(): Connection[] {
	return db.connections.map((c) => ({ ...c, tone: CONNECTION_TONE[c.status] ?? 'neutral' }))
}

route('GET', '/connections', () => connectionViews())
