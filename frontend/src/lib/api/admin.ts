import { http } from './client';

export interface OrgListItem {
	id: string;
	name: string;
	owner_email: string;
	user_count: number;
	max_users: number;
	subscription_status: string;
	seats: number;
	created_at: string;
}

export interface OrgUser {
	id: string;
	email: string;
	first_name: string;
	last_name: string;
	role: string;
	daily_token_limit: number;
	tokens_used_today: number;
	usage_percentage: number;
	last_login: string | null;
}

export interface OrgDetail {
	id: string;
	name: string;
	owner_email: string;
	user_count: number;
	max_users: number;
	subscription_status: string;
	created_at: string;
	users: OrgUser[];
}

export interface CreateUserRequest {
	email: string;
	password: string;
	first_name: string;
	last_name: string;
	org_mode: 'new' | 'existing';
	org_name?: string;
	org_id?: string;
	daily_token_limit: number;
}

export interface CreateUserResponse {
	user_id: string;
	email: string;
	organization_id: string;
	organization_name: string;
}

export interface UserTokenStats {
	user_id: string;
	tokens_used_today: number;
	daily_limit: number;
	usage_percentage: number;
	remaining_tokens: number;
}

export const admin = {
	organizations: {
		list: () => http.get<OrgListItem[]>('/api/v1/admin/organizations'),
		get: (id: string) => http.get<OrgDetail>(`/api/v1/admin/organizations/${id}`),
		update: (id: string, data: { max_users?: number }) =>
			http.put<OrgListItem>(`/api/v1/admin/organizations/${id}`, data),
		delete: (id: string) => http.delete<void>(`/api/v1/admin/organizations/${id}`),
		setSubscription: (id: string, status: string) =>
			http.patch<OrgListItem>(`/api/v1/admin/organizations/${id}/subscription`, { status })
	},

	users: {
		create: (data: CreateUserRequest) => http.post<CreateUserResponse>('/api/v1/admin/users', data),
		updateTokenLimit: (id: string, daily_token_limit: number) =>
			http.patch<{ id: string }>(`/api/v1/admin/users/${id}`, { daily_token_limit }),
		delete: (id: string) => http.delete<void>(`/api/v1/admin/users/${id}`)
	}
};
