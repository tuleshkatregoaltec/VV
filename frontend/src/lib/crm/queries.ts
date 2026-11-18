import { keepPreviousData, type QueryClient } from '@tanstack/svelte-query'
import type { OwnerImportRequestResponse } from '$lib/api/generated/hey-api/types.gen'
import { getTeams } from '$lib/api/organization'
import { getQueryClient } from '$lib/queries/client'
import type { AnalyticsDays } from './agentMetrics'
import { crm } from './api'
import type {
	CollectionListParams,
	CompanyListingFilter,
	DealTab,
	DealType,
	DocumentListParams,
	ImportRequest,
	ImportStatus,
	InboxFilter,
	LeadListParams,
	ListingScope,
	ListingStatus,
	MatchOptions,
	OwnerDroppedRowsParams,
	OwnerHistoryParams,
	OwnerImportDetail,
	OwnerImportRowsParams,
	OwnerListParams,
	OwnerPropertyParams,
	RenewalListParams,
	RenewalListResponse
} from './api/types'
import { crmIdentityKnown, crmScopeKey } from './identity.svelte'
import { importIsActive, importPollInterval } from './importStatus'
import { pendingImports, settleQueuedImports } from './stores/imports.svelte'

/** Previous rows are useful only inside the same authenticated membership. */
export function crmPreviousData<T>(
	data: T | undefined,
	previous?: { queryKey: readonly unknown[] }
): T | undefined {
	return previous && crmScopeKey().every((part, i) => previous.queryKey[i] === part)
		? data
		: undefined
}

/** Import completion refreshes worker-written records, never its own polling prefix. */
function refreshCompletedImports(
	scope: readonly unknown[],
	before: { id: string | number; status: ImportStatus }[] | undefined,
	after: { id: string | number; status: ImportStatus }[]
): void {
	if (!scope.every((part, i) => crmScopeKey()[i] === part)) return
	if (
		!before?.some(
			(job) =>
				importIsActive(job.status) &&
				after.some((next) => next.id === job.id && next.status === 'completed')
		)
	)
		return
	void getQueryClient().invalidateQueries(
		{
			queryKey: scope,
			predicate: (query) =>
				[
					'owners',
					'owner',
					'owner-history-summary',
					'leads',
					'lead',
					'counts',
					'home',
					'inbox',
					'matches',
					'search',
					'feed',
					'renewal'
				].includes(String(query.queryKey[scope.length]))
		},
		{ cancelRefetch: false }
	)
}

/** Every CRM Beta key starts with 'crm', so a write can refresh the whole CRM at once. */
export const crmKeys = {
	all: ['crm'] as const,
	me: () => [...crmScopeKey(), 'me'] as const,
	counts: () => [...crmScopeKey(), 'counts'] as const,
	home: (day: string) => [...crmScopeKey(), 'home', day] as const,
	leads: (p: LeadListParams) => [...crmScopeKey(), 'leads', p] as const,
	lead: (id: number) => [...crmScopeKey(), 'lead', id] as const,
	leadEvents: (id: number) => [...crmScopeKey(), 'lead', id, 'events'] as const,
	leadMatches: (id: number, _o: MatchOptions = {}) =>
		[...crmScopeKey(), 'lead', id, 'matches'] as const,
	matchClients: () => [...crmScopeKey(), 'matches', 'clients'] as const,
	inbox: (filter: InboxFilter, days = 30) => [...crmScopeKey(), 'inbox', filter, days] as const,
	handout: () => [...crmScopeKey(), 'settings', 'handout'] as const,
	leadConversation: (id: number) => [...crmScopeKey(), 'lead', id, 'conversation'] as const,
	feedSummary: () => [...crmScopeKey(), 'feed', 'summary'] as const,
	feedAreas: () => [...crmScopeKey(), 'feed', 'areas'] as const,
	feedPreferences: () => [...crmScopeKey(), 'feed', 'preferences'] as const,
	dealStages: () => [...crmScopeKey(), 'deal-stages'] as const,
	deals: (tab: DealTab, type: DealType | '' = '') =>
		[...crmScopeKey(), 'deals', tab, type] as const,
	deal: (id: string) => [...crmScopeKey(), 'deal', id] as const,
	dealForm: (id: string, code: string) => [...crmScopeKey(), 'deal', id, 'form', code] as const,
	listings: (
		scope: ListingScope,
		status?: ListingStatus,
		limit = 100,
		offset = 0,
		companyAgent?: CompanyListingFilter
	) => [...crmScopeKey(), 'listings', scope, status ?? 'all', limit, offset, companyAgent] as const,
	listing: (id: string) => [...crmScopeKey(), 'listing', id] as const,
	portfolio: () => [...crmScopeKey(), 'portfolio'] as const,
	renewals: (p: RenewalListParams) => [...crmScopeKey(), 'renewals', p] as const,
	renewal: (id: string) => [...crmScopeKey(), 'renewal', id] as const,
	market: () => [...crmScopeKey(), 'market'] as const,
	marketListing: (id: string) => [...crmScopeKey(), 'market', id] as const,
	owners: (p: OwnerListParams) => [...crmScopeKey(), 'owners', p] as const,
	owner: (id: string) => [...crmScopeKey(), 'owner', id] as const,
	ownerHistory: (id: string, p: OwnerHistoryParams) =>
		[...crmScopeKey(), 'owner', id, 'history', p] as const,
	ownerHistorySummary: (importId?: number) =>
		[...crmScopeKey(), 'owner-history-summary', importId ?? 'all'] as const,
	ownerReport: (id: string) => [...crmScopeKey(), 'owner', id, 'report'] as const,
	imports: () => [...crmScopeKey(), 'imports'] as const,
	ownerImports: () => [...crmScopeKey(), 'imports', 'owners'] as const,
	ownerImportRequests: () => [...crmScopeKey(), 'imports', 'owners', 'requests'] as const,
	ownerImportDetails: () => [...crmScopeKey(), 'imports', 'owners', 'details'] as const,
	documentInfo: (listingKey: string) => [...crmScopeKey(), 'document-info', listingKey] as const,
	documentsAll: () => [...crmScopeKey(), 'documents'] as const,
	documents: (p: DocumentListParams) => [...crmScopeKey(), 'documents', p] as const,
	collectionsAll: () => [...crmScopeKey(), 'collections'] as const,
	collections: (p: CollectionListParams) => [...crmKeys.collectionsAll(), 'list', p] as const,
	collection: (id: string) => [...crmKeys.collectionsAll(), 'detail', id] as const,
	ownerImportRows: (listId: number, p: OwnerImportRowsParams) =>
		[...crmScopeKey(), 'imports', 'owners', 'rows', listId, p] as const,
	ownerImportDropped: (importId: number, p: OwnerDroppedRowsParams) =>
		[...crmScopeKey(), 'imports', 'owners', 'dropped', importId, p] as const,
	ownerImportProperties: (importId: number, p: OwnerPropertyParams) =>
		[...crmScopeKey(), 'imports', 'owners', 'properties', importId, p] as const,
	events: (from: string, to: string) => [...crmScopeKey(), 'events', from, to] as const,
	event: (id: number) => [...crmScopeKey(), 'event', id] as const,
	calendarSide: () => [...crmScopeKey(), 'calendar-side'] as const,
	search: (q: string) => [...crmScopeKey(), 'search', q] as const,
	notifications: () => [...crmScopeKey(), 'notifications'] as const,
	connections: () => [...crmScopeKey(), 'connections'] as const,
	assignmentScope: () => [...crmScopeKey(), 'assignment', 'scope'] as const,
	leadAssignments: (id: number) => [...crmScopeKey(), 'lead', id, 'assignments'] as const,
	routingRules: () => [...crmScopeKey(), 'routing', 'rules'] as const,
	workload: () => [...crmScopeKey(), 'assignment', 'workload'] as const,
	analytics: (days: AnalyticsDays) => [...crmScopeKey(), 'assignment', 'analytics', days] as const,
	agentAnalytics: (userId: string, days: AnalyticsDays) =>
		[...crmScopeKey(), 'assignment', 'analytics', userId, days] as const,
	teams: () => [...crmScopeKey(), 'teams'] as const
}

/** Query option factories, same pattern as the main app's `$lib/queries/*`. */
export const crmQueries = {
	me: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.me(),
		queryFn: crm.me,
		staleTime: Number.POSITIVE_INFINITY
	}),
	counts: () => ({ enabled: crmIdentityKnown(), queryKey: crmKeys.counts(), queryFn: crm.counts }),
	home: (day: string) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.home(day),
		queryFn: () => crm.home(day),
		placeholderData: crmPreviousData
	}),
	leads: (p: LeadListParams) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.leads(p),
		queryFn: () => crm.leads.list(p),
		placeholderData: crmPreviousData
	}),
	lead: (id: number) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.lead(id),
		queryFn: () => crm.leads.get(id)
	}),
	leadEvents: (id: number) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.leadEvents(id),
		queryFn: () => crm.leads.events(id)
	}),
	leadMatches: (id: number, o: MatchOptions = {}) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.leadMatches(id, o),
		queryFn: () => crm.leads.matches(id, o),
		placeholderData: crmPreviousData
	}),
	matchClients: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.matchClients(),
		queryFn: crm.matches.clients
	}),
	inbox: (filter: InboxFilter, days = 30) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.inbox(filter, days),
		queryFn: () => crm.inbox.list(filter, days),
		placeholderData: crmPreviousData
	}),
	handout: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.handout(),
		queryFn: crm.settings.handout
	}),
	leadConversation: (id: number) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.leadConversation(id),
		queryFn: () => crm.leads.conversation(id)
	}),
	feedSummary: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.feedSummary(),
		queryFn: crm.feed.summary
	}),
	feedAreas: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.feedAreas(),
		queryFn: crm.feed.areas
	}),
	feedPreferences: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.feedPreferences(),
		queryFn: crm.feed.preferences
	}),
	dealStages: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.dealStages(),
		queryFn: crm.deals.stages,
		staleTime: Number.POSITIVE_INFINITY
	}),
	deals: (tab: DealTab, type: DealType | '' = '') => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.deals(tab, type),
		queryFn: () => crm.deals.list(tab, type),
		placeholderData: crmPreviousData
	}),
	deal: (id: string) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.deal(id),
		queryFn: () => crm.deals.get(id)
	}),
	dealForm: (id: string, code: string) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.dealForm(id, code),
		queryFn: () => crm.deals.form(id, code)
	}),
	listings: (
		scope: ListingScope,
		status?: ListingStatus,
		limit = 100,
		offset = 0,
		companyAgent?: CompanyListingFilter
	) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.listings(scope, status, limit, offset, companyAgent),
		queryFn: () => crm.listings.list(scope, status, limit, offset, companyAgent),
		placeholderData: crmPreviousData
	}),
	listing: (id: string) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.listing(id),
		queryFn: () => crm.listings.get(id)
	}),
	portfolio: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.portfolio(),
		queryFn: crm.portfolio.get
	}),
	documentInfo: (listingKey: string) => ({
		queryKey: crmKeys.documentInfo(listingKey),
		queryFn: () => crm.documents.info(listingKey)
	}),
	documents: (p: DocumentListParams) => ({
		queryKey: crmKeys.documents(p),
		queryFn: () => crm.documents.list(p)
	}),
	collections: (p: CollectionListParams = {}) => ({
		queryKey: crmKeys.collections(p),
		queryFn: () => crm.collections.list(p),
		placeholderData: keepPreviousData
	}),
	collection: (id: string) => ({
		queryKey: crmKeys.collection(id),
		queryFn: () => crm.collections.get(id)
	}),
	renewals: (p: RenewalListParams) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.renewals(p),
		// Passing the signal lets a filter change abandon the previous request.
		queryFn: ({ signal }: { signal: AbortSignal }) => crm.renewals.list(p, signal),
		placeholderData: crmPreviousData
	}),
	renewalsInfinite: (p: Omit<RenewalListParams, 'offset'>) => ({
		enabled: crmIdentityKnown(),
		queryKey: [...crmKeys.renewals(p), 'pages'],
		queryFn: ({ pageParam, signal }: { pageParam: number; signal: AbortSignal }) =>
			crm.renewals.list({ ...p, offset: pageParam }, signal),
		initialPageParam: 0,
		getNextPageParam: (page: RenewalListResponse) => {
			const next = page.offset + page.items.length
			return page.items.length && next < page.total ? next : undefined
		}
	}),
	renewal: (id: string) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.renewal(id),
		queryFn: () => crm.renewals.get(id)
	}),
	market: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.market(),
		queryFn: crm.market.list
	}),
	marketListing: (id: string) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.marketListing(id),
		queryFn: () => crm.market.get(id)
	}),
	owners: (p: OwnerListParams) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.owners(p),
		queryFn: () => crm.owners.list(p),
		placeholderData: crmPreviousData
	}),
	owner: (id: string) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.owner(id),
		queryFn: () => crm.owners.get(id)
	}),
	ownerHistory: (id: string, p: OwnerHistoryParams = {}) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.ownerHistory(id, p),
		queryFn: () => crm.owners.history(id, p)
	}),
	ownerHistorySummary: (importId?: number) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.ownerHistorySummary(importId),
		queryFn: () => crm.owners.historySummary(importId)
	}),
	ownerReport: (id: string) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.ownerReport(id),
		queryFn: () => crm.owners.report(id)
	}),
	imports: () => {
		const scope = crmScopeKey()
		const queryKey = crmKeys.imports()
		return {
			enabled: crmIdentityKnown(),
			queryKey,
			queryFn: async () => {
				const before = getQueryClient().getQueryData<ImportRequest[]>(queryKey)
				const after = await crm.imports.list()
				refreshCompletedImports(
					scope,
					[
						...(before?.map((job) => ({ id: job.id, status: job.jobStatus })) ?? []),
						...pendingImports.ids.map((id) => ({ id, status: 'queued' as const }))
					],
					after.map((job) => ({ id: job.id, status: job.jobStatus }))
				)
				if (scope.every((part, i) => crmScopeKey()[i] === part)) settleQueuedImports(after)
				return after
			},
			refetchInterval: (q: { state: { data?: ImportRequest[]; dataUpdateCount: number } }) =>
				importPollInterval(
					q.state.data?.some((i) => importIsActive(i.jobStatus)) ?? false,
					q.state.dataUpdateCount
				)
		}
	},
	ownerImports: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.ownerImports(),
		queryFn: crm.imports.ownerHistory
	}),
	/** Owner files waiting for approval keep updating until they are decided and processed. */
	ownerImportRequests: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.ownerImportRequests(),
		queryFn: crm.imports.ownerRequests,
		refetchInterval: (q: { state: { data?: OwnerImportRequestResponse[] } }) =>
			q.state.data?.some(
				(request) => request.status === 'queued' || request.status === 'processing'
			)
				? 5000
				: false
	}),
	/** Active durable jobs keep updating until they finish, with a capped polling backoff. */
	ownerImportDetails: () => {
		const scope = crmScopeKey()
		const queryKey = crmKeys.ownerImportDetails()
		return {
			enabled: crmIdentityKnown(),
			queryKey,
			queryFn: async () => {
				const before = getQueryClient().getQueryData<OwnerImportDetail[]>(queryKey)
				const after = await crm.imports.ownerDetails()
				refreshCompletedImports(scope, before, after)
				return after
			},
			refetchInterval: (q: { state: { data?: OwnerImportDetail[]; dataUpdateCount: number } }) =>
				importPollInterval(
					q.state.data?.some((i) => importIsActive(i.status)) ?? false,
					q.state.dataUpdateCount
				)
		}
	},
	ownerImportRows: (listId: number, p: OwnerImportRowsParams) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.ownerImportRows(listId, p),
		queryFn: () => crm.imports.ownerRows(listId, p),
		placeholderData: crmPreviousData
	}),
	ownerImportDropped: (importId: number, p: OwnerDroppedRowsParams) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.ownerImportDropped(importId, p),
		queryFn: () => crm.imports.ownerDropped(importId, p),
		placeholderData: crmPreviousData
	}),
	ownerImportProperties: (importId: number, p: OwnerPropertyParams) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.ownerImportProperties(importId, p),
		queryFn: () => crm.imports.ownerProperties(importId, p),
		placeholderData: crmPreviousData
	}),
	events: (from: string, to: string) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.events(from, to),
		queryFn: () => crm.events.list(from, to),
		placeholderData: crmPreviousData
	}),
	event: (id: number) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.event(id),
		queryFn: () => crm.events.get(id)
	}),
	calendarSide: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.calendarSide(),
		queryFn: crm.events.side
	}),
	search: (q: string) => ({
		queryKey: crmKeys.search(q),
		queryFn: () => crm.search(q),
		enabled: crmIdentityKnown() && q.length >= 2,
		placeholderData: crmPreviousData
	}),
	notifications: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.notifications(),
		queryFn: crm.notifications.list
	}),
	connections: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.connections(),
		queryFn: crm.connections
	}),
	assignmentScope: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.assignmentScope(),
		queryFn: crm.assignment.scope
	}),
	leadAssignments: (id: number) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.leadAssignments(id),
		queryFn: () => crm.assignment.history(id)
	}),
	routingRules: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.routingRules(),
		queryFn: crm.routing.list
	}),
	workload: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.workload(),
		queryFn: crm.assignment.workload
	}),
	teamAnalytics: (days: AnalyticsDays) => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.analytics(days),
		queryFn: () => crm.assignment.analytics(days)
	}),
	agentAnalytics: (userId: string, days: AnalyticsDays) => ({
		enabled: crmIdentityKnown() && Boolean(userId),
		queryKey: crmKeys.agentAnalytics(userId, days),
		queryFn: () => crm.assignment.agentAnalytics(userId, days),
		retry: false
	}),
	teams: () => ({
		enabled: crmIdentityKnown(),
		queryKey: crmKeys.teams(),
		queryFn: getTeams
	})
}

/** Refresh one collection and the list after any change to it. Call from every mutation's onSettled. */
export function invalidateCollection(qc: QueryClient, id: string) {
	return Promise.all([
		qc.invalidateQueries({ queryKey: crmKeys.collection(id) }),
		qc.invalidateQueries({ queryKey: crmKeys.collectionsAll() })
	])
}
