/**
 * Browser storage that belongs to the signed-in person. The Supabase session lives under its own
 * key and is removed by sign-out; everything here is removed on logout and when a session expires
 * so the next person on a shared browser starts clean.
 */
export const PREFERENCES_STORAGE_KEY = 'vitevue-preferences'
export const DASHBOARD_KPI_STORAGE_KEY = 'vitevue-dashboard-kpi-cards'
export const WORKFLOW_CARDS_STORAGE_KEY = 'vitevue-workflow-cards'
export const FILTER_PROPERTY_TYPE_STORAGE_KEY = 'filter-propertyType'
export const FILTER_TIMEFRAME_STORAGE_KEY = 'filter-timeframe'

export const USER_LOCAL_STORAGE_KEYS = [
	PREFERENCES_STORAGE_KEY,
	DASHBOARD_KPI_STORAGE_KEY,
	WORKFLOW_CARDS_STORAGE_KEY,
	FILTER_PROPERTY_TYPE_STORAGE_KEY,
	FILTER_TIMEFRAME_STORAGE_KEY
] as const

export const CHAT_SELECTION_SESSION_PREFIX = 'chat:conversation:'
export const SELECTED_TIER_SESSION_KEY = 'selected_tier'

function sessionKeysToClear(session: Storage): string[] {
	const keys = [SELECTED_TIER_SESSION_KEY]
	for (let index = 0; index < session.length; index += 1) {
		const key = session.key(index)
		if (key?.startsWith(CHAT_SELECTION_SESSION_PREFIX)) keys.push(key)
	}
	return keys
}

export function clearUserBrowserState(
	local: Storage | undefined = typeof localStorage === 'undefined' ? undefined : localStorage,
	session: Storage | undefined = typeof sessionStorage === 'undefined' ? undefined : sessionStorage
): void {
	try {
		for (const key of USER_LOCAL_STORAGE_KEYS) local?.removeItem(key)
	} catch {
		/* Storage can be blocked; there is nothing stored to clear then. */
	}
	try {
		if (session) for (const key of sessionKeysToClear(session)) session.removeItem(key)
	} catch {
		/* See above. */
	}
}
