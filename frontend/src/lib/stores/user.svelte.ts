import { browser } from '$app/environment';
import posthog from 'posthog-js';
import { me, get_session, type BackendUser } from '$lib/api/auth';

const STORAGE_KEY = 'vitevue-user';
const REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes

const userState = $state<{ data: BackendUser | null }>({ data: null });

let refreshInterval: number | null = null;
let lastRefresh = 0;
let autoRefreshStarted = false;
let identifiedUserId: string | null = null;

function handleVisibilityChange() {
	if (!document.hidden && Date.now() - lastRefresh > 60 * 1000) {
		refreshUser();
	}
}

function identifyUser(user: BackendUser) {
	if (browser && posthog.__loaded && identifiedUserId !== user.id) {
		posthog.identify(user.id, {
			email: user.email,
			first_name: user.first_name,
			last_name: user.last_name,
			organization_id: user.organization_id,
			organization_name: user.organization_name
		});
		identifiedUserId = user.id;
	}
}

/** Load cached user from localStorage (synchronous, no network) */
function loadCached(): BackendUser | null {
	if (!browser) return null;
	try {
		const cached = localStorage.getItem(STORAGE_KEY);
		if (cached) {
			const user = JSON.parse(cached) as BackendUser;
			userState.data = user;
			return user;
		}
	} catch {
		localStorage.removeItem(STORAGE_KEY);
	}
	return null;
}

function setUser(user: BackendUser | null) {
	userState.data = user;
	if (browser) {
		if (user) {
			localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
			identifyUser(user);
			startAutoRefresh();
		} else {
			localStorage.removeItem(STORAGE_KEY);
		}
	}
}

function clearUser() {
	userState.data = null;
	autoRefreshStarted = false;
	identifiedUserId = null;
	if (refreshInterval) {
		clearInterval(refreshInterval);
		refreshInterval = null;
	}
	if (browser) {
		if (posthog.__loaded) {
			posthog.reset();
		}
		document.removeEventListener('visibilitychange', handleVisibilityChange);
		localStorage.removeItem(STORAGE_KEY);
	}
}

async function getCurrentUser(): Promise<BackendUser | null> {
	if (!browser) return null;

	const session = await get_session();
	if (!session) {
		clearUser();
		return null;
	}

	if (userState.data) {
		return userState.data;
	}

	const cached = loadCached();
	if (cached) {
		setUser(cached);
		return cached;
	}

	return refreshUser();
}

/** Refresh user data from backend. Use after payment, invite acceptance, etc. */
async function refreshUser(): Promise<BackendUser | null> {
	if (!browser) return null;

	try {
		const session = await get_session();
		if (!session) {
			clearUser();
			return null;
		}

		const user = await me();
		setUser(user);
		lastRefresh = Date.now();
		return user;
	} catch (error) {
		console.error('Failed to refresh user:', error);
		return userState.data;
	}
}

function startAutoRefresh() {
	if (!browser || autoRefreshStarted) return;
	autoRefreshStarted = true;

	if (refreshInterval) clearInterval(refreshInterval);
	refreshInterval = window.setInterval(() => refreshUser(), REFRESH_INTERVAL);
	document.removeEventListener('visibilitychange', handleVisibilityChange);
	document.addEventListener('visibilitychange', handleVisibilityChange);
}

export const currentUser = userState;
export { clearUser, getCurrentUser, refreshUser };
