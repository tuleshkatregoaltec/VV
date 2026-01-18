import { browser } from '$app/environment';
import { me, identifyUser, get_session, type BackendUser } from '$lib/api/auth';

let currentUser = $state<BackendUser | null>(null);

let loadInitiated = false;

/**
 * Load user data from backend and identify with PostHog
 */
async function loadUser() {
	if (!browser || loadInitiated) return;
	
	loadInitiated = true;
	
	try {
		const session = await get_session();
		if (!session) {
			currentUser = null;
			return;
		}

		const user = await me();
		currentUser = user;
		
		identifyUser(user);
	} catch (error) {
		console.error('Failed to load user:', error);
		currentUser = null;
	}
}

function clearUser() {
	currentUser = null;
	loadInitiated = false;
}

// Auto-initialize when store is first imported
if (browser) {
	loadUser();
}

export { currentUser, loadUser, clearUser };
