import type { AuthChangeEvent, Session } from '@supabase/auth-js'
import { AuthClient } from '@supabase/auth-js'
import { env } from '$env/dynamic/public'
import { api } from './client'

export interface BackendUser {
	id: string
	email: string
	first_name: string
	last_name: string
	organization_id: string | null
	organization_name: string | null
	role: 'user' | 'admin' | 'owner' | 'member'
	is_owner: boolean
	subscription_status: string | null
}

export const client = new AuthClient({
	url: env.PUBLIC_AUTH_BASE_URL,
	storageKey: 'authentication',
	detectSessionInUrl: true,
	persistSession: true
})

const authSearchParams = ['code', 'state', 'provider_token', 'provider_refresh_token', 'error']

client.onAuthStateChange((event: AuthChangeEvent) => {
	if (!browser) return

	if (event === 'SIGNED_IN' || event === 'TOKEN_REFRESHED') {
		const url = new URL(window.location.href)
		authSearchParams.forEach((param) => {
			url.searchParams.delete(param)
		})
		window.history.replaceState({}, '', url)
	}
})

export type AuthResult<T = unknown> = {
	success: boolean
	error?: string
	data?: T
}

function toAuthResult<T>(
	res: { error: { message?: string } | null; data?: T | null },
	fallbackMessage: string
): AuthResult<T> {
	if (!res.error) {
		return res.data !== undefined
			? { success: true, data: res.data ?? undefined }
			: { success: true }
	}

	return { success: false, error: res.error.message || fallbackMessage }
}

export async function get_access_token(): Promise<string | undefined> {
	const res = await client.getSession()

	if (res.data && !res.error) {
		return res.data.session?.access_token
	}
}

/** Login with email/password. */
export async function login_with_email_pass(email: string, password: string): Promise<AuthResult> {
	const res = await client.signInWithPassword({ email, password })
	return toAuthResult(res, 'Login failed')
}

/** Sign up with email/password and optional metadata. */
export async function sign_up_with_password(
	email: string,
	password: string,
	firstName: string,
	lastName: string,
	redirectPath = '/setup'
): Promise<AuthResult> {
	const res = await client.signUp({
		email,
		password,
		options: {
			data: {
				first_name: firstName,
				last_name: lastName
			},
			emailRedirectTo: `${window.location.origin}${redirectPath}`
		}
	})

	return toAuthResult(res, 'Sign up failed')
}

/** Send a passwordless sign-in code or magic link. */
export async function sign_in_with_magic_link(email: string): Promise<AuthResult> {
	return sign_in_with_magic_link_to(email)
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
	})

	return toAuthResult(res, 'Failed to send magic link')
}

/** Send a passwordless sign-up flow with optional metadata. */
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
	})

	return toAuthResult(res, 'Failed to send magic link')
}

/** Verify an email OTP code. */
export async function verify_otp(
	email: string,
	token: string,
	type: 'signup' | 'magiclink' | 'recovery' | 'email_change' = 'signup'
): Promise<AuthResult> {
	const res = await client.verifyOtp({
		email,
		token,
		type
	})

	return toAuthResult(res, 'OTP verification failed')
}

/** Resend an OTP code. */
export async function resend_otp(
	email: string,
	type: 'signup' | 'email_change' = 'signup'
): Promise<AuthResult> {
	const res = await client.resend({
		email,
		type
	})

	return toAuthResult(res, 'Failed to resend OTP')
}

/** Request a password reset email. */
export async function request_password_reset(email: string): Promise<AuthResult> {
	const res = await client.resetPasswordForEmail(email, {
		redirectTo: `${window.location.origin}/reset`
	})

	return toAuthResult(res, 'Failed to send reset email')
}

/** Update the current user's password. */
export async function update_password(newPassword: string): Promise<AuthResult> {
	const res = await client.updateUser({
		password: newPassword
	})

	return toAuthResult(res, 'Failed to update password')
}

/** Get the current auth session. */
export async function get_session(): Promise<Session | null> {
	const res = await client.getSession()
	return res.data?.session || null
}

/** Listen to auth state changes. */
export function on_auth_state_change(
	callback: (event: AuthChangeEvent, session: Session | null) => void
): { data: { subscription: { unsubscribe: () => void } } } {
	return client.onAuthStateChange(callback)
}

/** Get current user info from the backend. */
export async function me(): Promise<BackendUser> {
	return api<BackendUser>('/api/v1/auth/me')
}

/** Update current user's profile through the backend API. */
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
	)
}

/** Sign out the current user and redirect. */
export async function logout(redirectTo = '/'): Promise<void> {
	try {
		const res = await client.signOut()
		if (res.error) {
			console.error('Supabase logout error:', res.error.message)
		}
	} catch (e) {
		console.error('Supabase logout error:', e)
	}

	const { clearUser } = await import('$lib/stores/user.svelte')
	clearUser()

	window.location.href = redirectTo
}
