/**
 * CRM calls answered by the existing Vitevue backend: leads (/api/v1/crm/inbound), owners
 * (/api/v1/crm/owner-registry), imports, portal listings (/api/v1/listings) and the signed-in
 * user (/api/v1/auth/me). Each function returns the shape in ./types, so screens don't change.
 *
 * Fields the backend does not hold yet are left empty (no agent names, no prior-deal records,
 * no deals or listings on a lead) rather than invented. Writes the backend can't store throw
 * a 501 so the screen shows an error instead of a fake success.
 */
import { me as authMe } from '$lib/api/auth'
import { ApiError, client } from '$lib/api/client'
import type {
	AuthMeResponse,
	CrmContactImportResponse,
	CrmOwnerProfile,
	CrmOwnerProperty,
	CrmOwnerRegistryResponse,
	CrmOwnerWorkspaceSummary,
	InboundEnquiryListResponse,
	InboundEnquiryResponse,
	InboundEnquiryUpdate,
	InboundImportPreviewResponse,
	InboundImportResponse,
	InboundMatchesResponse,
	InboundMatchResponse
} from '$lib/api/generated/hey-api/types.gen'
import { type ListingCardResponse, listings as portal } from '$lib/api/listings'
import { groupOf, LEAD_TYPES, SOURCE_OPTIONS } from '../config'
import { aed, short } from '../format'
import type {
	Chip,
	ImportPreview,
	ImportRequest,
	LeadCreate,
	LeadDetail,
	LeadEvent,
	LeadFieldKey,
	LeadFields,
	LeadListParams,
	LeadListResponse,
	LeadMatches,
	LeadPatch,
	LeadRow,
	LeadStage,
	LeadStageMove,
	LeadType,
	MarketListing,
	MarketListingDetail,
	MatchClient,
	MatchClients,
	MatchRow,
	MatchTier,
	Me,
	OwnerDetail,
	OwnerListParams,
	OwnerListResponse,
	OwnerRow,
	OwnerTab,
	OwnerUnit,
	SearchResults,
	Source,
	Written
} from './types'

const CRM = '/api/v1/crm'
/** Largest page the list endpoints serve; filters and tab counts run over this page. */
const LIST_LIMIT = 500
/** Off-plan buyers are marked with this enquiry tag. */
const OFF_PLAN_TAG = 'off-plan'

type Intent = InboundEnquiryResponse['intent']
type Status = InboundEnquiryResponse['status']
type Criteria = Record<string, unknown>

const done = <T>(data: T): Written<T> => ({ data, undo_token: null })
const notSaved = (what: string) =>
	new ApiError(`${what} isn't available on the backend yet.`, 501, 'not_supported')

/* ── dates ── */

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const dayMonth = (iso: string) => {
	const d = new Date(iso)
	return `${d.getDate()} ${MON[d.getMonth()]}`
}
const stamp = (iso: string) => {
	const d = new Date(iso)
	return `${dayMonth(iso)} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
const daysFromToday = (iso: string) => {
	const today = new Date()
	today.setHours(0, 0, 0, 0)
	return Math.round((new Date(`${iso.slice(0, 10)}T00:00:00`).getTime() - today.getTime()) / 864e5)
}
const received = (iso: string) => {
	const n = -daysFromToday(iso)
	return n <= 0 ? 'today' : n === 1 ? 'yesterday' : `${n} days ago`
}

/* ── signed-in user ── */

let mePromise: Promise<AuthMeResponse> | null = null
const whoAmI = () =>
	(mePromise ??= authMe().catch((e) => {
		mePromise = null
		throw e
	}))

const fullName = (u: AuthMeResponse) => `${u.first_name} ${u.last_name}`.trim() || u.email

/** The calendar day on this device, YYYY-MM-DD. */
export function localToday(): string {
	const d = new Date()
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** Name and initials from the backend. Agent areas are not stored yet, so `areas` is empty. */
export async function me(): Promise<Me> {
	const u = await whoAmI()
	const name = fullName(u)
	const initials = name
		.split(/\s+/)
		.map((w) => w[0] ?? '')
		.join('')
		.slice(0, 2)
		.toUpperCase()
	return { name, initials, role: 'agent', today: localToday(), areas: [] }
}

/* ── leads ── */

const LEAD_TYPE: Record<Exclude<Intent, 'unknown'>, LeadType> = {
	buy: 'buyer',
	rent: 'tenant',
	sell: 'seller',
	let: 'landlord'
}
const INTENT: Record<LeadType, Exclude<Intent, 'unknown'>> = {
	buyer: 'buy',
	tenant: 'rent',
	seller: 'sell',
	landlord: 'let'
}

/** Unqualified contacts (intent unknown) belong to the Inbox, not the Leads list. */
const typeOf = (e: InboundEnquiryResponse): LeadType =>
	e.intent === 'unknown' ? 'buyer' : LEAD_TYPE[e.intent]

function stageOf(status: Status, type: LeadType): LeadStage {
	switch (status) {
		case 'attempted':
		case 'contacted':
			return 'contacted'
		case 'qualified':
		case 'nurture':
		case 'valuation':
			return 'qualified'
		case 'viewing':
			return groupOf(type) === 'sl' ? 'qualified' : 'viewing'
		case 'signed':
		case 'active':
			return groupOf(type) === 'sl' ? 'listed' : 'qualified'
		case 'won':
			return 'won'
		case 'closed_lost':
		case 'disqualified':
			return 'lost'
		default:
			return 'new'
	}
}

function statusOf(stage: LeadStage): Status {
	switch (stage) {
		case 'offer':
			throw notSaved('The Offer stage')
		case 'listed':
			return 'signed'
		case 'lost':
			return 'closed_lost'
		default:
			return stage
	}
}

/** UI field → backend criteria key, where the backend already names it (matching reads these). */
const CRITERIA_KEY: Partial<Record<LeadFieldKey, string>> = {
	budget_aed: 'budget_max_aed',
	target_price_aed: 'expected_price_aed',
	finance: 'financing',
	areas: 'locations'
}

const text = (v: unknown): string | null => {
	if (v === null || v === undefined || v === '') return null
	return Array.isArray(v) ? v.join(', ') || null : String(v)
}
const num = (v: unknown): number | null => {
	const n = Number(v)
	return v === null || v === undefined || v === '' || Number.isNaN(n) ? null : n
}

function wantsOf(c: Criteria): string | null {
	const beds = num(c.bedrooms_min)
	const parts = [
		beds === null ? null : beds === 0 ? 'Studio' : `${beds} bed`,
		text(c.property_type),
		text(c.locations) ? `in ${text(c.locations)}` : null
	].filter(Boolean)
	return parts.length ? parts.join(' ') : null
}

function fieldsOf(c: Criteria): LeadFields {
	const out: LeadFields = {}
	const keys = Object.keys(LEAD_TYPES).flatMap((t) =>
		LEAD_TYPES[t as LeadType].fields.map((f) => f.key)
	)
	for (const k of new Set<LeadFieldKey>([...keys, 'areas', 'on_booking_aed', 'handover_by'])) {
		const raw = c[k] ?? (CRITERIA_KEY[k] ? c[CRITERIA_KEY[k]] : undefined)
		const v = k.endsWith('_aed') ? num(raw) : text(raw)
		if (v !== null) out[k] = v
	}
	out.wants ??= wantsOf(c)
	out.budget_aed ??= num(c.budget_min_aed)
	if (!out.unit) {
		const unit = [text(c.building), text(c.unit_number)].filter(Boolean).join(' #')
		if (unit) out.unit = unit
	}
	for (const k of Object.keys(out) as LeadFieldKey[]) if (out[k] === null) delete out[k]
	return out
}

function criteriaWith(current: Criteria, fields: LeadFields): Criteria {
	const next = { ...current }
	for (const [k, v] of Object.entries(fields)) {
		const key = CRITERIA_KEY[k as LeadFieldKey] ?? k
		if (v === null || v === undefined || v === '') delete next[key]
		else if (key === 'locations')
			next[key] = String(v)
				.split(',')
				.map((s) => s.trim())
				.filter(Boolean)
		else next[key] = v
	}
	return next
}

const sourceOf = (label: string): Source =>
	SOURCE_OPTIONS.find((o) => o.label.toLowerCase() === label.toLowerCase())?.source ?? 'inbound'

function summaryOf(type: LeadType, f: LeadFields): { line: string; sub: string } {
	const money = (v: unknown) => (num(v) ? `AED ${short(Number(v))}` : null)
	const join = (xs: (string | number | null | undefined)[]) => xs.filter(Boolean).join(' · ')
	if (groupOf(type) === 'bt') {
		return {
			line: String(f.wants ?? 'Not stated'),
			sub: join([money(f.budget_aed), f.finance, f.timeline, f.move_in])
		}
	}
	return {
		line: String(f.unit ?? 'Unit not stated'),
		sub: join([money(f.target_price_aed ?? f.expected_rent_aed), f.timeline, f.available])
	}
}

function nextActionOf(e: InboundEnquiryResponse): string {
	const set = text(e.qualification?.next_action)
	if (set) return set
	if (e.next_follow_up) return `Follow up ${dayMonth(e.next_follow_up)}`
	if (e.sla_state === 'overdue') return 'First reply overdue'
	if (e.sla_state === 'due_soon') return 'Reply due soon'
	return ''
}

function knownOf(e: InboundEnquiryResponse): string {
	const o = e.ownership_enrichment
	if (!o?.matched) return 'Not on file'
	return o.reasons?.[0] ?? 'Matches an owner on file'
}

function leadRow(e: InboundEnquiryResponse, u: AuthMeResponse): LeadRow {
	const type = typeOf(e)
	const fields = fieldsOf(e.criteria)
	const locations = e.criteria.locations
	return {
		id: e.id,
		name: e.contact.full_name,
		phone: e.contact.phone ?? e.contact.whatsapp ?? '',
		lead_type: type,
		deal_type: LEAD_TYPES[type].deal,
		source: sourceOf(e.source),
		source_detail: e.campaign ? `${e.source} · ${e.campaign}` : e.source,
		received_label: received(e.enquiry_date),
		stage: stageOf(e.status, type),
		// The backend stores a user id; only the signed-in agent's own name is known here.
		agent: e.assigned_user_id
			? e.assigned_user_id === u.id
				? fullName(u)
				: 'Another agent'
			: null,
		score: e.priority?.score ?? 0,
		area: (Array.isArray(locations) ? text(locations[0]) : null) ?? text(e.criteria.building) ?? '',
		language: e.contact.preferred_language ?? '',
		next_action: nextActionOf(e),
		off_plan: e.tags.includes(OFF_PLAN_TAG),
		gated: false,
		owner_id: null,
		fields,
		summary: summaryOf(type, fields),
		known: knownOf(e),
		source_short: e.source,
		listing: null
	}
}

function leadDetail(e: InboundEnquiryResponse, u: AuthMeResponse): LeadDetail {
	const row = leadRow(e, u)
	return {
		...row,
		owner_match: {
			summary: row.known,
			records: (e.contact.registry_profiles ?? []).map((p) => ({
				unit: [p.building_name || p.project_name, p.unit_number].filter(Boolean).join(' #'),
				area: p.area_name,
				status: p.ownership_status.replaceAll('_', ' '),
				purchase: p.transaction_price_aed
					? `${aed(p.transaction_price_aed)}${p.transaction_date ? ` · ${p.transaction_date.slice(0, 4)}` : ''}`
					: '—',
				owner_id: p.owner_key,
				owner_name: p.contact_name
			}))
		},
		pursued: [],
		suggested_agent: null,
		listing_card: null,
		own_listing: null,
		deal: null,
		stage_documents: [],
		can_undo: false
	}
}

const getEnquiry = (id: number) =>
	client.get<InboundEnquiryResponse>(`${CRM}/inbound/enquiries/${id}`)
const patchEnquiry = (id: number, body: InboundEnquiryUpdate) =>
	client.patch<InboundEnquiryResponse>(`${CRM}/inbound/enquiries/${id}`, body)
const addEnquiryNote = (id: number, body: string) =>
	client.post<InboundEnquiryResponse>(`${CRM}/inbound/enquiries/${id}/notes`, { body })
const addActivity = (id: number, activity_type: string, body?: string) =>
	client.post<InboundEnquiryResponse>(`${CRM}/inbound/enquiries/${id}/activities`, {
		activity_type,
		body: body || undefined
	})

const BUDGET_BANDS: Record<string, (deal: 'sale' | 'rent', v: number) => boolean> = {
	s1: (d, v) => d === 'sale' && v < 1e6,
	s2: (d, v) => d === 'sale' && v >= 1e6 && v <= 3e6,
	s3: (d, v) => d === 'sale' && v > 3e6,
	r1: (d, v) => d === 'rent' && v < 1e5,
	r2: (d, v) => d === 'rent' && v >= 1e5
}

const isVilla = (propertyType: unknown) => /villa|townhouse/i.test(String(propertyType ?? ''))

export async function listLeads(p: LeadListParams): Promise<LeadListResponse> {
	const [res, u] = await Promise.all([
		client.get<InboundEnquiryListResponse>(
			client.withQuery(`${CRM}/inbound/enquiries`, { search: p.q || undefined, limit: LIST_LIMIT })
		),
		whoAmI()
	])
	const all = res.enquiries
		.filter((e) => e.intent !== 'unknown')
		.map((e) => ({ e, row: leadRow(e, u) }))

	const matching = all.filter(({ e, row }) => {
		if (p.source && row.source !== p.source) return false
		if (p.stage && row.stage !== p.stage) return false
		if (p.area && row.area !== p.area) return false
		if (p.beds) {
			const beds = num(e.criteria.bedrooms_min)
			if (beds === null || (p.beds === '4' ? beds < 4 : beds !== Number(p.beds))) return false
		}
		if (p.ptype && (p.ptype === 'villa') !== isVilla(e.criteria.property_type)) return false
		if (p.budget) {
			const v = num(
				row.fields.budget_aed ?? row.fields.target_price_aed ?? row.fields.expected_rent_aed
			)
			if (v === null || !BUDGET_BANDS[p.budget]?.(row.deal_type, v)) return false
		}
		return true
	})
	const open = matching.filter(({ row }) => row.stage !== 'lost')
	const counts = {
		all: open.length,
		lost: matching.length - open.length
	} as LeadListResponse['counts']
	for (const t of Object.keys(LEAD_TYPES) as LeadType[])
		counts[t] = open.filter(({ row }) => row.lead_type === t).length

	const items = (p.lost ? matching.filter(({ row }) => row.stage === 'lost') : open)
		.map(({ row }) => row)
		.filter((row) => !p.lead_type || row.lead_type === p.lead_type)
	return {
		items,
		total: items.length,
		counts,
		new_count: open.filter(({ row }) => row.stage === 'new').length,
		areas: [...new Set(all.map(({ row }) => row.area).filter(Boolean))].sort()
	}
}

export async function getLead(id: number): Promise<LeadDetail> {
	const [e, u] = await Promise.all([getEnquiry(id), whoAmI()])
	return leadDetail(e, u)
}

export async function createLead(body: LeadCreate): Promise<Written<LeadDetail>> {
	const fields =
		body.area && !body.fields.areas ? { ...body.fields, areas: body.area } : body.fields
	const [e, u] = await Promise.all([
		client.post<InboundEnquiryResponse>(`${CRM}/inbound/enquiries`, {
			intent: INTENT[body.lead_type],
			record_kind: 'opportunity',
			full_name: body.name,
			phone: body.phone || undefined,
			source: body.source_detail || 'Manual',
			criteria: criteriaWith({}, fields)
		}),
		whoAmI()
	])
	return done(leadDetail(e, u))
}

export async function patchLead(id: number, body: LeadPatch): Promise<Written<LeadDetail>> {
	const [current, u] = await Promise.all([getEnquiry(id), whoAmI()])
	if (body.phone !== undefined && body.phone !== (current.contact.phone ?? '')) {
		throw notSaved('A changed phone number')
	}
	if (body.language !== undefined && body.language !== (current.contact.preferred_language ?? '')) {
		throw notSaved('A changed language')
	}
	const update: InboundEnquiryUpdate = {}
	if (body.lead_type) update.intent = INTENT[body.lead_type]
	if (body.stage) update.status = statusOf(body.stage)
	if (body.fields) update.criteria = criteriaWith(current.criteria, body.fields)
	if (body.off_plan !== undefined) {
		const tags = current.tags.filter((t) => t !== OFF_PLAN_TAG)
		update.tags = body.off_plan ? [...tags, OFF_PLAN_TAG] : tags
	}
	if (body.next_action !== undefined && body.next_action !== nextActionOf(current)) {
		update.qualification = { ...current.qualification, next_action: body.next_action }
	}
	const e = Object.keys(update).length ? await patchEnquiry(id, update) : current
	return done(leadDetail(e, u))
}

/** "No answer" counts as an attempt, a WhatsApp reply as WhatsApp, anything else as a call. */
const contactType = (outcome?: string) =>
	outcome === 'No answer' ? 'contact_attempt' : outcome?.includes('WhatsApp') ? 'whatsapp' : 'call'

/**
 * A stage move is a status change plus what the form collected. The backend has no calendar or
 * own listings yet, so a viewing's date and a listing's details are kept as a note on the lead.
 */
export async function moveLeadStage(id: number, body: LeadStageMove): Promise<Written<LeadDetail>> {
	const status = statusOf(body.stage)
	const [current, u] = await Promise.all([getEnquiry(id), whoAmI()])
	const update: InboundEnquiryUpdate = { status }
	if (body.stage === 'lost' && body.lost_reason) update.lost_reason = body.lost_reason
	if (body.fields) update.criteria = criteriaWith(current.criteria, body.fields)
	if (body.next_action)
		update.qualification = { ...current.qualification, next_action: body.next_action }
	let e = await patchEnquiry(id, update)

	const lines = [
		body.viewing &&
			`Viewing ${body.viewing.date}${body.viewing.time ? ` ${body.viewing.time}` : ''}`,
		body.listing &&
			`Listing: ${body.listing.unit}, ${body.listing.area} · ${aed(body.listing.price_aed)} · ${body.listing.status}`,
		body.note
	].filter(Boolean) as string[]
	if (body.stage === 'contacted') {
		e = await addActivity(
			id,
			contactType(body.outcome),
			[body.outcome, ...lines].filter(Boolean).join(' · ')
		)
	} else if (lines.length) {
		e = await addEnquiryNote(id, lines.join('\n'))
	}
	return done(leadDetail(e, u))
}

export async function addLeadNote(id: number, body: string): Promise<Written<LeadDetail>> {
	const [e, u] = await Promise.all([addEnquiryNote(id, body), whoAmI()])
	return done(leadDetail(e, u))
}

export async function logLeadCall(id: number, outcome?: string): Promise<Written<LeadDetail>> {
	const [e, u] = await Promise.all([addActivity(id, 'call', outcome), whoAmI()])
	return done(leadDetail(e, u))
}

const ACTIVITY: Record<string, string> = {
	contact_attempt: 'Contact attempt',
	call: 'Call',
	email: 'Email',
	whatsapp: 'WhatsApp',
	meeting: 'Meeting',
	status_changed: 'Stage changed'
}

export async function leadEvents(id: number): Promise<LeadEvent[]> {
	const e = await getEnquiry(id)
	const rows = [
		...(e.activities ?? []).map((a) => ({
			id: a.id,
			iso: a.created_at,
			text: [ACTIVITY[a.activity_type] ?? a.activity_type.replaceAll('_', ' '), a.body]
				.filter(Boolean)
				.join(' · ')
		})),
		// Notes and activities are separate tables; negative ids keep the list keys unique.
		...(e.notes ?? []).map((n) => ({ id: -n.id, iso: n.created_at, text: `Note · ${n.body}` }))
	]
	return rows
		.sort((a, b) => b.iso.localeCompare(a.iso))
		.map((r) => ({ id: r.id, at: stamp(r.iso), text: r.text, origin: 'human', revertible: false }))
}

/* ── lead matches ── */

const FIT: Record<InboundMatchResponse['fit'], Chip> = {
	exact: { tone: 'green', label: 'Exact fit' },
	near: { tone: 'blue', label: 'Near fit' },
	review: { tone: 'amber', label: 'Check' },
	outside: { tone: 'neutral', label: 'Outside the brief' }
}

/** Backend lanes in the order each side shows them; the row kind decides the buttons. */
const LANES: Record<
	'bt' | 'sl',
	{ lane: string; title: string; kind: MatchRow['kind']; line: MatchRow['line'] }[]
> = {
	bt: [
		{ lane: 'listings', title: 'Portal listings', kind: 'public', line: 'in' },
		{ lane: 'owners', title: 'Owners on your file', kind: 'owner', line: 'vv' },
		{ lane: 'units', title: 'Units on record', kind: 'owner', line: 'vv' },
		{ lane: 'offplan', title: 'Off-plan projects', kind: 'allocation', line: 'own' }
	],
	sl: [{ lane: 'demand', title: 'Buyers and tenants who fit', kind: 'lead', line: 'own' }]
}

const matchKey = (m: InboundMatchResponse) => `m${m.id}`

async function loadMatches(id: number): Promise<InboundMatchesResponse> {
	const res = await client.get<InboundMatchesResponse>(`${CRM}/inbound/enquiries/${id}/matches`)
	if (Object.values(res.lanes).some((rows) => rows.length)) return res
	// Matches are computed on request; a lead nobody has matched yet gets one run.
	return client.post<InboundMatchesResponse>(`${CRM}/inbound/enquiries/${id}/matches/refresh`)
}

export async function leadMatches(id: number): Promise<LeadMatches> {
	const [e, res, u] = await Promise.all([getEnquiry(id), loadMatches(id), whoAmI()])
	const lead = leadRow(e, u)
	const side = groupOf(lead.lead_type)
	const live = (lane: string) => (res.lanes[lane] ?? []).filter((m) => m.state !== 'dismissed')

	const tiers: MatchTier[] = LANES[side].map((t, i) => ({
		id: t.lane,
		n: i + 1,
		title: t.title,
		sub: `${live(t.lane).length} found`,
		chip: null,
		gate: null,
		groups: [
			{
				label: null,
				empty: 'No matches yet.',
				rows: live(t.lane).map(
					(m): MatchRow => ({
						key: matchKey(m),
						kind: t.kind,
						title: m.title,
						sub: m.subtitle,
						line: t.line,
						over_budget: null,
						chip: FIT[m.fit],
						why: m.missing_fields.length
							? [...m.reasons, `Missing: ${m.missing_fields.join(', ')}`]
							: m.reasons,
						ref:
							t.kind === 'public'
								? { kind: 'market', id: m.target_key }
								: t.kind === 'lead' && /^\d+$/.test(m.target_key)
									? { kind: 'lead', id: m.target_key }
									: null,
						lead_stages: null,
						colleague: null,
						owner: null,
						pursuable: false,
						pursued: null,
						shortlisted: m.state === 'saved',
						watching: false,
						renewal_planned: false,
						after_move: false,
						can_book: false
					})
				)
			}
		],
		hidden_after: 0
	}))

	return {
		tab: side === 'sl' ? 'sell' : lead.off_plan ? 'offplan' : 'ready',
		lead,
		brief: LEAD_TYPES[lead.lead_type].fields
			.filter((f) => lead.fields[f.key])
			.map((f) => ({
				k: f.label,
				v: f.money ? aed(Number(lead.fields[f.key])) : String(lead.fields[f.key])
			})),
		move_by: null,
		shortlist: Object.values(res.lanes)
			.flat()
			.filter((m) => m.state === 'saved').length,
		tiers,
		status: null,
		own_listing: null
	}
}

/** Shortlist = the backend's "saved" match state; again to take it off. */
export async function shortlistMatch(
	id: number,
	key: string
): Promise<Written<{ on: boolean; count: number }>> {
	const res = await client.get<InboundMatchesResponse>(`${CRM}/inbound/enquiries/${id}/matches`)
	const all = Object.values(res.lanes).flat()
	const match = all.find((m) => matchKey(m) === key)
	if (!match)
		throw new ApiError('This match is no longer there. Reopen the lead.', 404, 'not_found')
	const on = match.state !== 'saved'
	await client.patch(`${CRM}/inbound/matches/${match.id}`, { state: on ? 'saved' : 'suggested' })
	const count = all.filter((m) => (m.id === match.id ? on : m.state === 'saved')).length
	return done({ on, count })
}

/* ── owners ── */

const OWNERSHIP: Record<CrmOwnerProperty['ownership_status'], Chip> = {
	verified_current_owner: { tone: 'green', label: 'Verified owner' },
	probable_current_owner: { tone: 'green', label: 'Probable owner' },
	unit_linked_unverified: { tone: 'amber', label: 'Not verified' },
	former_owner: { tone: 'neutral', label: 'Sold' },
	conflicting_claim: { tone: 'red', label: 'Conflicting claim' },
	insufficient_property_data: { tone: 'neutral', label: 'Not enough data' },
	registry_not_observed: { tone: 'neutral', label: 'Not in registry' },
	unmatched: { tone: 'neutral', label: 'Unmatched' }
}

const unitLabel = (p: CrmOwnerProperty) =>
	[p.building_name || p.project_name, p.unit_number].filter(Boolean).join(' #')
const bedsOf = (p: CrmOwnerProperty) => {
	const b = p.registry_bedrooms?.trim().toLowerCase()
	if (!b) return null
	if (b.startsWith('studio')) return 0
	const n = Number.parseInt(b, 10)
	return Number.isNaN(n) ? null : n
}
const soldLater = (p: CrmOwnerProfile) =>
	(p.properties ?? []).some((x) => x.later_sale_date || x.ownership_status === 'former_owner')

function ownerRow(p: CrmOwnerProfile, ws: CrmOwnerWorkspaceSummary | undefined): OwnerRow {
	const end = p.next_lease_end ?? null
	const days = end ? daysFromToday(end) : null
	return {
		id: p.owner_key,
		name: p.contact_name,
		sources: ['agency_import'],
		source_label: 'Agency file',
		units: (p.properties ?? []).map(unitLabel),
		next_event: end ? 'Lease ends' : 'No event on record',
		next_event_date: end ?? '',
		next_event_label:
			days === null
				? ''
				: `${days >= 0 ? `in ${days} days` : `${-days} days ago`} · ${dayMonth(end as string)}`,
		last_contact: ws?.last_note ? dayMonth(ws.updated_at) : 'Never',
		tag: OWNERSHIP[p.highest_ownership_status].label,
		market_update_due: false,
		mine: Boolean(ws),
		on_file: true,
		// Prior deals are not recorded by the backend yet, so the DLD 02-2026 gate stays on.
		prior_deal: false,
		lead: null
	}
}

function ownerUnit(p: CrmOwnerProperty): OwnerUnit {
	const sale =
		p.registry_sale_price_aed ?? p.latest_sale_price_aed ?? p.imported_transaction_price_aed ?? null
	const saleDate = p.registry_sale_date ?? p.latest_sale_date ?? p.imported_transaction_date ?? null
	const transactions = [
		p.imported_transaction_date && {
			when: p.imported_transaction_date,
			what: 'On the agency file',
			aed: p.imported_transaction_price_aed ?? null
		},
		p.registry_sale_date && {
			when: p.registry_sale_date,
			what: 'Sale',
			aed: p.registry_sale_price_aed ?? null
		},
		p.later_sale_date && { when: p.later_sale_date, what: 'Sold on', aed: null }
	].filter(Boolean) as { when: string; what: string; aed: number | null }[]
	const chip = OWNERSHIP[p.ownership_status]
	return {
		key: p.property_key,
		number: p.unit_number,
		building: p.building_name || p.project_name,
		area: p.area_name,
		type: p.registry_property_type || p.property_type,
		bedrooms: bedsOf(p),
		size_sqft: p.registry_size_sqft ?? null,
		bought_aed: sale,
		bought_year: saleDate ? Number(saleDate.slice(0, 4)) : null,
		status:
			p.lease_end && p.annual_rent_aed
				? `Let at ${aed(p.annual_rent_aed)} a year until ${dayMonth(p.lease_end)}`
				: chip.label,
		status_chip: chip,
		// The backend keeps the lease end, not its start, so "Rent now" shows through `status`.
		rent: null,
		market: null,
		rent_history: [],
		transactions: [...new Map(transactions.map((t) => [`${t.when}${t.what}`, t])).values()].map(
			(t) => ({ ...t, when: t.when.slice(0, 10) })
		)
	}
}

const ownerWorkspaces = () => client.get<CrmOwnerWorkspaceSummary[]>(`${CRM}/owner-workspaces`)

export async function listOwners(p: OwnerListParams): Promise<OwnerListResponse> {
	const [res, ws] = await Promise.all([
		client.get<CrmOwnerRegistryResponse>(
			client.withQuery(`${CRM}/owner-registry`, {
				scope: 'all',
				search: p.q || undefined,
				limit: LIST_LIMIT
			})
		),
		ownerWorkspaces()
	])
	const byKey = new Map(ws.map((w) => [w.owner_key, w]))
	const all = res.owners.map((o) => ({ o, row: ownerRow(o, byKey.get(o.owner_key)) }))

	const matching = all.filter(({ o, row }) => {
		const props = o.properties ?? []
		if (p.source && !row.sources.includes(p.source)) return false
		if (p.area && !props.some((x) => x.area_name === p.area)) return false
		if (p.beds) {
			const want = Number(p.beds)
			if (!props.some((x) => (bedsOf(x) ?? -1) === want || (want === 4 && (bedsOf(x) ?? 0) >= 4)))
				return false
		}
		if (
			p.ptype &&
			!props.some(
				(x) => (p.ptype === 'villa') === isVilla(x.registry_property_type || x.property_type)
			)
		)
			return false
		if (p.units) {
			const n = props.length
			if (p.units === '3' ? n < 3 : n !== Number(p.units)) return false
		}
		return true
	})

	const inEvent = (o: CrmOwnerProfile) => {
		if (!o.next_lease_end) return false
		const d = daysFromToday(o.next_lease_end)
		return d >= 0 && d <= 90
	}
	const TABS: Record<OwnerTab, (x: (typeof all)[number]) => boolean> = {
		all: () => true,
		mine: ({ row }) => row.mine,
		multi: ({ o }) => (o.properties ?? []).length >= 3,
		event: ({ o }) => inEvent(o),
		sold: ({ o }) => soldLater(o),
		update: ({ row }) => row.market_update_due
	}
	const counts = Object.fromEntries(
		(Object.keys(TABS) as OwnerTab[]).map((t) => [t, matching.filter(TABS[t]).length])
	) as Record<OwnerTab, number>
	const items = matching.filter(TABS[p.tab]).map(({ row }) => row)

	return {
		items,
		counts,
		total: items.length,
		unit_total: items.reduce((n, r) => n + r.units.length, 0),
		with_event_90: matching.filter(({ o }) => inEvent(o)).length,
		on_file: res.total,
		areas: [
			...new Set(
				all.flatMap(({ o }) => (o.properties ?? []).map((x) => x.area_name)).filter(Boolean)
			)
		].sort()
	}
}

export async function getOwner(id: string): Promise<OwnerDetail> {
	const [o, ws] = await Promise.all([
		client.get<CrmOwnerProfile>(`${CRM}/owners/${encodeURIComponent(id)}`),
		ownerWorkspaces()
	])
	const w = ws.find((x) => x.owner_key === id)
	return {
		...ownerRow(o, w),
		unit_rows: (o.properties ?? []).map(ownerUnit),
		matched: [],
		// The workspace keeps the latest note only.
		notes: w?.last_note
			? [{ id: 1, at: stamp(w.updated_at), text: w.last_note, origin: 'human' }]
			: [],
		relationship: [],
		create_lead: null
	}
}

export async function addOwnerNote(id: string, note: string): Promise<Written<OwnerRow>> {
	await client.patch(`${CRM}/owner-workspaces/bulk`, { owner_keys: [id], note })
	const {
		unit_rows: _u,
		matched: _m,
		notes: _n,
		relationship: _r,
		create_lead: _c,
		...row
	} = await getOwner(id)
	return done(row)
}

/* ── imports ── */

const IMPORT_STATUS: Record<
	InboundImportResponse['status'],
	{ status: string; tone: Chip['tone'] }
> = {
	processing: { status: 'Processing', tone: 'amber' },
	completed: { status: 'Imported', tone: 'green' },
	failed: { status: 'Failed', tone: 'red' }
}

function importRow(
	kind: 'Owners' | 'Leads',
	r: InboundImportResponse | CrmContactImportResponse
): ImportRequest & { created: string } {
	return {
		id: `${kind === 'Leads' ? 'L' : 'O'}${r.id}`,
		who: r.name || 'Agency file',
		kind,
		file: r.original_filename,
		rows: r.summary.total_rows ?? 0,
		areas: '—',
		at: stamp(r.created_at),
		created: r.created_at,
		...IMPORT_STATUS[r.status]
	}
}

export async function listImports(): Promise<ImportRequest[]> {
	const [leads, owners] = await Promise.all([
		client.get<InboundImportResponse[]>(`${CRM}/inbound/imports`),
		client.get<CrmContactImportResponse[]>(`${CRM}/contact-imports`)
	])
	return [...leads.map((r) => importRow('Leads', r)), ...owners.map((r) => importRow('Owners', r))]
		.sort((a, b) => b.created.localeCompare(a.created))
		.map(({ created: _c, ...r }) => r)
}

/**
 * Leads files are read by the backend. Owner files have no preview endpoint, so only the row
 * count is shown; the backend maps their columns when the file is imported.
 */
export async function previewImport(file: File, kind: 'Owners' | 'Leads'): Promise<ImportPreview> {
	if (kind === 'Owners') {
		const lines = (await file.text()).split(/\r?\n/).filter((l) => l.trim())
		return {
			file: file.name,
			rows: Math.max(0, lines.length - 1),
			columns: { name: null, phone: null, budget: null, area: null },
			sample: [],
			problem: null
		}
	}
	const fd = new FormData()
	fd.append('file', file)
	const res = await client.post<InboundImportPreviewResponse>(`${CRM}/inbound/imports/preview`, fd)
	const sheet = res.sheets[0]
	const col = (key: string) => sheet?.field_map[key] ?? null
	return {
		file: res.original_filename,
		rows: res.total_rows,
		columns: {
			name: col('full_name'),
			phone: col('phone'),
			budget: col('budget_max'),
			area: col('locations')
		},
		sample: (sheet?.sample_rows ?? []).map((r) => ({
			name: r.full_name ?? '',
			phone: r.phone ?? '',
			budget: r.budget_max ?? '',
			area: r.locations ?? ''
		})),
		problem: res.warnings?.[0] ?? (res.sheets.length ? null : 'No rows found in this file.')
	}
}

/** The import endpoints take no areas; the Areas box is not sent. */
export async function createImport(
	file: File,
	kind: 'Owners' | 'Leads'
): Promise<Written<ImportRequest>> {
	const fd = new FormData()
	fd.append('file', file)
	fd.append('name', file.name)
	if (kind === 'Leads') {
		const r = await client.post<InboundImportResponse>(`${CRM}/inbound/imports`, fd)
		const { created: _c, ...row } = importRow('Leads', r)
		return done(row)
	}
	const r = await client.post<CrmContactImportResponse>(`${CRM}/contact-imports`, fd)
	const { created: _c, ...row } = importRow('Owners', r)
	return done(row)
}

/* ── portal listings (Assets › Market) ── */

function discountChip(pct: number): Chip {
	const p = Math.round(pct)
	if (pct >= 7) return { tone: 'green', label: `${p}% under` }
	if (pct <= -7) return { tone: 'amber', label: `${-p}% over` }
	return { tone: 'neutral', label: 'In line' }
}

function marketListing(l: ListingCardResponse): MarketListing | null {
	const price = l.price_value ?? null
	const value = l.market_estimate_aed ?? null
	if (!price || !value) return null
	const discount = Math.round(((value - price) / value) * 1000) / 10
	const beds = l.bedrooms ? (/^\d+$/.test(l.bedrooms) ? `${l.bedrooms}BR` : l.bedrooms) : null
	return {
		id: l.listing_id,
		unit: [l.tower_name || l.subcommunity_name || l.location_name || l.title, beds]
			.filter(Boolean)
			.join(' · '),
		area: l.area_name ?? '',
		deal_type: l.listing_mode === 'sale' ? 'sale' : 'rent',
		price_aed: price,
		value_from_comparables_aed: Math.round(value),
		discount_pct: discount,
		discount_chip: discountChip(discount),
		portal: l.broker_name ? `Property Finder · ${l.broker_name}` : 'Property Finder',
		days_listed: l.listing_age_days ?? 0,
		// Not tracked by the listings feed.
		price_cuts: 0,
		watch: false
	}
}

/** Residential sale and rent listings that have a comparable-sales estimate, best value first. */
export async function listMarket(): Promise<MarketListing[]> {
	const [sale, rent] = await Promise.all(
		(['sale', 'rent'] as const).map((mode) =>
			portal.list({ mode, asset_class: 'residential', limit: 120 })
		)
	)
	return [...sale.listings, ...rent.listings]
		.map(marketListing)
		.filter((m): m is MarketListing => m !== null)
		.sort((a, b) => b.discount_pct - a.discount_pct)
}

export async function getMarket(id: string): Promise<MarketListingDetail> {
	const l = await portal.get(id)
	const m = marketListing(l)
	if (!m)
		throw new ApiError('This listing has no comparable sales to compare against.', 404, 'not_found')
	return { ...m, matched: [] }
}

/* ── built from leads and owners ── */

/** Global search over leads and owners; deals and the agency's listings are not stored yet. */
export async function search(q: string): Promise<SearchResults> {
	const term = q.trim()
	if (!term) return { leads: [], deals: [], listings: [], owners: [], units: [] }
	const [leads, owners] = await Promise.all([
		listLeads({ q: term }),
		listOwners({ tab: 'all', q: term })
	])
	const needle = term.toLowerCase()
	return {
		leads: leads.items.slice(0, 8),
		deals: [],
		listings: [],
		owners: owners.items.slice(0, 8),
		units: owners.items
			.flatMap((o) =>
				o.units
					.filter((u) => u.toLowerCase().includes(needle))
					.map((unit) => ({ owner_id: o.id, owner_name: o.name, unit, area: '' }))
			)
			.slice(0, 8)
	}
}

/** Matches › clients: open leads split by what they look for. */
export async function matchClients(): Promise<MatchClients> {
	const { items } = await listLeads({})
	const client = (lead: LeadRow): MatchClient => ({
		lead,
		line: [lead.summary.line, lead.summary.sub].filter(Boolean).join(' · '),
		pursued: 0
	})
	return {
		ready: items.filter((l) => groupOf(l.lead_type) === 'bt' && !l.off_plan).map(client),
		offplan: items.filter((l) => l.lead_type === 'buyer' && l.off_plan).map(client),
		sell: items.filter((l) => groupOf(l.lead_type) === 'sl').map(client)
	}
}

/* ── calls with no backend yet ── */

/** A write (or a single record) the backend has no endpoint for yet: a 501, never a fake success. */
export const notOnBackend = <T>(what: string): Promise<T> => Promise.reject(notSaved(what))
