import { test, expect, type Page } from '@playwright/test';
import { backendPatch, backendPost } from './fixtures/real-auth';

/**
 * The leads board on real data: dragging a card to a stage opens that stage's form, and saving it
 * moves the card. Each test creates its own lead through the backend, in the throwaway organization
 * auth.setup.ts signs up, so no agent's records are touched.
 */

/** The signed-in Playwright owner's access token, from the app's saved session. */
async function accessToken(page: Page): Promise<string> {
	await page.goto('/crm');
	const raw = await page.evaluate(() => localStorage.getItem('authentication'));
	const token = raw ? (JSON.parse(raw) as { access_token?: string }).access_token : undefined;
	expect(token, 'signed-in session').toBeTruthy();
	return token as string;
}

/** A real buyer lead at Qualified; returns its id and unique name. */
async function qualifiedBuyer(page: Page): Promise<{ id: number; name: string }> {
	const token = await accessToken(page);
	const name = `E2E Board Buyer ${Date.now()}`;
	const created = await backendPost(page.request, '/api/v1/crm/inbound/enquiries', token, {
		intent: 'buy',
		record_kind: 'opportunity',
		full_name: name,
		phone: `+97150${String(Date.now()).slice(-7)}`,
		source: 'Manual',
		criteria: { property_type: 'Apartment', locations: ['JVC'], budget_max_aed: 1_500_000 }
	});
	expect(created.status(), await created.text()).toBe(201);
	const { id } = (await created.json()) as { id: number };
	const qualified = await backendPatch(page.request, `/api/v1/crm/inbound/enquiries/${id}`, token, {
		status: 'qualified'
	});
	expect(qualified.ok(), await qualified.text()).toBe(true);
	return { id, name };
}

const column = (page: Page, label: string) =>
	page.locator('section.col', { has: page.locator('.colh', { hasText: new RegExp(`^${label}\\d`) }) });

async function openBoard(page: Page, name: string) {
	await page.goto('/crm/leads');
	await page.getByRole('button', { name: 'Board', exact: true }).click();
	await expect(column(page, 'Qualified').getByRole('button', { name: new RegExp(name) })).toBeVisible();
}

test('dragging a lead to Lost asks why, saves it, and shows it in the Lost column', async ({ page }) => {
	const lead = await qualifiedBuyer(page);
	await openBoard(page, lead.name);

	const card = column(page, 'Qualified').getByRole('button', { name: new RegExp(lead.name) });
	await card.dragTo(column(page, 'Lost'));
	const saved = page.waitForResponse(
		(r) => r.request().method() === 'PATCH' && r.url().includes(`/inbound/enquiries/${lead.id}`)
	);
	await page.getByRole('button', { name: 'Move to Lost' }).click();

	// Stored as closed_lost with a reason, and still on the board, in its Lost column.
	const body = (await saved).request().postDataJSON() as { status: string; lost_reason?: string };
	expect(body.status).toBe('closed_lost');
	expect(body.lost_reason).toBeTruthy();
	await expect(column(page, 'Lost').getByRole('button', { name: new RegExp(lead.name) })).toBeVisible();
	await expect(column(page, 'Qualified').getByRole('button', { name: new RegExp(lead.name) })).toHaveCount(0);
});

test('dragging a buyer to Viewing books the viewing in the calendar', async ({ page }) => {
	const lead = await qualifiedBuyer(page);
	await openBoard(page, lead.name);

	const card = column(page, 'Qualified').getByRole('button', { name: new RegExp(lead.name) });
	await card.dragTo(column(page, 'Viewing'));
	const booked = page.waitForResponse(
		(r) => r.request().method() === 'POST' && r.url().includes(`/calendar/viewings/${lead.id}`)
	);
	await page.getByRole('button', { name: 'Move to Viewing' }).click();

	// The backend stored the viewing as a calendar event for this lead, not only a note.
	const res = await booked;
	expect(res.status()).toBe(201);
	expect(((await res.json()) as { lead_id?: number }).lead_id).toBe(lead.id);
	await expect(column(page, 'Viewing').getByRole('button', { name: new RegExp(lead.name) })).toBeVisible();
});
