import { http } from './client';

// ============================================================================
// Types
// ============================================================================

export interface Organisation {
    id: string;
    name: string;
    email_domain: string;
    max_users: number;
    is_active: boolean;
    active_user_count: number;
}

export interface OrganisationUser {
    id: string;
    email: string;
    first_name: string;
    last_name: string;
    is_active: boolean;
    created_at: string;
    last_login: string | null;
}

export interface OrganisationDetail {
    organisation: Organisation;
    users: OrganisationUser[];
}

export interface CreateOrganisationRequest {
    name: string;
    domain: string;
    max_users: number;
}

export interface UpdateOrganisationRequest {
    max_users?: number;
    is_active?: boolean;
}

export interface UpdateUserRequest {
    is_active?: boolean;
}

// ============================================================================
// Admin API
// ============================================================================

export const admin = {
    organisations: {
        /**
         * List all organisations
         */
        list: () => http.get<Organisation[]>('/api/admin/organisations'),

        /**
         * Get a single organisation with its users
         */
        get: (id: string) => http.get<OrganisationDetail>(`/api/admin/organisations/${id}`),

        /**
         * Create a new organisation
         */
        create: (data: CreateOrganisationRequest) =>
            http.post<Organisation>('/api/admin/organisations', data),

        /**
         * Update an organisation
         */
        update: (id: string, data: UpdateOrganisationRequest) =>
            http.put<Organisation>(`/api/admin/organisations/${id}`, data),

        /**
         * Delete an organisation
         */
        delete: (id: string) => http.delete<void>(`/api/admin/organisations/${id}`),
    },

    users: {
        /**
         * Update a user's status
         */
        update: (id: string, data: UpdateUserRequest) =>
            http.put<OrganisationUser>(`/api/admin/users/${id}`, data),
    },
};
