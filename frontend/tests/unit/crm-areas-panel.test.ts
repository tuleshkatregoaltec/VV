import { render } from 'svelte/server'
import { describe, expect, it, vi } from 'vitest'

// No DOM environment: the selection rules are pure functions; the panel's states by server
// render with the two queries mocked (as in crm-collections-ui.test.ts).
const q = vi.hoisted(() => ({ areas: undefined as unknown, saved: undefined as unknown }))

vi.mock('@tanstack/svelte-query', async (orig) => ({
	...(await orig<typeof import('@tanstack/svelte-query')>()),
	createQuery: (fn: () => { queryKey: unknown[] }) =>
		fn().queryKey.includes('preferences') ? q.saved : q.areas
}))
vi.mock('$lib/crm/api', () => ({ crm: { feed: { setPreferences: vi.fn() } } }))

import { allSelected, matchingAreas, setAll } from '$lib/crm/areaSelection'
import AreasPanel from '$lib/crm/components/panels/AreasPanel.svelte'

const AREAS = ['Dubai Marina', 'JVC', 'Jumeirah Lake Towers', 'Business Bay']
const rows = AREAS.map((area, index) => ({ area, owners_in_90_day_window: index + 1 }))

describe('All areas stays in sync with the individual checkboxes', () => {
	it('selecting all checks every area, unchecking one clears it, selecting all restores', () => {
		let selected = setAll(AREAS, new Set(), true)
		expect([...selected].sort()).toEqual([...AREAS].sort())
		expect(allSelected(AREAS, selected)).toBe(true)

		selected = new Set(selected)
		selected.delete('JVC')
		expect(allSelected(AREAS, selected)).toBe(false)

		selected = setAll(AREAS, selected, true)
		expect(allSelected(AREAS, selected)).toBe(true)
		expect(setAll(AREAS, selected, false).size).toBe(0)
	})

	it('is never "all selected" with no areas to choose from', () => {
		expect(allSelected([], new Set(['Dubai Marina']))).toBe(false)
	})
})

describe('area search filters what is shown, never what is selected', () => {
	it('matches names case-insensitively and shows everything when empty', () => {
		expect(matchingAreas(rows, 'jumeirah').map((r) => r.area)).toEqual(['Jumeirah Lake Towers'])
		expect(matchingAreas(rows, '  MARINA ').map((r) => r.area)).toEqual(['Dubai Marina'])
		expect(matchingAreas(rows, '')).toEqual(rows)
	})

	it('keeps selections the search hides, including when selecting all from a filtered view', () => {
		const selected = new Set(['Dubai Marina', 'Business Bay'])
		const shown = matchingAreas(rows, 'jvc')
		expect(shown.map((r) => r.area)).toEqual(['JVC'])
		// Filtering creates no new set: hidden picks are untouched.
		expect([...selected]).toEqual(['Dubai Marina', 'Business Bay'])
		// "All areas" means all of them, not only the matches on screen.
		expect(allSelected(AREAS, setAll(AREAS, selected, true))).toBe(true)
	})
})

describe('My areas panel', () => {
	function panel(saved: string[]) {
		q.areas = { data: rows, isError: false, error: null, refetch: vi.fn() }
		q.saved = {
			data: { areas: saved, forward_days: 60, lookback_days: 30 },
			isError: false,
			error: null,
			refetch: vi.fn()
		}
		return render(AreasPanel).body
	}

	it('shows All areas, a search field, every area with its count, the dates and Save', () => {
		const html = panel(['JVC'])
		expect(html).toContain('All areas')
		expect(html).toContain('Search areas')
		expect(html).toMatch(/type="search"/)
		for (const area of AREAS) expect(html).toContain(area)
		expect(html).toContain('Lease ends in the next (days)')
		expect(html).toContain('Or ended in the last (days)')
		expect(html).toContain('Save')
		expect(html).toContain('1 chosen')
	})

	it('checks All areas only when every area is selected', () => {
		const checkedLabels = (html: string) =>
			[
				...html.matchAll(/<input type="checkbox"[^>]*checked[^>]*\/?>\s*<span>([^<]+)<\/span>/g)
			].map((match) => match[1])
		expect(checkedLabels(panel(AREAS))).toEqual(['All areas', ...AREAS])
		expect(checkedLabels(panel(['JVC']))).toEqual(['JVC'])
	})
})
