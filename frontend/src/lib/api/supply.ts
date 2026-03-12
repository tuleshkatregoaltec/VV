import { client } from './client'
import type {
	UpcomingProjectResponse,
	UpcomingProjectsResponse
} from './generated/hey-api/types.gen'

export type { UpcomingProjectResponse, UpcomingProjectsResponse }

export const supply = {
	getUpcomingProjects: () =>
		client.get<UpcomingProjectsResponse>('/api/v1/supply/upcoming-projects')
}
