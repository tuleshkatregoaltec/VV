import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'
import type {
	AssignmentScopeResponse,
	InboundImportResponse
} from '$lib/api/generated/hey-api/types.gen'
import * as backend from '$lib/crm/api/backend'
import { assignChoices, importOutcome, personName, teamName } from '$lib/crm/assignment'

const SCOPE: AssignmentScopeResponse = {
	capabilities: {
		organization_admin: false,
		can_import: true,
		can_assign: true,
		can_manage_rules: false,
		can_manage_teams: false
	},
	teams: [
		{
			id: 'north',
			name: 'North',
			supervised: true,
			members: [
				{ user_id: 'omar', name: 'Omar Khan' },
				{ user_id: 'nadia', name: 'Nadia Saleh' }
			]
		},
		{
			id: 'marina',
			name: 'Marina',
			supervised: true,
			members: [{ user_id: 'omar', name: 'Omar Khan' }]
		}
	],
	people: [
		{ user_id: 'omar', name: 'Omar Khan' },
		{ user_id: 'sara', name: 'Sara Ali' },
		{ user_id: 'nadia', name: 'Nadia Saleh' }
	]
}

afterEach(() => vi.restoreAllMocks())

describe('assignment choices', () => {
	it('offers a person in two of your teams once per team, so the owning team is explicit', () => {
		// The lead belongs to one team: its manager sees it, the other team's does not. The
		// server refuses to guess which of Omar's teams is meant, so the choice names it.
		expect(assignChoices(SCOPE).map((c) => [c.label, c.user_id, c.team_id])).toEqual([
			['Nadia Saleh · North', 'nadia', 'north'],
			['Omar Khan · Marina', 'omar', 'marina'],
			['Omar Khan · North', 'omar', 'north']
		])
		expect(teamName(SCOPE, 'marina')).toBe('Marina')
	})

	it('only offers people in the teams the server returned, not everyone in the organization', () => {
		// Sara is a colleague but not in this manager's teams: assigning to her would be refused.
		expect(assignChoices(SCOPE).map((c) => c.user_id)).not.toContain('sara')
		expect(personName(SCOPE, 'sara')).toBe('Sara Ali')
		expect(personName(SCOPE, 'gone')).toBe('Former member')
	})
})

describe('import outcome', () => {
	it('names who received leads and says why the rest wait unassigned', () => {
		const outcome = importOutcome(
			{
				mode: 'rules',
				assigned: 70,
				unassigned: 30,
				by_assignee: { sara: 30, omar: 40 },
				by_rule: { '3': 40, '9': 30 },
				unassigned_reasons: { no_matching_rule: 28, destination_ineligible: 2 }
			},
			SCOPE,
			[{ id: 3, name: 'JVC' } as never]
		)
		expect(outcome.assigned).toEqual([
			{ label: 'Omar Khan', count: 40 },
			{ label: 'Sara Ali', count: 30 }
		])
		expect(outcome.byRule).toEqual([
			{ label: 'JVC', count: 40 },
			{ label: 'Rule #9', count: 30 }
		])
		expect(outcome.unassigned).toEqual([
			{ label: 'No routing rule matched', count: 28 },
			{ label: 'The matching rule’s agent is no longer in its team', count: 2 }
		])
	})

	it('says shared leads wait for an agent to take them, not for a manager', () => {
		const outcome = importOutcome(
			{ mode: 'team', team_id: 'north', assigned: 0, unassigned: 5, shared: 5 },
			SCOPE
		)
		expect(outcome.unassigned).toEqual([
			{ label: 'Shared with the team: the first agent to log contact takes each', count: 5 }
		])
	})
})

describe('leads import request', () => {
	const file = new File(['Name,Phone\n'], 'leads.csv', { type: 'text/csv' })
	const sent = () => {
		// A queued import as the backend returns it; only the request form matters here.
		const post = vi.spyOn(client, 'post').mockResolvedValue({
			id: 1,
			name: 'leads',
			original_filename: 'leads.csv',
			status: 'queued',
			summary: {},
			created_at: '2026-11-16T09:00:00Z'
		} as unknown as InboundImportResponse)
		return () => post.mock.calls[0][1] as FormData
	}

	it('always sends the chosen mode, so the server never falls back to the importer', async () => {
		const body = sent()
		await backend.createImport(file, { mode: 'unassigned' })
		expect(body().get('assignment_mode')).toBe('unassigned')
		expect(body().has('assignee_user_id')).toBe(false)
	})

	it('an agent import names no assignee: the server assigns the signed-in user', async () => {
		const body = sent()
		await backend.createImport(file, { mode: 'self' })
		expect(body().get('assignment_mode')).toBe('self')
		expect(body().has('assignee_user_id')).toBe(false)
	})

	it('sends the team that owns shared leads, and none for a self-import', async () => {
		const shared = sent()
		await backend.createImport(file, { mode: 'team', team_id: 'north' })
		expect([shared().get('assignment_mode'), shared().get('team_id')]).toEqual(['team', 'north'])
		vi.restoreAllMocks()
		const own = sent()
		await backend.createImport(file, { mode: 'self' })
		expect(own().has('team_id')).toBe(false)
	})

	it('sends the agent only when assigning to one agent', async () => {
		const body = sent()
		await backend.createImport(file, { mode: 'agent', assignee_user_id: 'omar' })
		expect([body().get('assignment_mode'), body().get('assignee_user_id')]).toEqual([
			'agent',
			'omar'
		])
	})
})

describe('reassignment request', () => {
	it('quotes the revision shown for every lead so a concurrent change is refused', async () => {
		const post = vi.spyOn(client, 'post').mockResolvedValue({ results: [] })
		await backend.assignLeads(
			[
				{ id: 4, assignment_revision: 2 },
				{ id: 9, assignment_revision: 0 }
			],
			null
		)
		expect(post.mock.calls[0][1]).toEqual({
			enquiry_ids: [4, 9],
			assignee_user_id: null,
			team_id: null,
			expected_revisions: { 4: 2, 9: 0 }
		})
	})

	it('sharing with a team pool also quotes the revisions shown', async () => {
		const post = vi.spyOn(client, 'post').mockResolvedValue({ results: [] })
		await backend.releaseToPool([{ id: 4, assignment_revision: 2 }], 'north')
		expect(post.mock.calls[0]).toEqual([
			'/api/v1/crm/inbound/pool',
			{ enquiry_ids: [4], team_id: 'north', expected_revisions: { 4: 2 } }
		])
	})
})

it('sends the selected owning team with an owner file so only its supervisor may approve', async () => {
	const post = vi.spyOn(client, 'post').mockResolvedValue({})
	await backend.requestOwnerImport(
		new File(['Name,Unit\nOwner,101\n'], 'owners.csv'),
		'Owners',
		'north'
	)
	const form = post.mock.calls[0][1] as FormData
	expect(post.mock.calls[0][0]).toBe('/api/v1/crm/contact-import-requests')
	expect(form.get('team_id')).toBe('north')
})
