import posthog from 'posthog-js'
import { browser } from '$app/environment'
import { type AuthMeResponse, get_session, me, on_auth_state_change } from '$lib/api/auth'

const REFRESH_INTERVAL = 5 * 60 * 1000 // 5 minutes

const userState = $state<{ data: AuthMeResponse | null }>({ data: null })

let refreshInterval: number | null = null
let lastRefresh = 0
let identityVersion = 0
let autoRefreshStarted = false
let identifiedUserId: string | null = null
const userListeners = new Set<(user: AuthMeResponse | null) => void>()

/** Synchronous identity notifications let private caches clear before the next render. */
export function subscribeUser(listener: (user: AuthMeResponse | null) => void): () => void {
	userListeners.add(listener)
	listener(userState.data)
	return () => {
		userListeners.delete(listener)
	}
}

function handleVisibilityChange() {
	if (!document.hidden && Date.now() - lastRefresh > 60 * 1000) {
		refreshUser()
	}
}

function identifyUser(user: AuthMeResponse) {
	if (browser && posthog.__loaded && identifiedUserId !== user.id) {
		posthog.identify(user.id, {
			email: user.email,
			first_name: user.first_name,
			last_name: user.last_name,
			organization_id: user.organization_id,
			organization_name: user.organization_name
		})
		identifiedUserId = user.id
	}
}

function setUser(user: AuthMeResponse | null) {
	userState.data = user
	for (const listener of userListeners) listener(user)
	if (browser && user) {
		identifyUser(user)
		startAutoRefresh()
	}
}

function clearUser() {
	identityVersion += 1
	userState.data = null
	for (const listener of userListeners) listener(null)
	autoRefreshStarted = false
	identifiedUserId = null
	if (refreshInterval) {
		clearInterval(refreshInterval)
		refreshInterval = null
	}
	if (browser) {
		if (posthog.__loaded) {
			posthog.reset()
		}
		document.removeEventListener('visibilitychange', handleVisibilityChange)
	}
}

async function getCurrentUser(): Promise<AuthMeResponse | null> {
	if (!browser) return null

	const session = await get_session()
	if (!session) {
		clearUser()
		return null
	}

	if (userState.data && userState.data.id === session.user.id) {
		return userState.data
	}

	if (userState.data && userState.data.id !== session.user.id) clearUser()
	return refreshUser()
}

/** Refresh user data from backend. Use after payment, invite acceptance, etc. */
async function refreshUser(): Promise<AuthMeResponse | null> {
	if (!browser) return null

	try {
		const session = await get_session()
		if (!session) {
			clearUser()
			return null
		}

		if (userState.data && userState.data.id !== session.user.id) clearUser()
		const version = identityVersion
		const user = await me()
		if (version !== identityVersion) return userState.data
		setUser(user)
		lastRefresh = Date.now()
		return user
	} catch (error) {
		console.error('Failed to refresh user:', error)
		return userState.data
	}
}

function startAutoRefresh() {
	if (!browser || autoRefreshStarted) return
	autoRefreshStarted = true

	if (refreshInterval) clearInterval(refreshInterval)
	refreshInterval = window.setInterval(() => refreshUser(), REFRESH_INTERVAL)
	document.removeEventListener('visibilitychange', handleVisibilityChange)
	document.addEventListener('visibilitychange', handleVisibilityChange)
}

if (browser) {
	on_auth_state_change((event, session) => {
		if (
			event === 'SIGNED_OUT' ||
			(event === 'SIGNED_IN' && userState.data?.id !== session?.user.id)
		) {
			clearUser()
		}
	})
}

export const currentUser = userState
export { clearUser, getCurrentUser, refreshUser }
