/** Progress lines for assistant tool calls. Events carry tool names only, never arguments. */
export type ToolCallState = 'start' | 'done'

export function toolDisplayLabel(
	tool: string | undefined,
	state: ToolCallState,
	cached = false
): string {
	// The CRM Operations Assistant's tools and Market AI's (/chat); anything else falls back to
	// its plain name.
	const labels: Record<string, { start: string; done: string }> = {
		// Market AI
		get_database_coverage: {
			start: 'Checking stored data coverage',
			done: 'Stored data coverage ready'
		},
		search_database_locations: {
			start: 'Finding stored locations',
			done: 'Stored location matches ready'
		},
		get_project_profile: {
			start: 'Reading stored project profile',
			done: 'Stored project profile ready'
		},
		query_market_metrics: {
			start: 'Querying stored market records',
			done: 'Stored market metrics ready'
		},
		get_listing_inventory: {
			start: 'Checking stored listing inventory',
			done: 'Stored listing inventory ready'
		},
		get_project_delivery_summary: {
			start: 'Checking registered project deliveries',
			done: 'Registered project deliveries ready'
		},
		show_listings: { start: 'Searching matching records', done: 'Matched records ready' },
		show_market_trend: { start: 'Building market view', done: 'Market view ready' },
		show_chart: { start: 'Building chart', done: 'Chart ready' },
		get_area_snapshot: { start: 'Reading area snapshot', done: 'Area snapshot ready' },
		compare_areas: { start: 'Comparing areas', done: 'Comparison ready' },
		get_rental_market_pulse: { start: 'Checking rental market', done: 'Rental market ready' },
		get_market_pulse: { start: 'Checking market pulse', done: 'Market pulse ready' },
		rank_areas: { start: 'Ranking areas', done: 'Area ranking ready' },
		rank_upcoming_project_areas: {
			start: 'Reading project pipeline',
			done: 'Project pipeline ready'
		},
		search_development_projects: { start: 'Searching projects', done: 'Project matches ready' },
		get_developer_pipeline: {
			start: 'Reading developer pipeline',
			done: 'Developer pipeline ready'
		},
		get_price_trends: { start: 'Reading price history', done: 'Price history ready' },
		research_market: { start: 'Researching the market', done: 'Market research ready' },
		analyze_pricing: { start: 'Analysing pricing evidence', done: 'Pricing analysis ready' },
		get_similar_projects: { start: 'Finding similar projects', done: 'Similar projects ready' },
		research_listing_shortlist: { start: 'Shortlisting listings', done: 'Listing shortlist ready' },
		comparable_evidence: { start: 'Reading comparable sales', done: 'Comparable evidence ready' },
		compare_stored_projects: { start: 'Comparing projects', done: 'Project comparison ready' },
		// CRM Operations Assistant (also used by Market AI for the user's own CRM)
		query_my_crm_records: {
			start: 'Reading your CRM records',
			done: 'Your CRM records ready'
		},
		query_my_calendar: { start: 'Checking your calendar', done: 'Calendar ready' },
		query_my_lead_emails: { start: 'Reading the lead emails', done: 'Lead emails ready' },
		// The workflow is distinct from each record read it makes; never share a label with one.
		retrieve_personal_crm: { start: 'Reviewing your CRM', done: 'CRM review complete' },
		plan_followups: { start: 'Planning follow-ups', done: 'Follow-up plan ready' },
		prepare_action: { start: 'Preparing the proposed change', done: 'Proposed change ready' },
		find_assignment_colleagues: { start: 'Finding colleagues', done: 'Colleague matches ready' },
		find_meeting_colleagues: { start: 'Finding colleagues', done: 'Colleague matches ready' },
		find_teams: { start: 'Finding the team', done: 'Team matches ready' },
		find_team_people: { start: 'Finding the person', done: 'People matches ready' },
		hold_pending_request: { start: 'Noting your request', done: 'Request noted' },
		propose_crm_action: { start: 'Preparing confirmation', done: 'Confirmation ready' }
	}
	const fallback = tool ? tool.replaceAll('_', ' ') : 'Working'
	const label = labels[tool ?? '']?.[state] ?? (state === 'done' ? `${fallback} ready` : fallback)
	return state === 'done' ? `✓ ${label}${cached ? ' (cached)' : ''}` : `${label}...`
}

/** What a chat turn shows while it streams: the answer so far and one transient status. */
export interface TurnView {
	answer: string
	status: string | null
}

export interface TurnEvent {
	type: string
	tool?: string
	content?: string
}

/**
 * Apply one stream event to the turn. Tool progress only replaces the single status line (the
 * latest step, e.g. "Reviewing your CRM…"); it never becomes part of the answer. The status
 * clears when the answer arrives, the turn ends or it fails.
 */
export function applyTurnEvent(view: TurnView, event: TurnEvent): TurnView {
	switch (event.type) {
		case 'thinking':
			return { ...view, status: view.status ?? 'Thinking…' }
		case 'tool_call_start':
			return { ...view, status: `${toolDisplayLabel(event.tool, 'start').replace(/\.\.\.$/, '')}…` }
		case 'content':
			return { answer: view.answer + (event.content ?? ''), status: null }
		case 'done':
		case 'error':
			return { ...view, status: null }
		default:
			return view
	}
}
