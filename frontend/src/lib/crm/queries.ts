import { keepPreviousData } from '@tanstack/svelte-query'
import { crm } from './api'
import type {
	CompanyListingFilter,
	DealTab,
	DealType,
	EmailLeadParams,
	EmailSendStatus,
	InboxFilter,
	LeadListParams,
	ListingScope,
	ListingStatus,
	MatchOptions,
	OwnerDroppedRowsParams,
	OwnerImportDetail,
	OwnerImportRowsParams,
	OwnerListParams,
	OwnerPropertyParams,
	RenewalListParams
} from './api/types'

/** Every CRM Beta key starts with 'crm', so a write can refresh the whole CRM at once. */
export const crmKeys = {
	all: ['crm'] as const,
	me: () => [...crmKeys.all, 'me'] as const,
	counts: () => [...crmKeys.all, 'counts'] as const,
	home: (day: string) => [...crmKeys.all, 'home', day] as const,
	leads: (p: LeadListParams) => [...crmKeys.all, 'leads', p] as const,
	lead: (id: number) => [...crmKeys.all, 'lead', id] as const,
	leadEvents: (id: number) => [...crmKeys.all, 'lead', id, 'events'] as const,
	leadMatches: (id: number, o: MatchOptions = {}) =>
		[...crmKeys.all, 'lead', id, 'matches', Boolean(o.over ?? true), Boolean(o.after)] as const,
	matchClients: () => [...crmKeys.all, 'matches', 'clients'] as const,
	inbox: (filter: InboxFilter, days = 30) => [...crmKeys.all, 'inbox', filter, days] as const,
	handout: () => [...crmKeys.all, 'settings', 'handout'] as const,
	connectors: () => [...crmKeys.all, 'settings', 'connectors'] as const,
	emailStatus: () => [...crmKeys.all, 'email', 'status'] as const,
	emailLeads: (p: EmailLeadParams) => [...crmKeys.all, 'email', 'leads', p] as const,
	emailSends: (status: EmailSendStatus | '') => [...crmKeys.all, 'email', 'sends', status] as const,
	emailTemplates: () => [...crmKeys.all, 'email', 'templates'] as const,
	emailInbound: () => [...crmKeys.all, 'email', 'inbound'] as const,
	emailThread: (id: number) => [...crmKeys.all, 'lead', id, 'email-thread'] as const,
	whatsappStatus: () => [...crmKeys.all, 'whatsapp', 'status'] as const,
	whatsappChats: () => [...crmKeys.all, 'whatsapp', 'chats'] as const,
	whatsappTemplates: () => [...crmKeys.all, 'whatsapp', 'templates'] as const,
	whatsappThread: (id: number) => [...crmKeys.all, 'lead', id, 'whatsapp-thread'] as const,
	whatsappChat: (waId: string) => [...crmKeys.all, 'whatsapp', 'chat', waId] as const,
	whatsappAudience: (p: { search: string; intent: string }) =>
		[...crmKeys.all, 'whatsapp', 'audience', p] as const,
	whatsappCampaigns: () => [...crmKeys.all, 'whatsapp', 'campaigns'] as const,
	whatsappNumbers: () => [...crmKeys.all, 'whatsapp', 'numbers'] as const,
	whatsappMetaNumbers: () => [...crmKeys.all, 'whatsapp', 'meta-numbers'] as const,
	whatsappCampaign: (id: number) => [...crmKeys.all, 'whatsapp', 'campaign', id] as const,
	whatsappCampaignChats: () => [...crmKeys.all, 'whatsapp', 'campaign-chats'] as const,
	whatsappCampaignChat: (waId: string) =>
		[...crmKeys.all, 'whatsapp', 'campaign-chat', waId] as const,
	leadConversation: (id: number) => [...crmKeys.all, 'lead', id, 'conversation'] as const,
	feedSummary: () => [...crmKeys.all, 'feed', 'summary'] as const,
	feedAreas: () => [...crmKeys.all, 'feed', 'areas'] as const,
	feedPreferences: () => [...crmKeys.all, 'feed', 'preferences'] as const,
	dealStages: () => [...crmKeys.all, 'deal-stages'] as const,
	deals: (tab: DealTab, type: DealType | '' = '') => [...crmKeys.all, 'deals', tab, type] as const,
	deal: (id: string) => [...crmKeys.all, 'deal', id] as const,
	dealForm: (id: string, code: string) => [...crmKeys.all, 'deal', id, 'form', code] as const,
	listings: (
		scope: ListingScope,
		status?: ListingStatus,
		limit = 100,
		offset = 0,
		companyAgent?: CompanyListingFilter
	) => [...crmKeys.all, 'listings', scope, status ?? 'all', limit, offset, companyAgent] as const,
	listing: (id: string) => [...crmKeys.all, 'listing', id] as const,
	portfolio: () => [...crmKeys.all, 'portfolio'] as const,
	renewals: (p: RenewalListParams) => [...crmKeys.all, 'renewals', p] as const,
	renewal: (id: string) => [...crmKeys.all, 'renewal', id] as const,
	market: () => [...crmKeys.all, 'market'] as const,
	marketListing: (id: string) => [...crmKeys.all, 'market', id] as const,
	owners: (p: OwnerListParams) => [...crmKeys.all, 'owners', p] as const,
	owner: (id: string) => [...crmKeys.all, 'owner', id] as const,
	ownerReport: (id: string) => [...crmKeys.all, 'owner', id, 'report'] as const,
	imports: () => [...crmKeys.all, 'imports'] as const,
	ownerImports: () => [...crmKeys.all, 'imports', 'owners'] as const,
	ownerImportDetails: () => [...crmKeys.all, 'imports', 'owners', 'details'] as const,
	ownerImportRows: (listId: number, p: OwnerImportRowsParams) =>
		[...crmKeys.all, 'imports', 'owners', 'rows', listId, p] as const,
	ownerImportDropped: (importId: number, p: OwnerDroppedRowsParams) =>
		[...crmKeys.all, 'imports', 'owners', 'dropped', importId, p] as const,
	ownerImportProperties: (importId: number, p: OwnerPropertyParams) =>
		[...crmKeys.all, 'imports', 'owners', 'properties', importId, p] as const,
	events: (from: string, to: string) => [...crmKeys.all, 'events', from, to] as const,
	event: (id: number) => [...crmKeys.all, 'event', id] as const,
	calendarSide: () => [...crmKeys.all, 'calendar-side'] as const,
	googleCalendar: () => [...crmKeys.all, 'google-calendar'] as const,
	search: (q: string) => [...crmKeys.all, 'search', q] as const,
	notifications: () => [...crmKeys.all, 'notifications'] as const,
	connections: () => [...crmKeys.all, 'connections'] as const
}

/** Query option factories, same pattern as the main app's `$lib/queries/*`. */
export const crmQueries = {
	me: () => ({ queryKey: crmKeys.me(), queryFn: crm.me, staleTime: Number.POSITIVE_INFINITY }),
	counts: () => ({ queryKey: crmKeys.counts(), queryFn: crm.counts }),
	home: (day: string) => ({
		queryKey: crmKeys.home(day),
		queryFn: () => crm.home(day),
		placeholderData: keepPreviousData
	}),
	leads: (p: LeadListParams) => ({
		queryKey: crmKeys.leads(p),
		queryFn: () => crm.leads.list(p),
		placeholderData: keepPreviousData
	}),
	lead: (id: number) => ({ queryKey: crmKeys.lead(id), queryFn: () => crm.leads.get(id) }),
	leadEvents: (id: number) => ({
		queryKey: crmKeys.leadEvents(id),
		queryFn: () => crm.leads.events(id)
	}),
	leadMatches: (id: number, o: MatchOptions = {}) => ({
		queryKey: crmKeys.leadMatches(id, o),
		queryFn: () => crm.leads.matches(id, o),
		placeholderData: keepPreviousData
	}),
	matchClients: () => ({ queryKey: crmKeys.matchClients(), queryFn: crm.matches.clients }),
	inbox: (filter: InboxFilter, days = 30) => ({
		queryKey: crmKeys.inbox(filter, days),
		queryFn: () => crm.inbox.list(filter, days),
		placeholderData: keepPreviousData
	}),
	handout: () => ({ queryKey: crmKeys.handout(), queryFn: crm.settings.handout }),
	connectors: () => ({ queryKey: crmKeys.connectors(), queryFn: crm.connectors.list }),
	emailStatus: () => ({ queryKey: crmKeys.emailStatus(), queryFn: crm.email.status }),
	emailLeads: (p: EmailLeadParams = {}) => ({
		queryKey: crmKeys.emailLeads(p),
		queryFn: () => crm.email.leads(p),
		placeholderData: keepPreviousData
	}),
	emailTemplates: () => ({ queryKey: crmKeys.emailTemplates(), queryFn: crm.email.templates }),
	emailInbound: () => ({ queryKey: crmKeys.emailInbound(), queryFn: crm.email.inbound }),
	emailThread: (id: number) => ({
		queryKey: crmKeys.emailThread(id),
		queryFn: () => crm.email.thread(id)
	}),
	emailSends: (status: EmailSendStatus | '') => ({
		queryKey: crmKeys.emailSends(status),
		queryFn: () => crm.email.sends(status),
		placeholderData: keepPreviousData
	}),
	whatsappStatus: () => ({ queryKey: crmKeys.whatsappStatus(), queryFn: crm.whatsapp.status }),
	whatsappChats: () => ({ queryKey: crmKeys.whatsappChats(), queryFn: crm.whatsapp.chats }),
	whatsappTemplates: () => ({
		queryKey: crmKeys.whatsappTemplates(),
		queryFn: crm.whatsapp.templates
	}),
	whatsappThread: (id: number) => ({
		queryKey: crmKeys.whatsappThread(id),
		queryFn: () => crm.whatsapp.thread(id)
	}),
	whatsappChat: (waId: string) => ({
		queryKey: crmKeys.whatsappChat(waId),
		queryFn: () => crm.whatsapp.chat(waId)
	}),
	whatsappAudience: (p: { search: string; intent: string }) => ({
		queryKey: crmKeys.whatsappAudience(p),
		queryFn: () => crm.whatsapp.campaigns.audience(p)
	}),
	/** Refreshes while a campaign is still sending, so its counts move on their own. */
	whatsappCampaigns: () => ({
		queryKey: crmKeys.whatsappCampaigns(),
		queryFn: crm.whatsapp.campaigns.list,
		refetchInterval: (q: { state: { data?: { status: string }[] } }) =>
			q.state.data?.some((c) => c.status === 'sending') ? 5000 : false
	}),
	whatsappCampaign: (id: number) => ({
		queryKey: crmKeys.whatsappCampaign(id),
		queryFn: () => crm.whatsapp.campaigns.get(id),
		refetchInterval: (q: { state: { data?: { status: string } } }) =>
			q.state.data?.status === 'sending' ? 5000 : false
	}),
	whatsappNumbers: () => ({
		queryKey: crmKeys.whatsappNumbers(),
		queryFn: crm.whatsapp.numbers.list
	}),
	whatsappMetaNumbers: () => ({
		queryKey: crmKeys.whatsappMetaNumbers(),
		queryFn: crm.whatsapp.numbers.meta
	}),
	whatsappCampaignChats: () => ({
		queryKey: crmKeys.whatsappCampaignChats(),
		queryFn: crm.whatsapp.campaigns.chats
	}),
	whatsappCampaignChat: (waId: string) => ({
		queryKey: crmKeys.whatsappCampaignChat(waId),
		queryFn: () => crm.whatsapp.campaigns.chat(waId)
	}),
	leadConversation: (id: number) => ({
		queryKey: crmKeys.leadConversation(id),
		queryFn: () => crm.leads.conversation(id)
	}),
	feedSummary: () => ({ queryKey: crmKeys.feedSummary(), queryFn: crm.feed.summary }),
	feedAreas: () => ({ queryKey: crmKeys.feedAreas(), queryFn: crm.feed.areas }),
	feedPreferences: () => ({ queryKey: crmKeys.feedPreferences(), queryFn: crm.feed.preferences }),
	dealStages: () => ({
		queryKey: crmKeys.dealStages(),
		queryFn: crm.deals.stages,
		staleTime: Number.POSITIVE_INFINITY
	}),
	deals: (tab: DealTab, type: DealType | '' = '') => ({
		queryKey: crmKeys.deals(tab, type),
		queryFn: () => crm.deals.list(tab, type),
		placeholderData: keepPreviousData
	}),
	deal: (id: string) => ({ queryKey: crmKeys.deal(id), queryFn: () => crm.deals.get(id) }),
	dealForm: (id: string, code: string) => ({
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
		queryKey: crmKeys.listings(scope, status, limit, offset, companyAgent),
		queryFn: () => crm.listings.list(scope, status, limit, offset, companyAgent),
		placeholderData: keepPreviousData
	}),
	listing: (id: string) => ({ queryKey: crmKeys.listing(id), queryFn: () => crm.listings.get(id) }),
	portfolio: () => ({ queryKey: crmKeys.portfolio(), queryFn: crm.portfolio.get }),
	renewals: (p: RenewalListParams) => ({
		queryKey: crmKeys.renewals(p),
		// Passing the signal lets a filter change abandon the previous request.
		queryFn: ({ signal }: { signal: AbortSignal }) => crm.renewals.list(p, signal),
		placeholderData: keepPreviousData
	}),
	renewal: (id: string) => ({ queryKey: crmKeys.renewal(id), queryFn: () => crm.renewals.get(id) }),
	market: () => ({ queryKey: crmKeys.market(), queryFn: crm.market.list }),
	marketListing: (id: string) => ({
		queryKey: crmKeys.marketListing(id),
		queryFn: () => crm.market.get(id)
	}),
	owners: (p: OwnerListParams) => ({
		queryKey: crmKeys.owners(p),
		queryFn: () => crm.owners.list(p),
		placeholderData: keepPreviousData
	}),
	owner: (id: string) => ({ queryKey: crmKeys.owner(id), queryFn: () => crm.owners.get(id) }),
	ownerReport: (id: string) => ({
		queryKey: crmKeys.ownerReport(id),
		queryFn: () => crm.owners.report(id)
	}),
	imports: () => ({ queryKey: crmKeys.imports(), queryFn: crm.imports.list }),
	ownerImports: () => ({ queryKey: crmKeys.ownerImports(), queryFn: crm.imports.ownerHistory }),
	/** Re-checks every 5 s while an import is still processing, so its counts appear by themselves. */
	ownerImportDetails: () => ({
		queryKey: crmKeys.ownerImportDetails(),
		queryFn: crm.imports.ownerDetails,
		refetchInterval: (q: { state: { data?: OwnerImportDetail[] } }) =>
			q.state.data?.some((i) => i.status === 'processing') ? 5000 : false
	}),
	ownerImportRows: (listId: number, p: OwnerImportRowsParams) => ({
		queryKey: crmKeys.ownerImportRows(listId, p),
		queryFn: () => crm.imports.ownerRows(listId, p),
		placeholderData: keepPreviousData
	}),
	ownerImportDropped: (importId: number, p: OwnerDroppedRowsParams) => ({
		queryKey: crmKeys.ownerImportDropped(importId, p),
		queryFn: () => crm.imports.ownerDropped(importId, p),
		placeholderData: keepPreviousData
	}),
	ownerImportProperties: (importId: number, p: OwnerPropertyParams) => ({
		queryKey: crmKeys.ownerImportProperties(importId, p),
		queryFn: () => crm.imports.ownerProperties(importId, p),
		placeholderData: keepPreviousData
	}),
	events: (from: string, to: string) => ({
		queryKey: crmKeys.events(from, to),
		queryFn: () => crm.events.list(from, to),
		placeholderData: keepPreviousData
	}),
	event: (id: number) => ({ queryKey: crmKeys.event(id), queryFn: () => crm.events.get(id) }),
	calendarSide: () => ({ queryKey: crmKeys.calendarSide(), queryFn: crm.events.side }),
	googleCalendar: () => ({
		queryKey: crmKeys.googleCalendar(),
		queryFn: crm.googleCalendar.status
	}),
	search: (q: string) => ({
		queryKey: crmKeys.search(q),
		queryFn: () => crm.search(q),
		enabled: q.length >= 2,
		placeholderData: keepPreviousData
	}),
	notifications: () => ({ queryKey: crmKeys.notifications(), queryFn: crm.notifications.list }),
	connections: () => ({ queryKey: crmKeys.connections(), queryFn: crm.connections })
}
