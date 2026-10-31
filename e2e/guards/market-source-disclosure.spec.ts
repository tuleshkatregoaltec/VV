import { expect, test } from '../fixtures/guards';

const providers = /\b(DLD|DXBI|DXBInteract|Reelly|DDA)\b/i;
const sale = {
	transaction_id: 'T-1', transaction_date: '2026-10-01', unit_number: '1203',
	building_name: 'Synthetic Tower', project_name: 'Synthetic Project', master_project: 'Synthetic Master',
	dld_area: 'Synthetic District', location_name: 'Synthetic Area', property_type: 'Apartment',
	property_usage: 'Residential', bedrooms: '2 Beds', status: 'Ready', size_sqft: 1000,
	price_aed: 1500000, price_per_sqft_aed: 1500
};

test.beforeEach(async ({ page, usePersona }) => {
	await usePersona('active-owner');
	await page.route('**/api/v1/**', async route => {
		const path = new URL(route.request().url()).pathname;
		if (path === '/api/v1/auth/me') return route.fallback();
		let body: unknown = { data: [], projects: [], articles: [], total: 0, summary: {}, sections: [] };
		if (path.endsWith('/news/summary')) body = { article_count: 0, macro: { title: 'Market conditions', bullets: [] }, real_estate: { title: 'Property news', bullets: [] } };
		if (path.endsWith('/transactions/sales')) body = { transactions: [sale], total: 1 };
		if (path.endsWith('/filters/sales')) body = { property_types: ['Apartment'], locations: ['Synthetic Area'], bedrooms: ['2 Beds'], buildings: [], projects: [], statuses: ['Ready'] };
		if (path.endsWith('/analytics/sales')) body = { summary: { transaction_count: 4, total_volume: 6000000, avg_price: 1500000, avg_price_sqft: 1500, min_price: 1500000 } };
		if (path.endsWith('/analytics/rentals')) body = { summary: { contract_count: 4, min_annual_rent: 120000 } };
		if (path.endsWith('/analytics/market-trend')) body = { data: [1, 2, 3, 4, 5].map((day) => ({ date: `2026-10-0${day}`, transaction_count: 4, avg_price: 1400000 + day * 20000, avg_price_sqft: 1400 + day * 20 })), total_transactions: 20 };
		if (path.endsWith('/analytics/project/summary')) body = {
			usage: 'Residential', usage_counts: {},
			project: { project_name: 'Synthetic Project', area_name: 'Synthetic Area', developer_name: 'Synthetic Developer', no_of_units: 10, field_sources: { developer_name: 'dxbi_buildings', no_of_units: 'dld_units' } },
			sales: { transaction_count: 4, total_volume: 6000000, avg_price: 1500000, avg_price_sqft: 1500, median_price: 1500000 },
			rentals: { contract_count: 4, total_annual_value: 480000, median_annual_rent: 120000, median_rent_sqft: 120 },
			by_rooms: [], by_property_type: [], by_reg_type: [], unit_composition: [], configuration_analysis: [],
			buildings: [{ building_id: 'B1', name: 'Synthetic Tower', units: 10, sales: 4, leases: 4, units_source: 'DLD private stock register' }]
		};
		if (path.endsWith('/analytics/projects')) body = { projects: [{ name: 'Synthetic Project', filter_type: 'project' }], total: 1 };
		if (path.endsWith('/analytics/project/price-distribution')) body = { by_rooms: [] };
		await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
	});
});

for (const theme of ['light', 'dark']) {
	test(`dashboard and card editor omit provider branding in ${theme} mode`, async ({ page }, testInfo) => {
		await page.addInitScript(value => localStorage.setItem('vitevue-preferences', JSON.stringify({ theme: value })), theme);
		await page.setViewportSize({ width: 1440, height: 900 });
		const browserErrors: string[] = [];
		page.on('pageerror', error => browserErrors.push(error.message));
		await page.goto('/dashboard');
		await expect(page.locator('.ui-metric-card')).toHaveCount(5);
		await expect(page.locator('.ui-metric-card').first()).toContainText('4');
		await expect(page.locator('main')).not.toContainText(providers);
		await page.screenshot({ path: testInfo.outputPath(`dashboard-${theme}.png`), animations: 'disabled' });
		await page.getByRole('button', { name: 'Edit cards', exact: true }).click();
		await expect(page.getByRole('heading', { name: 'Drag cards into the dashboard' })).toBeVisible();
		await expect(page.locator('main')).not.toContainText(providers);
		await page.getByRole('button', { name: 'Reset defaults', exact: true }).click();
		await expect(page.locator('.ui-metric-card')).toHaveCount(5);
		await page.getByRole('button', { name: 'Done', exact: true }).click();
		await page.setViewportSize({ width: 375, height: 812 });
		await expect(page.locator('main')).not.toContainText(providers);
		expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
		expect(browserErrors).toEqual([]);
	});
}

test('transaction details keep recorded values while analytics hides provider metadata', async ({ page }) => {
	await page.goto('/transactions/sales');
	await page.getByRole('row').filter({ hasText: 'Synthetic Tower' }).click();
	const dialog = page.getByRole('dialog');
	await expect(dialog).toBeVisible();
	await expect(dialog).toContainText('1203');
	await expect(dialog).toContainText('Synthetic District');
	await expect(dialog).not.toContainText(providers);
	await expect(page.locator('main')).not.toContainText(providers);

	await page.goto('/analytics');
	await expect(page.getByRole('heading', { name: 'Configuration Analysis', exact: true })).toBeVisible();
	await expect(page.locator('main')).not.toContainText(providers);
	await expect(page.getByTestId('analytics-field-sources')).toHaveCount(0);
	await page.getByRole('combobox').fill('Synthetic Project');
	await page.getByRole('option').filter({ hasText: 'Synthetic Project' }).click();
	await expect(page.getByTestId('analytics-buildings')).toBeVisible();
	await expect(page.locator('main')).not.toContainText(providers);
	const unitCell = page.getByTestId('analytics-buildings').getByRole('row').filter({ hasText: 'Synthetic Tower' }).getByRole('cell').nth(1);
	await expect(unitCell).toHaveText('10');
	await expect(unitCell).not.toHaveAttribute('title');
});
