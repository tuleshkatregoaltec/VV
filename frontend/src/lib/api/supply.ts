import { api } from './client';

export interface Developer {
    developer_id: number;
    developer_name_en: string | null;
    phone?: string;
    webpage?: string;
    total: number;
    active: number;
    completed: number;
    cancelled: number;
}

export interface DeveloperListResponse {
    developers: Developer[];
    total: number;
    limit: number;
    offset: number;
}

export interface DeveloperCountResponse {
    total: number;
}

export interface Project {
    project_id: number;
    project_name: string | null;
    project_status?: string;
    percent_completed?: number;
    project_start_date?: string;
    project_end_date?: string;
    completion_date?: string;
    cancellation_date?: string;
    project_description_en?: string;
    area_name?: string;
    no_of_buildings?: number;
    no_of_units?: number;
}

export type SortOption = 'projects' | 'transactions' | 'avg_price';

export const supply = {
    getDeveloperCount: () => 
        api<DeveloperCountResponse>('/api/v1/supply/developers/count'),
    getDevelopers: (sortBy: SortOption = 'projects', limit: number = 50, offset: number = 0) => 
        api<DeveloperListResponse>(`/api/v1/supply/developers?sort_by=${sortBy}&limit=${limit}&offset=${offset}`),
    getDeveloperProjects: (id: number) => api<Project[]>(`/api/v1/supply/developers/${id}/projects`),
    getProject: (id: number) => api<Project>(`/api/v1/supply/projects/${id}`)
};
