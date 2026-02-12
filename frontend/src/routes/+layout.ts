import { browser } from '$app/environment';
import { redirect } from '@sveltejs/kit';
import { QueryClient } from '@tanstack/svelte-query';
import posthog from 'posthog-js';
import type { LayoutLoad } from './$types';
import { env } from '$env/dynamic/public';
import { get_session, me, identifyUser } from '$lib/api/auth';
import { currentUser, setUser, loadCached } from '$lib/stores/user.svelte';

export const prerender = false;
export const ssr = false;

// Public paths — no auth check at all
const PUBLIC_PATHS = ['/', '/landing-new', '/landing-v2', '/terms', '/privacy'];

// Auth gate — redirect away if already authenticated
const AUTH_PATHS = ['/auth'];

// Onboarding — require session, enforce step order, no subscription check
const ONBOARDING_PATHS = ['/profile-setup', '/organization-setup', '/payment-success', '/payment-cancel'];

// Subscription recovery — require session + profile + org, but no subscription check
const RECOVERY_PATHS = ['/renew'];

// Everything else is protected — require session + profile + org + active subscription

function matchesCategory(pathname: string, paths: string[]): boolean {
	return paths.some((p) => pathname === p || pathname.startsWith(p + '/'));
}

/** Get user from store cache or fetch from backend. Returns null if no session. */
async function resolveUser() {
	// Use cached store data if available (no network call)
	if (currentUser.data) return currentUser.data;

	// Try localStorage cache
	const cached = loadCached();
	if (cached) return cached;

	// No cache — need to fetch from backend
	const session = await get_session();
	if (!session) return null;

	const user = await me();
	setUser(user);
	return user;
}

/** Determine where a user should be based on their completion status */
function getOnboardingRedirect(user: { first_name: string; last_name: string; organization_id: string | null; subscription_is_active: boolean; is_owner: boolean; subscription_status: string | null }): string {
	if (!user.first_name || !user.last_name) return '/profile-setup';
	if (!user.organization_id) return '/organization-setup';
	if (!user.subscription_is_active) {
		// Owner with no/failed subscription goes to org setup to retry payment
		if (user.is_owner && (!user.subscription_status || user.subscription_status === 'failed' || user.subscription_status === 'pending')) {
			return '/organization-setup';
		}
		return '/renew';
	}
	return '/dashboard';
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

	if (!browser) return { queryClient };

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

	// ── 1. Public paths — no auth needed ──
	if (matchesCategory(pathname, PUBLIC_PATHS)) {
		return { queryClient };
	}

	// ── 2. Auth gate — redirect authenticated users to correct step ──
	if (matchesCategory(pathname, AUTH_PATHS)) {
		const session = await get_session();
		if (session) {
			try {
				const user = await me();
				setUser(user);
				identifyUser(user);
				redirect(302, getOnboardingRedirect(user));
			} catch {
				// me() failed — let them stay on auth page (session may be invalid)
				return { queryClient };
			}
		}
		return { queryClient };
	}

	// ── All remaining paths require authentication ──
	let user;
	try {
		user = await resolveUser();
	} catch {
		user = null;
	}

	if (!user) {
		redirect(302, '/auth');
	}

	// ── 3. Onboarding paths — enforce step order ──
	if (matchesCategory(pathname, ONBOARDING_PATHS)) {
		if (pathname.startsWith('/profile-setup')) {
			// Always allow — handles both self-signup and invite flows
			return { queryClient };
		}

		if (pathname.startsWith('/organization-setup')) {
			if (!user.first_name || !user.last_name) redirect(302, '/profile-setup');
			if (user.organization_id && user.subscription_is_active) redirect(302, '/dashboard');
			return { queryClient };
		}

		if (pathname.startsWith('/payment-success')) {
			if (!url.searchParams.get('session_id')) redirect(302, '/dashboard');
			return { queryClient };
		}

		if (pathname.startsWith('/payment-cancel')) {
			return { queryClient };
		}

		return { queryClient };
	}

	// ── 4. Subscription recovery — require profile + org, skip subscription check ──
	if (matchesCategory(pathname, RECOVERY_PATHS)) {
		if (!user.first_name || !user.last_name) redirect(302, '/profile-setup');
		if (!user.organization_id) redirect(302, '/organization-setup');
		// If subscription is already active, go to dashboard
		if (user.subscription_is_active) redirect(302, '/dashboard');
		return { queryClient };
	}

	// ── 5. Protected paths — require everything ──
	const target = getOnboardingRedirect(user);
	if (target !== '/dashboard') {
		redirect(302, target);
	}

	return { queryClient };
};
