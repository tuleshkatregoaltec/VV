import { browser } from '$app/environment';
import { redirect } from '@sveltejs/kit';
import { QueryClient } from '@tanstack/svelte-query';
import posthog from 'posthog-js';
import type { LayoutLoad } from './$types';
import { env } from '$env/dynamic/public';
import { get_session, me } from '$lib/api/auth';
import { currentUser, setUser } from '$lib/stores/user.svelte';

export const prerender = false;
export const ssr = false;

// Public paths that don't require authentication
const PUBLIC_PATHS = [
	'/',
	'/landing-new',
	'/landing-v2',
	'/auth',
	'/auth/reset-password',
	'/auth/no-org',
	'/auth/deactivated'
];

// Onboarding paths - require auth but special handling
const ONBOARDING_PATHS = [
	'/profile-setup',
	'/organization-setup',
	'/payment-success',
	'/payment-cancel'
];

// Protected paths - require auth + complete profile + active org subscription
// All other paths are protected by default

function isPublicPath(pathname: string): boolean {
	return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p));
}

function isOnboardingPath(pathname: string): boolean {
	return ONBOARDING_PATHS.some((p) => pathname === p || pathname.startsWith(p));
}

export const load: LayoutLoad = async ({ url }) => {
	const queryClient = new QueryClient({
		defaultOptions: {
			queries: {
				enabled: browser,
				staleTime: 5 * 60 * 1000,
				refetchOnWindowFocus: false
			}
		}
	});

	if (browser) {
		// Initialize PostHog
		if (env.PUBLIC_POSTHOG_KEY && env.PUBLIC_POSTHOG_HOST && !posthog.__loaded) {
			try {
				posthog.init(env.PUBLIC_POSTHOG_KEY, {
					api_host: env.PUBLIC_POSTHOG_HOST,
					ui_host: 'https://eu.posthog.com',
					defaults: '2025-11-30'
				});
			} catch (error) {
				console.warn('Failed to initialize PostHog:', error);
			}
		}

		const pathname = url.pathname;

		// Public paths - no auth required
		if (isPublicPath(pathname)) {
			return { queryClient };
		}

		// Check authentication
		const session = await get_session();
		if (!session) {
			redirect(302, '/auth');
		}

		// Fetch user data
		let user = currentUser.data;
		if (!user) {
			try {
				user = await me();
				setUser(user);
			} catch (err) {
				redirect(302, '/auth');
			}
		}

		// Handle onboarding paths
		if (isOnboardingPath(pathname)) {
			// Profile setup: allow if user doesn't have first/last name
			if (pathname.startsWith('/profile-setup')) {
				// Allow access - this page handles both self-signup and invited users
				return { queryClient };
			}

			// Organization setup: only allow if user has profile but no org
			if (pathname.startsWith('/organization-setup')) {
				if (!user.first_name || !user.last_name) {
					redirect(302, '/profile-setup');
				}
				if (user.organization_id) {
					redirect(302, '/dashboard');
				}
				return { queryClient };
			}

			// Payment success/cancel: only allow if coming from Stripe (has session_id)
			if (pathname.startsWith('/payment-success') || pathname.startsWith('/payment-cancel')) {
				if (!url.searchParams.get('session_id')) {
					redirect(302, '/dashboard');
				}
				return { queryClient };
			}

			return { queryClient };
		}

		// Protected routes - require complete profile + organization + active subscription

		// Check if profile is complete
		if (!user.first_name || !user.last_name) {
			redirect(302, '/profile-setup');
		}

		// Check if user has organization
		if (!user.organization_id) {
			redirect(302, '/organization-setup');
		}

		// Check subscription status (cached from /auth/me response)
		if (!user.subscription_is_active) {
			redirect(302, '/auth/no-org');
		}

		return { queryClient };
	}

	return { queryClient };
};
