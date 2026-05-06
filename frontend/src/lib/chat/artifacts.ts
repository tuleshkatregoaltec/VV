import type { ListingListResponse, MarketTrendResponse } from '$lib/api/generated/hey-api/types.gen'

export type ChatArtifactStatus = 'loading' | 'ready' | 'error' | 'stale'

export interface ChatArtifactBase {
	id: string
	type: 'listing_results' | 'market_trend'
	status: ChatArtifactStatus
	title: string
	subtitle?: string | null
	created_at: string
	query?: Record<string, unknown> | null
	error?: string | null
}

export interface ListingResultsArtifact extends ChatArtifactBase {
	type: 'listing_results'
	data?: ListingListResponse | null
}

export interface MarketTrendArtifact extends ChatArtifactBase {
	type: 'market_trend'
	data?: MarketTrendResponse | null
}

export type ChatArtifact = ListingResultsArtifact | MarketTrendArtifact

export interface ChatArtifactStreamEvent {
	type: 'artifact_opened' | 'artifact_updated'
	artifact: ChatArtifact
}

export function isChatArtifact(value: unknown): value is ChatArtifact {
	if (!value || typeof value !== 'object') return false
	const candidate = value as Partial<ChatArtifact>
	return (
		typeof candidate.id === 'string' &&
		(candidate.type === 'listing_results' || candidate.type === 'market_trend') &&
		(candidate.status === 'loading' ||
			candidate.status === 'ready' ||
			candidate.status === 'error' ||
			candidate.status === 'stale') &&
		typeof candidate.title === 'string'
	)
}

export function artifactSortValue(artifact: ChatArtifact): number {
	const time = new Date(artifact.created_at).getTime()
	return Number.isFinite(time) ? time : 0
}
