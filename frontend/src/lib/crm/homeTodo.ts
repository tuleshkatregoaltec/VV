/**
 * Home › To do, from the agent's real leads: Gaps (what needs doing on an open lead, most urgent
 * first, one line per lead) and Owner file (owner-file leads still at New or Contacted).
 */
import type { InboundEnquiryResponse } from '$lib/api/generated/hey-api/types.gen'
import type { Gap, LeadRow } from './api/types'
import { shortDate } from './format'

export type TodoLead = { e: InboundEnquiryResponse; row: LeadRow }

const MAX = 20
const CLOSED = new Set(['won', 'lost'])

/** The most urgent gap on one lead, with its rank (lower comes first); null when it is fine. */
function gapOf({ e, row }: TodoLead, today: string): [number, string] | null {
	if (e.sla_state === 'overdue') return [0, 'First reply overdue']
	if (e.next_follow_up && e.next_follow_up < today)
		return [1, `Follow-up overdue since ${shortDate(e.next_follow_up)}`]
	if (row.gated) return [2, 'No prior deal on record · add a record before contacting']
	if (!e.contact.phone && !e.contact.whatsapp && !e.contact.email) return [3, 'No phone or email']
	if (row.lead_type === 'buyer' || row.lead_type === 'tenant') {
		const c = e.criteria as {
			budget_max_aed?: number | null
			budget_min_aed?: number | null
			locations?: string[] | null
		}
		const budget = c.budget_max_aed ?? c.budget_min_aed
		const area = (c.locations ?? []).length > 0 || Boolean(row.area)
		if (budget == null && !area) return [4, 'Budget and area missing']
		if (budget == null) return [4, 'Budget missing']
		if (!area) return [4, 'Area missing']
	}
	return null
}

export function leadTodo(leads: TodoLead[], today: string): { gaps: Gap[]; file_leads: LeadRow[] } {
	const open = leads.filter(({ row }) => !CLOSED.has(row.stage))
	const gaps = open
		.flatMap((lead) => {
			const gap = gapOf(lead, today)
			return gap ? [{ rank: gap[0], text: gap[1], lead }] : []
		})
		.sort((a, b) => a.rank - b.rank || b.lead.row.score - a.lead.row.score)
		.slice(0, MAX)
		.map(({ text, lead: { row } }) => ({
			text,
			detail: `${row.name} · ${row.source_short}`,
			ref_type: 'lead' as const,
			ref_id: String(row.id)
		}))
	const file_leads = open
		.filter(
			({ row }) => row.source === 'file' && (row.stage === 'new' || row.stage === 'contacted')
		)
		.map(({ row }) => row)
		.sort((a, b) => b.score - a.score)
		.slice(0, MAX)
	return { gaps, file_leads }
}
