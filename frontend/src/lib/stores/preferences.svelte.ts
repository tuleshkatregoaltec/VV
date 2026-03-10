/**
 * User preferences store using Svelte 5 runes.
 * Persists to localStorage and provides reactive access to settings.
 */

import { browser } from '$app/environment';
import type { AreaUnit } from '$lib/utils/units';

const STORAGE_KEY = 'vitevue-preferences';

interface UserPreferences {
	areaUnit: AreaUnit;
}

const defaultPreferences: UserPreferences = {
	areaUnit: 'sqm' // Default to metric (raw database values)
};

function loadPreferences(): UserPreferences {
	if (!browser) return defaultPreferences;

	try {
		const stored = localStorage.getItem(STORAGE_KEY);
		if (stored) {
			return { ...defaultPreferences, ...JSON.parse(stored) };
		}
	} catch (e) {
		console.warn('Failed to load preferences from localStorage:', e);
	}

	return defaultPreferences;
}

function savePreferences(prefs: UserPreferences): void {
	if (!browser) return;

	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
	} catch (e) {
		console.warn('Failed to save preferences to localStorage:', e);
	}
}

// Initialize from localStorage
let preferences = $state<UserPreferences>(loadPreferences());

/**
 * Reactive area unit preference
 */
export const areaUnit = {
	get current(): AreaUnit {
		return preferences.areaUnit;
	},
	set current(value: AreaUnit) {
		preferences.areaUnit = value;
		savePreferences(preferences);
	},
	toggle(): void {
		this.current = this.current === 'sqm' ? 'sqft' : 'sqm';
	}
};

/**
 * Check if using metric units
 */
export function isMetric(): boolean {
	return preferences.areaUnit === 'sqm';
}

/**
 * Check if using imperial units
 */
export function isImperial(): boolean {
	return preferences.areaUnit === 'sqft';
}
