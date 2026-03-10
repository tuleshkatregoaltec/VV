import { api } from './client'

export interface UpcomingProject {
	project_id: number
	project_name: string
	developer_name: string
	developer_id: number | null
	area_name: string
	project_start_date: string | null
	project_end_date: string | null
	percent_completed: number
	no_of_buildings: number | null
	no_of_units: number | null
}

export interface UpcomingProjectsResponse {
	projects: UpcomingProject[]
	total: number
}

export const supply = {
	getUpcomingProjects: () => api<UpcomingProjectsResponse>('/api/v1/supply/upcoming-projects')
}
