import { client } from './client'
import type {
	ListingCardResponse as GeneratedListingCardResponse,
	ListingDetailResponse as GeneratedListingDetailResponse,
	ListingFiltersResponse as GeneratedListingFiltersResponse,
	ListingListResponse as GeneratedListingListResponse,
	ListingFloorPlanResponse,
	ListingImageResponse
} from './generated/hey-api/types.gen'

export type ListingMode = 'sale' | 'rent'
export type ListingAssetClass = 'residential' | 'commercial'
export type ListingMarketPosition =
	| 'below_market'
	| 'near_market'
	| 'above_market'
	| 'insufficient_data'
export type ListingBenchmarkLevel = 'building_layout' | 'project_layout' | 'insufficient_data'
export type ListingUrgencySignal = 'explicit_urgency' | 'value_language' | 'none'
/** dld_sales: valued from DLD sales of the same bedroom count in the same building (11 Nov 2026).
    asking_peers: compared with other listings' asking prices (rent, commercial). */
export type ListingValuationMethod = 'dld_sales' | 'asking_peers'
export type ListingSort = 'default' | 'value_gap'

/** A DLD sale behind a listing's estimate: same building, type and bedrooms. */
export interface ListingComparableSale {
	date: string
	unit: string | null
	size_sqft: number
	price_aed: number
	psf: number
}

export interface ListingIntelligenceFields {
	asset_class: ListingAssetClass
	listing_age_days: number | null
	price_per_sqft_aed: number | null
	market_median_price_per_sqft_aed: number | null
	market_estimate_aed: number | null
	market_delta_pct: number | null
	market_position: ListingMarketPosition
	comparable_count: number
	benchmark_level: ListingBenchmarkLevel
	urgency_signal: ListingUrgencySignal
	urgency_terms: string[]
	valuation_method: ListingValuationMethod
	estimated_value_aed: number | null
	estimated_value_low_aed: number | null
	estimated_value_high_aed: number | null
	valuation_confidence: 'high' | 'medium' | 'low' | null
	/** Asking / estimate - 1: -0.12 is asking 12% below the estimate. Null when not flagged. */
	value_gap_pct: number | null
	is_off_plan: boolean
	valued_at: string | null
}

// The backend always serializes these defaulted fields; the generated types mark them optional.
export interface ListingCardResponse
	extends Omit<GeneratedListingCardResponse, keyof ListingIntelligenceFields>,
		ListingIntelligenceFields {}

export interface ListingDetailResponse
	extends Omit<GeneratedListingDetailResponse, keyof ListingIntelligenceFields>,
		ListingIntelligenceFields {
	valuation_comparables: ListingComparableSale[]
}

export interface ListingFiltersResponse extends GeneratedListingFiltersResponse {
	asset_classes: ListingAssetClass[]
}

export interface ListingListResponse
	extends Omit<GeneratedListingListResponse, 'listings' | 'filters'> {
	listings: ListingCardResponse[]
	filters: ListingFiltersResponse
	/** When the listing data was collected; listings may have sold or changed since. */
	data_as_of: string | null
}

export interface ListingTrendPoint {
	period: string
	average_asking_price_aed: number | null
	median_asking_price_aed: number | null
	median_price_per_sqft_aed: number | null
	listing_count: number
	median_achieved_price_per_sqft_aed: number | null
	achieved_transaction_count: number
}

export interface ListingAnalyticsResponse {
	total: number
	average_price_aed: number | null
	median_price_aed: number | null
	median_price_per_sqft_aed: number | null
	average_listing_age_days: number | null
	median_listing_age_days: number | null
	newly_listed_30d: number
	below_market_count: number
	near_market_count: number
	above_market_count: number
	benchmarked_count: number
	verified_count: number
	area_count: number
	snapshot_at: string | null
	data_as_of: string | null
	trend: ListingTrendPoint[]
}

export type { ListingFloorPlanResponse, ListingImageResponse }

export interface ListingParams {
	mode?: ListingMode
	asset_class?: ListingAssetClass
	limit?: number
	offset?: number
	search?: string
	area?: string
	property_type?: string
	bedrooms?: string
	price_min?: number
	price_max?: number
	/** List only: e.g. below_market with sort value_gap is the possible-bargains view. */
	market_position?: ListingMarketPosition
	sort?: ListingSort
}

export const listings = {
	list: (params: ListingParams = {}) =>
		client.get<ListingListResponse>(
			client.withQuery('/api/v1/listings', {
				mode: params.mode,
				asset_class: params.asset_class,
				limit: params.limit,
				offset: params.offset,
				search: params.search,
				area: params.area,
				property_type: params.property_type,
				bedrooms: params.bedrooms,
				price_min: params.price_min,
				price_max: params.price_max,
				market_position: params.market_position,
				sort: params.sort
			})
		),

	filters: (params: Pick<ListingParams, 'mode' | 'asset_class'> = {}) =>
		client.get<ListingFiltersResponse>(
			client.withQuery('/api/v1/listings/filters', {
				mode: params.mode,
				asset_class: params.asset_class
			})
		),

	analytics: (params: ListingParams = {}) =>
		client.get<ListingAnalyticsResponse>(
			client.withQuery('/api/v1/listings/analytics', {
				mode: params.mode,
				asset_class: params.asset_class,
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
