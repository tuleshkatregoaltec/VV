import { expect, test } from '../fixtures/guards';

// Synthetic, mocked API only: an unqualified Inbox contact is qualified as a tenant in place and
// opens, under the same ID, in the Leads view. No live CRM is read or written.

const now = new Date().toISOString();
const enquiry: Record<string, unknown> = {
	id: 41,
	contact: { id: 9, full_name: 'Hana Unqualified', phone: '+971500000001', consent_status: 'provided', do_not_contact: false },
	record_kind: 'unqualified_contact',
	intent: 'unknown',
	status: 'needs_review',
	assigned_user_id: 'user-1',
	assignment_revision: 1,
	team_id: 'north',
	source: 'Website',
	enquiry_date: now,
	criteria: {},
	strict_fields: [],
	raw_notes: 'Looking for something near JVC',
	observed_data: {},
	inferred_data: {},
	confirmed_data: {},
	qualification: {},
	extraction_confidence: 1,
	review_reasons: [],
	sla_state: 'on_time',
	qualification_complete: false,
	tags: [],
	notes: [],
	activities: [],
	created_at: now,
	updated_at: now
};

test('an unqualified Inbox contact is qualified in place and opens in Leads', async ({ page, usePersona }) => {
	await usePersona('active-owner');
	const patches: Record<string, unknown>[] = [];
	await page.route('**/api/v1/crm/**', async route => {
		const url = new URL(route.request().url());
		const path = url.pathname;
		const typed = enquiry.intent !== 'unknown';
		let body: unknown = [];
		if (path.endsWith('/inbound/enquiries')) {
			const listed =
				url.searchParams.get('leads_only') === 'true'
					? typed
					: url.searchParams.get('workspace') === 'unqualified' && !typed;
			body = { enquiries: listed ? [enquiry] : [], total: listed ? 1 : 0, summary: {} };
		} else if (path.endsWith('/inbound/enquiries/41')) {
			if (route.request().method() === 'PATCH') {
				const change = route.request().postDataJSON() as Record<string, unknown>;
				patches.push(change);
				// What the backend's lead edit does with a known intent.
				Object.assign(enquiry, change, {
					record_kind: 'opportunity',
					confirmed_data: { intent: change.intent, criteria: change.criteria }
				});
			}
			body = enquiry;
		} else if (path.endsWith('/area-preferences')) {
			body = { areas: [], forward_days: 60, lookback_days: 30 };
		}
		await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
	});

	await page.setViewportSize({ width: 1440, height: 900 });
	await page.goto('/crm/inbox');
	await expect(page.getByRole('heading', { name: 'Hana Unqualified' })).toBeVisible({ timeout: 15_000 });
	await expect(page.getByRole('button', { name: 'Open lead', exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: 'Qualify lead', exact: true }).click();

	const form = page.getByRole('dialog', { name: 'Qualify Hana Unqualified' });
	await expect(form).toBeVisible();
	await expect(form.getByLabel('Name', { exact: true })).toHaveCount(0);
	await form.getByRole('group', { name: 'Lead type' }).getByRole('button', { name: 'Tenant', exact: true }).click();
	// Required fields are enforced before anything is sent.
	await form.getByRole('button', { name: 'Qualify lead', exact: true }).click();
	expect(patches).toHaveLength(0);
	await form.getByLabel('Budget a year (AED)').fill('120000');
	await form.getByLabel('Area', { exact: true }).fill('JVC');
	await form.getByRole('button', { name: 'Qualify lead', exact: true }).click();

	// The same record opens in the normal lead flow.
	await expect(page).toHaveURL(/\/crm\/leads\?lead=41/);
	await expect(page.getByRole('dialog', { name: 'Hana Unqualified' })).toBeVisible();
	expect(patches).toEqual([
		{ intent: 'rent', criteria: { budget_max_aed: 120000, locations: ['JVC'] } }
	]);
});
