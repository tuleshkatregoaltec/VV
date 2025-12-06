import { PUBLIC_API_BASE_URL } from '$env/static/public';
import { http } from './client';

export interface User {
    id: string;
    email: string;
    first_name: string;
    last_name: string;
    organization_id: string;
    organization_name: string;
    role: 'user' | 'admin';
}

export interface UserWithInitials extends User {
    initials: string;
}

export const auth = {
    /**
     * Get the current authenticated user
     */
    me: () => http.get<User>('/auth/me'),

    /**
     * Get the login URL for redirect
     */
    getLoginUrl: () => `${PUBLIC_API_BASE_URL}/auth/login`,

    /**
     * Redirect to the login page
     */
    login: () => {
        window.location.href = auth.getLoginUrl();
    },

    /**
     * Logout the current user
     */
    logout: () => http.post<void>('/auth/logout'),
};
