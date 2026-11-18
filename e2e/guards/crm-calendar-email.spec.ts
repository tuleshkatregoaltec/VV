import type { Page, Route } from '@playwright/test';

import { expect, test } from '../fixtures/guards';

/**
 * Calendar (Google) in the browser with the CRM API mocked. The server's own rules (whose
 * sign-in it is) are covered by backend tests; this checks what the screen sends and that
 * Google's one-time code leaves the address bar.
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
