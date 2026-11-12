import { test, expect, type Browser, type Page } from '@playwright/test';

/**
 * Shareable property collections, end to end: an agent builds a collection from Company
 * listings, shares it, and an anonymous client sees the live state at the same URL.
 *
 * Needs the collection tables on the target database and an organization whose connected
 * Property Finder company is the one browsed in Company listings.
 */

const NAME = 'Ahmed — Marina 2BR';
const RENAMED = 'Ahmed — Marina 2BR (updated)';
const UNAVAILABLE = 'This collection is no longer available.';

async function openCompanyListings(page: Page) {
	await page.goto('/crm/assets');
	await page.getByRole('tab', { name: 'Company listings' }).click();
	await expect(page.getByRole('button', { name: 'Add to collection' }).first()).toBeVisible({
		timeout: 30_000
	});
}

async function openCollections(page: Page) {
	await page.getByRole('tab', { name: 'Collections' }).click();
}

/** Adds the company-listing cards with these positions to the named collection. */
async function addCards(page: Page, name: string, positions: number[]) {
	for (const i of positions) {
		await page.getByRole('button', { name: 'Add to collection' }).nth(i).click();
		await page.getByRole('menuitem', { name: new RegExp(name.replace(/[()]/g, '\\$&')) }).click();
		await expect(page.getByText('Added to collection').last()).toBeVisible();
	}
}

async function copyLink(page: Page): Promise<string> {
	const response = page.waitForResponse(
		(r) => /\/collections\/[^/]+\/share-link$/.test(r.url()) && r.request().method() === 'POST'
	);
	await page.getByRole('button', { name: 'Copy link' }).click();
	const { url } = (await (await response).json()) as { url: string };
	return url;
}

async function anonymousPage(browser: Browser) {
	const context = await browser.newContext({ storageState: undefined });
	const page = await context.newPage();
	const posthogRequests: string[] = [];
	page.on('request', (r) => {
		if (/posthog/i.test(r.url())) posthogRequests.push(r.url());
	});
	return { context, page, posthogRequests };
}

test('agent shares a live collection that an anonymous client sees at one stable URL', async ({
	page,
	browser
}) => {
	test.setTimeout(180_000);

	// Pick as many listings as exist (up to 8): add all but the last 3 first, remove 2, add the rest.
	await openCompanyListings(page);
	const available = await page.getByRole('button', { name: 'Add to collection' }).count();
	const total = Math.min(8, available);
	test.skip(total < 5, 'Needs at least 5 company listings on screen');
	const initial = Math.min(5, total - 3);
	const finalCount = total - 2;

	// Create the collection and add the first listings. The add button must not open the listing panel.
	await openCollections(page);
	await page.getByLabel('New collection name').fill(NAME);
	await page.getByRole('button', { name: 'Create', exact: true }).click();
	await expect(page.getByLabel('Collection name')).toHaveValue(NAME);
	await page.getByRole('button', { name: '← Collections' }).click();

	await page.getByRole('tab', { name: 'Company listings' }).click();
	await expect(page.getByRole('button', { name: 'Add to collection' }).first()).toBeVisible();
	await page.getByRole('button', { name: 'Add to collection' }).first().click();
	await expect(page.getByRole('dialog')).toHaveCount(0);
	await page.getByRole('menuitem', { name: NAME }).click();
	await expect(page.getByText('Added to collection').last()).toBeVisible();
	await expect(page.getByRole('dialog')).toHaveCount(0);
	await addCards(page, NAME, Array.from({ length: initial - 1 }, (_, i) => i + 1));

	// Enable sharing and copy the link.
	await openCollections(page);
	await page.getByRole('button', { name: new RegExp(NAME) }).click();
	await expect(page.getByText(`${initial} / 50`)).toBeVisible();
	await page.getByLabel(/^Sharing/).check();
	await expect(page.getByLabel(/^Sharing on/)).toBeChecked();
	const shareUrl = await copyLink(page);

	// Anonymous client: no login prompt, the cards, and no analytics traffic.
	const anon = await anonymousPage(browser);
	try {
		await anon.page.goto(shareUrl);
		await expect(anon.page.getByRole('heading', { level: 1, name: NAME })).toBeVisible();
		await expect(anon.page.locator('main ul > li')).toHaveCount(initial);
		await expect(anon.page).not.toHaveURL(/\/auth/);
		await expect(anon.page.getByRole('button', { name: 'Sign in' })).toHaveCount(0);

		// Agent removes 2, adds the rest, renames.
		await page.getByRole('button', { name: 'Remove' }).first().click();
		await expect(page.getByText(`${initial - 1} / 50`)).toBeVisible();
		await page.getByRole('button', { name: 'Remove' }).first().click();
		await expect(page.getByText(`${initial - 2} / 50`)).toBeVisible();

		await page.getByRole('button', { name: '← Collections' }).click();
		await page.getByRole('tab', { name: 'Company listings' }).click();
		await expect(page.getByRole('button', { name: 'Add to collection' }).first()).toBeVisible();
		await addCards(page, NAME, Array.from({ length: total - initial }, (_, i) => initial + i));

		await openCollections(page);
		await page.getByRole('button', { name: new RegExp(NAME) }).click();
		await expect(page.getByText(`${finalCount} / 50`)).toBeVisible();
		const nameInput = page.getByLabel('Collection name');
		await nameInput.fill(RENAMED);
		await nameInput.press('Enter');
		await expect(nameInput).toHaveValue(RENAMED);

		// Same URL, live state.
		await anon.page.reload();
		await expect(anon.page.getByRole('heading', { level: 1, name: RENAMED })).toBeVisible();
		await expect(anon.page.locator('main ul > li')).toHaveCount(finalCount);

		// Disable: the link stops working.
		await page.getByRole('button', { name: 'Disable link' }).click();
		await expect(page.getByLabel(/^Sharing off/)).not.toBeChecked();
		await anon.page.reload();
		await expect(anon.page.getByText(UNAVAILABLE)).toBeVisible();

		// Re-enable: the very same URL works again.
		await page.getByLabel(/^Sharing/).check();
		await expect(page.getByLabel(/^Sharing on/)).toBeChecked();
		await anon.page.reload();
		await expect(anon.page.getByRole('heading', { level: 1, name: RENAMED })).toBeVisible();
		await expect(anon.page.locator('main ul > li')).toHaveCount(finalCount);

		// Rotate: the old URL is dead, the new one works.
		page.once('dialog', (d) => d.accept());
		await page.getByRole('button', { name: 'Get a new link' }).click();
		await expect(page.getByText('New link created')).toBeVisible();
		const newUrl = await copyLink(page);
		expect(newUrl).not.toBe(shareUrl);

		await anon.page.reload();
		await expect(anon.page.getByText(UNAVAILABLE)).toBeVisible();
		await anon.page.goto(newUrl);
		await expect(anon.page.getByRole('heading', { level: 1, name: RENAMED })).toBeVisible();

		expect(anon.posthogRequests, 'anonymous page must not call PostHog').toEqual([]);
	} finally {
		await anon.context.close();
		// Clean up so reruns start from an empty list.
		page.once('dialog', (d) => d.accept());
		await page.getByRole('button', { name: 'Delete', exact: true }).click().catch(() => {});
	}
});
