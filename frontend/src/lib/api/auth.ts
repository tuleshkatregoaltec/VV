import { env } from '$env/dynamic/public';
import { browser } from '$app/environment';

import { AuthClient } from '@supabase/auth-js';
import type { AuthChangeEvent, Session } from '@supabase/auth-js';
import { api } from './client';

export interface BackendUser {
	id: string;
	email: string;
	first_name: string;
	last_name: string;
	organization_id: string | null;
	organization_name: string | null;
	role: 'user' | 'admin' | 'owner' | 'member';
	is_owner: boolean;
	subscription_status: string | null;
}

export const client = new AuthClient({
	url: `${env.PUBLIC_AUTH_BASE_URL}`,
	storageKey: 'authentication',
	detectSessionInUrl: true,
	persistSession: true
});

const authSearchParams = ['code', 'state', 'provider_token', 'provider_refresh_token', 'error'];

client.onAuthStateChange((event: AuthChangeEvent, _session: Session | null) => {
	if (!browser) return;

	if (event === 'SIGNED_IN' || event === 'TOKEN_REFRESHED') {
		const url = new URL(window.location.href);
		authSearchParams.forEach((param) => url.searchParams.delete(param));
		window.history.replaceState({}, '', url);
	}
});

export type AuthResult<T = unknown> = {
	success: boolean;
	error?: string;
	data?: T;
};

function toAuthResult<T>(
	res: { error: { message?: string } | null; data?: T | null },
	fallbackMessage: string
): AuthResult<T> {
	if (!res.error) {
		return res.data !== undefined
			? { success: true, data: res.data ?? undefined }
			: { success: true };
	}

	return { success: false, error: res.error.message || fallbackMessage };
}

export async function get_access_token(): Promise<string | undefined> {
	const res = await client.getSession();

	if (res.data && !res.error) {
		return res.data.session?.access_token;
	}
}

/**
 * Login with email/password, storing into localstorage if successful.
 *
 * @param email Email address
 * @param password Password
 * @returns AuthResult with success status, error message, and session data
 */
export async function login_with_email_pass(email: string, password: string): Promise<AuthResult> {
	const res = await client.signInWithPassword({ email, password });
	return toAuthResult(res, 'Login failed');
}

/**
 * Sign up with email/password, sending OTP verification email.
 * Pass first and last name as user metadata.
 *
 * @param email Email address
 * @param password Password
 * @param firstName User's first name
 * @param lastName User's last name
 * @returns AuthResult with success status and error message
 */
export async function sign_up_with_password(
	email: string,
	password: string,
	firstName: string,
	lastName: string
): Promise<AuthResult> {
	const res = await client.signUp({
		email,
		password,
		options: {
			data: {
				first_name: firstName,
				last_name: lastName
			},
			emailRedirectTo: `${window.location.origin}/dashboard`
		}
	});

	return toAuthResult(res, 'Sign up failed');
}

/**
 * Send magic link for passwordless login.
 *
 * @param email Email address
 * @returns AuthResult with success status
 */
export async function sign_in_with_magic_link(email: string): Promise<AuthResult> {
	return sign_in_with_magic_link_to(email);
}

export async function sign_in_with_magic_link_to(
	email: string,
	redirectPath = '/dashboard'
): Promise<AuthResult> {
	const res = await client.signInWithOtp({
		email,
		options: {
			emailRedirectTo: `${window.location.origin}${redirectPath}`
		}
	});

	return toAuthResult(res, 'Failed to send magic link');
}

/**
 * Send magic link for signup with first/last name metadata.
 *
 * @param email Email address
 * @param firstName User's first name
 * @param lastName User's last name
 * @returns AuthResult with success status
 */
export async function sign_up_with_magic_link(
	email: string,
	firstName: string,
	lastName: string,
	redirectPath = '/dashboard'
): Promise<AuthResult> {
	const res = await client.signInWithOtp({
		email,
		options: {
			data: {
				first_name: firstName,
				last_name: lastName
			},
			emailRedirectTo: `${window.location.origin}${redirectPath}`
		}
	});

	return toAuthResult(res, 'Failed to send magic link');
}

/**
 * Verify OTP code sent via email.
 *
 * @param email Email address
 * @param token 6-digit OTP code
 * @param type Type of OTP (signup, magiclink, recovery, email_change)
 * @returns AuthResult with success status and session data
 */
export async function verify_otp(
	email: string,
	token: string,
	type: 'signup' | 'magiclink' | 'recovery' | 'email_change' = 'signup'
): Promise<AuthResult> {
	const res = await client.verifyOtp({
		email,
		token,
		type
	});

	return toAuthResult(res, 'OTP verification failed');
}

/**
 * Resend OTP code.
 *
 * @param email Email address
 * @param type Type of OTP (signup or email_change)
 * @returns AuthResult with success status
 */
export async function resend_otp(
	email: string,
	type: 'signup' | 'email_change' = 'signup'
): Promise<AuthResult> {
	const res = await client.resend({
		email,
		type
	});

	return toAuthResult(res, 'Failed to resend OTP');
}

/**
 * Request password reset email.
 *
 * @param email Email address
 * @returns AuthResult with success status
 */
export async function request_password_reset(email: string): Promise<AuthResult> {
	const res = await client.resetPasswordForEmail(email, {
		redirectTo: `${window.location.origin}/auth/reset-password`
	});

	return toAuthResult(res, 'Failed to send reset email');
}

/**
 * Update password (used after password reset).
 *
 * @param newPassword New password
 * @returns AuthResult with success status
 */
export async function update_password(newPassword: string): Promise<AuthResult> {
	const res = await client.updateUser({
		password: newPassword
	});

	return toAuthResult(res, 'Failed to update password');
}

/**
 * Get current session.
 *
 * @returns Current session or null
 */
export async function get_session(): Promise<Session | null> {
	const res = await client.getSession();
	return res.data?.session || null;
}

/**
 * Listen to auth state changes.
 *
 * @param callback Function to call on auth state change
 * @returns Unsubscribe function
 */
export function on_auth_state_change(
	callback: (event: AuthChangeEvent, session: Session | null) => void
): { data: { subscription: { unsubscribe: () => void } } } {
	return client.onAuthStateChange(callback);
}

/**
 * Get current user info from backend
 */
export async function me(): Promise<BackendUser> {
	return api<BackendUser>('/api/v1/auth/me');
}

/**
 * Update current user's profile (first_name, last_name) via backend API
 *
 * @param firstName User's first name
 * @param lastName User's last name
 * @returns AuthResult with success status
 */
export async function update_user_profile(
	firstName: string,
	lastName: string
): Promise<{ success: boolean; first_name: string; last_name: string }> {
	return api<{ success: boolean; first_name: string; last_name: string }>(
		'/api/v1/auth/update-profile',
		{
			method: 'POST',
			body: { first_name: firstName, last_name: lastName }
		}
	);
}

/**
 * Sign out the current user - Supabase + PostHog reset + redirect
 */
export async function logout(): Promise<void> {
	try {
		const res = await client.signOut();
		if (res.error) {
			console.error('Supabase logout error:', res.error.message);
		}
	} catch (e) {
		console.error('Supabase logout error:', e);
	}

	const { clearUser } = await import('$lib/stores/user.svelte');
	clearUser();

	window.location.href = '/';
}
