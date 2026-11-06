import { describe, expect, it } from 'vitest'

import {
	type AgentRow,
	ago,
	leaderboard,
	MGR_STAGES,
	type MgrData,
	MOCK,
	MOCK_ME_ID,
	MOCK_NOW,
	type MockAgent,
	type MockLead,
	maskEmail,
	maskPhone,
	mins,
	needsAttention,
	scopeFor,
	sortRows,
	stageCounts,
	teamKpis
} from '$lib/crm/mock/manager'

// The manager view mockup (context.md, 6 Nov) runs on fake data, but the numbers it shows on the
// review call must add up, and the Agent view must never show another agent's leads: that
// privacy split is what the call is about.

const NOW = MOCK_NOW
const hoursAgo = (h: number) => new Date(Date.parse(NOW) - h * 3_600_000).toISOString()

function agent(id: number, over: Partial<MockAgent> = {}): MockAgent {
	return {
		id,
		name: `Agent ${id}`,
		initials: `A${id}`,
		lastActiveAt: hoursAgo(1),
		replies30d: 10,
		medianReplyMins: 30,
		matches30d: 5,
		overdueFollowUps: 0,
		...over
	}
}

function lead(id: number, over: Partial<MockLead> = {}): MockLead {
	return {
		id,
		name: `Lead ${id}`,
		phone: '+971 50 123 4567',
		email: 'lead@example.com',
		stage: 'contacted',
		agentId: 1,
		valueAed: 1_000_000,
		createdAt: hoursAgo(48),
		lastAgentReplyAt: hoursAgo(47),
		wonAt: null,
		source: 'Website',
		...over
	}
}

const data = (agents: MockAgent[], leads: MockLead[]): MgrData => ({
	agents,
	leads,
	activity: [],
	trend: []
})

describe('teamKpis', () => {
	it('counts open leads as everything not won or lost, and pipeline as their value', () => {
		const k = teamKpis(
			data(
				[agent(1)],
				[
					lead(1, { stage: 'new', valueAed: 1_000_000 }),
					lead(2, { stage: 'offer', valueAed: 2_000_000 }),
					lead(3, { stage: 'won', valueAed: 3_000_000, wonAt: hoursAgo(5) }),
					lead(4, { stage: 'lost', valueAed: 4_000_000 })
				]
			),
			NOW
		)
		expect(k.openLeads).toBe(2)
		expect(k.pipelineAed).toBe(3_000_000)
	})

	it('counts deals won in the calendar month of now only, in Dubai time', () => {
		const k = teamKpis(
			data(
				[agent(1)],
				[
					lead(1, { stage: 'won', wonAt: '2026-11-02T10:00:00+04:00' }),
					lead(2, { stage: 'won', wonAt: '2026-10-30T10:00:00+04:00' }),
					// 22:00 UTC on 31 Oct is already 1 Nov in Dubai, where the firm works.
					lead(3, { stage: 'won', wonAt: '2026-10-31T22:00:00Z' })
				]
			),
			NOW
		)
		expect(k.wonThisMonth).toBe(2)
	})

	it('counts an agent as active when last active within 7 days', () => {
		const k = teamKpis(
			data(
				[
					agent(1, { lastActiveAt: hoursAgo(6 * 24) }),
					agent(2, { lastActiveAt: hoursAgo(8 * 24) })
				],
				[]
			),
			NOW
		)
		expect(k.activeAgents).toBe(1)
	})

	it('takes the median of agent reply times, not the mean, and sums overdue follow-ups', () => {
		// One very slow agent must not drag the team figure: that is why it is a median.
		const k = teamKpis(
			data(
				[
					agent(1, { medianReplyMins: 10, overdueFollowUps: 2 }),
					agent(2, { medianReplyMins: 20, overdueFollowUps: 0 }),
					agent(3, { medianReplyMins: 600, overdueFollowUps: 5 })
				],
				[]
			),
			NOW
		)
		expect(k.medianReplyMins).toBe(20)
		expect(k.overdueFollowUps).toBe(7)
	})
})

describe('leaderboard', () => {
	it('ranks by deals won, then conversion', () => {
		const rows = leaderboard(
			data(
				[agent(1), agent(2), agent(3)],
				[
					lead(1, { agentId: 1, stage: 'won' }),
					lead(2, { agentId: 1 }),
					lead(3, { agentId: 1 }),
					lead(4, { agentId: 2, stage: 'won' }),
					lead(5, { agentId: 2, stage: 'won' }),
					lead(6, { agentId: 3, stage: 'won' })
				]
			)
		)
		// Agent 2 won most; agents 1 and 3 won one each, but 3 converted 100% vs 33%.
		expect(rows.map((r) => [r.agent.id, r.rank])).toEqual([
			[2, 1],
			[3, 2],
			[1, 3]
		])
	})

	it('gives an agent with no leads a null conversion, never NaN', () => {
		const [row] = leaderboard(data([agent(1)], []))
		expect(row.leads).toBe(0)
		expect(row.conversion).toBeNull()
	})

	it('computes conversion as won / assigned leads, as a whole percent', () => {
		const [row] = leaderboard(
			data(
				[agent(1)],
				[
					lead(1, { stage: 'won' }),
					lead(2),
					lead(3),
					lead(4, { stage: 'lost' }),
					lead(5, { agentId: null })
				]
			)
		)
		expect(row.leads).toBe(4)
		expect(row.won).toBe(1)
		expect(row.conversion).toBe(25)
	})
})

describe('sortRows', () => {
	const rows: AgentRow[] = leaderboard(
		data(
			[agent(1, { name: 'Bea' }), agent(2, { name: 'Ali' }), agent(3, { name: 'Cy' })],
			[lead(1, { agentId: 1, stage: 'won' }), lead(2, { agentId: 3 })]
		)
	)

	it('sorts null conversion last in both directions', () => {
		// Agent 2 has no leads: "no data" is not "worst" or "best", so it stays at the bottom.
		expect(sortRows(rows, 'conversion', 'desc').map((r) => r.agent.id)).toEqual([1, 3, 2])
		expect(sortRows(rows, 'conversion', 'asc').map((r) => r.agent.id)).toEqual([3, 1, 2])
	})

	it('sorts names alphabetically', () => {
		expect(sortRows(rows, 'name', 'asc').map((r) => r.agent.name)).toEqual(['Ali', 'Bea', 'Cy'])
	})

	it('does not mutate its input', () => {
		const before = rows.map((r) => r.agent.id)
		sortRows(rows, 'name', 'asc')
		expect(rows.map((r) => r.agent.id)).toEqual(before)
	})
})

describe('stageCounts', () => {
	it('returns all six stages in pipeline order, zero-filled', () => {
		expect(stageCounts([])).toEqual(MGR_STAGES.map((stage) => ({ stage, count: 0 })))
		expect(MGR_STAGES).toEqual(['new', 'contacted', 'viewing', 'offer', 'won', 'lost'])
	})

	it('filters to one agent when agentId is given', () => {
		const leads = [
			lead(1, { agentId: 1, stage: 'new' }),
			lead(2, { agentId: 2, stage: 'new' }),
			lead(3, { agentId: 1 })
		]
		const counts = Object.fromEntries(stageCounts(leads, 1).map((s) => [s.stage, s.count]))
		expect(counts).toMatchObject({ new: 1, contacted: 1 })
		expect(stageCounts(leads).find((s) => s.stage === 'new')?.count).toBe(2)
	})
})

describe('needsAttention', () => {
	it('lists open leads with no agent as unassigned', () => {
		const a = needsAttention(
			data(
				[agent(1)],
				[lead(1, { agentId: null }), lead(2, { agentId: null, stage: 'lost' }), lead(3)]
			),
			NOW
		)
		expect(a.unassigned.map((l) => l.id)).toEqual([1])
	})

	it('lists assigned new/contacted leads older than 24h with no agent reply as waiting', () => {
		const a = needsAttention(
			data(
				[agent(1)],
				[
					lead(1, { stage: 'new', createdAt: hoursAgo(25), lastAgentReplyAt: null }),
					lead(2, { stage: 'new', createdAt: hoursAgo(23), lastAgentReplyAt: null }),
					lead(3, { stage: 'contacted', createdAt: hoursAgo(30), lastAgentReplyAt: hoursAgo(29) }),
					lead(4, { stage: 'contacted', createdAt: hoursAgo(50), lastAgentReplyAt: null }),
					lead(5, { stage: 'viewing', createdAt: hoursAgo(50), lastAgentReplyAt: null })
				]
			),
			NOW
		)
		// Oldest first: the longest wait is the most urgent.
		expect(a.waiting.map((l) => l.id)).toEqual([4, 1])
	})

	it('lists agents with overdue follow-ups, most overdue first', () => {
		const a = needsAttention(
			data([agent(1, { overdueFollowUps: 2 }), agent(2), agent(3, { overdueFollowUps: 6 })], []),
			NOW
		)
		expect(a.overdueAgents.map((x) => x.id)).toEqual([3, 1])
	})
})

describe('scopeFor', () => {
	it('returns data unchanged for a manager', () => {
		expect(scopeFor('manager', MOCK)).toBe(MOCK)
	})

	it('keeps only my agent record, my leads and my activity for an agent', () => {
		const mine = scopeFor('agent', MOCK, MOCK_ME_ID)
		expect(mine.agents.map((a) => a.id)).toEqual([MOCK_ME_ID])
		expect(mine.leads.length).toBeGreaterThan(0)
		expect(mine.leads.every((l) => l.agentId === MOCK_ME_ID)).toBe(true)
		expect(mine.activity.every((x) => x.agentId === MOCK_ME_ID)).toBe(true)
	})

	it('drops unassigned leads from the agent view', () => {
		const mine = scopeFor('agent', MOCK, MOCK_ME_ID)
		expect(mine.leads.some((l) => l.agentId === null)).toBe(false)
	})

	it('shows an agent a smaller trend than the team, never the team totals', () => {
		const sum = (d: MgrData) => d.trend.reduce((n, t) => n + t.incoming, 0)
		const mine = scopeFor('agent', MOCK, MOCK_ME_ID)
		expect(mine.trend).toHaveLength(MOCK.trend.length)
		expect(sum(mine)).toBeLessThan(sum(MOCK))
	})
})

describe('ago', () => {
	// "Last active" tells a manager at a glance who has gone quiet, so days must read as days.
	it('reads minutes, hours, then days', () => {
		expect(ago(hoursAgo(0.25), NOW)).toBe('15 min ago')
		expect(ago(hoursAgo(5), NOW)).toBe('5 h ago')
		expect(ago(hoursAgo(9 * 24 + 3), NOW)).toBe('9 d ago')
	})
})

describe('mins', () => {
	// Reply times run from minutes to hours; "95 min" is harder to read on a KPI tile than "1 h 35 min".
	it('shows minutes under an hour, hours and minutes above', () => {
		expect(mins(33)).toBe('33 min')
		expect(mins(95)).toBe('1 h 35 min')
		expect(mins(120)).toBe('2 h')
	})
})

describe('masking', () => {
	it('keeps country code and last two digits of a phone', () => {
		expect(maskPhone('+971 50 123 4567')).toBe('+971 •• ••• ••67')
	})

	it('keeps only the last two digits of a phone without spaces', () => {
		expect(maskPhone('+971501234567')).toBe('+••••••••••67')
	})

	it('keeps the first letter and domain of an email', () => {
		expect(maskEmail('sara.k@gmail.com')).toBe('s•••@gmail.com')
	})
})

describe('MOCK', () => {
	it('is one firm of 10 agents whose leads point at real agents or nobody', () => {
		expect(MOCK.agents).toHaveLength(10)
		const ids = new Set(MOCK.agents.map((a) => a.id))
		expect(MOCK.leads.every((l) => l.agentId === null || ids.has(l.agentId))).toBe(true)
		expect(new Set(MOCK.leads.map((l) => l.id)).size).toBe(MOCK.leads.length)
	})

	it('has an agent with no leads, so the leaderboard shows the "—" case', () => {
		expect(leaderboard(MOCK).some((r) => r.conversion === null)).toBe(true)
	})

	it('has something in every needs-attention list, so the call sees each one', () => {
		const a = needsAttention(MOCK)
		expect(a.unassigned.length).toBeGreaterThanOrEqual(3)
		expect(a.waiting.length).toBeGreaterThanOrEqual(3)
		expect(a.overdueAgents.length).toBeGreaterThan(0)
		expect(a.waiting.some((l) => l.agentId === MOCK_ME_ID)).toBe(true)
	})

	it('gives "me" a win this month, so the Agent view tile is not a bare 0', () => {
		expect(teamKpis(scopeFor('agent', MOCK)).wonThisMonth).toBeGreaterThan(0)
	})

	it('has 30 trend days ending the day of MOCK_NOW', () => {
		expect(MOCK.trend).toHaveLength(30)
		expect(MOCK.trend.at(-1)?.day).toBe('2026-11-06')
	})

	it('is the same on every load', () => {
		expect(MOCK.leads.length).toBeGreaterThan(50)
		expect(teamKpis(MOCK)).toEqual(teamKpis(MOCK))
	})
})
