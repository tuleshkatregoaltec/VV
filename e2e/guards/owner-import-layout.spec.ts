import { expect, test } from '../fixtures/guards';

// Synthetic responses isolate presentation from the real-service upload regression in owner-import.spec.ts.
// Contact rows, workbook references and people–property associations deliberately have different totals.
test('owners and import reports keep evidence available without a metric dashboard', async ({ page, usePersona }, testInfo) => {
	await usePersona('active-owner');
	const audit = {
		mode: 'source_only', import_count: 1, source_row_count: 8,
		reference_count: 3, owner_candidate_reference_count: 2, review_reference_count: 1,
		bank_reference_count: 0, excluded_nonownership_reference_count: 0,
		excluded_scope_reference_count: 0, disposition_counts: {}
	};
	const imported = {
		id: 91, name: 'Synthetic owner workbook', original_filename: 'synthetic-owners.csv',
		status: 'completed', created_at: '2026-10-29T10:00:00Z', list_id: 41, mappings: [],
		summary: { total_rows: 8, candidate_rows: 5, duplicate_rows_collapsed: 2, source_audit: audit }
	};
	const owners = ['Synthetic Buyer', 'Synthetic Organization', 'Synthetic Candidate'].map((name, i) => ({
		owner_key: `synthetic-${i}`, contact_name: name,
		highest_ownership_status: 'probable_current_owner',
		properties: [{
			property_key: `synthetic-property-${i}`, unit_number: String(100 + i),
			building_name: 'Synthetic Tower', project_name: 'Synthetic Project', area_name: 'Synthetic Area',
			property_type: 'Apartment', ownership_status: 'probable_current_owner',
			match_reason: 'Source buyer claim; transaction matching was not run'
		}]
	}));
	await page.route('**/api/v1/crm/**', async route => {
		const url = new URL(route.request().url());
		let body: unknown = [];
		if (url.pathname.endsWith('/owner-registry')) body = { owners, total: owners.length, summary: {}, source_audit: audit };
		if (url.pathname.endsWith('/contact-imports')) body = [imported, {
			...imported, id: 92, name: 'Synthetic pending workbook', status: 'processing', summary: {}
		}];
		if (url.pathname.endsWith('/owner-summary') || url.pathname.endsWith('/owner-history/summary')) body = {
			source_event_count: 5, identifiable_property_count: 3, owner_property_count: 4,
			verified_current_count: 0, probable_current_count: 3, former_count: 0, unresolved_count: 1,
			invalid_identity_source_count: 0, legacy_source_event_count: 0, resolver_versions: {},
			warehouse_status: 'not_requested', checked_at: null
		};
		if (url.pathname.endsWith('/contact-lists/41')) body = {
			contacts: [{
				id: 1, owner_key: 'synthetic-0', contact_name: 'Synthetic Buyer', phone_primary: '+971500000001',
				building_name: 'Synthetic Tower', project_name: 'Synthetic Project', area_name: 'Synthetic Area',
				unit_number: '100', property_type: 'Apartment', property_details: {},
				ownership_status: 'probable_current_owner', confidence_score: 50,
				match_reason: 'Source buyer claim; transaction matching was not run', source_sheet: 'Owners', source_row_number: 2
			}], total: 1, offset: 0, limit: 100
		};
		if (url.pathname.endsWith('/inbound/enquiries')) body = { enquiries: [], total: 0 };
		await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
	});

	await page.setViewportSize({ width: 1440, height: 900 });
	await page.goto('/crm/owners');
	await expect(page.getByRole('button', { name: 'Synthetic Buyer', exact: true })).toBeVisible({ timeout: 15_000 });
	await expect(page.getByText('Workbook only — transaction matching not run. DXBI sales evidence was not checked.', { exact: true })).toBeVisible();
	const auditRegion = page.getByRole('region', { name: 'Workbook source audit', exact: true });
	await expect(auditRegion.locator('details').first()).not.toHaveAttribute('open', '');
	await expect(auditRegion.getByText('Workbook references', { exact: true })).not.toBeVisible();
	await expect(page.getByLabel('Ownership', { exact: true })).toHaveValue('current');
	await page.getByLabel('Ownership', { exact: true }).selectOption('former');
	await expect(page.getByLabel('Ownership', { exact: true })).toHaveValue('former');
	await page.getByLabel('Ownership', { exact: true }).selectOption('current');
	await expect(page.locator('.kpi:visible')).toHaveCount(0);
	const screenshots: string[] = [];
	for (const theme of ['light', 'dark'] as const) {
		const switcher = page.getByRole('button', { name: `Switch to ${theme}`, exact: true });
		if (await switcher.isVisible()) await switcher.click();
		const path = testInfo.outputPath(`owners-${theme}.png`);
		await page.screenshot({ path, fullPage: true, animations: 'disabled' });
		screenshots.push(path);
	}
	await page.setViewportSize({ width: 375, height: 812 });
	await expect(page.getByRole('button', { name: 'Synthetic Buyer', exact: true })).toBeVisible();
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
	await page.screenshot({ path: testInfo.outputPath('owners-mobile.png'), fullPage: true, animations: 'disabled' });

	await page.setViewportSize({ width: 1440, height: 900 });
	await page.getByRole('button', { name: 'Switch to light', exact: true }).click();
	await page.goto('/crm/owners/imports');
	const importedRow = page.locator('tbody tr').filter({ has: page.getByRole('button', { name: imported.name, exact: true }) });
	for (const [label, count] of [['Rows', '8'], ['Kept', '5'], ['Merged', '2'], ['Dropped', '1']]) {
		await expect(importedRow.locator(`[data-label="${label}"]`)).toHaveText(count);
	}
	await expect(page.locator('tbody tr').filter({ hasText: 'Synthetic pending workbook' }).locator('[data-label="Rows"]')).toHaveText('—');
	await importedRow.getByRole('button', { name: imported.name, exact: true }).click();
	await expect(page.locator('.row-accounting')).toHaveText('8 source rows · 5 kept · 2 merged · 1 dropped.');
	await expect(page.locator('.kpi:visible')).toHaveCount(0);
	await page.locator('details.snapshot').getByText('Processing details', { exact: true }).click();
	const ownership = page.getByRole('region', { name: 'Current ownership summary', exact: true });
	const disclosure = ownership.getByText('Evidence and counting details', { exact: true });
	await expect(ownership.getByText('Source associations', { exact: true })).not.toBeVisible();
	await disclosure.focus();
	await page.keyboard.press('Enter');
	await expect(ownership.getByText('Source associations', { exact: true })).toBeVisible();
	await expect(ownership.locator('div').filter({ has: page.getByText('Source associations', { exact: true }) }).locator('dd')).toHaveText('4');
	await disclosure.click();
	await expect(page.getByRole('heading', { name: 'Source rows', exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Rename', exact: true }).click();
	await expect(page.getByLabel('Import name', { exact: true })).toHaveValue(imported.name);
	await page.getByRole('button', { name: 'Cancel', exact: true }).click();
	await page.getByRole('button', { name: 'Delete', exact: true }).click();
	await expect(page.getByText('Delete this import, its saved list and its rows?', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Cancel', exact: true }).click();
	const reportPath = testInfo.outputPath('owner-import-report.png');
	await page.screenshot({ path: reportPath, fullPage: true, animations: 'disabled' });
	console.log('Owner UI layout screenshots:', JSON.stringify([...screenshots, testInfo.outputPath('owners-mobile.png'), reportPath]));
});
