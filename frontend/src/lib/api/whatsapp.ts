import { client } from './client'
import type {
	ConnectionCreate,
	ConnectionResponse,
	ConnectionUpdate,
	CustomerMessageResponse,
	KnowledgeUpdate,
	PublishedListingCreate,
	PublishedListingResponse,
	PublishedListingUpdate,
	ReplyEdit,
	RevisionDecision,
	ThreadResponse
} from './generated/hey-api/types.gen'

const base = '/api/v1/whatsapp'
const id = encodeURIComponent

async function allPages<T extends { id: string }>(endpoint: string): Promise<T[]> {
	const rows = new Map<string, T>()
	const limit = 100
	for (let offset = 0; ; offset += limit) {
		const page = await client.get<T[]>(client.withQuery(endpoint, { limit, offset }))
		for (const row of page) rows.set(row.id, row)
		if (page.length < limit) return [...rows.values()]
	}
}

export const whatsapp = {
	connections: () => client.get<ConnectionResponse[]>(`${base}/connections`),
	createConnection: (body: ConnectionCreate) =>
		client.post<ConnectionResponse, ConnectionCreate>(`${base}/connections`, body),
	updateConnection: (connectionId: string, body: ConnectionUpdate) =>
		client.patch<ConnectionResponse, ConnectionUpdate>(
			`${base}/connections/${id(connectionId)}`,
			body
		),
	updateKnowledge: (connectionId: string, body: KnowledgeUpdate) =>
		client.put<ConnectionResponse, KnowledgeUpdate>(
			`${base}/connections/${id(connectionId)}/knowledge`,
			body
		),
	listings: (connectionId: string) =>
		allPages<PublishedListingResponse>(`${base}/connections/${id(connectionId)}/listings`),
	publishListing: (connectionId: string, body: PublishedListingCreate) =>
		client.post<PublishedListingResponse, PublishedListingCreate>(
			`${base}/connections/${id(connectionId)}/listings`,
			body
		),
	updateListing: (connectionId: string, listingId: string, body: PublishedListingUpdate) =>
		client.put<PublishedListingResponse, PublishedListingUpdate>(
			`${base}/connections/${id(connectionId)}/listings/${id(listingId)}`,
			body
		),
	revokeListing: (connectionId: string, listingId: string, expected_revision: number) =>
		client.post<PublishedListingResponse, RevisionDecision>(
			`${base}/connections/${id(connectionId)}/listings/${id(listingId)}/revoke`,
			{ expected_revision }
		),
	threads: (connectionId: string) =>
		allPages<ThreadResponse>(`${base}/connections/${id(connectionId)}/threads`),
	messages: (threadId: string) =>
		allPages<CustomerMessageResponse>(`${base}/threads/${id(threadId)}/messages`),
	notifications: () => allPages<CustomerMessageResponse>(`${base}/notifications`),
	approve: (messageId: string, expected_revision: number) =>
		client.post<CustomerMessageResponse, RevisionDecision>(
			`${base}/messages/${id(messageId)}/approve`,
			{ expected_revision }
		),
	cancel: (messageId: string, expected_revision: number) =>
		client.post<CustomerMessageResponse, RevisionDecision>(
			`${base}/messages/${id(messageId)}/cancel`,
			{ expected_revision }
		),
	edit: (messageId: string, body: ReplyEdit) =>
		client.patch<CustomerMessageResponse, ReplyEdit>(`${base}/messages/${id(messageId)}`, body),
	seen: (messageId: string, expected_revision: number) =>
		client.post<CustomerMessageResponse, RevisionDecision>(
			`${base}/notifications/${id(messageId)}/seen`,
			{ expected_revision }
		),
	takeover: (threadId: string) =>
		client.post<ThreadResponse>(`${base}/threads/${id(threadId)}/takeover`),
	resume: (threadId: string) =>
		client.post<ThreadResponse>(`${base}/threads/${id(threadId)}/resume`)
}
