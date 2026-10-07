/**
 * CRM API. Every screen reads and writes through these functions only.
 *
 * Fixtures are the default (7 Oct: frontend only, the CRM backend was removed): every call is
 * answered by the fixture backend in ./mock (src/lib/crm/api/mock/fixtures.json).
 * PUBLIC_CRM_API_MODE=live sends calls to FastAPI at /api/v1/crm-beta through the Vitevue API
 * client (auth header, 401 redirect) once that backend exists. Switching modes changes nothing
 * outside this module.
 */
import { env } from '$env/dynamic/public'
import { ApiError, client } from '$lib/api/client'
import type {
	CalendarEvent,
	CalendarSide,
	CommissionAmounts,
	CommissionPatch,
	Connection,
	ConversationMessage,
	DealCreate,
	DealDetail,
	DealListResponse,
	DealStages,
	DealTab,
	DealType,
	DocumentUploadResult,
	EventCreate,
	FeedArea,
	FeedSummary,
	FormPreview,
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
	LeadListParams,
	LeadListResponse,
	LeadMatches,
	LeadPatch,
	LeadStageMove,
	ListingCreate,
	ListingCreateResult,
	ListingDetail,
	ListingListResponse,
	ListingScope,
	ListingStatus,
	MarketListing,
	MarketListingDetail,
	MatchClients,
	MatchOptions,
	Me,
	NavCounts,
	Notification,
	OwnerDetail,
	OwnerLeadCreate,
	OwnerListParams,
	OwnerListResponse,
	OwnerRecordCreate,
	OwnerReport,
	OwnerRow,
	PortfolioResponse,
	PursueResult,
	Renewal,
	SearchResults,
	Written
} from './types'

export const API_BASE = '/api/v1/crm-beta'

const { withQuery } = client

export const apiMode: 'fixtures' | 'live' =
	String(env.PUBLIC_CRM_API_MODE ?? '')
		.trim()
		.toLowerCase() === 'live'
		? 'live'
		: 'fixtures'

if (typeof window !== 'undefined') {
	// One line so a support run can tell which backend answered (not an error).
	console.info(
		`[CRM] API: ${apiMode === 'live' ? `live · ${env.PUBLIC_API_BASE_URL || 'same origin'}${API_BASE}` : 'fixtures (no backend needed)'}`
	)
}

interface Http {
	get<T>(path: string): Promise<T>
	post<T>(path: string, body?: unknown): Promise<T>
	put<T>(path: string, body?: unknown): Promise<T>
	patch<T>(path: string, body?: unknown): Promise<T>
	delete<T>(path: string): Promise<T>
}

const live: Http = {
	get: <T>(p: string) => client.get<T>(API_BASE + p),
	post: <T>(p: string, b?: unknown) => client.post<T>(API_BASE + p, b),
	put: <T>(p: string, b?: unknown) => client.put<T>(API_BASE + p, b),
	patch: <T>(p: string, b?: unknown) => client.patch<T>(API_BASE + p, b),
	delete: <T>(p: string) => client.delete<T>(API_BASE + p)
}

const latency = Number(env.PUBLIC_CRM_MOCK_LATENCY_MS ?? 250) || 0
const failing = (env.PUBLIC_CRM_MOCK_FAIL ?? '')
	.split(',')
	.map((s) => s.trim())
	.filter(Boolean)

async function fixture<T>(method: string, path: string, body?: unknown): Promise<T> {
	const { handle } = await import('./mock/server')
	if (latency) await new Promise((r) => setTimeout(r, latency))
	if (failing.some((p) => path.startsWith(p))) {
		throw new ApiError('Could not load this. Check your connection and retry.', 503, 'unavailable')
	}
	return (await handle(method, path, body)) as T
}

const fixtures: Http = {
	get: <T>(p: string) => fixture<T>('GET', p),
	post: <T>(p: string, b?: unknown) => fixture<T>('POST', p, b),
	put: <T>(p: string, b?: unknown) => fixture<T>('PUT', p, b),
	patch: <T>(p: string, b?: unknown) => fixture<T>('PATCH', p, b),
	delete: <T>(p: string) => fixture<T>('DELETE', p)
}

const http: Http = apiMode === 'live' ? live : fixtures

const upload = (fields: Record<string, string | Blob | null | undefined>) => {
	const fd = new FormData()
	for (const [k, v] of Object.entries(fields)) if (v !== null && v !== undefined) fd.append(k, v)
	return fd
}

type Ok = { ok: boolean }

export const crm = {
	me: () => http.get<Me>('/me'),
	counts: () => http.get<NavCounts>('/crm/counts'),
	home: (day: string) => http.get<HomeResponse>(withQuery('/crm/home', { day })),
	undo: (token: string) => http.post<Ok>('/undo', { token }),

	leads: {
		list: (p: LeadListParams) => http.get<LeadListResponse>(withQuery('/leads', { ...p })),
		get: (id: number) => http.get<LeadDetail>(`/leads/${id}`),
		create: (body: LeadCreate) => http.post<Written<LeadDetail>>('/leads', body),
		patch: (id: number, body: LeadPatch) => http.patch<Written<LeadDetail>>(`/leads/${id}`, body),
		/** Move to a stage with what that stage needs (one history row, one Undo). */
		moveStage: (id: number, body: LeadStageMove) =>
			http.post<Written<LeadDetail>>(`/leads/${id}/stage`, body),
		uploadDocument: (id: number, file: File, docType: string) =>
			http.post<Written<LeadDetail>>(`/leads/${id}/documents`, upload({ file, doc_type: docType })),
		events: (id: number) => http.get<LeadEvent[]>(`/leads/${id}/events`),
		undoLast: (id: number, eventId?: number) =>
			http.post<{ data: LeadDetail; undone: string }>(`/leads/${id}/undo`, { event_id: eventId }),
		addNote: (id: number, text: string) =>
			http.post<Written<LeadDetail>>(`/leads/${id}/notes`, { text }),
		logCall: (id: number, outcome?: string) =>
			http.post<Written<LeadDetail>>(`/leads/${id}/calls`, { outcome }),
		bookViewing: (
			id: number,
			body: { date: string; time: string; listing_id: string | null; note: string }
		) => http.post<Written<CalendarEvent>>(`/leads/${id}/viewings`, body),
		matches: (id: number, o: MatchOptions = {}) =>
			http.get<LeadMatches>(
				withQuery(`/leads/${id}/matches`, {
					over: o.over === false ? '0' : undefined,
					after: o.after ? '1' : undefined
				})
			),
		/** Pursue a match (again to stop): "Match pursued" on both records + the next action. */
		pursue: (id: number, key: string) =>
			http.post<Written<PursueResult>>(`/leads/${id}/pursue`, { key }),
		shortlist: (id: number, key: string) =>
			http.post<Written<{ on: boolean; count: number }>>(`/leads/${id}/shortlist`, { key }),
		renewalCall: (id: number, key: string) =>
			http.post<Written<CalendarEvent>>(`/leads/${id}/renewal-call`, { key }),
		/** Ask a colleague about their listing, lead or allocation (logged; nothing goes to a client). */
		ask: (id: number, key: string) =>
			http.post<Written<{ asked: string }>>(`/leads/${id}/ask`, { key }),
		conversation: (id: number) => http.get<ConversationMessage[]>(`/leads/${id}/conversation`),
		createListing: (id: number, body: ListingCreate) =>
			http.post<Written<ListingCreateResult>>(`/leads/${id}/listing`, body)
	},

	feed: {
		summary: () => http.get<FeedSummary>('/feed/summary'),
		areas: () => http.get<FeedArea[]>('/feed/areas'),
		setAreas: (areas: string[]) => http.put<Written<FeedSummary>>('/me/areas', { areas })
	},

	inbox: {
		list: (filter: InboxFilter) => http.get<InboxResponse>(withQuery('/inbox', { filter })),
		ask: (id: string) => http.post<Written<InboxItem>>(`/inbox/${id}/ask`),
		withdraw: (id: string) => http.post<Written<InboxItem>>(`/inbox/${id}/withdraw`),
		release: (id: string) => http.post<Written<InboxItem>>(`/inbox/${id}/release`),
		dismiss: (id: string) => http.post<Written<InboxItem>>(`/inbox/${id}/dismiss`),
		restore: (id: string) => http.post<Written<InboxItem>>(`/inbox/${id}/restore`)
	},

	settings: {
		handout: () => http.get<HandoutSettings>('/settings/handout'),
		setHandout: (mode: HandoutMode) =>
			http.put<Written<HandoutSettings>>('/settings/handout', { mode })
	},

	matches: {
		clients: () => http.get<MatchClients>('/matches/clients'),
		/** Watch a unit whose owner is not on your file (unit events). */
		watchUnit: (key: string) => http.post<Written<{ on: boolean }>>('/units/watch', { key })
	},

	deals: {
		stages: () => http.get<DealStages>('/deal-stages'),
		list: (tab: DealTab, dealType?: DealType | '') =>
			http.get<DealListResponse>(withQuery('/deals', { tab, deal_type: dealType })),
		get: (id: string) => http.get<DealDetail>(`/deals/${id}`),
		check: (id: string, key: string, done: boolean) =>
			http.patch<Written<DealDetail>>(`/deals/${id}/checklist`, { key, done }),
		commissionPreview: (id: string, body: CommissionPatch) =>
			http.post<CommissionAmounts>(`/deals/${id}/commission/preview`, body),
		create: (body: DealCreate) => http.post<Written<DealDetail>>('/deals', body),
		move: (id: string, direction: 'next' | 'back') =>
			http.patch<Written<DealDetail>>(`/deals/${id}/stage`, { direction }),
		patch: (id: string, body: { dld_transaction_id?: string }) =>
			http.patch<Written<DealDetail>>(`/deals/${id}`, body),
		upload: (id: string, file: File, docType?: string | null) =>
			http.post<Written<DocumentUploadResult>>(
				`/deals/${id}/documents`,
				upload({ file, doc_type: docType ?? undefined })
			),
		removeDocument: (id: string, docId: number) =>
			http.delete<Written<{ removed: string }>>(`/deals/${id}/documents/${docId}`),
		requestDocuments: (id: string, docTypes: string[]) =>
			http.post<{ requested: number }>(`/deals/${id}/document-requests`, { doc_types: docTypes }),
		commission: (id: string, body: CommissionPatch) =>
			http.patch<Written<DealDetail>>(`/deals/${id}/commission`, body),
		invoice: (id: string) =>
			http.post<Written<DealDetail> & { invoice: { amount_aed: number; vat_aed: number } }>(
				`/deals/${id}/invoice`
			),
		form: (id: string, code: string) => http.get<FormPreview>(`/deals/${id}/forms/${code}`),
		compliance: (id: string, body: { due_diligence: 'complete' | 'pending' }) =>
			http.patch<Written<DealDetail>>(`/deals/${id}/compliance`, body),
		screening: (id: string) => http.post<{ status: string }>(`/deals/${id}/screening`),
		goaml: (id: string) => http.post<{ status: string }>(`/deals/${id}/goaml`)
	},

	listings: {
		list: (scope: ListingScope, status?: ListingStatus) =>
			http.get<ListingListResponse>(withQuery('/listings', { scope, status })),
		get: (id: string) => http.get<ListingDetail>(`/listings/${id}`),
		create: (body: ListingCreate) => http.post<Written<ListingCreateResult>>('/listings', body),
		addPermit: (id: string, body: { number: string; expires: string }) =>
			http.post<Written<ListingDetail>>(`/listings/${id}/permit`, body),
		publish: (id: string) => http.post<Written<ListingDetail>>(`/listings/${id}/publish`),
		unpublish: (id: string) => http.post<Written<ListingDetail>>(`/listings/${id}/unpublish`),
		relist: (id: string) =>
			http.post<Written<ListingDetail> & { message: string | null }>(`/listings/${id}/relist`),
		upload: (id: string, file: File, docType: string) =>
			http.post<Written<ListingDetail>>(
				`/listings/${id}/documents`,
				upload({ file, doc_type: docType })
			),
		send: (id: string, leadIds: number[]) =>
			http.post<Written<{ sent: number }>>(`/listings/${id}/send`, { lead_ids: leadIds }),
		sendBrochure: (id: string) => http.post<{ sent: boolean }>(`/listings/${id}/brochure/send`)
	},

	portfolio: {
		get: () => http.get<PortfolioResponse>('/portfolio'),
		checkIn: (client: string) => http.post<{ sent: boolean }>('/portfolio/check-in', { client })
	},

	renewals: {
		list: () => http.get<Renewal[]>('/renewals'),
		start: (id: number) => http.post<Written<Renewal>>(`/renewals/${id}/start`),
		send: (id: number) => http.post<{ sent: boolean }>(`/renewals/${id}/send`)
	},

	market: {
		list: () => http.get<MarketListing[]>('/market-listings'),
		get: (id: string) => http.get<MarketListingDetail>(`/market-listings/${id}`),
		watch: (id: string, watch: boolean) =>
			http.post<Written<MarketListing>>(`/market-listings/${id}/watch`, { watch }),
		send: (id: string, leadIds: number[]) =>
			http.post<Written<{ sent: number }>>(`/market-listings/${id}/send`, { lead_ids: leadIds })
	},

	owners: {
		list: (p: OwnerListParams) => http.get<OwnerListResponse>(withQuery('/owners', { ...p })),
		get: (id: string) => http.get<OwnerDetail>(`/owners/${id}`),
		createLead: (id: string, body: OwnerLeadCreate) =>
			http.post<Written<LeadDetail>>(`/owners/${id}/lead`, body),
		create: (body: { name: string; units: string[] }) =>
			http.post<Written<OwnerRow>>('/owners', body),
		addNote: (id: string, text: string) =>
			http.post<Written<OwnerRow>>(`/owners/${id}/notes`, { text }),
		/** Add record: a documented prior transaction (sale, tenancy, listing agreement). */
		addRecord: (id: string, body: OwnerRecordCreate) =>
			http.post<Written<OwnerRow>>(`/owners/${id}/records`, body),
		report: (id: string) => http.get<OwnerReport>(`/owners/${id}/report`),
		sendReport: (id: string) => http.post<Written<OwnerRow>>(`/owners/${id}/report/send`),
		sendMarketUpdate: (id: string) => http.post<Written<OwnerRow>>(`/owners/${id}/market-update`)
	},

	imports: {
		list: () => http.get<ImportRequest[]>('/imports'),
		/** The backend reads the file and picks the columns (exact header names first). */
		preview: (file: File, kind: 'Owners' | 'Leads') =>
			http.post<ImportPreview>('/imports/preview', upload({ file, kind })),
		create: (file: File, kind: 'Owners' | 'Leads', areas: string) =>
			http.post<Written<ImportRequest>>('/imports', upload({ file, kind, areas }))
	},

	events: {
		list: (from: string, to: string) =>
			http.get<CalendarEvent[]>(withQuery('/events', { from, to })),
		get: (id: number) => http.get<CalendarEvent>(`/events/${id}`),
		create: (body: EventCreate) => http.post<Written<CalendarEvent>>('/events', body),
		done: (id: number) => http.patch<Written<CalendarEvent>>(`/events/${id}`, { done: true }),
		/** Reschedule: a lead's event is logged on the lead and becomes its next action. */
		reschedule: (id: number, date: string, time: string | null) =>
			http.patch<Written<CalendarEvent>>(`/events/${id}`, { date, time }),
		remove: (id: number) => http.delete<Written<{ deleted: string }>>(`/events/${id}`),
		side: () => http.get<CalendarSide>('/calendar/side')
	},

	search: (q: string) => http.get<SearchResults>(withQuery('/search', { q })),

	notifications: {
		list: () => http.get<Notification[]>('/notifications'),
		read: (ids?: number[]) =>
			http.post<Written<{ unread: number }>>('/notifications/read', ids ? { ids } : {})
	},

	connections: () => http.get<Connection[]>('/connections')
}
