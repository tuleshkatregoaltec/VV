import { browser } from '$app/environment';
import { me, identifyUser, get_session, type BackendUser } from '$lib/api/auth';

// Wrap state in an object so we mutate properties instead of reassigning
const userState = $state<{ data: BackendUser | null }>({ data: null });

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
			userState.data = null;
			return;
		}

		const user = await me();
		userState.data = user;
		
		identifyUser(user);
	} catch (error) {
		console.error('Failed to load user:', error);
		userState.data = null;
	}
}

function clearUser() {
	userState.data = null;
	loadInitiated = false;
}

// Auto-initialize when store is first imported
if (browser) {
	loadUser();
}

/**
 * Current user - access via currentUser.data
 */
export const currentUser = userState;

export { loadUser, clearUser };
