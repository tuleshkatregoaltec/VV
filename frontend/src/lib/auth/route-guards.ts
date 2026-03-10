import type { BackendUser } from '$lib/api/auth';

export type RouteCategory = 'public' | 'auth' | 'onboarding' | 'recovery' | 'protected';

export type GuardDecision = { action: 'allow' } | { action: 'redirect'; location: string };

const PUBLIC_PATHS = [
	'/',
	'/landing-new',
	'/landing-v2',
	'/invite',
	'/terms',
	'/privacy',
	'/auth/reset-password',
	'/auth/deactivated'
];
const AUTH_PATHS = ['/auth'];
const ONBOARDING_PATHS = [
	'/profile-setup',
	'/organization-setup',
	'/payment-success',
	'/payment-cancel'
];
const RECOVERY_PATHS = ['/renew'];

function hasActiveSubscription(status: BackendUser['subscription_status']): boolean {
	return status === 'active' || status === 'trialing';
}

export function matchesCategory(pathname: string, paths: string[]): boolean {
	return paths.some((path) => pathname === path || pathname.startsWith(path + '/'));
}

export function getRouteCategory(pathname: string): RouteCategory {
	if (matchesCategory(pathname, PUBLIC_PATHS)) return 'public';
	if (matchesCategory(pathname, AUTH_PATHS)) return 'auth';
	if (matchesCategory(pathname, ONBOARDING_PATHS)) return 'onboarding';
	if (matchesCategory(pathname, RECOVERY_PATHS)) return 'recovery';
	return 'protected';
}

export function getOnboardingRedirect(
	user: Pick<
		BackendUser,
		'first_name' | 'last_name' | 'organization_id' | 'is_owner' | 'subscription_status'
	>
): string {
	if (!user.first_name || !user.last_name) return '/profile-setup';
	if (!user.organization_id) return '/organization-setup';

	if (!hasActiveSubscription(user.subscription_status)) {
		if (
			user.is_owner &&
			(!user.subscription_status ||
				user.subscription_status === 'failed' ||
				user.subscription_status === 'pending')
		) {
			return '/organization-setup';
		}

		return '/renew';
	}

	return '/dashboard';
}

export function decideRouteAccess(
	pathname: string,
	user: Pick<
		BackendUser,
		'first_name' | 'last_name' | 'organization_id' | 'is_owner' | 'subscription_status'
	> | null,
	options: { hasPaymentSessionId?: boolean } = {}
): GuardDecision {
	const category = getRouteCategory(pathname);

	if (category === 'public') {
		return { action: 'allow' };
	}

	if (category === 'auth') {
		if (!user) return { action: 'allow' };
		return { action: 'redirect', location: getOnboardingRedirect(user) };
	}

	if (!user) {
		return { action: 'redirect', location: '/auth' };
	}

	if (category === 'onboarding') {
		if (pathname.startsWith('/profile-setup')) {
			return { action: 'allow' };
		}

		if (pathname.startsWith('/organization-setup')) {
			if (!user.first_name || !user.last_name) {
				return { action: 'redirect', location: '/profile-setup' };
			}

			if (user.organization_id && !user.is_owner) {
				return { action: 'redirect', location: '/renew' };
			}

			if (user.organization_id && hasActiveSubscription(user.subscription_status)) {
				return { action: 'redirect', location: '/dashboard' };
			}

			return { action: 'allow' };
		}

		if (pathname.startsWith('/payment-success')) {
			if (!options.hasPaymentSessionId) {
				return { action: 'redirect', location: '/dashboard' };
			}
			return { action: 'allow' };
		}

		return { action: 'allow' };
	}

	if (category === 'recovery') {
		if (!user.first_name || !user.last_name) {
			return { action: 'redirect', location: '/profile-setup' };
		}

		if (!user.organization_id) {
			return { action: 'redirect', location: '/organization-setup' };
		}

		if (hasActiveSubscription(user.subscription_status)) {
			return { action: 'redirect', location: '/dashboard' };
		}

		return { action: 'allow' };
	}

	const target = getOnboardingRedirect(user);
	if (target !== '/dashboard') {
		return { action: 'redirect', location: target };
	}

	return { action: 'allow' };
}
