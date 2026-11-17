import type { Page, Route } from '@playwright/test'

import { expect, test } from '../fixtures/guards'

/**
 * Agent lead analytics for managers (agreed 17 Nov 2026), against a mocked API: managers get an
 * "Agents" view on Leads and a page per person; agents get neither.
 */

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

const MANAGER_SCOPE = {
	capabilities: {
		organization_admin: false,
		can_import: true,
		can_assign: true,
		can_manage_rules: true,
		can_manage_teams: false
	},
	teams: [
		{
			id: 'north',
			name: 'North',
			supervised: true,
			members: [
				{ user_id: 'omar', name: 'Omar Khan' },
				{ user_id: 'sara', name: 'Sara Ali' }
			]
		}
	],
	people: [
		{ user_id: 'omar', name: 'Omar Khan' },
		{ user_id: 'sara', name: 'Sara Ali' }
	]
}

const AGENT_SCOPE = {
	...MANAGER_SCOPE,
	capabilities: { ...MANAGER_SCOPE.capabilities, can_assign: false, can_manage_rules: false },
	teams: []
}

const metrics = (over: Record<string, unknown>) => ({
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

const TEAM = {
	days: 30,
	generated_at: '2026-11-17T09:00:00Z',
	agents: [
		metrics({
			user_id: 'omar',
			name: 'Omar Khan',
			open_leads: 5,
			by_status: { new: 2, contacted: 3 },
			contacted_24h: 4,
			avg_first_response_minutes: 14,
			avg_claim_minutes: 22,
			assigned_in_window: 4,
			qualified_or_better: 1
		}),
		metrics({
			user_id: 'sara',
			name: 'Sara Ali',
			avg_first_response_minutes: 160,
			overdue_first_contact: 2
		})
	]
}

/** Anything not mocked answers 404, so no test reaches a real backend (registered first:
 * Playwright tries the most recently registered route first). */
async function isolate(page: Page) {
	await page.route('**/api/v1/**', (route) => json(route, { detail: 'Not mocked' }, 404))
}

/** Every CRM read answers empty unless a test says otherwise. */
async function mockCrm(page: Page, scope: unknown) {
	await page.route('**/api/v1/crm/**', async (route) => {
		const path = new URL(route.request().url()).pathname
		let body: unknown = []
		if (path.endsWith('/inbound/enquiries')) body = { enquiries: [], total: 0 }
		if (path.endsWith('/area-preferences'))
			body = { areas: [], forward_days: 60, lookback_days: 30 }
		await json(route, body)
	})
	await page.route('**/api/v1/crm/assignment/scope', (route) => json(route, scope))
	await page.route('**/api/v1/crm/assignment/analytics?**', (route) => json(route, TEAM))
}

test('a manager sees each agent’s lead figures under Leads › Agents', async ({
	page,
	usePersona
}) => {
	await isolate(page)
	await usePersona('active-member')
	await mockCrm(page, MANAGER_SCOPE)
	await page.setViewportSize({ width: 1440, height: 900 })
	await page.goto('/crm/leads')

	await page.getByRole('button', { name: 'Agents', exact: true }).click()

	await expect(page.getByText('Omar Khan').first()).toBeVisible({ timeout: 15_000 })
	await expect(page.getByText('14 min').first()).toBeVisible()
	await expect(page.getByText('2 h 40 min').first()).toBeVisible()
	await expect(page.getByText('Team average', { exact: true })).toBeVisible()
	await expect(page.getByRole('link', { name: /Omar Khan/ }).first()).toHaveAttribute(
		'href',
		'/crm/team/omar'
	)
})

test('an agent is not offered the Agents view', async ({ page, usePersona }) => {
	await isolate(page)
	await usePersona('active-member')
	await mockCrm(page, AGENT_SCOPE)
	await page.goto('/crm/leads')

	await expect(page.getByRole('button', { name: 'List', exact: true })).toBeVisible({
		timeout: 15_000
	})
	await expect(page.getByRole('button', { name: 'Agents', exact: true })).toHaveCount(0)
})

const DETAIL = {
	days: 30,
	metrics: TEAM.agents[0],
	sources: [
		{ kind: 'marketing', label: 'Property Finder', count: 3 },
		{ kind: 'vitevue_sold', label: 'Owner file · recently sold', count: 1 }
	],
	activity: ['11', '12', '13', '14', '15', '16', '17'].map((d, i) => ({
		date: `2026-11-${d}`,
		calls: i,
		messages: 2,
		meetings: 0
	})),
	leads: [
		{
			id: 42,
			name: 'Tom Walsh',
			status: 'new',
			source: 'Meta',
			source_kind: 'marketing',
			assigned_at: '2026-11-17T08:00:00Z',
			first_contact_at: null,
			last_contact_at: null,
			next_follow_up: null,
			overdue: true
		},
		{
			id: 41,
			name: 'Lina Saleh',
			status: 'contacted',
			source: 'Property Finder',
			source_kind: 'marketing',
			assigned_at: '2026-11-16T08:00:00Z',
			first_contact_at: '2026-11-16T08:14:00Z',
			last_contact_at: '2026-11-16T09:00:00Z',
			next_follow_up: '2026-11-19',
			overdue: false
		}
	]
}

test('a manager opens one agent’s lead analytics', async ({ page, usePersona }) => {
	await isolate(page)
	await usePersona('active-member')
	await mockCrm(page, MANAGER_SCOPE)
	await page.route('**/api/v1/crm/assignment/analytics/omar?**', (route) => json(route, DETAIL))
	await page.setViewportSize({ width: 1440, height: 900 })
	await page.goto('/crm/team/omar')

	await expect(page.getByRole('heading', { name: 'Omar Khan' })).toBeVisible({ timeout: 15_000 })
	await expect(page.getByText('Avg first response').first()).toBeVisible()
	await expect(page.getByText('14 min').first()).toBeVisible()
	await expect(page.getByText('Activity · last 7 days')).toBeVisible()
	await expect(page.getByText('Owner file · recently sold')).toBeVisible()
	await expect(page.getByRole('link', { name: 'Lina Saleh' })).toHaveAttribute(
		'href',
		'/crm/leads?lead=41'
	)
	await expect(page.getByText('Overdue', { exact: true })).toBeVisible()
	const nav = page.getByRole('navigation', { name: 'CRM sections' })
	await expect(nav.getByRole('link', { name: 'Manager view', exact: true })).toHaveAttribute(
		'aria-current',
		'page'
	)
})

test('a person outside the manager’s teams is not shown', async ({ page, usePersona }) => {
	await isolate(page)
	await usePersona('active-member')
	await mockCrm(page, MANAGER_SCOPE)
	await page.route('**/api/v1/crm/assignment/analytics/zed?**', (route) =>
		json(route, { detail: 'This person is not in a team you manage' }, 404)
	)
	await page.goto('/crm/team/zed')

	await expect(page.getByText('This person is not in a team you manage.')).toBeVisible({
		timeout: 15_000
	})
})
