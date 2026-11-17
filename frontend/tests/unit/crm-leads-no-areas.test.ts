import { render } from 'svelte/server'
import { describe, expect, it, vi } from 'vitest'
import LeadsPage from '../../src/routes/crm/leads/+page.svelte'

const state = vi.hoisted(() => ({ areas: [] as string[] }))

vi.mock('$app/state', () => ({ page: { url: new URL('http://localhost/crm/leads') } }))
vi.mock('@tanstack/svelte-query', async (importOriginal) => ({
	...(await importOriginal<typeof import('@tanstack/svelte-query')>()),
	createQuery: (options: () => { queryKey: readonly unknown[] }) => {
		const key = options().queryKey
		const kind = key[4] === 'feed' ? 'feed' : key[4]
		if (kind === 'feed') {
			return {
				data: {
					areas: state.areas,
					forward_days: 60,
					lookback_days: 30,
					window_total: 0,
					on_file: 0,
					entered_today: 0
				},
				isError: false
			}
		}
		if (kind === 'leads') {
			return {
				data: {
					items: [],
					counts: { all: 0, lost: 0 },
					areas: [],
					lease_page: undefined
				},
				isError: false
			}
		}
		return { data: undefined, isError: false }
	}
}))

describe('Leads page with no area preferences', () => {
	it('says no areas are chosen and links to choosing them, instead of looking like no leads', () => {
		state.areas = []
		const html = render(LeadsPage).body
		expect(html).toContain('Choose your areas')
		expect(html).toMatch(/no lease leads/i)
	})

	it('shows no such notice once areas are chosen', () => {
		state.areas = ['Dubai Marina']
		const html = render(LeadsPage).body
		expect(html).not.toContain('Choose your areas')
	})
})
