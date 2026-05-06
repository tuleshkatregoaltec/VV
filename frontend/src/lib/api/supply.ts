import { client } from './client'
import type {
	SupplyCatalogueProjectCardResponse,
	SupplyCatalogueProjectDetailResponse,
	SupplyCatalogueProjectsResponse,
	UpcomingProjectResponse,
	UpcomingProjectsResponse
} from './generated/hey-api/types.gen'

export type {
	SupplyCatalogueProjectCardResponse,
	SupplyCatalogueProjectDetailResponse,
	SupplyCatalogueProjectsResponse,
	UpcomingProjectResponse,
	UpcomingProjectsResponse
}

export interface SupplyCatalogueParams {
	limit?: number
	offset?: number
	search?: string
	area?: string
	status?: string
}

export const supply = {
	getUpcomingProjects: () =>
		client.get<UpcomingProjectsResponse>('/api/v1/supply/upcoming-projects'),

	catalogue: (params: SupplyCatalogueParams = {}) =>
		client.get<SupplyCatalogueProjectsResponse>(
			client.withQuery('/api/v1/supply/catalogue/projects', {
				limit: params.limit,
				offset: params.offset,
				search: params.search,
				area: params.area,
				status: params.status
			})
		),

	catalogueProject: (projectId: number) =>
		client.get<SupplyCatalogueProjectDetailResponse>(
			`/api/v1/supply/catalogue/projects/${projectId}`
		)
}
