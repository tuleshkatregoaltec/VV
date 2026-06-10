import { client } from './client'
import type {
	ListingCardResponse,
	ListingDetailResponse,
	ListingFiltersResponse,
	ListingFloorPlanResponse,
	ListingImageResponse,
	ListingListResponse,
	ListingPartyResponse
} from './generated/hey-api/types.gen'

export type ListingMode = 'sale' | 'rent'

export type {
	ListingCardResponse,
	ListingDetailResponse,
	ListingFiltersResponse,
	ListingFloorPlanResponse,
	ListingImageResponse,
	ListingListResponse,
	ListingPartyResponse
}

export interface ListingParams {
	mode?: ListingMode
	limit?: number
	offset?: number
	search?: string
	area?: string
	property_type?: string
	bedrooms?: string
	price_min?: number
	price_max?: number
}

export const listings = {
	list: (params: ListingParams = {}) =>
		client.get<ListingListResponse>(
			client.withQuery('/api/v1/listings', {
				mode: params.mode,
				limit: params.limit,
				offset: params.offset,
				search: params.search,
				area: params.area,
				property_type: params.property_type,
				bedrooms: params.bedrooms,
				price_min: params.price_min,
				price_max: params.price_max
			})
		),

	get: (listingId: string) =>
		client.get<ListingDetailResponse>(`/api/v1/listings/${encodeURIComponent(listingId)}`)
}
