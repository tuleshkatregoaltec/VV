import { expect as baseExpect, test, type Response } from '@playwright/test';
import { loginUser, seedBrowserSession } from './fixtures/real-auth';

const expect = baseExpect.configure({ timeout: 30_000 });

// Failure snapshots would retain real contact names in the test-results directory.
process.env.PLAYWRIGHT_NO_COPY_PROMPT = '1';
test.use({ screenshot: 'off', trace: 'off', video: 'off' });

// Read the existing agency file with a real session; never seed or edit owner records.
test('Owners defaults to ten rows and resets server pagination when the view changes', async ({ page, request }) => {
	test.setTimeout(180_000);
	page.setDefaultTimeout(30_000);
	const session = await loginUser(
		request,
		process.env.TEST_EMAIL ?? process.env.FIRST_SUPERUSER ?? 'admin@example.com',
		process.env.TEST_PASSWORD ?? process.env.FIRST_SUPERUSER_PASSWORD ?? 'admin123'
	);
	await seedBrowserSession(page, session);

	const isPage = (response: Response, limit: number, offset: number, search = '') => {
		const url = new URL(response.url());
		return url.pathname.endsWith('/crm/owner-registry') &&
			url.searchParams.get('scope') === 'all' &&
			url.searchParams.get('limit') === String(limit) &&
			url.searchParams.get('offset') === String(offset) &&
			(url.searchParams.get('search') ?? '') === search;
	};
	const firstResponse = page.waitForResponse(response => isPage(response, 10, 0), { timeout: 120_000 });
	await page.goto('/crm/owners');
	const response = await firstResponse;
	expect(response.ok()).toBeTruthy();
	const first = await response.json();
	await response.finished();
	console.log(`Owner registry initial request: ${Math.round(response.request().timing().responseEnd)}ms (no latency threshold).`);
	// This read-only regression needs enough pre-existing owners to exercise a larger page.
	expect(first.total, 'At least 51 existing owners are required for pagination coverage').toBeGreaterThan(50);
	const size = page.getByLabel('Rows per page');
	const count = page.locator('.filters .count');
	const rows = page.locator('.owners-table tbody tr.row');
	const next = page.getByRole('button', { name: 'Next', exact: true });
	const previous = page.getByRole('button', { name: 'Previous', exact: true });
	await expect(size).toHaveValue('10');
	await expect(size.locator('option')).toHaveText(['10', '50', '100', '200', '500']);
	await expect(rows).toHaveCount(10);
	await expect(count).toHaveText(/^Showing 1–10 of /);
	await expect(previous).toBeDisabled();
	const firstNames = await rows.locator('.rowlink').allTextContents();

	const nextResponse = page.waitForResponse(result => isPage(result, 10, 10));
	await next.click();
	expect((await nextResponse).ok()).toBeTruthy();
	await expect(count).toHaveText(/^Showing 11–20 of /);
	await expect(rows).toHaveCount(10);
	expect(JSON.stringify(await rows.locator('.rowlink').allTextContents()) === JSON.stringify(firstNames)).toBe(false);
	await previous.click();
	await expect(count).toHaveText(/^Showing 1–10 of /);
	expect(JSON.stringify(await rows.locator('.rowlink').allTextContents()) === JSON.stringify(firstNames)).toBe(true);

	await next.click();
	await expect(count).toHaveText(/^Showing 11–20 of /);
	const largerResponse = page.waitForResponse(result => isPage(result, 50, 0));
	await size.selectOption('50');
	expect((await largerResponse).ok()).toBeTruthy();
	await expect(count).toHaveText(/^Showing 1–50 of /);
	await expect(rows).toHaveCount(50);
	await next.click();
	await expect(count).toHaveText(/^Showing 51–/);
	await size.selectOption('10');
	await expect(count).toHaveText(/^Showing 1–10 of /);
	await expect(previous).toBeDisabled();

	await next.click();
	await expect(count).toHaveText(/^Showing 11–20 of /);
	const search = 'pagination-regression-no-such-owner-7da0fc';
	const searchResponse = page.waitForResponse(result => isPage(result, 10, 0, search));
	await page.getByRole('textbox', { name: 'Search owners' }).fill(search);
	expect((await searchResponse).ok()).toBeTruthy();
	await expect(count).toHaveText('No owners');
	await page.getByRole('textbox', { name: 'Search owners' }).fill('');
	await expect(count).toHaveText(/^Showing 1–10 of /);

	await next.click();
	await expect(count).toHaveText(/^Showing 11–20 of /);
	await page.getByRole('tab', { name: /^3\+ associated properties/ }).click();
	await expect(count).toHaveText(/^(Showing 1–|No owners)/);
	await page.getByRole('tab', { name: /^All\b/ }).click();
	await expect(count).toHaveText(/^Showing 1–10 of /);
	await next.click();
	await expect(count).toHaveText(/^Showing 11–20 of /);
	await page.getByRole('button', { name: 'Source: All sources', exact: true }).click();
	await page.getByRole('menuitemradio', { name: 'Agency file', exact: true }).click();
	await expect(count).toHaveText(/^Showing 1–10 of /);
	await expect(previous).toBeDisabled();

	console.log('Owner pagination: default=10; options=10,50,100,200,500; next/previous and page-size/search/tab/filter resets passed.');
});
