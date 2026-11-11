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
	CrmAreaPreferencesResponse,
	CrmCompanyListingDetail,
	CrmContactImportResponse,
	CrmContactListDetail,
	CrmDroppedRowsResponse,
	CrmImportPropertiesResponse,
	CrmLead,
	CrmLeadDetailResponse,
	CrmLeadImportedContact,
	CrmOwnerProfile,
	CrmOwnerProperty,
	CrmOwnerRegistryResponse,
	CrmOwnerWorkspaceSummary,
	CrmRenewalArea,
	CrmRenewalLeadsResponse,
	CrmRenewalOwner,
	CrmRenewalsResponse,
	CrmWorkspaceResponse,
	DocumentDownloadResponse,
	GenerateDocumentRequest,
	GeneratedDocumentListResponse,
	GeneratedDocumentResponse,
	InboundEnquiryListResponse,
	InboundEnquiryResponse,
	InboundEnquiryUpdate,
	InboundImportPreviewResponse,
	InboundImportResponse,
	InboundMatchesResponse,
	InboundMatchResponse,
	ListingDocumentInfoResponse,
	ListingDocumentInfoUpdate
} from '$lib/api/generated/hey-api/types.gen'
import { type ListingCardResponse, listings as portal } from '$lib/api/listings'
import { groupOf, LEAD_TYPES, ownerPropertyKind, PROPERTY_TYPES, SOURCE_OPTIONS } from '../config'
import { aed, dayLabel, fmt, fullDate, ISO_DAY, plural, short } from '../format'
import {
	type ClaimStatus,
	importCounts,
	isFlagged,
	mappingChecks,
	STATUS_INFO
} from '../ownerImportReport'
import type {
	CalendarEvent,
	CalendarSide,
	Chip,
	CompanyListingAgentInventory,
	CompanyListingCompany,
	CompanyListingFilter,
	DocumentListParams,
	EmailInboundList,
	EmailLeadList,
	EmailLeadParams,
	EmailSendBatch,
	EmailSendList,
	EmailSendStatus,
	EmailStatus,
	EmailSync,
	EmailTemplate,
	EmailTemplateInput,
	EmailThreadItem,
	EventCreate,
	FeedArea,
	FeedPreferences,
	FeedSummary,
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
	LeadListParams,
	LeadListResponse,
	LeadMatches,
	LeadPatch,
	LeadRow,
	LeadStage,
	LeadStageMove,
	LeadType,
	ListingCard,
	ListingDetail,
	ListingListResponse,
	ListingStatus,
	MarketingConsent,
	MarketListing,
	MarketListingDetail,
	MatchClient,
	MatchClients,
	MatchRow,
	MatchTier,
	Me,
	OwnerDetail,
	OwnerDroppedRows,
	OwnerDroppedRowsParams,
	OwnerFilePreview,
	OwnerImport,
	OwnerImportDetail,
	OwnerImportResult,
	OwnerImportRow,
	OwnerImportRows,
	OwnerImportRowsParams,
	OwnerImportSource,
	OwnerListParams,
	OwnerListResponse,
	OwnerProperties,
	OwnerPropertyParams,
	OwnerRow,
	OwnerTab,
	OwnerUnit,
	RecentSale,
	Renewal,
	RenewalDetail,
	RenewalListParams,
	RenewalListResponse,
	RenewalOwner,
	SearchResults,
	Source,
	VitevueLease,
	WhatsAppAudience,
	WhatsAppCampaign,
	WhatsAppCampaignCreate,
	WhatsAppCampaignDetail,
	WhatsAppChat,
	WhatsAppMetaNumber,
	WhatsAppNumber,
	WhatsAppNumberWrite,
	WhatsAppStatus,
	WhatsAppTemplate,
	WhatsAppThread,
	Written
} from './types'

const CRM = '/api/v1/crm'
/** Largest page the list endpoints serve; filters and tab counts run over this page. */
const LIST_LIMIT = 500
/** Off-plan buyers are marked with this enquiry tag. */
const OFF_PLAN_TAG = 'off-plan'
/** Source of the leads Vitevue supplies from lease data (backend VITEVUE_LEASE_SOURCE). */
const VITEVUE_SOURCE = 'Vitevue lease lead'
/** Owners on the agency file whose unit just resold (backend SOLD_OWNER_SOURCE). */
const SOLD_OWNER_SOURCE = 'Owner file · recently sold'

export interface GoogleCalendarStatus {
	configured: boolean
	connected: boolean
	email: string | null
}

export const googleCalendarStatus = () => client.get<GoogleCalendarStatus>(`${CRM}/calendar/google`)
export const connectGoogleCalendar = () =>
	client.post<{ authorization_url: string }>(`${CRM}/calendar/google/connect`)
export const disconnectGoogleCalendar = () => client.delete<void>(`${CRM}/calendar/google`)
export const listCalendarEvents = (from: string, to: string) =>
	client.get<CalendarEvent[]>(`${CRM}/calendar/events?start=${from}&end=${to}`)
export const getCalendarEvent = (id: number) =>
	client.get<CalendarEvent>(`${CRM}/calendar/events/${id}`)
export const createCalendarEvent = (body: EventCreate) =>
	client.post<CalendarEvent>(`${CRM}/calendar/events`, body)
export const bookCalendarViewing = (
	leadId: number,
	body: { date: string; time: string; listing_id: string | null; note: string }
) => client.post<CalendarEvent>(`${CRM}/calendar/viewings/${leadId}`, body)
export const moveCalendarEvent = (id: number, date: string, time: string | null) =>
	client.patch<CalendarEvent>(`${CRM}/calendar/events/${id}`, { date, time })
export const updateCalendarEvent = (id: number, body: EventCreate) =>
	client.put<CalendarEvent>(`${CRM}/calendar/events/${id}`, body)
export const completeCalendarEvent = (id: number) =>
	client.post<CalendarEvent>(`${CRM}/calendar/events/${id}/done`)
export const deleteCalendarEvent = (id: number) =>
	client.delete<void>(`${CRM}/calendar/events/${id}`)
export const calendarSide = async (): Promise<CalendarSide> => ({ overdue: [], deadlines: [] })

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
	return { name, initials, role: 'agent', is_owner: u.is_owner, today: localToday(), areas: [] }
}

/* ── leads ── */

const LEAD_TYPE: Record<Exclude<Intent, 'unknown'>, LeadType> = {
	buy: 'buyer',
	rent: 'tenant',
	sell: 'seller',
	let: 'landlord'
}
const INTENT: Record<LeadType, Intent> = {
	buyer: 'buy',
	tenant: 'rent',
	seller: 'sell',
	landlord: 'let',
	owner: 'unknown'
}

const isVitevue = (e: InboundEnquiryResponse) => e.source === VITEVUE_SOURCE

/**
 * Unqualified contacts (intent unknown) belong to the Inbox, not the Leads list. A Vitevue lease
 * lead is the exception: it stays in Leads as "seller or landlord" until the agent picks one.
 */
const typeOf = (e: InboundEnquiryResponse): LeadType =>
	e.intent === 'unknown' ? (isVitevue(e) ? 'owner' : 'buyer') : LEAD_TYPE[e.intent]

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
	wants: 'property_type',
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

/** Imported synonyms, shown as the portal type the Wants dropdown offers. */
const TYPE_SYNONYMS: Record<string, string> = {
	flat: 'Apartment',
	unit: 'Apartment',
	residential: 'Apartment',
	'residential flat': 'Apartment',
	'residential flats': 'Apartment',
	apartments: 'Apartment',
	villas: 'Villa',
	townhouses: 'Townhouse'
}

/** The Wants option for a stored property type; an unknown name is kept as it is. */
function wantsOption(v: unknown): string | null {
	const raw = text(v)
	if (!raw) return null
	const key = raw.trim().toLowerCase()
	return PROPERTY_TYPES.find((t) => t.toLowerCase() === key) ?? TYPE_SYNONYMS[key] ?? raw
}

/** The Bedrooms option for a saved range: 0 is a studio, 7 with no upper bound is 7+. */
function bedroomsOption(c: Criteria): string | null {
	const beds = num(c.bedrooms_min)
	if (beds === null) return null
	if (beds === 0) return 'Studio'
	return beds >= 7 && num(c.bedrooms_max) === null ? '7+' : String(beds)
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
	// Wants is the property type matching filters on, not the older free text under `wants`.
	out.wants = wantsOption(c.property_type)
	out.bedrooms = bedroomsOption(c)
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
	// Wants now saves as property_type; drop the older free text so it cannot drift from it.
	if ('wants' in fields) delete next.wants
	for (const [k, v] of Object.entries(fields)) {
		if (k === 'bedrooms') {
			// One choice is a range for matching: Studio = 0, "7+" = 7 and up, else exactly that.
			delete next.bedrooms_min
			delete next.bedrooms_max
			if (v === null || v === undefined || v === '') continue
			const beds = v === 'Studio' ? 0 : Number.parseInt(String(v), 10)
			next.bedrooms_min = beds
			if (v !== '7+') next.bedrooms_max = beds
			continue
		}
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
	label === VITEVUE_SOURCE
		? 'vitevue'
		: label === SOLD_OWNER_SOURCE
			? 'file'
			: (SOURCE_OPTIONS.find((o) => o.label.toLowerCase() === label.toLowerCase())?.source ??
				'inbound')

function summaryOf(type: LeadType, f: LeadFields, c: Criteria): { line: string; sub: string } {
	const money = (v: unknown) => (num(v) ? `AED ${short(Number(v))}` : null)
	const join = (xs: (string | number | null | undefined)[]) => xs.filter(Boolean).join(' · ')
	if (groupOf(type) === 'bt') {
		return {
			line: wantsOf(c) ?? text(c.wants) ?? 'Not stated',
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
	const lease = isVitevue(e) ? leaseOfEnquiry(e) : null
	return {
		id: e.id,
		// An owner nobody has identified yet has no name: show the unit, never an invented name.
		name: e.contact.full_name || lease?.unit || 'Owner not identified',
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
		score: lease ? vitevueScore(lease.days_left, lease.vacant) : (e.priority?.score ?? 0),
		area: (Array.isArray(locations) ? text(locations[0]) : null) ?? text(e.criteria.building) ?? '',
		language: e.contact.preferred_language ?? '',
		next_action: nextActionOf(e),
		off_plan: e.tags.includes(OFF_PLAN_TAG),
		gated: false,
		owner_id: null,
		fields,
		summary:
			lease && type === 'owner' ? vitevueSummary(lease) : summaryOf(type, fields, e.criteria),
		known: knownOf(e),
		source_short: e.source,
		listing: null,
		lease,
		recent_sales: recentSales(e)
	}
}

const CONSENT: MarketingConsent[] = ['unknown', 'provided', 'withdrawn']

function leadDetail(e: InboundEnquiryResponse, u: AuthMeResponse): LeadDetail {
	const row = leadRow(e, u)
	return {
		...row,
		email: e.contact.email ?? '',
		consent: CONSENT.includes(e.contact.consent_status as MarketingConsent)
			? (e.contact.consent_status as MarketingConsent)
			: 'unknown',
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
	const [res, u, leaseResult] = await Promise.all([
		client.get<InboundEnquiryListResponse>(
			// Leads only: Inbox contacts (e.g. recently sold owners) would take the page's places.
			client.withQuery(`${CRM}/inbound/enquiries`, {
				search: p.q || undefined,
				leads_only: true,
				limit: LIST_LIMIT
			})
		),
		whoAmI(),
		// The agency's own leads still show when the lease data cannot load; the page says so.
		p.vitevue ? renewalLeads().catch(() => 'failed' as const) : null
	])
	const leases = leaseResult === 'failed' ? null : leaseResult
	const stored = res.enquiries
		.filter((e) => e.intent !== 'unknown' || (p.vitevue && isVitevue(e)))
		.map((e) => ({ e: e as InboundEnquiryResponse | null, row: leadRow(e, u) }))
	// Opened units carry today's lease state; the rest are shown until an agent opens them.
	const live = new Map((leases?.items ?? []).map((i) => [i.lead_record_id, i.lead]))
	for (const item of stored) {
		const l = item.row.lease && live.get(item.row.id)
		if (l) {
			const lease = leaseOfLead(l)
			item.row = { ...item.row, lease, score: vitevueScore(lease.days_left, lease.vacant) }
		}
	}
	const needle = (p.q ?? '').trim().toLowerCase()
	const unopened = (leases?.items ?? [])
		.filter((i) => !i.lead_record_id)
		.map((i) => ({ e: null, row: unopenedVitevueLead(i) }))
		.filter(
			({ row }) =>
				!needle || `${row.name} ${row.summary.line} ${row.area}`.toLowerCase().includes(needle)
		)
	// Vitevue lease leads follow the agency's own leads, ranked among themselves.
	const all = [
		...stored.filter(({ row }) => !row.lease),
		...[...stored.filter(({ row }) => row.lease), ...unopened].sort(
			(a, b) => b.row.score - a.row.score
		)
	]

	const matching = all.filter(({ e, row }) => {
		if (p.source && row.source !== p.source) return false
		if (p.stage && row.stage !== p.stage) return false
		if (p.area && row.area !== p.area) return false
		if (p.beds) {
			if (!e) return false
			const beds = num(e.criteria.bedrooms_min)
			if (beds === null || (p.beds === '4' ? beds < 4 : beds !== Number(p.beds))) return false
		}
		if (
			p.ptype &&
			(p.ptype === 'villa') !== isVilla(e ? e.criteria.property_type : row.lease?.property)
		)
			return false
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
		areas: [...new Set(all.map(({ row }) => row.area).filter(Boolean))].sort(),
		vitevue_unavailable: leaseResult === 'failed'
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
			email: body.email?.trim() || undefined,
			source: body.source_detail || 'Manual',
			criteria: criteriaWith({}, fields)
		}),
		whoAmI()
	])
	return done(leadDetail(e, u))
}

export async function patchLead(id: number, body: LeadPatch): Promise<Written<LeadDetail>> {
	const [current, u] = await Promise.all([getEnquiry(id), whoAmI()])
	if (body.language !== undefined && body.language !== (current.contact.preferred_language ?? '')) {
		throw notSaved('A changed language')
	}
	const update: InboundEnquiryUpdate = {}
	// The backend normalises the phone (+971) and the email.
	if (body.name !== undefined && body.name.trim() !== current.contact.full_name)
		update.full_name = body.name.trim()
	if (body.phone !== undefined && body.phone.trim() !== (current.contact.phone ?? ''))
		update.phone = body.phone.trim() || null
	if (body.email !== undefined && body.email.trim() !== (current.contact.email ?? ''))
		update.email = body.email.trim() || null
	if (body.lead_type) update.intent = INTENT[body.lead_type]
	if (body.stage) update.status = statusOf(body.stage)
	if (body.fields) update.criteria = criteriaWith(current.criteria, body.fields)
	if (body.consent !== undefined && body.consent !== current.contact.consent_status)
		update.consent_status = body.consent
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
	// 26 Oct call: the agency's own listings first (it can earn both sides), then the owner
	// file, then portal listings.
	bt: [
		{ lane: 'company', title: 'Company listings', kind: 'colleague_listing', line: 'own' },
		{ lane: 'owners', title: 'Owners on your file', kind: 'owner', line: 'vv' },
		{ lane: 'listings', title: 'Portal listings', kind: 'public', line: 'in' },
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
	const [e, u] = await Promise.all([getEnquiry(id), whoAmI()])
	const lead = leadRow(e, u)
	const side = groupOf(lead.lead_type)
	const brief = LEAD_TYPES[lead.lead_type].fields
		.filter((f) => lead.fields[f.key])
		.map((f) => {
			const v = String(lead.fields[f.key])
			return {
				k: f.label,
				v: f.money ? aed(Number(lead.fields[f.key])) : f.date && ISO_DAY.test(v) ? fullDate(v) : v
			}
		})
	const tab = side === 'sl' ? 'sell' : lead.off_plan ? 'offplan' : 'ready'
	// Matching needs a qualified brief (the backend refuses otherwise): ask the agent for one.
	if (!e.qualification_complete) {
		return {
			tab,
			lead,
			brief,
			move_by: null,
			shortlist: 0,
			tiers: [],
			status: null,
			own_listing: null,
			needs_brief: true
		}
	}
	const res = await loadMatches(id)
	const live = (lane: string) => (res.lanes[lane] ?? []).filter((m) => m.state !== 'dismissed')
	// A tenant's matches are held to the move-in date; say how many only free up later.
	const moveBy = res.move_in ?? null
	const freeAfter = (lane: string) => {
		const n = res.hidden_after?.[lane] ?? 0
		return n && moveBy ? ` · ${n} free after ${dayLabel(moveBy)}` : ''
	}

	const tiers: MatchTier[] = LANES[side].map((t, i) => ({
		id: t.lane,
		n: i + 1,
		title: t.title,
		sub: `${live(t.lane).length} found${freeAfter(t.lane)}`,
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
		tab,
		lead,
		brief,
		move_by: moveBy,
		shortlist: Object.values(res.lanes)
			.flat()
			.filter((m) => m.state === 'saved').length,
		tiers,
		status: null,
		own_listing: null,
		needs_brief: false
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

/** Today's estimated value of the unit (owner valuation, 5 Nov); rent is not estimated yet. */
function ownerMarket(p: CrmOwnerProperty): OwnerUnit['market'] {
	if (!p.estimated_value_aed || !p.valuation_confidence || !p.valued_at) return null
	return {
		sale: [
			p.estimated_value_low_aed ?? p.estimated_value_aed,
			p.estimated_value_high_aed ?? p.estimated_value_aed
		],
		rent: null,
		estimate: p.estimated_value_aed,
		confidence: p.valuation_confidence,
		valued_at: p.valued_at
	}
}

/** valuation_service skip statuses, in words an agent can act on. */
const NOT_ESTIMATED: Record<string, string> = {
	non_residential: 'land or commercial',
	no_registry_match: 'no matching DLD sale',
	ambiguous_registry_match: 'DLD match unclear',
	no_comparables: 'too few recent sales',
	not_current_owner: 'no longer owned'
}

function ownerMarketNote(p: CrmOwnerProperty): string | undefined {
	if (p.estimated_value_aed) return undefined
	const why = p.valuation_status ? NOT_ESTIMATED[p.valuation_status] : undefined
	return why ? `Not estimated · ${why}` : 'Not estimated yet'
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
		owned_from: (p.imported_transaction_date ?? p.registry_sale_date ?? null)?.slice(0, 10) ?? null,
		owned_to: p.later_sale_date?.slice(0, 10) ?? null,
		status:
			p.lease_end && p.annual_rent_aed
				? `Let at ${aed(p.annual_rent_aed)} a year until ${dayMonth(p.lease_end)}`
				: chip.label,
		status_chip: chip,
		// The backend keeps the lease end, not its start, so "Rent now" shows through `status`.
		rent: null,
		market: ownerMarket(p),
		market_note: ownerMarketNote(p),
		rent_history: [],
		transactions: [...new Map(transactions.map((t) => [`${t.when}${t.what}`, t])).values()].map(
			(t) => ({ ...t, when: t.when.slice(0, 10) })
		),
		source: unitSource(p),
		check: {
			imported: {
				date: p.imported_transaction_date ?? null,
				aed: p.imported_transaction_price_aed ?? null,
				type: p.imported_property_type || p.property_type,
				unit: p.unit_number,
				role: p.imported_party_role ?? ''
			},
			dld: {
				unit: p.registry_unit_number ?? '',
				building: p.registry_building_name ?? '',
				area: p.registry_area_name ?? '',
				date: p.registry_sale_date ?? p.latest_sale_date ?? null,
				aed: p.registry_sale_price_aed ?? p.latest_sale_price_aed ?? null,
				type: p.registry_property_type ?? '',
				bedrooms: p.registry_bedrooms ?? '',
				size_sqft: p.registry_size_sqft ?? null,
				built_up_sqft: p.registry_built_up_area_sqft ?? null,
				aed_per_sqft: p.registry_price_per_sqft_aed ?? null,
				market: p.registry_market_status ?? ''
			},
			// Same wording as the import report, so the panel and the report agree.
			result: {
				label: STATUS_INFO[p.ownership_status].label,
				confidence: p.confidence_score,
				reason: p.match_reason,
				chip: {
					tone: STATUS_INFO[p.ownership_status].tone,
					label: STATUS_INFO[p.ownership_status].label
				}
			},
			lease: p.lease_end ? { end: p.lease_end, aed: p.annual_rent_aed ?? null } : null
		}
	}
}

/** "Sheet1:12" → "Sheet1 row 12". */
const sourceRow = (r: string) => {
	const i = r.lastIndexOf(':')
	return i > 0 ? `${r.slice(0, i)} row ${r.slice(i + 1)}` : r
}

/** "Business Bay 2024 SVR · Sheet1 row 12": the import(s), then the sheet and row(s) in the file. */
function unitSource(p: CrmOwnerProperty): string {
	return [(p.source_lists ?? []).join(', '), (p.source_rows ?? []).map(sourceRow).join(', ')]
		.filter(Boolean)
		.join(' · ')
}

/** The imports an owner's units came from, matched to the import history by name, oldest first. */
function ownerImportSources(
	properties: CrmOwnerProperty[],
	imports: CrmContactImportResponse[]
): OwnerImportSource[] {
	const units = new Map<string, number>()
	for (const p of properties)
		for (const name of p.source_lists ?? []) units.set(name, (units.get(name) ?? 0) + 1)
	return [...units]
		.map(([name, count]) => {
			const imp = imports.find((i) => i.name === name)
			return {
				importId: imp?.id ?? null,
				name,
				file: imp?.original_filename ?? null,
				date: imp?.created_at.slice(0, 10) ?? null,
				units: count
			}
		})
		.sort((a, b) => (a.date ?? '9999').localeCompare(b.date ?? '9999'))
}

const ownerWorkspaces = () => client.get<CrmOwnerWorkspaceSummary[]>(`${CRM}/owner-workspaces`)

/** Tabs whose count covers only the page of 500 in view (none since the backend filters them). */
const PAGE_ONLY_TABS: OwnerTab[] = []

/** The tabs the backend filters for the whole file, and the query for each. */
const SERVER_TABS = {
	all: { scope: 'all' },
	sold: { scope: 'prior_owners' },
	multi: { scope: 'all', min_properties: 3 },
	event: { scope: 'all', next_event_days: 90 }
} as const
type ServerTab = keyof typeof SERVER_TABS
const isServerTab = (t: OwnerTab): t is ServerTab => t in SERVER_TABS

/**
 * One page (500) of the owner file. All, Just sold (every former owner), 3+ units and Next event
 * (lease ends within 90 days) come from the backend for the whole file, so their counts and rows
 * are complete. My contacts counts the whole workspace list; its rows, Update due and the source,
 * area, bedrooms and type filters work on the page in view.
 */
export async function listOwners(p: OwnerListParams): Promise<OwnerListResponse> {
	const registry = (tab: ServerTab, limit: number, offset: number) =>
		client.get<CrmOwnerRegistryResponse>(
			client.withQuery(`${CRM}/owner-registry`, {
				...SERVER_TABS[tab],
				search: p.q || undefined,
				limit,
				offset
			})
		)
	const current: ServerTab = isServerTab(p.tab) ? p.tab : 'all'
	const others = (Object.keys(SERVER_TABS) as ServerTab[]).filter((t) => t !== current)
	// The page in view, plus each other server tab's total (one row each) for its count.
	const limit = p.limit ?? LIST_LIMIT
	const [res, ws, ...otherTotals] = await Promise.all([
		registry(current, limit, p.offset ?? 0),
		ownerWorkspaces(),
		...others.map((t) => registry(t, 1, 0))
	])
	const totals = Object.fromEntries([
		[current, res.total],
		...others.map((t, i) => [t, otherTotals[i].total])
	]) as Record<ServerTab, number>
	const byKey = new Map(ws.map((w) => [w.owner_key, w]))
	const all = res.owners.map((o) => ({ o, row: ownerRow(o, byKey.get(o.owner_key)) }))
	// Source, area, bedrooms, type and units are filtered here, on this page only.
	const pageOnlyFilter = Boolean(p.source || p.area || p.beds || p.ptype || p.units)

	const matching = all.filter(({ o, row }) => {
		const props = o.properties ?? []
		if (p.source && !row.sources.includes(p.source)) return false
		if (p.area && !props.some((x) => x.area_name === p.area)) return false
		if (p.beds) {
			const want = Number(p.beds)
			if (!props.some((x) => (bedsOf(x) ?? -1) === want || (want === 4 && (bedsOf(x) ?? 0) >= 4)))
				return false
		}
		// DLD's type when known (opened owners), else the file's; generic "Unit" is "unspecified".
		if (
			p.ptype &&
			!props.some((x) => ownerPropertyKind(x.registry_property_type || x.property_type) === p.ptype)
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
	// With no page-only filter, the server tabs cover the whole file (or the whole search result),
	// and My contacts is the whole workspace list when nothing narrows it.
	if (!pageOnlyFilter) {
		Object.assign(counts, totals)
		if (!p.q) counts.mine = ws.length
	}
	// A server tab's rows already come filtered from the backend.
	const items = (isServerTab(p.tab) ? matching : matching.filter(TABS[p.tab])).map(({ row }) => row)

	return {
		items,
		counts,
		total: items.length,
		unit_total: items.reduce((n, r) => n + r.units.length, 0),
		with_event_90: matching.filter(({ o }) => inEvent(o)).length,
		on_file: totals.all,
		page: { offset: p.offset ?? 0, limit, total: res.total, loaded: res.owners.length },
		pageOnlyTabs: PAGE_ONLY_TABS,
		areas: [
			...new Set(
				all.flatMap(({ o }) => (o.properties ?? []).map((x) => x.area_name)).filter(Boolean)
			)
		].sort()
	}
}

export async function getOwner(id: string): Promise<OwnerDetail> {
	const [o, ws, imports] = await Promise.all([
		client.get<CrmOwnerProfile>(`${CRM}/owners/${encodeURIComponent(id)}`),
		ownerWorkspaces(),
		client.get<CrmContactImportResponse[]>(`${CRM}/contact-imports`)
	])
	const w = ws.find((x) => x.owner_key === id)
	return {
		...ownerRow(o, w),
		unit_rows: (o.properties ?? []).map(ownerUnit),
		imported_from: ownerImportSources(o.properties ?? [], imports),
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

/** Leads files are read by the backend, which picks the columns. */
export async function previewImport(file: File): Promise<ImportPreview> {
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
export async function createImport(file: File): Promise<Written<ImportRequest>> {
	const fd = new FormData()
	fd.append('file', file)
	fd.append('name', file.name)
	const r = await client.post<InboundImportResponse>(`${CRM}/inbound/imports`, fd)
	const { created: _c, ...row } = importRow('Leads', r)
	return done(row)
}

/* ── owner files (/contact-imports) ── */

/** The same limits the backend applies to an owners file. */
export const OWNER_FILE_TYPES = ['.csv', '.xlsx']
const OWNER_FILE_MAX_BYTES = 50 * 1024 * 1024
const HEADER_SCAN_ROWS = 15
const MAX_COLUMNS = 100
const PLACEHOLDER_HEADER = /^column\s*\d+$/i

function ownerFileProblem(file: File): string | null {
	const name = file.name.toLowerCase()
	if (!OWNER_FILE_TYPES.some((t) => name.endsWith(t))) return 'Choose a CSV or XLSX file.'
	if (!file.size) return 'File is empty, so nothing will be imported.'
	if (file.size > OWNER_FILE_MAX_BYTES) return 'This file is over 50 MB.'
	return null
}

/** The row in the first 15 with the most filled cells is the header row. */
function headerRow(rows: string[][]): number {
	let best = 0
	let bestCount = -1
	rows.slice(0, HEADER_SCAN_ROWS).forEach((row, i) => {
		const filled = row
			.slice(0, MAX_COLUMNS)
			.filter((c) => c.trim() && !PLACEHOLDER_HEADER.test(c.trim())).length
		if (filled > bestCount) {
			best = i
			bestCount = filled
		}
	})
	return best
}

/**
 * Read an owners file in the browser so the agent can check it before upload: the header row,
 * the number of data rows and the first five. Nothing is sent; the backend maps the columns.
 */
export async function previewOwnerFile(file: File): Promise<OwnerFilePreview> {
	const base = { file: file.name, size: file.size, sheets: 0, rows: 0, headers: [], sample: [] }
	const problem = ownerFileProblem(file)
	if (problem) return { ...base, problem }
	let workbook: import('xlsx').WorkBook
	const XLSX = await import('xlsx')
	try {
		workbook = XLSX.read(await file.arrayBuffer(), { type: 'array', dense: true, raw: true })
	} catch {
		return {
			...base,
			problem: 'This file could not be read. Save it again as CSV or XLSX without a password.'
		}
	}
	let rows = 0
	let sheets = 0
	let headers: string[] = []
	let sample: string[][] = []
	for (const sheetName of workbook.SheetNames) {
		const grid = XLSX.utils
			.sheet_to_json<unknown[]>(workbook.Sheets[sheetName], {
				header: 1,
				blankrows: false,
				defval: '',
				raw: false
			})
			.map((r) => r.map((c) => String(c ?? '').trim()))
		if (!grid.length) continue
		const h = headerRow(grid)
		const data = grid.slice(h + 1).filter((r) => r.some((c) => c))
		if (!data.length) continue
		sheets += 1
		rows += data.length
		if (!headers.length) {
			const cols = grid[h]
				.slice(0, MAX_COLUMNS)
				.map((c, i) => ({ c, i }))
				.filter(({ c }) => c && !PLACEHOLDER_HEADER.test(c))
			headers = cols.map(({ c }) => c)
			sample = data.slice(0, 5).map((r) => cols.map(({ i }) => r[i] ?? ''))
		}
	}
	return {
		...base,
		sheets,
		rows,
		headers,
		sample,
		problem: rows ? null : 'File is empty, so nothing will be imported.'
	}
}

function ownerImportResult(
	r: CrmContactImportResponse,
	alreadyImported: boolean
): OwnerImportResult {
	const s = r.summary
	return {
		id: r.id,
		name: r.name,
		status: r.status,
		alreadyImported,
		createdAt: r.created_at,
		summary: {
			totalRows: s.total_rows ?? 0,
			candidateRows: s.candidate_rows ?? 0,
			distinctProperties: s.distinct_properties ?? null,
			duplicatesCollapsed: s.duplicate_rows_collapsed ?? 0,
			validContacts: s.valid_contacts ?? 0,
			verified: s.verified_current_owners ?? 0,
			probable: s.probable_current_owners ?? 0,
			unitLinked: s.unit_linked_unverified ?? 0,
			former: s.former_owners ?? 0,
			conflicting: s.conflicting_claims ?? 0,
			notMatched:
				(s.unmatched ?? 0) + (s.registry_not_observed ?? 0) + (s.insufficient_property_data ?? 0),
			rentalOpportunities: s.rental_opportunities ?? 0,
			contactReady: s.contact_ready ?? 0
		}
	}
}

/**
 * Upload an owners file. The backend reads, matches and saves it before it answers. When the
 * same file was uploaded before, it returns that import instead; the list taken first tells
 * the two apart. A failed import reads as one generic line; the server keeps the details.
 */
export async function importOwnerFile(
	file: File,
	name: string
): Promise<Written<OwnerImportResult>> {
	const problem = ownerFileProblem(file)
	if (problem) throw new ApiError(problem, 400)
	const before = await client.get<CrmContactImportResponse[]>(`${CRM}/contact-imports`)
	const known = new Set(before.map((r) => r.id))
	const fd = new FormData()
	fd.append('file', file)
	fd.append('name', name.trim() || file.name.replace(/\.[^.]+$/, '') || file.name)
	let r: CrmContactImportResponse
	try {
		r = await client.post<CrmContactImportResponse>(`${CRM}/contact-imports`, fd)
	} catch (e) {
		if (e instanceof ApiError && e.status === 422)
			throw new ApiError('This file could not be imported. Check the columns and try again.', 422)
		throw e
	}
	return done(ownerImportResult(r, known.has(r.id)))
}

/** The organization's owner files, newest first. */
export async function listOwnerImports(): Promise<OwnerImport[]> {
	const rows = await client.get<CrmContactImportResponse[]>(`${CRM}/contact-imports`)
	return [...rows]
		.sort((a, b) => b.created_at.localeCompare(a.created_at))
		.map((r) => ({
			id: r.id,
			name: r.name || r.original_filename,
			file: r.original_filename,
			status: r.status,
			claims: r.summary.candidate_rows ?? 0,
			rentalLeads: r.summary.rental_opportunities ?? 0,
			at: stamp(r.created_at)
		}))
}

/** Owner files with counts, sheet mappings and checks, newest first (dashboard and report). */
export async function listOwnerImportDetails(): Promise<OwnerImportDetail[]> {
	const rows = await client.get<CrmContactImportResponse[]>(`${CRM}/contact-imports`)
	return [...rows]
		.sort((a, b) => b.created_at.localeCompare(a.created_at))
		.map((r) => {
			const mappings = r.mappings ?? []
			return {
				id: r.id,
				name: r.name || r.original_filename,
				file: r.original_filename,
				status: r.status,
				at: stamp(r.created_at),
				createdAt: r.created_at,
				listId: r.list_id ?? null,
				counts: importCounts(r.summary, r.mortgage_by_status ?? {}),
				sheets: mappings.map((m) => ({
					name: m.sheet_name,
					rows: m.meaningful_rows,
					family: m.sheet_family,
					source: m.mapping_source,
					confidence: m.confidence,
					fields: Object.entries(m.field_map ?? {}).map(([field, column]) => ({ field, column })),
					warnings: m.warnings ?? [],
					checks: mappingChecks(m)
				})),
				flagged: isFlagged(r.status, mappings)
			}
		})
}

const OWNER_ROWS_LIMIT = 100

/** One page (100) of an owner file's kept rows, filtered by status and search. */
export async function listOwnerImportRows(
	listId: number,
	p: OwnerImportRowsParams
): Promise<OwnerImportRows> {
	const res = await client.get<CrmContactListDetail>(
		client.withQuery(`${CRM}/contact-lists/${listId}`, {
			status: p.status ?? undefined,
			search: p.search.trim() || undefined,
			limit: OWNER_ROWS_LIMIT,
			offset: p.offset
		})
	)
	return {
		rows: res.contacts.map(
			(c): OwnerImportRow => ({
				id: c.id,
				ownerKey: c.owner_key,
				name: c.contact_name,
				phone: c.phone_primary || c.phone_alternate || c.email_primary || '',
				building: c.building_name || c.project_name,
				area: c.area_name,
				project: c.project_name,
				propertyType: c.property_type,
				propertyDetails: c.property_details ?? {},
				latestSaleDate: c.latest_sale_date ?? null,
				latestSalePrice: c.latest_sale_price_aed ?? null,
				unit: c.unit_number,
				date: c.transaction_date ?? null,
				price: c.transaction_price_aed ?? null,
				status: c.report_status === 'mortgage' ? 'mortgage' : c.ownership_status,
				confidence: c.confidence_score,
				reason: c.match_reason,
				sheet: c.source_sheet,
				rowNumber: c.source_row_number
			})
		),
		total: res.total,
		offset: res.offset,
		limit: res.limit
	}
}

/**
 * One page (100) of the rows an owner file did not keep, read from the dropped-rows log saved at
 * upload, filtered by reason and searched by name, building or unit.
 */
export async function listOwnerImportDropped(
	importId: number,
	p: OwnerDroppedRowsParams
): Promise<OwnerDroppedRows> {
	const res = await client.get<CrmDroppedRowsResponse>(
		client.withQuery(`${CRM}/contact-imports/${importId}/dropped-rows`, {
			reason: p.reason ?? undefined,
			search: p.search.trim() || undefined,
			limit: OWNER_ROWS_LIMIT,
			offset: p.offset
		})
	)
	return {
		available: res.available,
		rows: res.rows.map((r) => ({
			sheet: r.sheet,
			rowNumber: r.row,
			reason: r.reason,
			name: r.name ?? '',
			building: r.building ?? '',
			unit: r.unit ?? '',
			date: r.date ?? '',
			price: r.price ?? '',
			role: r.role ?? '',
			procedure: r.procedure ?? ''
		})),
		byReason: res.by_reason,
		total: res.total,
		offset: res.offset,
		limit: res.limit
	}
}

/**
 * One page (100) of an owner file's distinct properties (building + unit), each with its kept
 * rows, searched by building, project, area, unit or owner name.
 */
export async function listOwnerImportProperties(
	importId: number,
	p: OwnerPropertyParams
): Promise<OwnerProperties> {
	const res = await client.get<CrmImportPropertiesResponse>(
		client.withQuery(`${CRM}/contact-imports/${importId}/properties`, {
			search: p.search.trim() || undefined,
			limit: OWNER_ROWS_LIMIT,
			offset: p.offset
		})
	)
	return {
		rows: res.rows.map((r) => ({
			key: r.property_key,
			area: r.area,
			project: r.project,
			building: r.building,
			unit: r.unit,
			type: r.property_type,
			rows: r.rows,
			buyers: r.buyers,
			sellers: r.sellers,
			currentOwner: r.current_owner ?? null,
			latestDate: r.latest_date ?? null,
			latestPrice: r.latest_price_aed ?? null,
			records: r.records.map((x) => ({
				name: x.name,
				procedure: x.procedure ?? '',
				identifiers: x.identifiers ?? {},
				propertyDetails: x.property_details ?? {},
				matchReason: x.match_reason ?? '',
				role: x.role,
				date: x.sale_date ?? null,
				price: x.price_aed ?? null,
				status: x.status as ClaimStatus,
				sheet: x.sheet,
				rowNumber: x.row
			}))
		})),
		total: res.total,
		offset: res.offset,
		limit: res.limit
	}
}

/** Rename an owner file; the backend renames its saved list too. */
export async function renameOwnerImport(id: number, name: string): Promise<Written<null>> {
	await client.patch<CrmContactImportResponse>(`${CRM}/contact-imports/${id}`, { name })
	return done(null)
}

/** Delete one owner file, its saved list and its claims; owner notes and pipelines stay. */
export async function deleteOwnerImport(id: number): Promise<Written<null>> {
	await client.delete<void>(`${CRM}/contact-imports/${id}`)
	return done(null)
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

/* ── lease renewals (Assets › Renewals and the Leads inbox) ── */

/** Owner-import claims that tie a contact to the unit as its owner today. */
const CURRENT_OWNER = new Set(['verified_current_owner', 'probable_current_owner'])

function renewalUnit(l: CrmLead): string {
	const place = l.building_name || l.project_name || l.area_name || 'Unit'
	return l.unit_number ? `${place} · unit ${l.unit_number}` : place
}

function renewalProperty(l: CrmLead): string {
	return [
		l.property_subtype || l.property_type,
		l.bedrooms && l.bedrooms !== 'Not stated' ? l.bedrooms : null,
		l.size_sqft ? `${fmt(l.size_sqft)} sqft` : null
	]
		.filter(Boolean)
		.join(' · ')
}

function leaseEndChip(days: number): Chip {
	if (days < 0) return { tone: 'red', label: `Ended ${plural(-days, 'day')} ago` }
	if (days === 0) return { tone: 'red', label: 'Ends today' }
	return { tone: days <= 30 ? 'amber' : 'blue', label: `Ends in ${plural(days, 'day')}` }
}

function renewalOwner(o: CrmRenewalOwner | null | undefined): RenewalOwner | null {
	if (!o) return null
	return {
		name: o.name ?? null,
		phone: o.phone ?? null,
		email: o.email ?? null,
		source: o.source === 'workspace' ? 'Saved on this lead' : 'Owner import'
	}
}

function renewal(l: CrmLead, owner: RenewalOwner | null): Renewal {
	return {
		id: l.lead_id,
		unit: renewalUnit(l),
		area: l.area_name,
		property: renewalProperty(l),
		rent_aed: l.annual_rent_aed,
		lease_start: l.lease_start,
		lease_end: l.lease_end,
		days_left: l.days_to_expiry,
		end_chip: leaseEndChip(l.days_to_expiry),
		owner
	}
}

/**
 * Every lease in the dataset, whatever any agent's areas: /api/v1/crm/renewals. `signal` drops
 * the request when a filter changes, and the backend then stops its query.
 */
export async function listRenewals(
	p: RenewalListParams,
	signal?: AbortSignal
): Promise<RenewalListResponse> {
	const res = await client.get<CrmRenewalsResponse>(
		client.withQuery(`${CRM}/renewals`, {
			window: p.window || undefined,
			area: p.area || undefined,
			property_type: p.property_type || undefined,
			project: p.project || undefined,
			building: p.building || undefined,
			limit: p.limit,
			owner: p.owner || undefined
		}),
		{ signal }
	)
	const owners = res.owners ?? {}
	return {
		items: res.leads.map((l) => {
			const o = owners[l.unit_candidate_key]
			const owner: RenewalOwner | null = o
				? {
						name: o.name ?? null,
						phone: o.phone ?? null,
						email: o.email ?? null,
						source: o.source === 'workspace' ? 'Saved on this lead' : 'Owner import'
					}
				: null
			return renewal(l, owner)
		}),
		total: res.total,
		property_types: res.property_types ?? [],
		projects: res.projects ?? [],
		buildings: res.buildings ?? []
	}
}

/**
 * One lease with its property history (/leads/{id}) and owner. The owner is the one saved on
 * the agent's lead workspace, else a current-owner match from an owner import, else nobody.
 */
export async function getRenewal(id: string): Promise<RenewalDetail> {
	const key = encodeURIComponent(id)
	const [detail, workspace, contacts] = await Promise.all([
		client.get<CrmLeadDetailResponse>(`${CRM}/leads/${key}`),
		client.get<CrmWorkspaceResponse>(`${CRM}/workspaces/${key}`),
		client.get<CrmLeadImportedContact[]>(`${CRM}/leads/${key}/contacts`)
	])
	const typed = workspace.owner_name || workspace.owner_phone || workspace.owner_email
	const matched = contacts.find((c) => CURRENT_OWNER.has(c.ownership_status))
	const owner: RenewalOwner | null = typed
		? {
				name: workspace.owner_name ?? null,
				phone: workspace.owner_phone ?? null,
				email: workspace.owner_email ?? null,
				source: 'Saved on this lead'
			}
		: matched
			? {
					name: matched.contact_name || null,
					phone: matched.phone_primary || matched.phone_alternate || null,
					email: matched.email_primary ?? null,
					source: `Owner import · ${matched.list_name}`
				}
			: null
	const l = detail.lead
	return {
		...renewal(l, owner),
		reason: l.lead_reason,
		action: l.recommended_action,
		last_purchase: l.last_purchase_date
			? { date: l.last_purchase_date, price_aed: l.latest_purchase_price_aed ?? null }
			: null,
		gross_yield_pct: l.gross_yield_pct ?? null,
		history: detail.timeline.map((e) => ({
			id: e.event_id,
			kind: e.event_type,
			date: e.event_date,
			end_date: e.end_date ?? null,
			title: e.title,
			detail: e.description,
			amount_aed: e.amount_aed ?? null,
			source: e.source
		})),
		match_explanation: detail.match_explanation
	}
}

/** Type in the owner of a lease's unit; an empty field clears it. */
export async function saveRenewalOwner(
	id: string,
	owner: { name: string; phone: string; email: string }
): Promise<Written<RenewalDetail>> {
	await client.patch(`${CRM}/workspaces/${encodeURIComponent(id)}`, {
		owner_name: owner.name.trim() || null,
		owner_phone: owner.phone.trim() || null,
		owner_email: owner.email.trim() || null
	})
	return done(await getRenewal(id))
}

/* My areas: the agent's areas and lease-end windows that fill the Leads inbox. */

const preferences = (p: CrmAreaPreferencesResponse): FeedPreferences => ({
	areas: p.areas,
	forward_days: p.forward_days ?? 60,
	lookback_days: p.lookback_days ?? 30
})

export async function getFeedPreferences(): Promise<FeedPreferences> {
	return preferences(await client.get<CrmAreaPreferencesResponse>(`${CRM}/area-preferences`))
}

export async function setFeedPreferences(p: FeedPreferences): Promise<Written<FeedPreferences>> {
	return done(
		preferences(await client.put<CrmAreaPreferencesResponse>(`${CRM}/area-preferences`, p))
	)
}

export async function feedAreas(): Promise<FeedArea[]> {
	const rows = await client.get<CrmRenewalArea[]>(`${CRM}/renewal-areas`)
	return rows.map((r) => ({ area: r.area, owners_in_90_day_window: r.upcoming_90_days }))
}

/** Largest page /renewal-leads serves. */
const RENEWAL_LEADS_LIMIT = 500

/**
 * Lease leads in My areas. Screens that load at the same moment (the Leads list and its feed
 * strip, or a save refreshing every CRM query) share one request.
 */
let renewalLeadsInFlight: Promise<CrmRenewalLeadsResponse> | null = null
const renewalLeads = () =>
	(renewalLeadsInFlight ??= client
		.get<CrmRenewalLeadsResponse>(
			client.withQuery(`${CRM}/renewal-leads`, { limit: RENEWAL_LEADS_LIMIT })
		)
		.finally(() => {
			renewalLeadsInFlight = null
		}))

export async function feedSummary(): Promise<FeedSummary> {
	const res = await renewalLeads()
	return {
		areas: res.preferences.areas,
		forward_days: res.preferences.forward_days ?? 60,
		lookback_days: res.preferences.lookback_days ?? 30,
		window_total: res.total,
		on_file: res.items.filter((i) => i.owner).length,
		entered_today: res.entered_today
	}
}

/* Vitevue lease leads in Leads: one shared lead per unit, created when an agent first opens it. */

/**
 * Rank: vacant units first (most recently vacated on top), then ended leases not confirmed
 * vacant, then leases still running, the sooner they end the higher.
 */
function vitevueScore(daysLeft: number, vacant: boolean): number {
	const ended = Math.min(-daysLeft, 60)
	if (daysLeft < 0) return (vacant ? 100 : 80) - Math.floor(ended / 6)
	return Math.max(10, 69 - Math.floor(daysLeft * 0.6))
}

function leaseOfLead(l: CrmLead): VitevueLease {
	return {
		id: l.lead_id,
		unit: renewalUnit(l),
		area: l.area_name,
		property: renewalProperty(l),
		lease_start: l.lease_start,
		lease_end: l.lease_end,
		days_left: l.days_to_expiry,
		vacant: l.lease_evidence_state === 'unlet_signal',
		rent_aed: l.annual_rent_aed,
		last_purchase: l.last_purchase_date
			? {
					date: l.last_purchase_date,
					price_aed: l.latest_purchase_price_aed ?? l.matched_sale_price_aed ?? null
				}
			: null,
		end_chip: leaseEndChip(l.days_to_expiry)
	}
}

/** The lease saved on a stored Vitevue lead when it was opened. */
function leaseOfEnquiry(e: InboundEnquiryResponse): VitevueLease | null {
	const v = e.observed_data?.vitevue_lease as Record<string, unknown> | undefined
	if (!v || typeof v.lease_id !== 'string' || typeof v.lease_end !== 'string') return null
	const c = e.criteria
	const days = daysFromToday(v.lease_end)
	return {
		id: v.lease_id,
		unit: [text(c.building), text(c.unit_number) && `unit ${text(c.unit_number)}`]
			.filter(Boolean)
			.join(' · '),
		area: (Array.isArray(c.locations) ? text(c.locations[0]) : null) ?? '',
		property: [
			text(c.property_type),
			text(c.bedrooms),
			num(c.size_sqft) && `${fmt(Number(c.size_sqft))} sqft`
		]
			.filter(Boolean)
			.join(' · '),
		lease_start: String(v.lease_start ?? ''),
		lease_end: v.lease_end,
		days_left: days,
		vacant: Boolean(v.vacant) && days < 0,
		rent_aed: num(v.annual_rent_aed) ?? 0,
		last_purchase: v.last_purchase_date
			? { date: String(v.last_purchase_date), price_aed: num(v.last_purchase_price_aed) }
			: null,
		end_chip: leaseEndChip(days)
	}
}

const vitevueSummary = (lease: VitevueLease) => ({
	line: lease.unit,
	sub: [lease.end_chip.label, lease.rent_aed ? `${aed(lease.rent_aed)} a year` : null]
		.filter(Boolean)
		.join(' · ')
})

/** A unit nobody has opened yet: shown in Leads, stored when an agent opens it (id 0). */
function unopenedVitevueLead(item: CrmRenewalLeadsResponse['items'][number]): LeadRow {
	const lease = leaseOfLead(item.lead)
	const owner = renewalOwner(item.owner)
	return {
		id: 0,
		name: owner?.name || lease.unit,
		phone: owner?.phone ?? '',
		lead_type: 'owner',
		deal_type: 'sale',
		source: 'vitevue',
		source_detail: VITEVUE_SOURCE,
		received_label: lease.end_chip.label,
		stage: 'new',
		agent: null,
		score: vitevueScore(lease.days_left, lease.vacant),
		area: lease.area,
		language: '',
		next_action: '',
		off_plan: false,
		gated: false,
		owner_id: null,
		fields: { unit: lease.unit },
		summary: vitevueSummary(lease),
		known: owner
			? `${owner.name ?? 'Owner'} · ${owner.source.toLowerCase()}`
			: 'Owner not identified yet',
		source_short: VITEVUE_SOURCE,
		listing: null,
		lease,
		recent_sales: null
	}
}

/** Open a Vitevue lease as the agency's shared lead for its unit (created the first time). */
export async function openVitevueLead(leaseId: string): Promise<Written<LeadDetail>> {
	const [e, u] = await Promise.all([
		client.post<InboundEnquiryResponse>(`${CRM}/renewal-leads/${encodeURIComponent(leaseId)}/lead`),
		whoAmI()
	])
	return done(leadDetail(e, u))
}

/** Approve a recently sold owner in the Inbox as a possible buyer lead (no brief yet). */
export async function approveRecentSeller(id: number): Promise<Written<LeadDetail>> {
	const [e, u] = await Promise.all([
		client.post<InboundEnquiryResponse>(`${CRM}/inbound/enquiries/${id}/approve-buyer`),
		whoAmI()
	])
	return done(leadDetail(e, u))
}

/* ── inbox (/api/v1/crm/inbound/enquiries) ── */

const LINE: Record<Source, InboxItem['line']> = {
	inbound: 'in',
	file: 'vv',
	vitevue: 'vv',
	own_contact: 'own',
	agent_to_agent: 'a2a'
}
const BAND: Record<string, string> = {
	high: 'High',
	medium: 'Medium',
	standard: 'Standard'
}

/** A recently sold owner's sales, newest first: "Recently sold · 2 sales · latest 5 Oct · AED 2.4M". */
/** The sales stored on a recently sold owner (Inbox item or the lead approved from it). */
function recentSales(e: InboundEnquiryResponse): RecentSale[] | null {
	if (e.source !== SOLD_OWNER_SOURCE) return null
	return (e.observed_data?.recent_sales ?? []) as RecentSale[]
}

function soldLine(e: InboundEnquiryResponse): string | null {
	if (e.source !== SOLD_OWNER_SOURCE) return null
	const sales = (e.observed_data?.recent_sales ?? []) as {
		sold_on: string
		price_aed: number | null
		bought_price_aed?: number | null
		est_cash_in_hand_aed?: number | null
	}[]
	const latest = sales[0]
	if (!latest) return 'Recently sold'
	// What the latest sale made over the owner's purchase: the cash the seller freed up.
	const gain =
		latest.price_aed && latest.bought_price_aed ? latest.price_aed - latest.bought_price_aed : null
	return [
		'Recently sold',
		`${sales.length} ${sales.length === 1 ? 'sale' : 'sales'}`,
		`latest ${dayMonth(latest.sold_on)}`,
		latest.price_aed ? `AED ${short(latest.price_aed)}` : null,
		gain === null ? null : gain < 0 ? `Loss −AED ${short(-gain)}` : `Profit +AED ${short(gain)}`,
		// Sale less the loan DLD recorded at purchase; repayments since are unknown, so "≈".
		latest.est_cash_in_hand_aed != null
			? `Est. cash in hand ≈ AED ${short(latest.est_cash_in_hand_aed)}`
			: latest.price_aed
				? 'Cash in hand: mortgage unknown'
				: null
	]
		.filter(Boolean)
		.join(' · ')
}

function inboxItem(e: InboundEnquiryResponse, u: AuthMeResponse): InboxItem {
	const type = typeOf(e)
	const typed = e.intent !== 'unknown'
	const summary = summaryOf(type, fieldsOf(e.criteria), e.criteria)
	const name = e.contact.full_name || 'Unnamed contact'
	const dismissed = e.status === 'disqualified'
	const mine = e.assigned_user_id === u.id
	const agent = e.assigned_user_id ? (mine ? fullName(u) : 'Another agent') : 'Unassigned'
	return {
		id: String(e.id),
		name,
		source: e.campaign ? `${e.source} · ${e.campaign}` : e.source,
		line: LINE[sourceOf(e.source)],
		at_label: stamp(e.enquiry_date),
		ago: received(e.enquiry_date),
		text: e.raw_notes || (typed ? summary.line : 'Not yet qualified'),
		owner_check: knownOf(e),
		priority: `${BAND[e.priority?.band ?? 'standard']} · ${e.priority?.score ?? 0}`,
		state: dismissed ? 'dismissed' : e.assigned_user_id ? 'assigned' : 'waiting',
		status_chip: dismissed
			? { tone: 'neutral', label: 'Not a real enquiry' }
			: e.sla_state === 'overdue'
				? { tone: 'red', label: 'First reply overdue' }
				: e.assigned_user_id
					? { tone: mine ? 'green' : 'blue', label: mine ? 'Yours' : 'Assigned' }
					: { tone: 'amber', label: 'Waiting for a manager' },
		agent,
		// Agent suggestions and the handout system are not on the backend yet.
		suggested: '—',
		reason: (e.priority?.reasons ?? []).join(' · '),
		requests: [],
		want_line: typed
			? [LEAD_TYPES[type].label, summary.line, summary.sub].filter(Boolean).join(' · ')
			: (soldLine(e) ?? 'Not yet qualified as a buyer, seller, tenant or landlord'),
		// Only a typed enquiry opens as a lead; an unqualified contact has no lead type yet.
		lead_id: typed ? e.id : null,
		conversation: e.raw_notes
			? [{ from: 'client', who: name, at: stamp(e.enquiry_date), text: e.raw_notes }]
			: [],
		can: {
			ask: false,
			withdraw: false,
			release: false,
			dismiss: false,
			restore: false,
			approve: e.source === SOLD_OWNER_SOURCE && e.intent === 'unknown'
		},
		my_request: null
	}
}

/**
 * Inbox: typed enquiries still waiting for a first response (the backend's inbox rule) and
 * contacts not yet qualified. Vitevue lease leads live in Leads. Dismissed (disqualified) items are
 * left out: the Not real tab was removed (28 Oct), nothing on the backend marks items not real.
 * Read only: asking for, releasing and dismissing enquiries need the handout system.
 */
export async function listInbox(filter: InboxFilter, days = 30): Promise<InboxResponse> {
	// Inbox window ("Last 30 days"): items dated within `days`; a recent seller by the sale date.
	const get = (q: Record<string, string>, limit = LIST_LIMIT) =>
		client.get<InboundEnquiryListResponse>(
			client.withQuery(`${CRM}/inbound/enquiries`, { ...q, within_days: days, limit })
		)
	const [inbox, unqualified, u] = await Promise.all([
		get({ workspace: 'inbox' }),
		// Recent sellers are unqualified contacts: up to 1,000, so 90 days fits.
		get({ workspace: 'unqualified' }, 1000),
		whoAmI()
	])
	const seen = new Set<number>()
	const open = [...inbox.enquiries, ...unqualified.enquiries]
		.filter((e) => !isVitevue(e) && e.status !== 'disqualified')
		.filter((e) => !seen.has(e.id) && Boolean(seen.add(e.id)))
		.sort((a, b) => b.enquiry_date.localeCompare(a.enquiry_date))
		.map((e) => inboxItem(e, u))
	const lists: Record<InboxFilter, InboxItem[]> = {
		all: open,
		mine: open.filter((x) => x.agent === fullName(u)),
		waiting: open.filter((x) => x.state === 'waiting')
	}
	return {
		items: lists[filter],
		lists,
		counts: {
			all: lists.all.length,
			mine: lists.mine.length,
			waiting: lists.waiting.length
		},
		today: open.filter((x) => x.ago === 'today').length,
		waiting: lists.waiting.length,
		handout: 'manager',
		handout_label: 'Not set',
		sources: []
	}
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

/* ── company listings (/company-listings) ── */

/** GET /crm/company-listings row (not in the generated client yet). */
interface CompanyListingResponse {
	reference: string
	agent_name: string
	agent_phone: string | null
	mode: string
	title: string
	property_type: string
	bedrooms: number | null
	size_sqft: number | null
	price_aed: number
	area_name: string
	building_name: string | null
	unit_number: string | null
	status: string
	listed_at: string
}

interface CompanyListingsResponse {
	company: CompanyListingCompany | null
	matching_company: CompanyListingCompany | null
	companies: CompanyListingCompany[]
	agents: CompanyListingAgentInventory[]
	items: CompanyListingResponse[]
	total: number
	limit: number
	offset: number
}

/** Active or under offer is live; pocket is off-market (not advertised); sold or withdrawn is expired. */
const companyStatus = (s: string): ListingStatus =>
	s === 'active' || s === 'under_offer' ? 'live' : s === 'pocket' ? 'pocket' : 'expired'

function companyCard(r: CompanyListingResponse): ListingCard {
	return {
		id: r.reference,
		unit: r.title,
		area: r.area_name,
		bedrooms: r.bedrooms ?? 0,
		size_sqft: r.size_sqft ?? 0,
		price_aed: r.price_aed,
		deal_type: r.mode === 'rent' ? 'rent' : 'sale',
		status: companyStatus(r.status),
		scope: 'company',
		agent: r.agent_name,
		owner: '',
		portals: '',
		days_live: Math.max(0, Math.floor((Date.now() - Date.parse(r.listed_at)) / 86_400_000)),
		enquiries: 0,
		permit: null,
		// No permit is recorded for company listings yet; the card's chip shows the type instead.
		permit_chip: { tone: 'neutral', label: r.property_type },
		form_a_expires: null,
		form_a_chip: null,
		comparables_note: '',
		from_lead_id: null
	}
}

export async function listCompanyListings(
	status?: ListingStatus,
	limit = 100,
	offset = 0,
	filter?: CompanyListingFilter
): Promise<ListingListResponse> {
	const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
	if (filter?.brokerId) params.set('broker_id', filter.brokerId)
	if (filter?.allCompanies) params.set('all_companies', 'true')
	if (filter?.agentId) params.set('agent_id', filter.agentId)
	else if (filter?.agentName) params.set('agent_name', filter.agentName)
	if (filter?.search) params.set('search', filter.search)
	const r = await client.get<CompanyListingsResponse>(`${CRM}/company-listings?${params}`)
	const cards = r.items.map(companyCard)
	const count = (s: ListingStatus) => (s === 'live' ? r.total : 0)
	return {
		items: status ? cards.filter((c) => c.status === status) : cards,
		counts: { live: count('live'), pocket: count('pocket'), expired: count('expired') },
		company: r.company,
		matching_company: r.matching_company,
		companies: r.companies,
		agent_inventory: r.agents,
		total: r.total,
		limit: r.limit,
		offset: r.offset
	}
}

/** Stop matching buyers and tenants against any company's listings (owners only). */
export async function clearCompanyListingSource() {
	return client.delete<void>(`${CRM}/company-listings/source`)
}

export async function selectCompanyListingSource(broker_id: string) {
	return client.put<{ broker_id: string; broker_name: string }>(`${CRM}/company-listings/source`, {
		broker_id
	})
}

/* ── listing documents (/company-listings/{key}, /listing-document-info, /documents) ── */

/** A company card's id is `PF-<Property Finder listing id>`; documents use the bare id. */
export const listingKeyOf = (id: string): string | null =>
	/^PF-([A-Za-z0-9]{1,40})$/.exec(id)?.[1] ?? null

export async function getCompanyListing(listingKey: string): Promise<ListingDetail> {
	const r = await client.get<CrmCompanyListingDetail>(`${CRM}/company-listings/${listingKey}`)
	return {
		...companyCard(r),
		managed: r.managed,
		listing_key: r.listing_key,
		documents: { required: [], notes: {}, received: [] },
		form_a_status: { tone: 'neutral', label: 'Not tracked' },
		permit_status: 'none',
		leads: [],
		lead_stages: null,
		deals: [],
		matched: [],
		from_lead: null,
		can_publish: false
	}
}

export const getDocumentInfo = (listingKey: string) =>
	client.get<ListingDocumentInfoResponse>(
		`${CRM}/listing-document-info?source=property_finder&listing_key=${encodeURIComponent(listingKey)}`
	)

export const saveDocumentInfo = (body: ListingDocumentInfoUpdate) =>
	client.put<ListingDocumentInfoResponse>(`${CRM}/listing-document-info`, body)

export const generateDocument = (body: GenerateDocumentRequest) =>
	client.post<GeneratedDocumentResponse>(`${CRM}/documents`, body)

export function listDocuments(p: DocumentListParams = {}) {
	const params = new URLSearchParams()
	if (p.listingKey) params.set('listing_key', p.listingKey)
	if (p.docType) params.set('doc_type', p.docType)
	if (p.search?.trim()) params.set('search', p.search.trim())
	if (p.limit) params.set('limit', String(p.limit))
	if (p.offset) params.set('offset', String(p.offset))
	const q = params.toString()
	return client.get<GeneratedDocumentListResponse>(`${CRM}/documents${q ? `?${q}` : ''}`)
}

export const getDocument = (id: string) =>
	client.get<GeneratedDocumentResponse>(`${CRM}/documents/${id}`)

/** A link valid for a few minutes; ask again for every download. */
export const downloadDocument = (id: string) =>
	client.post<DocumentDownloadResponse>(`${CRM}/documents/${id}/download`, {})

/** Same short-lived link, but the browser shows the PDF instead of saving it. */
export const previewDocument = (id: string) =>
	client.post<DocumentDownloadResponse>(`${CRM}/documents/${id}/download?inline=true`, {})

/* ── Connectors › Email (/email, Brevo) ── */

export const emailStatus = () => client.get<EmailStatus>(`${CRM}/email/status`)

export function emailLeads(p: EmailLeadParams = {}) {
	const params = new URLSearchParams()
	if (p.search?.trim()) params.set('search', p.search.trim())
	if (p.intent) params.set('intent', p.intent)
	if (p.source) params.set('source', p.source)
	for (const id of p.ids ?? []) params.append('ids', String(id))
	const q = params.toString()
	return client.get<EmailLeadList>(`${CRM}/email/leads${q ? `?${q}` : ''}`)
}

export const sendEmails = (body: { enquiry_ids: number[]; subject: string; body: string }) =>
	client.post<EmailSendBatch>(`${CRM}/email/send`, body)

export const emailSends = (status: EmailSendStatus | '' = '') =>
	client.get<EmailSendList>(`${CRM}/email/sends${status ? `?status=${status}` : ''}`)

export const syncEmailEvents = () => client.post<EmailSync>(`${CRM}/email/tracking/sync`, {})

export const emailTemplates = () => client.get<EmailTemplate[]>(`${CRM}/email/templates`)

export const createEmailTemplate = (body: EmailTemplateInput) =>
	client.post<EmailTemplate>(`${CRM}/email/templates`, body)

export const updateEmailTemplate = (id: number, body: EmailTemplateInput) =>
	client.put<EmailTemplate>(`${CRM}/email/templates/${id}`, body)

export const deleteEmailTemplate = (id: number) =>
	client.delete<void>(`${CRM}/email/templates/${id}`)

export const emailInbound = () => client.get<EmailInboundList>(`${CRM}/email/inbound`)

export const emailThread = (enquiryId: number) =>
	client.get<EmailThreadItem[]>(`${CRM}/email/leads/${enquiryId}/thread`)

export const deleteEmailSend = (id: number) => client.delete<void>(`${CRM}/email/sends/${id}`)

/* ── Connectors › WhatsApp (/whatsapp, Meta WhatsApp Cloud API) ── */

/** A chat as the backend lists it: the lead's stage, score and source are read from the lead. */
type WhatsAppChatRow = Omit<
	WhatsAppChat,
	'lead_stage' | 'lead_score' | 'lead_source' | 'lead_source_short'
>

/** The template to send and its {{1}}, {{2}}… values; {{1}} defaults to the first name. */
export interface WhatsAppTemplateSend {
	name: string
	language: string
	params?: string[]
}

type Ok = { ok: boolean }

export const whatsappStatus = () => client.get<WhatsAppStatus>(`${CRM}/whatsapp/status`)

export const whatsappTemplates = () => client.get<WhatsAppTemplate[]>(`${CRM}/whatsapp/templates`)

/** The signed-in agent's chats, each with its lead's stage, score and source when it is on one. */
export async function whatsappChats(): Promise<WhatsAppChat[]> {
	const rows = await client.get<WhatsAppChatRow[]>(`${CRM}/whatsapp/chats`)
	const ids = [...new Set(rows.flatMap((r) => (r.lead_id === null ? [] : [r.lead_id])))]
	const leads = new Map(
		await Promise.all(ids.map(async (id) => [id, await getLead(id).catch(() => null)] as const))
	)
	return rows.map((r) => {
		const lead = r.lead_id === null ? null : leads.get(r.lead_id)
		return {
			...r,
			lead_stage: lead?.stage ?? null,
			lead_score: lead?.score ?? null,
			lead_source: lead?.source ?? null,
			lead_source_short: lead?.source_short ?? null
		}
	})
}

export const whatsappLeadThread = (enquiryId: number) =>
	client.get<WhatsAppThread>(`${CRM}/whatsapp/leads/${enquiryId}/thread`)

export const whatsappLeadTemplate = (enquiryId: number, body: WhatsAppTemplateSend) =>
	client.post<Ok>(`${CRM}/whatsapp/leads/${enquiryId}/template`, body)

export const whatsappLeadReply = (enquiryId: number, body: string) =>
	client.post<Ok>(`${CRM}/whatsapp/leads/${enquiryId}/reply`, { body })

export const whatsappChat = (waId: string) =>
	client.get<WhatsAppThread>(`${CRM}/whatsapp/chats/${waId}`)

export const whatsappChatTemplate = (waId: string, body: WhatsAppTemplateSend) =>
	client.post<Ok>(`${CRM}/whatsapp/chats/${waId}/template`, body)

export const whatsappChatReply = (waId: string, body: string) =>
	client.post<Ok>(`${CRM}/whatsapp/chats/${waId}/reply`, { body })

/* Sender numbers (organization owners). */

export const whatsappNumbers = () => client.get<WhatsAppNumber[]>(`${CRM}/whatsapp/numbers`)

export const whatsappMetaNumbers = () =>
	client.get<WhatsAppMetaNumber[]>(`${CRM}/whatsapp/meta/numbers`)

export const saveWhatsappNumber = (phoneNumberId: string, body: WhatsAppNumberWrite) =>
	client.put<WhatsAppNumber>(`${CRM}/whatsapp/numbers/${phoneNumberId}`, body)

/* Campaigns from the campaign number (organization owners). */

export function whatsappAudience(p: { search?: string; intent?: string } = {}) {
	const params = new URLSearchParams()
	if (p.search?.trim()) params.set('search', p.search.trim())
	if (p.intent) params.set('intent', p.intent)
	const q = params.toString()
	return client.get<WhatsAppAudience>(`${CRM}/whatsapp/campaign/audience${q ? `?${q}` : ''}`)
}

export const whatsappCampaigns = () => client.get<WhatsAppCampaign[]>(`${CRM}/whatsapp/campaigns`)

export const whatsappCampaign = (id: number) =>
	client.get<WhatsAppCampaignDetail>(`${CRM}/whatsapp/campaigns/${id}`)

export const createWhatsappCampaign = (body: WhatsAppCampaignCreate) =>
	client.post<WhatsAppCampaignDetail>(`${CRM}/whatsapp/campaigns`, body)

export const resumeWhatsappCampaign = (id: number) =>
	client.post<WhatsAppCampaignDetail>(`${CRM}/whatsapp/campaigns/${id}/resume`, {})

export const whatsappCampaignChats = () =>
	client.get<WhatsAppChatRow[]>(`${CRM}/whatsapp/campaign/chats`)

export const whatsappCampaignChat = (waId: string) =>
	client.get<WhatsAppThread>(`${CRM}/whatsapp/campaign/chats/${waId}`)

export const whatsappCampaignReply = (waId: string, body: string) =>
	client.post<Ok>(`${CRM}/whatsapp/campaign/chats/${waId}/reply`, { body })
