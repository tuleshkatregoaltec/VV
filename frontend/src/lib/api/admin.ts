import { http } from './client';

export interface Organization {
    id: string;
    name: string;
    email_domain: string;
    max_users: number;
    is_active: boolean;
    active_user_count: number;
}

export interface OrganizationUser {
    id: string;
    email: string;
    first_name: string;
    last_name: string;
    is_active: boolean;
    created_at: string;
    last_login: string | null;
}

export interface OrganizationDetail {
    organization: Organization;
    users: OrganizationUser[];
}

export interface CreateOrganizationRequest {
    name: string;
    domain: string;
    max_users: number;
}

export interface UpdateOrganizationRequest {
    max_users?: number;
    is_active?: boolean;
}

export interface UpdateUserRequest {
    is_active?: boolean;
}


export const admin = {
	organizations: {
		list: () => http.get<Organization[]>('/api/v1/admin/organizations'),
		get: (id: string) => http.get<OrganizationDetail>(`/api/v1/admin/organizations/${id}`),
		create: (data: CreateOrganizationRequest) =>
			http.post<Organization>('/api/v1/admin/organizations', data),
		update: (id: string, data: UpdateOrganizationRequest) =>
			http.put<Organization>(`/api/v1/admin/organizations/${id}`, data),
		delete: (id: string) => http.delete<void>(`/api/v1/admin/organizations/${id}`)
	},

	users: {
		update: (id: string, data: UpdateUserRequest) =>
			http.put<OrganizationUser>(`/api/v1/admin/users/${id}`, data)
	}
};
