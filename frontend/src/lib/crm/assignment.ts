/**
 * Lead assignment display rules. Who may do what comes from the server's assignment scope;
 * nothing here grants access, it only decides what to show.
 */
import type {
	AssignmentScopeResponse,
	InboundImportAssignmentSummary,
	RoutingRuleResponse
} from '$lib/api/generated/hey-api/types.gen'

export type AssignChoice = { key: string; user_id: string; team_id: string; label: string }

/**
 * Every person the user may assign to, once per team of theirs the person is in, so someone in
 * two of the user's teams is given to one explicit team (the server refuses to guess).
 */
export function assignChoices(scope: AssignmentScopeResponse): AssignChoice[] {
	return scope.teams
		.flatMap((team) =>
			team.members.map((m) => ({
				key: `${m.user_id}|${team.id}`,
				user_id: m.user_id,
				team_id: team.id,
				label: `${m.name} · ${team.name}`
			}))
		)
		.sort((a, b) => a.label.localeCompare(b.label))
}

/** A team's name as the user's scope knows it. */
export function teamName(scope: AssignmentScopeResponse | undefined, teamId: string | null) {
	if (!teamId) return ''
	return (
		scope?.teams.find((t) => t.id === teamId)?.name ??
		scope?.my_teams?.find((t) => t.id === teamId)?.name ??
		'Team'
	)
}

/** A user's name, or a neutral label when they are no longer in the organization. */
export function personName(scope: AssignmentScopeResponse | undefined, userId: string): string {
	return scope?.people.find((p) => p.user_id === userId)?.name ?? 'Former member'
}

const REASON: Record<string, string> = {
	chosen_unassigned: 'Left unassigned, as chosen',
	no_matching_rule: 'No routing rule matched',
	destination_ineligible: 'The matching rule’s agent is no longer in its team',
	no_language_speaker: 'Nobody in the matching rule speaks the lead’s language'
}

export type OutcomeLine = { label: string; count: number }

/** What an import did with its leads: who got how many, and why the rest are unassigned. */
export function importOutcome(
	summary: InboundImportAssignmentSummary,
	scope: AssignmentScopeResponse | undefined,
	rules: RoutingRuleResponse[] = []
): { assigned: OutcomeLine[]; byRule: OutcomeLine[]; unassigned: OutcomeLine[] } {
	const desc = (a: OutcomeLine, b: OutcomeLine) =>
		b.count - a.count || a.label.localeCompare(b.label)
	return {
		assigned: Object.entries(summary.by_assignee ?? {})
			.map(([id, count]) => ({ label: personName(scope, id), count }))
			.sort(desc),
		byRule: Object.entries(summary.by_rule ?? {})
			.map(([id, count]) => ({
				label: rules.find((r) => String(r.id) === id)?.name ?? `Rule #${id}`,
				count
			}))
			.sort(desc),
		unassigned: [
			...(summary.shared
				? [
						{
							label: 'Shared with the team: the first agent to log contact takes each',
							count: summary.shared
						}
					]
				: []),
			...Object.entries(summary.unassigned_reasons ?? {})
				.filter(([, count]) => count > 0)
				.map(([reason, count]) => ({ label: REASON[reason] ?? reason, count }))
		].sort(desc)
	}
}
