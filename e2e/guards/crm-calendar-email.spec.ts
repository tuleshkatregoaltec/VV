import type { Page, Route } from '@playwright/test';

import { expect, test } from '../fixtures/guards';

/**
 * Calendar (Google) and Email (Brevo) in the browser with the CRM API mocked. The server's own
 * rules (whose sign-in it is, which leads an agent may email) are covered by backend tests;
 * this checks what the screens send and that Google's one-time code leaves the address bar.
 */

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

type Call = { method: string; path: string; body: unknown };

async function mockCrm(page: Page, calls: Call[], google = { configured: true, connected: false, email: null as string | null }) {
	await page.route('**/api/v1/crm/**', async (route) => {
		const request = route.request();
		const url = new URL(request.url());
		const path = url.pathname.replace('/api/v1/crm', '');
		calls.push({ method: request.method(), path, body: request.postDataJSON?.() ?? null });
		if (path === '/calendar/google') return json(route, google);
		if (path === '/calendar/google/complete') {
			google = { configured: true, connected: true, email: 'agent@example.com' };
			return json(route, google);
		}
		if (path === '/calendar/events') return json(route, []);
		if (path === '/email/status') return json(route, { configured: true, sender_name: 'Agency', sender_email: 'hello@agency.example', webhook_configured: true });
		if (path === '/email/leads') return json(route, {
			items: [{ id: 7, name: 'Sara Khan', email: 'sara@example.com', phone: null, intent: 'buy', source: 'Property Finder', status: 'new', do_not_contact: false, last_status: null, last_sent_at: null, sends: 0 }],
			total: 1,
			sources: ['Property Finder']
		});
		if (path === '/email/templates') return json(route, []);
		if (path === '/email/inbound') return json(route, { items: [], total: 0 });
		if (path === '/email/sends') return json(route, { items: [], total: 0, counts: {} });
		if (path === '/assignment/scope') return route.fallback();
		return json(route, { detail: 'Not found' }, 404);
	});
}

test('back from Google, the calendar finishes sign-in once and drops the code from the address', async ({ page, usePersona }) => {
	const calls: Call[] = [];
	await usePersona('active-member');
	await mockCrm(page, calls);

	await page.goto('/crm/calendar#google_code=4%2Fabc&google_state=state-from-google');

	await expect(page.getByText('Google connected', { exact: true })).toBeVisible({ timeout: 15_000 });
	const completes = calls.filter((c) => c.path === '/calendar/google/complete');
	expect(completes).toEqual([
		{ method: 'POST', path: '/calendar/google/complete', body: { code: '4/abc', state: 'state-from-google' } }
	]);
	expect(new URL(page.url()).hash).toBe('');
	expect(page.url()).not.toContain('4%2Fabc');
});

test('a cancelled Google sign-in posts nothing and says so', async ({ page, usePersona }) => {
	const calls: Call[] = [];
	await usePersona('active-member');
	await mockCrm(page, calls);

	await page.goto('/crm/calendar#google_calendar=error');

	await expect(page.getByText('Google Calendar was not connected', { exact: true })).toBeVisible({ timeout: 15_000 });
	expect(calls.some((c) => c.path === '/calendar/google/complete')).toBe(false);
	await expect(page.getByRole('button', { name: 'Connect Google Calendar' })).toBeVisible();
});

test('the email connector lists the leads the server returns', async ({ page, usePersona }) => {
	const calls: Call[] = [];
	await usePersona('active-member');
	await mockCrm(page, calls);

	await page.goto('/crm/connectors/email');

	await expect(page).toHaveURL(/\/crm\/connectors\/email$/);
	await expect(page.getByRole('button', { name: 'Sara Khan', exact: true })).toBeVisible({ timeout: 15_000 });
	await expect(page.getByText('sara@example.com', { exact: true })).toBeVisible();
	expect(calls.some((c) => c.method === 'GET' && c.path === '/email/leads')).toBe(true);
});
