import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'
import type { AgentLeadMetrics } from '$lib/api/generated/hey-api/types.gen'
import { formatMinutes, qualifiedRate, responseTone, teamAverage } from '$lib/crm/agentMetrics'
import * as backend from '$lib/crm/api/backend'

const agent = (over: Partial<AgentLeadMetrics> = {}): AgentLeadMetrics => ({
	user_id: 'omar',
	name: 'Omar Khan',
	team_ids: ['north'],
	open_leads: 0,
	by_status: {},
	awaiting_first_contact: 0,
	overdue_first_contact: 0,
	contacted_24h: 0,
	avg_first_response_minutes: null,
	avg_claim_minutes: null,
	assigned_in_window: 0,
	qualified_or_better: 0,
	last_activity_at: null,
	...over
})

afterEach(() => vi.restoreAllMocks())

describe('agent metrics display', () => {
	it('formats minutes as the mockup shows them', () => {
		expect(formatMinutes(null)).toBe('—')
		expect(formatMinutes(undefined)).toBe('—')
		expect(formatMinutes(14)).toBe('14 min')
		expect(formatMinutes(160)).toBe('2 h 40 min')
		expect(formatMinutes(120)).toBe('2 h')
	})

	it('marks response times as responsive, watch or slow', () => {
		expect(responseTone(15)).toBe('green')
		expect(responseTone(16)).toBe('amber')
		expect(responseTone(59)).toBe('amber')
		expect(responseTone(60)).toBe('red')
		expect(responseTone(null)).toBe('neutral')
	})

	it('has no qualified rate without leads assigned in the window', () => {
		expect(qualifiedRate(agent())).toBeNull()
		expect(qualifiedRate(agent({ assigned_in_window: 4, qualified_or_better: 1 }))).toBe(25)
	})

	it('averages the team over people who have a figure', () => {
		const team = [
			agent({ avg_first_response_minutes: 10 }),
			agent({ avg_first_response_minutes: null }),
			agent({ avg_first_response_minutes: 21 })
		]
		expect(teamAverage(team, (a) => a.avg_first_response_minutes)).toBe(16)
		expect(teamAverage([agent()], (a) => a.avg_first_response_minutes)).toBeNull()
	})
})

describe('analytics API', () => {
	it('asks for the team over the chosen window', async () => {
		const get = vi.spyOn(client, 'get').mockResolvedValue({ days: 7, agents: [] })
		await backend.teamAnalytics(7)
		expect(get).toHaveBeenCalledWith('/api/v1/crm/assignment/analytics?days=7')
	})

	it('asks for one person by id, safely encoded', async () => {
		const get = vi.spyOn(client, 'get').mockResolvedValue({})
		await backend.agentAnalytics('omar/x', 30)
		expect(get).toHaveBeenCalledWith('/api/v1/crm/assignment/analytics/omar%2Fx?days=30')
	})
})
