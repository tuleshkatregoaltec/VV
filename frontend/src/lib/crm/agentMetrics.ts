/**
 * Agent lead analytics display (manager screens, agreed 17 Nov 2026). The server computes every
 * figure; these helpers only format them and derive the team average for comparison.
 */
import type { AgentLeadMetrics } from '$lib/api/generated/hey-api/types.gen'

export type AnalyticsDays = 7 | 30 | 90

export const ANALYTICS_WINDOWS: { id: `${AnalyticsDays}`; label: string }[] = [
	{ id: '7', label: 'Last 7 days' },
	{ id: '30', label: 'Last 30 days' },
	{ id: '90', label: 'This quarter' }
]

/** "—" with no figure; "14 min"; "2 h 40 min"; "2 h". */
export function formatMinutes(minutes: number | null | undefined): string {
	if (minutes == null) return '—'
	if (minutes < 60) return `${minutes} min`
	const rest = minutes % 60
	return `${Math.floor(minutes / 60)} h${rest ? ` ${rest} min` : ''}`
}

/** ≤ 15 min responsive, under an hour watch, an hour or more slow (the mockup's thresholds). */
export function responseTone(
	minutes: number | null | undefined
): 'green' | 'amber' | 'red' | 'neutral' {
	if (minutes == null) return 'neutral'
	if (minutes <= 15) return 'green'
	return minutes < 60 ? 'amber' : 'red'
}

export const TONE_LABEL = {
	green: 'Responsive',
	amber: 'Watch',
	red: 'Slow replies',
	neutral: 'No replies yet'
} as const

/** Share of leads assigned in the window that reached qualified or beyond, in percent. */
export function qualifiedRate(m: AgentLeadMetrics): number | null {
	const assigned = m.assigned_in_window ?? 0
	return assigned ? Math.round(((m.qualified_or_better ?? 0) / assigned) * 100) : null
}

/** The rounded mean over people who have a figure; null when nobody does. */
export function teamAverage(
	agents: AgentLeadMetrics[],
	pick: (a: AgentLeadMetrics) => number | null | undefined
): number | null {
	const values = agents.map(pick).filter((v): v is number => v != null)
	return values.length ? Math.round(values.reduce((s, v) => s + v, 0) / values.length) : null
}
