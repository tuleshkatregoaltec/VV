import type { Page, Route } from '@playwright/test';

import { expect, test } from '../fixtures/guards';

/**
 * Lead assignment screens against a mocked API: what each role is offered comes from the
 * server's assignment scope, and what the screens send is the canonical contract.
 */

const MANAGER_SCOPE = {
	capabilities: {
		organization_admin: false,
		can_import: true,
		can_assign: true,
		can_manage_rules: true,
		can_manage_teams: false,
	},
	teams: [
		{
			id: 'north',
			name: 'North',
			supervised: true,
			members: [
				{ user_id: 'omar', name: 'Omar Khan' },
				{ user_id: 'nadia', name: 'Nadia Saleh' },
			],
		},
	],
	people: [
		{ user_id: 'omar', name: 'Omar Khan' },
		{ user_id: 'nadia', name: 'Nadia Saleh' },
		{ user_id: 'sara', name: 'Sara Ali' },
	],
};

/** An agent in no team: the server lets every member import, only for themselves. */
const AGENT_SCOPE = {
	capabilities: {
		organization_admin: false,
		can_import: true,
		can_assign: false,
		can_manage_rules: false,
		can_manage_teams: false,
	},
	teams: [],
	people: [...MANAGER_SCOPE.people, { user_id: 'user-1', name: 'Ada Lovelace' }],
};

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

for (const persona of ['active-owner', 'active-member'] as const) {
	test(`team administration lives in organisation settings for ${persona}`, async ({ page, usePersona }) => {
		await isolate(page);
		await usePersona(persona);
		await page.route('**/api/v1/crm/assignment/scope', (route) => json(route, {
			...MANAGER_SCOPE,
			capabilities: { ...MANAGER_SCOPE.capabilities, organization_admin: true, can_manage_rules: true, can_manage_teams: true },
		}));
		await page.route('**/api/v1/crm/routing/rules', (route) => json(route, []));
		await page.route('**/api/v1/organization/teams', (route) => json(route, {
			teams: [],
			people: [{ user_id: 'omar', name: 'Omar Khan', role: 'member', organization_admin: false }],
		}));
		const scopeReady = page.waitForResponse((response) => response.url().endsWith('/api/v1/crm/assignment/scope') && response.ok());
		await page.goto('/crm/settings');
		await scopeReady;
		await expect(page.getByRole('heading', { name: 'Manager view is coming soon' })).toBeVisible({ timeout: 15_000 });
		await page.getByRole('link', { name: 'Lead Routing', exact: true }).click();
		await expect(page).toHaveURL(/\/crm\/lead-routing$/);
		await expect(page.getByRole('heading', { name: 'Routing rules', exact: true })).toBeVisible();
		await expect(page.getByRole('heading', { name: 'Teams & members', exact: true })).toHaveCount(0);
		await expect(page.getByRole('heading', { name: 'Roles & access', exact: true })).toHaveCount(0);
		await page.getByRole('link', { name: /Manage teams & access/ }).click();
		await expect(page).toHaveURL(/\/crm\/organization#teams$/);
		await expect(page.getByRole('heading', { name: 'Teams & members', exact: true })).toBeVisible();
		await expect(page.getByRole('heading', { name: 'Roles & access', exact: true })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Create team', exact: true })).toBeVisible();
		await expect(page.getByRole('checkbox', { name: 'Organization admin', exact: true })).toHaveCount(persona === 'active-owner' ? 1 : 0);
		if (persona === 'active-member') {
			await expect(page.getByRole('heading', { name: 'Subscription', exact: true })).toHaveCount(0);
		}
	});
}

test('an ordinary agent cannot manage teams from organisation settings', async ({ page, usePersona }) => {
	await isolate(page);
	await usePersona('active-member');
	await page.route('**/api/v1/crm/assignment/scope', (route) => json(route, AGENT_SCOPE));
	await page.goto('/crm/organization');
	await expect(page.getByText('Only organisation owners and administrators can manage teams and access.')).toBeVisible({ timeout: 15_000 });
	await expect(page.getByRole('button', { name: 'Create team', exact: true })).toHaveCount(0);
});

/** Anything not mocked below answers 404, so no test reaches a real backend. Registered first:
 * Playwright tries the most recently registered route first. */
async function isolate(page: Page) {
	await page.route('**/api/v1/**', (route) => json(route, { detail: 'Not mocked' }, 404));
}

test('an agent is not offered routing administration', async ({
	page,
	usePersona,
}) => {
	await isolate(page);
	await usePersona('active-member');
	await page.route('**/api/v1/crm/assignment/scope', (route) => json(route, AGENT_SCOPE));

	const scopeReady = page.waitForResponse((response) => response.url().endsWith('/api/v1/crm/assignment/scope') && response.ok());
	await page.goto('/crm/settings');
	await scopeReady;
	await expect(page.getByRole('heading', { name: 'Manager view is coming soon' })).toBeVisible({ timeout: 15_000 });
	await expect(page.getByRole('link', { name: 'Lead Routing', exact: true })).toHaveCount(0);
	await expect(page.getByRole('link', { name: 'Manager view', exact: true })).toHaveCount(0);
	await page.goto('/crm/lead-routing');
	await expect(page.getByRole('heading', { name: 'Access restricted' })).toBeVisible({ timeout: 15_000 });
	await expect(page.getByRole('heading', { name: 'Routing rules', exact: true })).toHaveCount(0);
	await expect(page.getByRole('heading', { name: 'Teams and agents' })).toHaveCount(0);
});

test('a supervisor sees the Manager role and manager navigation', async ({ page, usePersona }) => {
    await isolate(page);
    await usePersona('active-member');
    await page.route('**/api/v1/crm/assignment/scope', (route) => json(route, MANAGER_SCOPE));
    const scopeReady = page.waitForResponse((response) => response.url().endsWith('/api/v1/crm/assignment/scope') && response.ok());
    await page.goto('/crm/settings');
    await scopeReady;
    await expect(page.getByRole('complementary', { name: 'CRM', exact: true }).locator('.who .muted')).toHaveText('Manager', { timeout: 15000 });
    await expect(page.getByRole('link', { name: 'Lead Routing', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Manager view', exact: true })).toBeVisible();
});

/** Mocks the leads-file preview and import; returns what the import request sent. */
async function mockLeadImport(page: Page, assignment: Record<string, unknown>) {
	await page.route('**/api/v1/crm/inbound/imports/preview', (route) =>
		json(route, {
			original_filename: 'leads.csv',
			size_bytes: 40,
			total_rows: 2,
			warnings: [],
			sheets: [
				{
					sheet: 'leads',
					header_row: 1,
					headers: ['Name', 'Phone'],
					field_map: { full_name: 'Name', phone: 'Phone' },
					sample_rows: [{ row: '2', full_name: 'Jade Buyer', phone: 'Present' }],
					row_count: 2,
					mapping_source: 'deterministic',
				},
			],
		}),
	);
	let sent = '';
	await page.route('**/api/v1/crm/inbound/imports', async (route) => {
		if (route.request().method() !== 'POST') return json(route, []);
		sent = route.request().postData() ?? '';
		return json(route, {
			id: 1,
			name: 'leads.csv',
			original_filename: 'leads.csv',
			status: 'completed',
			mapping: {},
			created_at: '2026-11-12T08:00:00Z',
			summary: { total_rows: 2, imported: 2, needs_review: 2, assignment },
		});
	});
	return () => sent;
}

async function chooseLeadsFile(page: Page) {
	await page.goto('/crm/leads');
	await page.getByRole('button', { name: 'Import leads' }).click();
	await page
		.locator('input[type="file"]')
		.setInputFiles({ name: 'leads.csv', mimeType: 'text/csv', buffer: Buffer.from('Name,Phone\n') });
}

test('an agent imports leads for themselves without choosing who gets them', async ({
	page,
	usePersona,
}) => {
	await isolate(page);
	await usePersona('active-member');
	await page.route('**/api/v1/crm/assignment/scope', (route) => json(route, AGENT_SCOPE));
	const sent = await mockLeadImport(page, {
		mode: 'self',
		assigned: 2,
		unassigned: 0,
		by_assignee: { 'user-1': 2 },
		by_rule: {},
		unassigned_reasons: {},
	});

	await chooseLeadsFile(page);
	await expect(page.getByText('These leads will be assigned to you.')).toBeVisible();
	// Nothing to choose: no mode switch, no agent list, no routing rules.
	await expect(page.getByRole('group', { name: 'Who handles the new leads' })).toHaveCount(0);
	await expect(page.getByLabel('Agent')).toHaveCount(0);
	await page.getByRole('button', { name: 'Import 2 rows' }).click();

	await expect(page.getByRole('heading', { name: 'Who handles them' })).toBeVisible();
	const outcome = page.locator('section', {
		has: page.getByRole('heading', { name: 'Who handles them' }),
	});
	await expect(outcome.getByText('Ada Lovelace')).toBeVisible();
	expect(sent()).toMatch(/name="assignment_mode"\r\n\r\nself\r\n/);
	expect(sent()).not.toContain('name="assignee_user_id"');
});

test('a manager imports leads for an agent in their team and sees who received them', async ({
	page,
	usePersona,
}) => {
	await isolate(page);
	await usePersona('active-member');
	await page.route('**/api/v1/crm/assignment/scope', (route) => json(route, MANAGER_SCOPE));
	await page.route('**/api/v1/crm/routing/rules', (route) => json(route, []));
	const sent = await mockLeadImport(page, {
		mode: 'agent',
		assignee_user_id: 'omar',
		assigned: 2,
		unassigned: 0,
		by_assignee: { omar: 2 },
		by_rule: {},
		unassigned_reasons: {},
	});

	await chooseLeadsFile(page);
	await expect(page.getByText('These leads will be assigned to you.')).toHaveCount(0);

	// Only people in the manager's own teams are offered; Sara is a colleague in another team.
	const agent = page.getByLabel('Agent');
	await expect(agent.locator('option')).toHaveText([
		'Choose an agent',
		'Nadia Saleh · North',
		'Omar Khan · North',
	]);
	const importButton = page.getByRole('button', { name: 'Import 2 rows' });
	await expect(importButton).toHaveCount(0); // no import until someone is chosen
	await agent.selectOption({ label: 'Omar Khan · North' });
	await importButton.click();

	await expect(page.getByRole('heading', { name: 'Who handles them' })).toBeVisible();
	await expect(page.getByText('Omar Khan')).toBeVisible();
	expect(sent()).toMatch(/name="assignment_mode"\r\n\r\nagent\r\n/);
	expect(sent()).toMatch(/name="assignee_user_id"\r\n\r\nomar\r\n/);
	// The team that owns the leads is sent explicitly, so its manager (and no other) sees them.
	expect(sent()).toMatch(/name="team_id"\r\n\r\nnorth\r\n/);
});

for (const width of [1440, 390]) {
	test(`routing redesign keeps editing and priority controls usable at ${width}px`, async ({ page, usePersona }) => {
		await page.setViewportSize({ width, height: 1000 });
		await isolate(page);
		await usePersona('active-owner');
		await page.route('**/api/v1/crm/assignment/scope', (route) => json(route, {
			...MANAGER_SCOPE,
			capabilities: { ...MANAGER_SCOPE.capabilities, organization_admin: true, can_manage_rules: true, can_manage_teams: true },
		}));
		await page.route('**/api/v1/organization/teams', (route) => json(route, { teams: [], people: [] }));
		await page.route('**/api/v1/crm/assignment/workload', (route) => json(route, { teams: [] }));
		const rule = {
			id: 1, name: 'Marina buyers', team_id: 'north', destination_user_id: 'omar', enabled: true,
			priority: 1, match_mode: 'all', revision: 1,
			conditions: [{ field: 'area', operator: 'is_any_of', values: ['Dubai Marina'] }, { field: 'intent', operator: 'is_any_of', values: ['buy'] }],
		};
		await page.route('**/api/v1/crm/routing/rules', (route) => json(route, [rule]));
		let saved: Record<string, unknown> | undefined;
		await page.route('**/api/v1/crm/routing/rules/1', async (route) => {
			saved = route.request().postDataJSON();
			await json(route, { ...rule, ...saved });
		});
		await page.goto('/crm/lead-routing');
		const card = page.locator('article.rule');
		await expect(card.getByText('Match all', { exact: true })).toBeVisible({ timeout: 15_000 });
		await expect(card.getByText('Assign to', { exact: true })).toBeVisible();
		await expect(card.getByText('Omar Khan', { exact: true })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Move Marina buyers up' })).toBeDisabled();
		await expect(page.getByRole('switch', { name: 'Use Marina buyers' })).toBeChecked();
		await expect(page.getByText('No matching rule', { exact: true })).toBeVisible();
		expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
		await page.getByRole('button', { name: 'Edit Marina buyers', exact: true }).click();
		await expect(page.getByRole('heading', { name: 'Edit rule', exact: true })).toBeVisible();
		expect(await page.locator('.routing').evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
		expect(await page.locator('.editor').evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
		await page.getByRole('button', { name: 'Any condition', exact: true }).click();
		// Language routing is an explicit choice per rule; the server records it as speakers_only.
		await page.getByRole('checkbox', { name: /speak its language/ }).check();
		await expect(page.getByText(/No languages recorded yet for Omar Khan/)).toBeVisible();
		await page.getByRole('button', { name: 'Save changes', exact: true }).click();
		await expect(page.getByRole('heading', { name: 'Edit rule', exact: true })).toHaveCount(0);
		expect(saved).toMatchObject({ match_mode: 'any', expected_revision: 1, team_id: 'north', destination_user_id: 'omar', conditions: rule.conditions, speakers_only: true });
	});
}

test('a manager records the languages their people speak; nothing is inferred', async ({ page, usePersona }) => {
	await isolate(page);
	await usePersona('active-member');
	await page.route('**/api/v1/crm/assignment/scope', (route) => json(route, MANAGER_SCOPE));
	await page.route('**/api/v1/crm/routing/rules', (route) => json(route, []));
	await page.route('**/api/v1/crm/assignment/workload', (route) => json(route, { teams: [] }));
	let sent: { languages: string[] } | undefined;
	await page.route('**/api/v1/crm/assignment/people/omar/languages', async (route) => {
		sent = route.request().postDataJSON();
		await json(route, { user_id: 'omar', languages: sent?.languages ?? [] });
	});
	await page.goto('/crm/lead-routing');
	const section = page.getByRole('region', { name: 'Languages your agents speak' });
	await expect(section).toBeVisible({ timeout: 15_000 });
	// Omar's row shows no language until a manager records one; his name alone implies nothing.
	await expect(section.getByText('No languages recorded').first()).toBeVisible();
	await section.getByRole('button', { name: 'Edit languages for Omar Khan' }).click();
	await section.getByRole('textbox', { name: /Languages Omar Khan speaks/ }).fill('Hindi, english; Hindi');
	await section.getByRole('button', { name: 'Save', exact: true }).click();
	await expect.poll(() => sent).toEqual({ languages: ['Hindi', 'english', 'Hindi'] });
	// The server, not the browser, normalises and de-duplicates (see AgentLanguagesWrite).
});

test('a multi-team agent chooses the owning team before sending an owner file', async ({ page, usePersona }) => {
	test.setTimeout(60000);
	await isolate(page);
	await usePersona('active-member');
	await page.route('**/api/v1/crm/assignment/scope', (route) => json(route, {
		...AGENT_SCOPE, my_teams: [{ id: 'north', name: 'North' }, { id: 'south', name: 'South' }],
	}));
	let sent = '';
	await page.route('**/api/v1/crm/contact-import-requests', async (route) => {
		if (route.request().method() !== 'POST') return json(route, []);
		sent = route.request().postData() ?? '';
		return json(route, { id: 1, status: 'pending' }, 201);
	});
	const scopeReady = page.waitForResponse((response) => response.url().endsWith('/api/v1/crm/assignment/scope') && response.ok());
	await page.goto('/crm/owners');
	await scopeReady;
	await page.getByRole('button', { name: 'Upload', exact: true }).click();
	await page.locator('input[type="file"]').setInputFiles({
		name: 'owners.csv', mimeType: 'text/csv', buffer: Buffer.from('Name,Unit\nOwner,101\n'),
	});
	const submit = page.getByRole('button', { name: 'Import 1 rows', exact: true });
	await expect(submit).toBeDisabled();
	await page.getByLabel('Team that owns this owner file').selectOption('south');
	await expect(submit).toBeEnabled();
	await submit.click();
	await expect(page.getByText('Sent for approval.', { exact: false })).toBeVisible();
	expect(sent).toMatch(/name="team_id"\r\n\r\nsouth\r\n/);
});
