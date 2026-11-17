import type { Locator } from '@playwright/test';
import { expect, test } from '../fixtures/guards';

async function surfaceStyle(locator: Locator) {
	return locator.evaluate(element => {
		const style = getComputedStyle(element);
		return {
			background: style.backgroundColor,
			border: style.borderTopColor,
			radius: style.borderTopLeftRadius,
			shadow: style.boxShadow,
			color: style.color,
			font: style.fontFamily
		};
	});
}

test.beforeEach(async ({ page, usePersona }) => {
	await usePersona('active-owner');
	// Presentation checks use synthetic empty data and never read the live CRM.
	await page.route('**/api/v1/crm/**', async route => {
		const path = new URL(route.request().url()).pathname;
		let body: unknown = [];
		if (path.endsWith('/inbound/enquiries')) body = { enquiries: [], total: 0 };
		if (path.endsWith('/area-preferences')) body = { areas: [], forward_days: 60, lookback_days: 30 };
		await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
	});
});

for (const theme of ['light', 'dark'] as const) {
	test(`CRM shares Market surfaces and preserves the ${theme} theme across sections`, async ({ page }, testInfo) => {
		await page.addInitScript(value => {
			localStorage.setItem('vitevue-preferences', JSON.stringify({ theme: value }));
		}, theme);
		await page.setViewportSize({ width: 1440, height: 900 });
		await page.goto('/workflows');
		await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
		const marketCard = await surfaceStyle(page.locator('.ui-surface').first());
		const marketBackground = await page.locator('.theme-app').evaluate(element => getComputedStyle(element).backgroundColor);
		const marketSidebar = await page.getByRole('complementary', { name: 'Market', exact: true })
			.evaluate(element => getComputedStyle(element).backgroundColor);
		const marketActive = await surfaceStyle(page.getByRole('navigation', { name: 'Market sections' })
			.getByRole('link', { name: 'Workflows', exact: true }));

		await page.getByRole('navigation', { name: 'Switch section' }).getByRole('link', { name: 'CRM', exact: true }).click();
		await expect(page.getByRole('heading', { name: 'Home', exact: true })).toBeVisible();
		await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
		// These are rendered surfaces in each tool, so a future private CRM palette fails this check.
		expect(await surfaceStyle(page.locator('.crm-root .card').first())).toEqual(marketCard);
		expect(await surfaceStyle(page.locator('.crm-root .kpi').first())).toEqual(marketCard);
		expect(await page.locator('.crm-root .sb').evaluate(element => getComputedStyle(element).backgroundColor)).toBe(marketSidebar);
		expect(await surfaceStyle(page.getByRole('navigation', { name: 'CRM sections' })
			.getByRole('link', { name: 'Home', exact: true }))).toEqual(marketActive);
		expect(await page.locator('.crm-root').evaluate(element => getComputedStyle(element).backgroundColor)).toBe(marketBackground);

		for (const width of [1440, 1024, 768, 375]) {
			await page.setViewportSize({ width, height: 900 });
			expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
			await page.screenshot({ path: testInfo.outputPath(`crm-${theme}-${width}.png`), animations: 'disabled' });
		}
		await page.getByRole('button', { name: `Switch to ${theme === 'dark' ? 'light' : 'dark'}`, exact: true }).click();
		await expect(page.locator('html')).toHaveAttribute('data-theme', theme === 'dark' ? 'light' : 'dark');
		await page.getByRole('button', { name: 'Show or hide the sidebar', exact: true }).click();
		await page.getByRole('navigation', { name: 'Switch section' }).getByRole('link', { name: 'Market', exact: true }).click();
		await expect(page.getByRole('complementary', { name: 'Market', exact: true })).toBeAttached();
		await expect(page.locator('html')).toHaveAttribute('data-theme', theme === 'dark' ? 'light' : 'dark');
	});
}

test('grouped CRM navigation keeps every destination and highlights nested owner pages', async ({ page }) => {
	await page.setViewportSize({ width: 1440, height: 900 });
	await page.goto('/crm/owners/imports');
	const nav = page.getByRole('navigation', { name: 'CRM sections' });
	await expect(nav.locator('.sb-grp')).toHaveText(['CRM', 'Leads and contacts', 'Deals and properties', 'Tools', 'Management']);
	const destinations = {
		Home: '/crm', Leads: '/crm/leads', Inbox: '/crm/inbox', Matches: '/crm/matches',
		Owners: '/crm/owners', Deals: '/crm/deals', Assets: '/crm/assets',
		Calendar: '/crm/calendar', Assistant: '/crm/assistant', 'Manager view': '/crm/settings'
	};
	for (const [label, href] of Object.entries(destinations)) {
		await expect(nav.getByRole('link', { name: label, exact: true })).toHaveAttribute('href', href);
	}
	await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
	await expect(nav.getByRole('link', { name: 'Owners', exact: true })).toHaveAttribute('aria-current', 'page');

	for (const width of [768, 375]) {
		await page.setViewportSize({ width, height: 900 });
		await page.getByRole('button', { name: 'Show or hide the sidebar', exact: true }).click();
		await expect(nav.getByText('Leads and contacts', { exact: true })).toBeVisible();
		const calendar = nav.getByRole('link', { name: 'Calendar', exact: true });
		await calendar.focus();
		await page.keyboard.press('Enter');
		await expect(page).toHaveURL(/\/crm\/calendar$/);
		await expect(page.locator('.crm-root')).not.toHaveClass(/sbopen/);
		await expect(calendar).toHaveAttribute('aria-current', 'page');
	}
});
