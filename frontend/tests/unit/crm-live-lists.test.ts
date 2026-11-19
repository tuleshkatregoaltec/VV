import { describe, expect, it } from 'vitest'
import { crmQueries } from '$lib/crm/queries'

describe('lead lists stay live', () => {
	it('refresh leads, counts and the manager figures on returning to the tab and every 30 seconds', () => {
		for (const q of [
			crmQueries.leads({}),
			crmQueries.counts(),
			crmQueries.dealOversight(),
			crmQueries.teamAnalytics(30),
			crmQueries.agentAnalytics('omar', 30),
			crmQueries.workload()
		]) {
			expect(q.refetchOnWindowFocus).toBe(true)
			expect(q.refetchInterval).toBe(30_000)
		}
	})

	it('refresh Home every minute (it also syncs the week with Google)', () => {
		const q = crmQueries.home('')
		expect(q.refetchOnWindowFocus).toBe(true)
		expect(q.refetchInterval).toBe(60_000)
	})
})
