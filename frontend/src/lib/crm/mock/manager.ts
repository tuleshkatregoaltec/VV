/**
 * Manager view mockup (context.md, 6 Nov): one fake firm and the pure selectors the page uses.
 * Frontend only: no API, no real roles. The View-as toggle runs everything through `scopeFor`.
 */
import type { LeadStage } from '../api/types'

export type ViewAs = 'manager' | 'agent'
export type MgrStage = Extract<
	LeadStage,
	'new' | 'contacted' | 'viewing' | 'offer' | 'won' | 'lost'
>
export const MGR_STAGES: MgrStage[] = ['new', 'contacted', 'viewing', 'offer', 'won', 'lost']

/** All "now" maths uses this, so the mock looks the same on every load. */
export const MOCK_NOW = '2026-11-06T09:00:00+04:00'
/** The agent you "are" in Agent view. */
export const MOCK_ME_ID = 3

export interface MockAgent {
	id: number
	name: string
	initials: string
	lastActiveAt: string
	replies30d: number
	medianReplyMins: number
	matches30d: number
	overdueFollowUps: number
}

export interface MockLead {
	id: number
	name: string
	phone: string
	email: string
	stage: MgrStage
	agentId: number | null
	valueAed: number
	createdAt: string
	lastAgentReplyAt: string | null
	wonAt: string | null
	source: 'Property Finder' | 'Website' | 'WhatsApp' | 'Referral'
}

export interface MockActivity {
	agentId: number
	at: string
	kind: 'reply' | 'viewing' | 'stage' | 'note'
	/** What happened, never message content (privacy matrix: managers see activity, not messages). */
	text: string
}

export interface TrendDay {
	day: string
	incoming: number
	handled: number
	medianReplyMins: number
}

export interface MgrData {
	agents: MockAgent[]
	leads: MockLead[]
	activity: MockActivity[]
	trend: TrendDay[]
}

export interface TeamKpis {
	activeAgents: number
	openLeads: number
	pipelineAed: number
	wonThisMonth: number
	medianReplyMins: number
	overdueFollowUps: number
}

export interface AgentRow {
	agent: MockAgent
	leads: number
	won: number
	/** null when the agent has no leads: shown as "—", never NaN. */
	conversion: number | null
	rank: number
}

export type SortKey =
	| 'name'
	| 'leads'
	| 'replies'
	| 'response'
	| 'matches'
	| 'deals'
	| 'conversion'
	| 'lastActive'

/* ── time helpers (the firm works in Dubai time, UTC+4, no DST) ── */

const HOUR = 3_600_000
const DUBAI = 4 * HOUR
const ms = (iso: string) => Date.parse(iso)
const iso = (t: number) => new Date(t).toISOString()
/** The Dubai calendar day of a moment, e.g. '2026-11-06'. */
const dubaiDay = (t: number) => iso(t + DUBAI).slice(0, 10)
const isOpen = (l: MockLead) => l.stage !== 'won' && l.stage !== 'lost'

function median(xs: number[]): number {
	if (!xs.length) return 0
	const s = [...xs].sort((a, b) => a - b)
	const m = s.length >> 1
	return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2)
}

/* ── selectors ── */

export function teamKpis(d: MgrData, now: string = MOCK_NOW): TeamKpis {
	const t = ms(now)
	const month = dubaiDay(t).slice(0, 7)
	const open = d.leads.filter(isOpen)
	return {
		activeAgents: d.agents.filter((a) => t - ms(a.lastActiveAt) <= 7 * 24 * HOUR).length,
		openLeads: open.length,
		pipelineAed: open.reduce((n, l) => n + l.valueAed, 0),
		wonThisMonth: d.leads.filter(
			(l) => l.stage === 'won' && l.wonAt && dubaiDay(ms(l.wonAt)).startsWith(month)
		).length,
		medianReplyMins: median(d.agents.map((a) => a.medianReplyMins)),
		overdueFollowUps: d.agents.reduce((n, a) => n + a.overdueFollowUps, 0)
	}
}

/** Null conversion always sorts last, whatever the direction. */
function byConversion(a: AgentRow, b: AgentRow, dir: 1 | -1): number {
	if (a.conversion === null || b.conversion === null)
		return (a.conversion === null ? 1 : 0) - (b.conversion === null ? 1 : 0)
	return (a.conversion - b.conversion) * dir
}

/** Ranked by deals won, then conversion. */
export function leaderboard(d: MgrData): AgentRow[] {
	const rows = d.agents.map((agent) => {
		const mine = d.leads.filter((l) => l.agentId === agent.id)
		const won = mine.filter((l) => l.stage === 'won').length
		return {
			agent,
			leads: mine.length,
			won,
			conversion: mine.length ? Math.round((won / mine.length) * 100) : null,
			rank: 0
		}
	})
	rows.sort(
		(a, b) => b.won - a.won || byConversion(a, b, -1) || a.agent.name.localeCompare(b.agent.name)
	)
	return rows.map((r, i) => ({ ...r, rank: i + 1 }))
}

const SORT_VALUE: Record<Exclude<SortKey, 'name' | 'conversion'>, (r: AgentRow) => number> = {
	leads: (r) => r.leads,
	replies: (r) => r.agent.replies30d,
	response: (r) => r.agent.medianReplyMins,
	matches: (r) => r.agent.matches30d,
	deals: (r) => r.won,
	lastActive: (r) => ms(r.agent.lastActiveAt)
}

/** Returns a new array; null conversion sorts last in both directions. */
export function sortRows(rows: AgentRow[], key: SortKey, dir: 'asc' | 'desc'): AgentRow[] {
	const s = dir === 'asc' ? 1 : -1
	return [...rows].sort((a, b) => {
		if (key === 'name') return a.agent.name.localeCompare(b.agent.name) * s
		if (key === 'conversion') return byConversion(a, b, s)
		return (SORT_VALUE[key](a) - SORT_VALUE[key](b)) * s
	})
}

/** All six stages in pipeline order, zero-filled; one agent's leads when agentId is given. */
export function stageCounts(
	leads: MockLead[],
	agentId?: number | null
): { stage: MgrStage; count: number }[] {
	const pick = agentId == null ? leads : leads.filter((l) => l.agentId === agentId)
	return MGR_STAGES.map((stage) => ({ stage, count: pick.filter((l) => l.stage === stage).length }))
}

export function needsAttention(
	d: MgrData,
	now: string = MOCK_NOW
): { unassigned: MockLead[]; waiting: MockLead[]; overdueAgents: MockAgent[] } {
	const t = ms(now)
	const oldestFirst = (a: MockLead, b: MockLead) => ms(a.createdAt) - ms(b.createdAt)
	return {
		unassigned: d.leads.filter((l) => l.agentId === null && isOpen(l)).sort(oldestFirst),
		waiting: d.leads
			.filter(
				(l) =>
					l.agentId !== null &&
					(l.stage === 'new' || l.stage === 'contacted') &&
					l.lastAgentReplyAt === null &&
					t - ms(l.createdAt) > 24 * HOUR
			)
			.sort(oldestFirst),
		overdueAgents: d.agents
			.filter((a) => a.overdueFollowUps > 0)
			.sort((a, b) => b.overdueFollowUps - a.overdueFollowUps)
	}
}

/**
 * Manager: unchanged. Agent: only my agent record, my leads, my activity. The team trend is scaled
 * down to my share of leads (mock approximation), so an agent never sees team totals.
 */
export function scopeFor(view: ViewAs, d: MgrData, meId: number = MOCK_ME_ID): MgrData {
	if (view === 'manager') return d
	const leads = d.leads.filter((l) => l.agentId === meId)
	const share = d.leads.length ? leads.length / d.leads.length : 0
	const me = d.agents.find((a) => a.id === meId)
	const teamMedian = median(d.agents.map((a) => a.medianReplyMins)) || 1
	const replyRatio = me ? me.medianReplyMins / teamMedian : 1
	return {
		agents: me ? [me] : [],
		leads,
		activity: d.activity.filter((x) => x.agentId === meId),
		trend: d.trend.map((t) => ({
			day: t.day,
			incoming: Math.round(t.incoming * share),
			handled: Math.round(t.handled * share),
			medianReplyMins: Math.round(t.medianReplyMins * replyRatio)
		}))
	}
}

/** '+971 50 123 4567' → '+971 •• ••• ••67'; without spaces only the last two digits stay. */
export function maskPhone(p: string): string {
	const parts = p.trim().split(/\s+/)
	const dots = (s: string, keep = 0) =>
		s.slice(0, s.length - keep).replace(/\d/g, '•') + s.slice(s.length - keep)
	if (parts.length < 2) return dots(parts[0] ?? '', 2)
	return parts.map((s, i) => (i === 0 ? s : dots(s, i === parts.length - 1 ? 2 : 0))).join(' ')
}

/** 'sara.k@gmail.com' → 's•••@gmail.com' */
export function maskEmail(e: string): string {
	const at = e.indexOf('@')
	return at < 1 ? '•••' : `${e[0]}•••${e.slice(at)}`
}

/** How long ago, from MOCK_NOW: '5 min ago', '3 h ago', '9 d ago'. */
export function ago(at: string, now: string = MOCK_NOW): string {
	const m = Math.max(0, Math.round((ms(now) - ms(at)) / 60_000))
	if (m < 60) return m < 1 ? 'just now' : `${m} min ago`
	if (m < 24 * 60) return `${Math.floor(m / 60)} h ago`
	return `${Math.floor(m / (24 * 60))} d ago`
}

/** Reply times: 33 → '33 min', 95 → '1 h 35 min', 120 → '2 h'. */
export function mins(m: number): string {
	if (m < 60) return `${m} min`
	const h = Math.floor(m / 60)
	return m % 60 ? `${h} h ${m % 60} min` : `${h} h`
}

export type PrivacyKey =
	| 'contacts'
	| 'otherLeads'
	| 'phoneEmail'
	| 'messages'
	| 'metrics'
	| 'ranking'

/** The privacy matrix from context.md: the open questions for the call. */
export const PRIVACY: Record<PrivacyKey, { label: string; agent: string; manager: string }> = {
	contacts: { label: 'Own leads and contacts', agent: 'Full', manager: 'Full, or names only?' },
	otherLeads: {
		label: 'Other agents’ leads',
		agent: 'Nothing',
		manager: 'Counts only, or full detail?'
	},
	phoneEmail: {
		label: 'Lead phone/email',
		agent: 'Own only',
		manager: 'Hidden behind “reveal”, or shown?'
	},
	messages: {
		label: 'Inbox / WhatsApp content',
		agent: 'Own',
		manager: 'Probably not: activity stats only'
	},
	metrics: { label: 'Performance metrics', agent: 'Own only', manager: 'Everyone’s' },
	ranking: { label: 'Leaderboard / ranking', agent: 'Hidden, or own rank only?', manager: 'Full' }
}

/* ── the fake firm ── */

/** Small seeded PRNG so the mock is identical on every load. */
function mulberry32(seed: number) {
	let a = seed
	return () => {
		a = (a + 0x6d2b79f5) | 0
		let t = Math.imul(a ^ (a >>> 15), 1 | a)
		t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296
	}
}

function buildMock(): MgrData {
	const rnd = mulberry32(42)
	const int = (lo: number, hi: number) => lo + Math.floor(rnd() * (hi - lo + 1))
	const pick = <T>(xs: readonly T[]) => xs[Math.floor(rnd() * xs.length)]
	const now = ms(MOCK_NOW)
	const ago = (h: number) => iso(now - h * HOUR)

	// Varied on purpose: a clear leader, a slow replier, one overdue-heavy agent, one away for over
	// a week, and a new hire with no leads yet.
	const agents: MockAgent[] = [
		{
			id: 1,
			name: 'Sara Khalil',
			initials: 'SK',
			lastActiveAt: ago(0.3),
			replies30d: 214,
			medianReplyMins: 12,
			matches30d: 48,
			overdueFollowUps: 0
		},
		{
			id: 2,
			name: 'Omar Haddad',
			initials: 'OH',
			lastActiveAt: ago(1.5),
			replies30d: 188,
			medianReplyMins: 18,
			matches30d: 41,
			overdueFollowUps: 1
		},
		{
			id: 3,
			name: 'Priya Nair',
			initials: 'PN',
			lastActiveAt: ago(0.1),
			replies30d: 162,
			medianReplyMins: 22,
			matches30d: 37,
			overdueFollowUps: 2
		},
		{
			id: 4,
			name: 'Daniel Brooks',
			initials: 'DB',
			lastActiveAt: ago(4),
			replies30d: 141,
			medianReplyMins: 35,
			matches30d: 29,
			overdueFollowUps: 0
		},
		{
			id: 5,
			name: 'Fatima Al Mansoori',
			initials: 'FA',
			lastActiveAt: ago(2),
			replies30d: 133,
			medianReplyMins: 27,
			matches30d: 33,
			overdueFollowUps: 3
		},
		{
			id: 6,
			name: 'Yusuf Rahman',
			initials: 'YR',
			lastActiveAt: ago(20),
			replies30d: 97,
			medianReplyMins: 64,
			matches30d: 18,
			overdueFollowUps: 7
		},
		{
			id: 7,
			name: 'Elena Petrova',
			initials: 'EP',
			lastActiveAt: ago(6),
			replies30d: 118,
			medianReplyMins: 31,
			matches30d: 24,
			overdueFollowUps: 1
		},
		{
			id: 8,
			name: 'Karim Aziz',
			initials: 'KA',
			lastActiveAt: ago(30),
			replies30d: 76,
			medianReplyMins: 95,
			matches30d: 12,
			overdueFollowUps: 4
		},
		{
			id: 9,
			name: 'Aisha Siddiqui',
			initials: 'AS',
			lastActiveAt: ago(9 * 24),
			replies30d: 41,
			medianReplyMins: 48,
			matches30d: 7,
			overdueFollowUps: 0
		},
		{
			id: 10,
			name: 'Marco Rossi',
			initials: 'MR',
			lastActiveAt: ago(3),
			replies30d: 9,
			medianReplyMins: 40,
			matches30d: 2,
			overdueFollowUps: 0
		}
	]

	const FIRST = [
		'Ahmed',
		'Hannah',
		'Rahul',
		'Mariam',
		'James',
		'Noor',
		'Ivan',
		'Layla',
		'Chen',
		'Zara',
		'Lucas',
		'Huda',
		'Arjun',
		'Sofia',
		'Khalid',
		'Emma',
		'Tariq',
		'Mei',
		'Ravi',
		'Dina'
	]
	const LAST = [
		'Saleh',
		'Miller',
		'Kapoor',
		'Hassan',
		'Clarke',
		'Farouk',
		'Volkov',
		'Ibrahim',
		'Wang',
		'Qureshi',
		'Silva',
		'Nasser',
		'Mehta',
		'Rossi',
		'Obeid',
		'Grant'
	]
	const SOURCES = ['Property Finder', 'Website', 'WhatsApp', 'Referral'] as const
	const DOMAINS = ['gmail.com', 'outlook.com', 'icloud.com', 'yahoo.com']

	let nextId = 1001
	function person() {
		const first = pick(FIRST)
		const last = pick(LAST)
		return {
			id: nextId++,
			name: `${first} ${last}`,
			phone: `+971 5${pick([0, 2, 4, 5, 6, 8])} ${int(100, 999)} ${int(1000, 9999)}`,
			email: `${first.toLowerCase()}.${last[0].toLowerCase()}@${pick(DOMAINS)}`,
			valueAed: int(8, 120) * 100_000,
			source: pick(SOURCES)
		}
	}

	// Leads the needs-attention section must always have: unassigned, and waiting over 24h
	// (one of them mine, so the Agent view has its own).
	const leads: MockLead[] = []
	for (const h of [3, 14, 31, 52]) {
		leads.push({
			...person(),
			stage: 'new',
			agentId: null,
			createdAt: ago(h),
			lastAgentReplyAt: null,
			wonAt: null
		})
	}
	for (const [agentId, h] of [
		[MOCK_ME_ID, 29],
		[6, 47],
		[8, 70],
		[6, 36]
	] as const) {
		leads.push({
			...person(),
			stage: pick(['new', 'contacted'] as const),
			agentId,
			createdAt: ago(h),
			lastAgentReplyAt: null,
			wonAt: null
		})
	}

	// The rest: handled leads over the last 45 days. Wins per agent are fixed so the leaderboard reads
	// believably (fast, busy agents win most; "me", agent 3, comes third); the new hire has none.
	const WINS: Record<number, number> = { 1: 7, 2: 5, 3: 4, 4: 3, 5: 3, 6: 1, 7: 2, 8: 0, 9: 1 }
	const NOT_WON: Record<number, number> = { 1: 8, 2: 7, 3: 7, 4: 6, 5: 6, 6: 5, 7: 5, 8: 5, 9: 3 }
	const OTHER_STAGES: MgrStage[] = [
		'new',
		'contacted',
		'contacted',
		'viewing',
		'viewing',
		'offer',
		'lost',
		'lost'
	]
	function handled(agentId: number, stage: MgrStage): MockLead {
		const created = now - (stage === 'new' ? int(1, 20) : int(24, 45 * 24)) * HOUR
		const won = stage === 'won' ? Math.min(now - HOUR, created + int(3, 20) * 24 * HOUR) : null
		return {
			...person(),
			stage,
			agentId,
			createdAt: iso(created),
			lastAgentReplyAt: iso(created + int(5, 180) * 60_000),
			wonAt: won === null ? null : iso(won)
		}
	}
	for (const [id, n] of Object.entries(WINS))
		for (let i = 0; i < n; i++) leads.push(handled(+id, 'won'))
	for (const [id, n] of Object.entries(NOT_WON)) {
		for (let i = 0; i < n; i++) leads.push(handled(+id, pick(OTHER_STAGES)))
	}
	// One of my wins lands this month, so the Agent view's "won this month" tile isn't a bare 0.
	const myWin = leads.find((l) => l.agentId === MOCK_ME_ID && l.stage === 'won')
	if (myWin) {
		myWin.createdAt = ago(18 * 24)
		myWin.lastAgentReplyAt = ago(18 * 24 - 0.5)
		myWin.wonAt = ago(3 * 24)
	}

	const activity: MockActivity[] = []
	for (let i = 0; i < 40; i++) {
		const l = pick(leads.filter((x) => x.agentId !== null))
		const kind = pick(['reply', 'reply', 'viewing', 'stage', 'note'] as const)
		const text = {
			reply: `Replied to ${l.name}`,
			viewing: `Booked a viewing with ${l.name}`,
			stage: `Moved ${l.name} to ${pick(['Contacted', 'Viewing', 'Offer'])}`,
			note: `Added a note on ${l.name}`
		}[kind]
		activity.push({ agentId: l.agentId as number, at: ago(int(1, 7 * 24 * 4) / 4), kind, text })
	}
	activity.sort((a, b) => ms(b.at) - ms(a.at))

	const trend: TrendDay[] = []
	for (let d = 29; d >= 0; d--) {
		const incoming = int(4, 14)
		trend.push({
			day: dubaiDay(now - d * 24 * HOUR),
			incoming,
			handled: Math.max(0, incoming - int(0, 3)),
			medianReplyMins: int(18, 55)
		})
	}

	return { agents, leads, activity, trend }
}

export const MOCK: MgrData = buildMock()
