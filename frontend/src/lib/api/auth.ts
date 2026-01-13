import { env } from '$env/dynamic/public';
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
	me: () => http.get<User>('/auth/me'),

	getLoginUrl: () => `${env.PUBLIC_API_BASE_URL}/auth/login`,

	/** Triggers full page navigation to OAuth provider */
	login: () => {
		window.location.href = auth.getLoginUrl();
	},

	logout: () => http.post<void>('/auth/logout')
};
