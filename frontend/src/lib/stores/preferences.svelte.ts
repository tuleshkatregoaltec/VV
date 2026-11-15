/**
 * User preferences store using Svelte 5 runes.
 * Persists to localStorage and provides reactive access to settings.
 */

import { browser } from '$app/environment'
import { PREFERENCES_STORAGE_KEY } from '$lib/auth/user-browser-state'

const STORAGE_KEY = PREFERENCES_STORAGE_KEY

export type ThemePreference = 'system' | 'light' | 'dark'
export type ResolvedTheme = 'light' | 'dark'

interface UserPreferences {
	theme: ThemePreference
}

const defaultPreferences: UserPreferences = {
	theme: 'system'
}

function isThemePreference(value: unknown): value is ThemePreference {
	return value === 'system' || value === 'light' || value === 'dark'
}

function normalizePreferences(value: Partial<UserPreferences>): UserPreferences {
	return {
		theme: isThemePreference(value.theme) ? value.theme : defaultPreferences.theme
	}
}

function loadPreferences(): UserPreferences {
	if (!browser) return defaultPreferences

	try {
		const stored = localStorage.getItem(STORAGE_KEY)
		if (stored) {
			return normalizePreferences({ ...defaultPreferences, ...JSON.parse(stored) })
		}
	} catch (e) {
		console.warn('Failed to load preferences from localStorage:', e)
	}

	return defaultPreferences
}

function savePreferences(prefs: UserPreferences): void {
	if (!browser) return

	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs))
	} catch (e) {
		console.warn('Failed to save preferences to localStorage:', e)
	}
}

// Initialize from localStorage
const preferences = $state<UserPreferences>(loadPreferences())
let systemTheme = $state<ResolvedTheme>(
	browser && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
)

function resolveThemePreference(value: ThemePreference): ResolvedTheme {
	return value === 'system' ? systemTheme : value
}

function applyTheme(value: ThemePreference = preferences.theme): void {
	if (!browser) return

	const resolved = resolveThemePreference(value)
	const root = document.documentElement
	root.dataset.theme = resolved
	root.dataset.themePreference = value
	root.style.colorScheme = resolved

	document
		.querySelector('meta[name="theme-color"]')
		?.setAttribute('content', resolved === 'dark' ? '#0A0F18' : '#0B1B2B')
}

if (browser) {
	const themeQuery = window.matchMedia('(prefers-color-scheme: dark)')
	const handleSystemThemeChange = (event: MediaQueryListEvent) => {
		systemTheme = event.matches ? 'dark' : 'light'
		if (preferences.theme === 'system') applyTheme('system')
	}

	themeQuery.addEventListener('change', handleSystemThemeChange)
	applyTheme(preferences.theme)
}

/**
 * Reactive color theme preference.
 */
export const colorTheme = {
	get current(): ThemePreference {
		return preferences.theme
	},
	set current(value: ThemePreference) {
		preferences.theme = value
		savePreferences(preferences)
		applyTheme(value)
	},
	get resolved(): ResolvedTheme {
		return resolveThemePreference(preferences.theme)
	},
	toggle(): void {
		this.current = this.resolved === 'dark' ? 'light' : 'dark'
	}
}
