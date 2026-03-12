import { client } from './client'
import type { FilterOptionsResponse } from './generated/hey-api/types.gen'

export type { FilterOptionsResponse }

export interface FilterParams {
	property_usage?: string
	project?: string
	filter_type?: string
	property_type?: string
	area?: string
}

export const filters = {
	sales: (filterParams: FilterParams = {}) => {
		return client.get<FilterOptionsResponse>(
			client.withQuery('/api/v1/filters/sales', {
				property_usage: filterParams.property_usage,
				project: filterParams.project,
				filter_type: filterParams.filter_type,
				property_type:
					filterParams.property_type && filterParams.property_type !== 'All'
						? filterParams.property_type
						: undefined,
				area: filterParams.area && filterParams.area !== 'All' ? filterParams.area : undefined
			})
		)
	},

	rentals: (filterParams: FilterParams = {}) => {
		return client.get<FilterOptionsResponse>(
			client.withQuery('/api/v1/filters/rentals', {
				property_usage: filterParams.property_usage,
				project: filterParams.project,
				filter_type: filterParams.filter_type,
				property_type:
					filterParams.property_type && filterParams.property_type !== 'All'
						? filterParams.property_type
						: undefined,
				area: filterParams.area && filterParams.area !== 'All' ? filterParams.area : undefined
			})
		)
	}
}
