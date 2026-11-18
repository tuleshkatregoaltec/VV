/** CRM contracts use the backend by default. The isolated pilot can explicitly select
 * fictional, read-only presentation fixtures; no fixture operation writes to the backend.
 */
import { env } from '$env/dynamic/public'
import { ApiError } from '$lib/api/client'
import { homeCalendar } from '../calendar'
import { addDays } from '../format'
import * as backend from './backend'
import { createPresentationCrm } from './presentation'
import type {
	CalendarEvent,
	CalendarSide,
	CommissionAmounts,
	CommissionPatch,
	CompanyListingFilter,
	Connection,
	ConversationMessage,
	DealCreate,
	DealDetail,
	DealListResponse,
	DealRow,
	DealStages,
	DealTab,
	DealType,
	DocumentUploadResult,
	EmailLeadParams,
	EmailSendStatus,
	EmailTemplateInput,
	EventCreate,
	FeedArea,
	FeedPreferences,
	FeedSummary,
	FormPreview,
	HandoutMode,
	HandoutSettings,
	HomeResponse,
	ImportAssignment,
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
	OwnerDroppedRows,
	OwnerDroppedRowsParams,
	OwnerFilePreview,
	OwnerHistory,
	OwnerHistoryParams,
	OwnerHistorySummary,
	OwnerImport,
	OwnerImportDetail,
	OwnerImportResult,
	OwnerImportRows,
	OwnerImportRowsParams,
	OwnerLeadCreate,
	OwnerListParams,
	OwnerListResponse,
	OwnerProperties,
	OwnerPropertyParams,
	OwnerRecordCreate,
	OwnerReport,
	OwnerRow,
	PortfolioResponse,
	PursueResult,
	RenewalDetail,
	RenewalListParams,
	RenewalListResponse,
	SearchResults,
	Written
} from './types'

type Ok = { ok: boolean }

const notOnBackend = backend.notOnBackend
const done = <T>(data: T): Written<T> => ({ data, undo_token: null })

/** Conveyancing steps of a Dubai sale and a let: the process, not stored records. */
const DEAL_STAGES: DealStages = {
	sale: [
		'Offer accepted',
		'Form F signed',
		'Mortgage / bank',
		'NOC',
		'Transfer booked',
		'Transferred'
	],
	rent: ['Contract', 'Deposit and cheques', 'Ejari', 'Keys']
}

/** Monday to Sunday of the week holding `day`. */
function weekOf(day: string): string[] {
	const dow = (new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7
	const monday = addDays(day, -dow)
	return Array.from({ length: 7 }, (_, i) => addDays(monday, i))
}

/** The week's events for Home; Home still renders (without them) if the calendar is unavailable. */
async function weekEvents(week: string[]): Promise<CalendarEvent[]> {
	try {
		return await backend.listCalendarEvents(week[0], week[6])
	} catch {
		return []
	}
}

/** The first of the agent's areas (up to three tried) that has market figures; null without. */
async function homeMarket(): Promise<HomeResponse['counters']['market']> {
	try {
		const { areas } = await backend.getFeedPreferences()
		for (const area of areas.slice(0, 3)) {
			const market = await backend.areaMarket(area)
			if (market) return market
		}
	} catch {
		// Home still renders; the card asks for an area.
	}
	return null
}

/** Open deals for Home's Conveyancing board (the same list as Deals › Conveyancing). */
async function homeDeals(): Promise<DealRow[]> {
	try {
		return (await backend.listDeals('conveyancing')).items
	} catch {
		return [] // Home still renders without them
	}
}

/** The device's current day and minute, "YYYY-MM-DD HH:MM", for "next viewing". */
function nowStamp(): string {
	const d = new Date()
	const pad = (n: number) => String(n).padStart(2, '0')
	return `${backend.localToday()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** Home: new leads, To do (gaps and owner-file leads), the calendar (the same events as the
 * Calendar page), the market figures for the agent's area and open deals (Conveyancing) are real.
 * Own listings (permits, Form A) and commission have no backend yet: those counters are null so
 * Home shows "—" rather than a made-up 0. */
async function home(day: string): Promise<HomeResponse> {
	const date = day || backend.localToday()
	const week = weekOf(date)
	const [leads, events, market, todo, deals] = await Promise.all([
		backend.listLeads({ stage: 'new' }),
		weekEvents(week),
		homeMarket(),
		backend.homeTodo(),
		homeDeals()
	])
	const fresh = [...leads.items].sort((a, b) => b.score - a.score)
	const cal = homeCalendar(events, week, date, backend.localToday(), nowStamp())
	return {
		limited: leads.limited,
		date,
		facts: { events_today: cal.events_today, conveyancing: deals.length, permits_under_14: 0 },
		counters: {
			viewings_week: cal.viewings_week,
			expiring_14: null,
			market,
			commission: null,
			new_leads: fresh.length,
			overdue: 0,
			conveyancing: {
				count: deals.length,
				value_aed: deals.reduce((n, d) => n + (d.value_aed || 0), 0)
			}
		},
		week: cal.week,
		day: cal.day,
		conveyancing: deals,
		new_leads: fresh,
		gaps: todo.gaps,
		file_leads: todo.file_leads
	}
}

async function counts(): Promise<NavCounts> {
	const leads = await backend.listLeads({})
	return {
		limited: leads.limited,
		new_leads: leads.new_count,
		inbox: 0,
		open_deals: 0,
		events_today: 0,
		waiting: 0,
		unread_notifications: 0
	}
}

const liveCrm = {
	me: (): Promise<Me> => backend.me(),
	counts,
	home,
	undo: (_token: string) => notOnBackend<Ok>('Undo'),

	/** Backend: /api/v1/crm/inbound/enquiries (a lead is an enquiry with a known intent). */
	leads: {
		list: (p: LeadListParams): Promise<LeadListResponse> => backend.listLeads(p),
		get: (id: number): Promise<LeadDetail> => backend.getLead(id),
		create: (body: LeadCreate) => backend.createLead(body),
		/** Open a Vitevue lease as the agency's shared lead for its unit (created the first time). */
		openVitevue: (leaseId: string) => backend.openVitevueLead(leaseId),
		patch: (id: number, body: LeadPatch) => backend.patchLead(id, body),
		/** Move to a stage with what that stage needs (status + a note or contact activity). */
		moveStage: (id: number, body: LeadStageMove) => backend.moveLeadStage(id, body),
		uploadDocument: (_id: number, _file: File, _docType: string) =>
			notOnBackend<Written<LeadDetail>>('Lead documents'),
		events: (id: number): Promise<LeadEvent[]> => backend.leadEvents(id),
		undoLast: (_id: number, _eventId?: number) =>
			notOnBackend<{ data: LeadDetail; undone: string }>('Undo'),
		addNote: (id: number, text: string) => backend.addLeadNote(id, text),
		logCall: (id: number, outcome?: string) => backend.logLeadCall(id, outcome),
		/** Books the viewing on the signed-in agent's calendar (and Google, when connected). */
		bookViewing: async (
			id: number,
			body: { date: string; time: string; listing_id: string | null; note: string }
		) => done(await backend.bookCalendarViewing(id, body)),
		/** The backend has no over-budget or after-move options; both are ignored. */
		matches: (id: number, _o: MatchOptions = {}): Promise<LeadMatches> => backend.leadMatches(id),
		refreshMatches: (id: number) => backend.refreshLeadMatches(id),
		/** Pursue a match (again to stop): "Match pursued" on both records + the next action. */
		pursue: (_id: number, _key: string) => notOnBackend<Written<PursueResult>>('Pursue'),
		shortlist: (id: number, key: string) => backend.shortlistMatch(id, key),
		renewalCall: (_id: number, _key: string) =>
			notOnBackend<Written<CalendarEvent>>('Planning a renewal call'),
		/** Ask a colleague about their listing, lead or allocation (logged; nothing goes to a client). */
		ask: (_id: number, _key: string) =>
			notOnBackend<Written<{ asked: string }>>('Asking a colleague'),
		conversation: async (_id: number): Promise<ConversationMessage[]> => [],
		createListing: (_id: number, _body: ListingCreate) =>
			notOnBackend<Written<ListingCreateResult>>('A listing from a lead')
	},

	/** Backend: /api/v1/crm/area-preferences, /renewal-areas and /renewal-leads (My areas). */
	feed: {
		summary: (): Promise<FeedSummary> => backend.feedSummary(),
		areas: (): Promise<FeedArea[]> => backend.feedAreas(),
		preferences: (): Promise<FeedPreferences> => backend.getFeedPreferences(),
		setPreferences: (p: FeedPreferences): Promise<Written<FeedPreferences>> =>
			backend.setFeedPreferences(p)
	},

	inbox: {
		/** Backend: /api/v1/crm/inbound/enquiries. Read only until the handout system exists. */
		list: (filter: InboxFilter, days?: number): Promise<InboxResponse> =>
			backend.listInbox(filter, days),
		/** A recently sold owner → a possible buyer lead (preferences filled in by the agent). */
		approve: (id: string) => backend.approveRecentSeller(Number(id)),
		ask: (_id: string) => notOnBackend<Written<InboxItem>>('Asking for an enquiry'),
		withdraw: (_id: string) => notOnBackend<Written<InboxItem>>('Withdrawing a request'),
		release: (_id: string) => notOnBackend<Written<InboxItem>>('Releasing an enquiry'),
		dismiss: (_id: string) => notOnBackend<Written<InboxItem>>('Dismissing an enquiry'),
		restore: (_id: string) => notOnBackend<Written<InboxItem>>('Restoring an enquiry')
	},

	settings: {
		handout: () => notOnBackend<HandoutSettings>('The lead handout setting'),
		setHandout: (_mode: HandoutMode) =>
			notOnBackend<Written<HandoutSettings>>('The lead handout setting')
	},

	matches: {
		clients: (): Promise<MatchClients> => backend.matchClients(),
		/** Watch a unit whose owner is not on your file (unit events). */
		watchUnit: (_key: string) => notOnBackend<Written<{ on: boolean }>>('Watching a unit')
	},

	deals: {
		stages: async (): Promise<DealStages> => DEAL_STAGES,
		/** Deals on leads, scoped like leads (own / teams / organization). */
		list: (tab: DealTab, dealType: DealType | '' = ''): Promise<DealListResponse> =>
			backend.listDeals(tab, dealType),
		get: (id: string): Promise<DealDetail> => backend.getDeal(id),
		check: (_id: string, _key: string, _done: boolean) =>
			notOnBackend<Written<DealDetail>>('The deal checklist'),
		commissionPreview: (_id: string, _body: CommissionPatch) =>
			notOnBackend<CommissionAmounts>('Commission'),
		create: (body: DealCreate) => backend.createDeal(body),
		/** One step on or back; completing the last step closes the deal as won. */
		move: (id: string, direction: 'next' | 'back', expectedStageIndex: number) =>
			backend.moveDeal(id, direction, expectedStageIndex),
		patch: (id: string, body: { dld_transaction_id?: string }) => backend.updateDeal(id, body),
		close: (id: string, outcome: 'lost' | 'reopen', reason?: string) =>
			backend.closeDeal(id, outcome, reason),
		/** Per agent overseen: open deals, value, stages and origins. */
		oversight: backend.dealOversight,
		upload: (_id: string, _file: File, _docType?: string | null) =>
			notOnBackend<Written<DocumentUploadResult>>('Deal documents'),
		removeDocument: (_id: string, _docId: number) =>
			notOnBackend<Written<{ removed: string }>>('Deal documents'),
		requestDocuments: (_id: string, _docTypes: string[]) =>
			notOnBackend<{ requested: number }>('Requesting documents'),
		commission: (_id: string, _body: CommissionPatch) =>
			notOnBackend<Written<DealDetail>>('Commission'),
		invoice: (_id: string) =>
			notOnBackend<Written<DealDetail> & { invoice: { amount_aed: number; vat_aed: number } }>(
				'Invoicing'
			),
		form: (_id: string, _code: string) => notOnBackend<FormPreview>('Deal forms'),
		compliance: (_id: string, _body: { due_diligence: 'complete' | 'pending' }) =>
			notOnBackend<Written<DealDetail>>('Compliance'),
		screening: (_id: string) => notOnBackend<{ status: string }>('Screening'),
		goaml: (_id: string) => notOnBackend<{ status: string }>('goAML')
	},

	companyListings: {
		selectSource: backend.selectCompanyListingSource,
		clearSource: backend.clearCompanyListingSource
	},

	/** Company inventory from the Property Finder broker selected by the organization owner. */
	listings: {
		list: async (
			scope: ListingScope,
			status?: ListingStatus,
			limit = 100,
			offset = 0,
			companyAgent?: CompanyListingFilter
		): Promise<ListingListResponse> =>
			scope === 'company'
				? backend.listCompanyListings(status, limit, offset, companyAgent)
				: { items: [], counts: { live: 0, pocket: 0, expired: 0 } },
		/** Company listings (PF-<id>) come from Property Finder; other listings aren't on the backend yet. */
		get: (id: string): Promise<ListingDetail> => {
			const key = backend.listingKeyOf(id)
			return key ? backend.getCompanyListing(key) : notOnBackend<ListingDetail>('Listings')
		},
		create: (_body: ListingCreate) =>
			notOnBackend<Written<ListingCreateResult>>('Creating a listing'),
		addPermit: (_id: string, _body: { number: string; expires: string }) =>
			notOnBackend<Written<ListingDetail>>('Permits'),
		publish: (_id: string) => notOnBackend<Written<ListingDetail>>('Publishing a listing'),
		unpublish: (_id: string) => notOnBackend<Written<ListingDetail>>('Unpublishing a listing'),
		relist: (_id: string) =>
			notOnBackend<Written<ListingDetail> & { message: string | null }>('Relisting'),
		upload: (_id: string, _file: File, _docType: string) =>
			notOnBackend<Written<ListingDetail>>('Listing documents'),
		send: (_id: string, _leadIds: number[]) =>
			notOnBackend<Written<{ sent: number }>>('Sending a listing')
	},

	/** Generated listing documents: private PDFs made from a managed listing's saved details. */
	documents: {
		info: backend.getDocumentInfo,
		saveInfo: backend.saveDocumentInfo,
		generate: backend.generateDocument,
		list: backend.listDocuments,
		get: backend.getDocument,
		download: backend.downloadDocument,
		preview: backend.previewDocument
	},

	/** Shareable property collections (managed listings shared by a public link). */
	collections: {
		list: backend.listCollections,
		get: backend.getCollection,
		create: backend.createCollection,
		update: backend.updateCollection,
		remove: backend.deleteCollection,
		addItem: backend.addCollectionItem,
		removeItem: backend.removeCollectionItem,
		shareLink: backend.getCollectionShareLink,
		rotateLink: backend.rotateCollectionShareLink
	},

	portfolio: {
		get: async (): Promise<PortfolioResponse> => ({
			clients: [],
			totals: {
				sales: 0,
				sales_value_aed: 0,
				lets: 0,
				lets_value_aed: 0,
				commission_aed: 0,
				clients: 0
			}
		}),
		checkIn: (_client: string) => notOnBackend<{ sent: boolean }>('Client check-ins')
	},

	/** Backend: /api/v1/crm/dashboard (every lease), /leads/{id} (history), /workspaces/{id} (owner). */
	renewals: {
		list: (p: RenewalListParams, signal?: AbortSignal): Promise<RenewalListResponse> =>
			backend.listRenewals(p, signal),
		get: (id: string): Promise<RenewalDetail> => backend.getRenewal(id),
		/** A manager issues selected units to agents as outbound leads. */
		issue: (leaseIds: string[], assignment: ImportAssignment) =>
			backend.issueRenewals(leaseIds, assignment),
		saveOwner: (id: string, owner: { name: string; phone: string; email: string }) =>
			backend.saveRenewalOwner(id, owner),
		/** Starting a renewal opens a rent deal; deals are not stored yet. */
		start: (_id: string) => notOnBackend<Written<RenewalDetail>>('Starting a renewal')
	},

	/** Backend: /api/v1/listings (Property Finder listings with a comparable-sales estimate). */
	market: {
		list: (): Promise<MarketListing[]> => backend.listMarket(),
		get: (id: string): Promise<MarketListingDetail> => backend.getMarket(id),
		watch: (_id: string, _watch: boolean) => notOnBackend<Written<MarketListing>>('The watchlist'),
		send: (_id: string, _leadIds: number[]) =>
			notOnBackend<Written<{ sent: number }>>('Sending a portal listing')
	},

	/** Backend: /api/v1/crm/owner-registry and /owner-workspaces (the agency's imported owner file). */
	owners: {
		/** A manager issues owners from a processed owner sheet to agents as outbound leads. */
		issue: backend.issueOwners,
		list: (p: OwnerListParams): Promise<OwnerListResponse> => backend.listOwners(p),
		get: (id: string): Promise<OwnerDetail> => backend.getOwner(id),
		history: (id: string, p: OwnerHistoryParams = {}): Promise<OwnerHistory> =>
			backend.getOwnerHistory(id, p),
		historySummary: (importId?: number): Promise<OwnerHistorySummary> =>
			backend.getOwnerHistorySummary(importId),
		createLead: (_id: string, _body: OwnerLeadCreate) =>
			notOnBackend<Written<LeadDetail>>('A lead from an owner'),
		create: (_body: { name: string; units: string[] }) =>
			notOnBackend<Written<OwnerRow>>('Adding an owner by hand'),
		addNote: (id: string, text: string) => backend.addOwnerNote(id, text),
		/** Add record: a documented prior transaction (sale, tenancy, listing agreement). */
		addRecord: (_id: string, _body: OwnerRecordCreate) =>
			notOnBackend<Written<OwnerRow>>('Adding a prior deal record'),
		report: (_id: string) => notOnBackend<OwnerReport>('The owner report'),
		sendReport: (_id: string) => notOnBackend<Written<OwnerRow>>('Sending the owner report'),
		sendMarketUpdate: (_id: string) => notOnBackend<Written<OwnerRow>>('Sending a market update')
	},

	/** Backend: /api/v1/crm/inbound/imports (leads) and /contact-imports (owners). */
	imports: {
		list: (): Promise<ImportRequest[]> => backend.listImports(),
		/** The backend reads a leads file and picks the columns. */
		preview: (file: File): Promise<ImportPreview> => backend.previewImport(file),
		/** Import leads; `assignment` says who handles them. The endpoint takes no areas. */
		create: (file: File, _areas: string, assignment: ImportAssignment) =>
			backend.createImport(file, assignment),
		/** An owners file is read in the browser; the backend only says which field each column feeds. */
		previewOwners: (file: File): Promise<OwnerFilePreview> => backend.previewOwnerFile(file),
		/** Upload, match against DLD and save an owners file (/contact-imports). */
		importOwners: (file: File, name: string): Promise<Written<OwnerImportResult>> =>
			backend.importOwnerFile(file, name),
		/** An agent's owner file, held until their manager approves it (/contact-import-requests). */
		requestOwners: backend.requestOwnerImport,
		ownerRequests: backend.ownerImportRequests,
		decideOwnerRequest: backend.decideOwnerImport,
		/** Owner files uploaded by the organization, newest first. */
		ownerHistory: (): Promise<OwnerImport[]> => backend.listOwnerImports(),
		/** Owner files with counts, sheet mappings and checks (dashboard and report). */
		ownerDetails: (): Promise<OwnerImportDetail[]> => backend.listOwnerImportDetails(),
		/** One page of an owner file's kept rows. */
		ownerRows: (listId: number, p: OwnerImportRowsParams): Promise<OwnerImportRows> =>
			backend.listOwnerImportRows(listId, p),
		/** One page of the rows an owner file did not keep, with the reason. */
		ownerDropped: (importId: number, p: OwnerDroppedRowsParams): Promise<OwnerDroppedRows> =>
			backend.listOwnerImportDropped(importId, p),
		/** One page of an owner file's distinct properties, with their rows. */
		ownerProperties: (importId: number, p: OwnerPropertyParams): Promise<OwnerProperties> =>
			backend.listOwnerImportProperties(importId, p),
		/** Rename an owner file and its saved list. */
		renameOwners: (id: number, name: string): Promise<Written<null>> =>
			backend.renameOwnerImport(id, name),
		/** Delete an owner file with its saved list and claims. No undo. */
		removeOwners: (id: number): Promise<Written<null>> => backend.deleteOwnerImport(id)
	},

	/** The signed-in user's own calendar; pushed to Google Calendar when connected. */
	events: {
		list: (from: string, to: string): Promise<CalendarEvent[]> =>
			backend.listCalendarEvents(from, to),
		get: (id: number) => backend.getCalendarEvent(id),
		create: async (body: EventCreate) => done(await backend.createCalendarEvent(body)),
		/** Full edit; pushed to Google Calendar when connected. */
		update: async (id: number, body: EventCreate) =>
			done(await backend.updateCalendarEvent(id, body)),
		done: async (id: number) => done(await backend.completeCalendarEvent(id)),
		/** Reschedule: keeps the event's length; the earlier slot is kept as history. */
		reschedule: async (id: number, date: string, time: string | null) =>
			done(await backend.moveCalendarEvent(id, date, time)),
		/** Already gone (deleted in another tab or by another user) counts as deleted. */
		remove: async (id: number) => {
			try {
				await backend.deleteCalendarEvent(id)
			} catch (e) {
				if (!(e instanceof ApiError && e.status === 404)) throw e
			}
			return done({ deleted: String(id) })
		},
		side: async (): Promise<CalendarSide> => ({ overdue: [], deadlines: [] })
	},

	googleCalendar: {
		status: backend.googleCalendarStatus,
		connect: backend.connectGoogleCalendar,
		complete: backend.completeGoogleCalendar,
		disconnect: backend.disconnectGoogleCalendar
	},

	/** Connectors › Email: the Brevo pipeline (Leads, Tracking, Templates, Inbox). Every list
	 * follows lead assignment on the server: an agent sees mail about leads they may see. */
	email: {
		status: backend.emailStatus,
		leads: (p: EmailLeadParams = {}) => backend.emailLeads(p),
		send: (body: { enquiry_ids: number[]; subject: string; body: string }) =>
			backend.sendEmails(body),
		sends: (status: EmailSendStatus | '' = '') => backend.emailSends(status),
		sync: backend.syncEmailEvents,
		removeSend: (id: number) => backend.deleteEmailSend(id),
		templates: backend.emailTemplates,
		inbound: backend.emailInbound,
		thread: (enquiryId: number) => backend.emailThread(enquiryId),
		createTemplate: (body: EmailTemplateInput) => backend.createEmailTemplate(body),
		updateTemplate: (id: number, body: EmailTemplateInput) => backend.updateEmailTemplate(id, body),
		removeTemplate: (id: number) => backend.deleteEmailTemplate(id)
	},

	search: (q: string): Promise<SearchResults> => backend.search(q),

	notifications: {
		list: async (): Promise<Notification[]> => [],
		read: async (_ids?: number[]): Promise<Written<{ unread: number }>> => ({
			data: { unread: 0 },
			undo_token: null
		})
	},

	connections: async (): Promise<Connection[]> => [],

	/** Backend: /api/v1/crm/assignment, /inbound/assignments and /routing/rules. */
	assignment: {
		/** Capabilities and assignable teams, decided by the server (not by a display role). */
		scope: backend.assignmentScope,
		assign: backend.assignLeads,
		/** Put leads in a team's shared pool; the first agent to log contact takes each one. */
		release: backend.releaseToPool,
		history: backend.leadAssignments,
		workload: backend.teamWorkload,
		/** Per-person lead analytics for managers (response and claim times, contacts). */
		analytics: backend.teamAnalytics,
		agentAnalytics: backend.agentAnalytics,
		/** The languages a person speaks, as their manager records them; never inferred. */
		setLanguages: backend.setAgentLanguages
	},
	routing: {
		list: backend.routingRules,
		create: backend.createRoutingRule,
		update: backend.updateRoutingRule,
		remove: backend.deleteRoutingRule,
		reorder: backend.reorderRoutingRules
	}
}

export type CrmApi = typeof liveCrm

// Explicit opt-in for the isolated pilot; the normal API remains the default.
export const crmPresentationMode = env.PUBLIC_CRM_PRESENTATION_MODE === 'true'
export const crm: CrmApi = crmPresentationMode
	? createPresentationCrm(liveCrm, backend.localToday())
	: liveCrm
