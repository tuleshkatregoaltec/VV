import { browser } from '$app/environment';
import { me, identifyUser, get_session, type BackendUser } from '$lib/api/auth';

const STORAGE_KEY = 'vitevue-user';
const REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes

// Wrap state in an object so we mutate properties instead of reassigning
const userState = $state<{ data: BackendUser | null }>({ data: null });

let loadInitiated = false;
let refreshInterval: number | null = null;
let lastRefresh = 0;

/**
 * Load user data from localStorage cache first, then sync with backend
 */
async function loadUser() {
	if (!browser || loadInitiated) return;
	
	loadInitiated = true;
	
	try {
		// Try to load from cache first
		const cached = localStorage.getItem(STORAGE_KEY);
		if (cached) {
			try {
				userState.data = JSON.parse(cached);
				identifyUser(userState.data!);
			} catch (e) {
				console.warn('Failed to parse cached user data:', e);
			}
		}

		// Then sync with backend in the background
		const session = await get_session();
		if (!session) {
			userState.data = null;
			localStorage.removeItem(STORAGE_KEY);
			return;
		}

		const user = await me();
		userState.data = user;
		localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
		
		identifyUser(user);
	} catch (error) {
		console.error('Failed to load user:', error);
		// Keep cached data if backend fails
		if (!userState.data) {
			userState.data = null;
		}
	}
}

function clearUser() {
	userState.data = null;
	loadInitiated = false;
	if (browser) {
		localStorage.removeItem(STORAGE_KEY);
	}
}

function invalidateUser() {
	clearUser();
}

function setUser(user: BackendUser | null) {
	userState.data = user;
	if (browser) {
		if (user) {
			localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
		} else {
			localStorage.removeItem(STORAGE_KEY);
		}
	}
}

/**
 * Refresh user data from backend (strategic refresh)
 * Use after: payment, invite acceptance, or manual refresh
 */
async function refreshUser(): Promise<void> {
	if (!browser) return;

	try {
		const session = await get_session();
		if (!session) {
			clearUser();
			return;
		}

		const user = await me();
		setUser(user);
		identifyUser(user);
		lastRefresh = Date.now();
	} catch (error) {
		console.error('Failed to refresh user:', error);
	}
}

/**
 * Setup automatic user refresh
 * - Every 5 minutes
 * - On visibility change (user returns to tab)
 */
function setupAutoRefresh() {
	if (!browser) return;

	// Periodic refresh (every 5 minutes)
	if (refreshInterval) {
		clearInterval(refreshInterval);
	}
	refreshInterval = window.setInterval(async () => {
		await refreshUser();
	}, REFRESH_INTERVAL);

	// Refresh on visibility change (user returns to tab)
	const handleVisibilityChange = async () => {
		if (!document.hidden) {
			// Only refresh if last refresh was more than 1 minute ago
			if (Date.now() - lastRefresh > 60 * 1000) {
				await refreshUser();
			}
		}
	};

	document.addEventListener('visibilitychange', handleVisibilityChange);
}

// Auto-initialize when store is first imported
if (browser) {
	loadUser();
	setupAutoRefresh();
}

/**
 * Current user - access via currentUser.data
 */
export const currentUser = userState;

export { loadUser, clearUser, invalidateUser, setUser, refreshUser };
