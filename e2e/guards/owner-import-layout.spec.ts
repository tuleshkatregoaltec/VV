import { expect, test } from '../fixtures/guards';
import { personas } from '../fixtures/personas';

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
	await expect(page.getByText('transaction matching not run')).toHaveCount(0);
	const auditRegion = page.getByRole('region', { name: 'Import summary', exact: true });
	await expect(auditRegion.locator('details').first()).not.toHaveAttribute('open', '');
	await expect(auditRegion.getByText('File references', { exact: true })).not.toBeVisible();
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
	// Like the mock's import requests card: what the file held, then status with what happened to the rows.
	await expect(importedRow.locator('[data-label="What"]')).toHaveText('Owners · 8 rows');
	await expect(importedRow.locator('[data-label="Status"]')).toHaveText('Completed · 5 kept · 2 duplicates merged · 1 dropped');
	const pending = page.locator('tbody tr').filter({ hasText: 'Synthetic pending workbook' });
	await expect(pending.locator('[data-label="What"]')).toHaveText('Owners');
	await expect(pending.locator('[data-label="Status"]')).toHaveText('Processing');
	await importedRow.getByRole('button', { name: imported.name, exact: true }).click();
	await expect(page.locator('.row-accounting')).toHaveText('8 source rows · 5 kept · 2 merged · 1 dropped.');
	await expect(page.locator('.kpi:visible')).toHaveCount(0);
	await page.locator('details.snapshot').getByText('Processing details', { exact: true }).click();
	const ownership = page.getByRole('region', { name: 'Current ownership summary', exact: true });
	const disclosure = ownership.getByText('Details', { exact: true });
	await expect(ownership.getByText('Owner–property associations', { exact: true })).not.toBeVisible();
	await disclosure.focus();
	await page.keyboard.press('Enter');
	await expect(ownership.getByText('Owner–property associations', { exact: true })).toBeVisible();
	await expect(ownership.locator('div').filter({ has: page.getByText('Owner–property associations', { exact: true }) }).locator('dd')).toHaveText('4');
	await disclosure.click();
	await expect(page.getByRole('heading', { name: 'Source rows', exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Rename', exact: true }).click();
	await expect(page.getByLabel('Import name', { exact: true })).toHaveValue(imported.name);
	await page.getByRole('button', { name: 'Cancel', exact: true }).click();
	await page.getByRole('button', { name: 'Delete', exact: true }).click();
	await expect(page.getByText('Delete this import, its saved list and its rows? Owner notes stay.', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Cancel', exact: true }).click();
	const reportPath = testInfo.outputPath('owner-import-report.png');
	await page.screenshot({ path: reportPath, fullPage: true, animations: 'disabled' });
	console.log('Owner UI layout screenshots:', JSON.stringify([...screenshots, testInfo.outputPath('owners-mobile.png'), reportPath]));
});

// Identity changes must evict previous-organization rows before the replacement request resolves.
test('CRM membership changes clear old rows and Owners reads one registry page', async ({ page, usePersona }) => {
	await usePersona('active-owner');
	let organization = 'org-a';
	let registryRequests = 0;
	let releaseNewPage: (() => void) | undefined;
	let waitingForNewPage = false;
	await page.route('**/api/v1/auth/me', async route => {
		await route.fulfill({ json: { ...personas['active-owner'], organization_id: organization } });
	});
	await page.route('**/api/v1/crm/**', async route => {
		const path = new URL(route.request().url()).pathname;
		let body: unknown = [];
		if (path.endsWith('/owner-registry')) {
			registryRequests += 1;
			if (organization === 'org-b') {
				waitingForNewPage = true;
				await new Promise<void>(resolve => { releaseNewPage = resolve; });
			}
			body = { owners: [{ owner_key: organization, contact_name: `Private ${organization} owner`, highest_ownership_status: 'probable_current_owner', properties: [] }], total: 1 };
		}
		if (path.endsWith('/inbound/enquiries')) body = { enquiries: [], total: 0 };
		await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
	});
	await page.goto('/crm/owners');
	await expect(page.getByRole('button', { name: 'Private org-a owner', exact: true })).toBeVisible();
	expect(registryRequests).toBe(1);
	organization = 'org-b';
	await page.evaluate(async () => {
		const userStore = await import('/src/lib/stores/user.svelte.ts');
		await userStore.refreshUser();
	});
	await expect.poll(() => waitingForNewPage).toBe(true);
	await expect(page.getByRole('button', { name: 'Private org-a owner', exact: true })).toHaveCount(0);
	releaseNewPage?.();
	await expect(page.getByRole('button', { name: 'Private org-b owner', exact: true })).toBeVisible();
	expect(registryRequests).toBe(2);
});

test('Renewals accumulates offset pages past 200 without requesting earlier rows again', async ({ page, usePersona }) => {
	await usePersona('active-owner');
	const requests: { limit: number; offset: number }[] = [];
	await page.route('**/api/v1/crm/**', async route => {
		const url = new URL(route.request().url());
		let body: unknown = [];
		if (url.pathname.endsWith('/inbound/enquiries')) body = { enquiries: [], total: 0 };
		if (url.pathname.endsWith('/renewals')) {
			const limit = Number(url.searchParams.get('limit'));
			const offset = Number(url.searchParams.get('offset'));
			requests.push({ limit, offset });
			body = { leads: Array.from({ length: Math.min(limit, 230 - offset) }, (_, i) => ({ lead_id: `lease-${offset + i}`, building_name: `Synthetic Lease ${offset + i}`, unit_number: '1', area_name: 'Synthetic Area', days_to_expiry: 15, annual_rent_aed: 50000 })), total: 230 };
		}
		await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
	});
	await page.goto('/crm/assets');
	await page.getByRole('tab', { name: 'Renewals', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Synthetic Lease 0 · unit 1', exact: true })).toBeVisible();
	for (const loaded of [50, 100, 150, 200]) {
		await page.getByRole('button', { name: `Show more · ${loaded} of 230`, exact: true }).click();
		await expect(page.getByRole('button', { name: `Synthetic Lease ${Math.min(loaded + 49, 229)} · unit 1`, exact: true })).toBeVisible();
	}
	await expect(page.getByRole('button', { name: /Show more/ })).toHaveCount(0);
	await expect(page.locator('tbody tr')).toHaveCount(230);
	expect(requests).toEqual([0, 50, 100, 150, 200].map(offset => ({ limit: 50, offset })));
});

test('accepted owner uploads show queue progress and update their report after background completion', async ({ page, usePersona }) => {
	test.setTimeout(45_000);
	await usePersona('active-owner');
	let status: 'queued' | 'retry_wait' | 'completed' = 'queued';
	let accepted = false;
	let enquiryReads = 0;
	const job = () => ({
		id: 193, name: 'Synthetic queued workbook', original_filename: 'queued.csv', status,
		created_at: '2026-11-01T00:00:00Z', list_id: status === 'completed' ? 41 : null,
		mappings: [], summary: status === 'completed' ? { total_rows: 1, candidate_rows: 1 } : {}
	});
	await page.route('**/api/v1/crm/**', async route => {
		const url = new URL(route.request().url());
		let body: unknown = [];
		let responseStatus = 200;
		if (url.pathname.endsWith('/contact-imports/preview')) body = { sheets: [{ sheet_name: 'Owners', rows: 1, columns: [{ header: 'Name', field: 'contact_name' }, { header: 'Unit', field: 'unit_number' }], mapped_at_import: false }] };
		if (url.pathname.endsWith('/contact-imports')) {
			if (route.request().method() === 'POST') {
				accepted = true;
				responseStatus = 202;
				body = job();
			} else body = accepted ? [job()] : [];
		}
		if (url.pathname.endsWith('/owner-history/summary') || url.pathname.endsWith('/owner-summary')) body = { source_event_count: 0, identifiable_property_count: 0, owner_property_count: 0, verified_current_count: 0, probable_current_count: 0, former_count: 0, unresolved_count: 0, invalid_identity_source_count: 0, legacy_source_event_count: 0, resolver_versions: {}, warehouse_status: 'not_requested', checked_at: null };
		if (url.pathname.endsWith('/contact-lists/41')) body = { contacts: [], total: 0, offset: 0, limit: 100 };
		if (url.pathname.endsWith('/inbound/enquiries')) { enquiryReads += 1; body = { enquiries: [], total: 0 }; }
		await route.fulfill({ status: responseStatus, contentType: 'application/json', body: JSON.stringify(body) });
	});
	await page.goto('/crm/owners/imports');
	await page.getByRole('button', { name: 'Import a file', exact: true }).click();
	await page.locator('input[type="file"]').setInputFiles({ name: 'queued.csv', mimeType: 'text/csv', buffer: Buffer.from('Name,Unit\nSynthetic Person,101\n') });
	await page.getByRole('button', { name: 'Import 1 rows', exact: true }).click();
	await expect(page.getByText('This file is queued. You can close this panel; processing continues in the background.', { exact: true })).toBeVisible();
	await expect(page.getByText(/This file was already imported/)).toHaveCount(0);
	await expect(page.getByText(/0 rows kept/)).toHaveCount(0);
	await page.getByRole('button', { name: 'Open report', exact: true }).click();
	await expect(page).toHaveURL(/\/crm\/owners\/imports\/193$/);
	const beforeCompletion = enquiryReads;
	status = 'retry_wait';
	await expect(page.getByText('This file is waiting to retry. Processing will resume automatically.', { exact: true })).toBeVisible({ timeout: 15_000 });
	status = 'completed';
	await expect(page.locator('.row-accounting')).toHaveText('1 source rows · 1 kept · 0 merged · 0 dropped.', { timeout: 25_000 });
	await expect(page.getByText('This file is waiting to retry. Processing will resume automatically.', { exact: true })).toHaveCount(0);
	expect(enquiryReads).toBeGreaterThan(beforeCompletion);
});

test('inbound queue polling starts only after upload and refreshes Inbox after the panel closes', async ({ page, usePersona }) => {
	await usePersona('active-owner');
	let accepted = false;
	let completed = false;
	let historyReads = 0;
	const inbound = () => ({ id: 194, name: 'Synthetic inbound file', original_filename: 'leads.csv', status: completed ? 'completed' : 'queued', summary: completed ? { total_rows: 1 } : {}, created_at: '2026-11-01T00:00:00Z' });
	await page.route('**/api/v1/crm/**', async route => {
		const url = new URL(route.request().url());
		let body: unknown = [];
		let responseStatus = 200;
		if (url.pathname.endsWith('/inbound/imports/preview')) body = { original_filename: 'leads.csv', total_rows: 1, warnings: [], sheets: [{ field_map: { full_name: 'Name', phone: 'Phone' }, sample_rows: [{ full_name: 'Synthetic Queued Enquiry', phone: '0500000000' }] }] };
		if (url.pathname.endsWith('/inbound/imports')) {
			if (route.request().method() === 'POST') { accepted = true; responseStatus = 202; body = inbound(); }
			else { historyReads += 1; body = accepted ? [inbound()] : []; }
		}
		if (url.pathname.endsWith('/contact-imports')) historyReads += 1;
		if (url.pathname.endsWith('/inbound/enquiries')) {
			const rows = completed && url.searchParams.get('workspace') === 'unqualified' ? [{ id: 194, contact: { full_name: 'Synthetic Queued Enquiry', phone: '0500000000', registry_profiles: [] }, intent: 'unknown', status: 'new', assigned_user_id: null, source: 'Imported file', enquiry_date: '2026-11-01T00:00:00Z', criteria: {}, tags: [], observed_data: {}, strict_fields: [], review_reasons: [], sla_state: 'on_time' }] : [];
			body = { enquiries: rows, total: rows.length };
		}
		await route.fulfill({ status: responseStatus, contentType: 'application/json', body: JSON.stringify(body) });
	});
	await page.goto('/crm/inbox');
	await expect(page.getByText('No enquiries.', { exact: true })).toBeVisible();
	expect(historyReads).toBe(0);
	await page.getByRole('button', { name: 'Everything you can create', exact: true }).click();
	await page.getByRole('button', { name: 'Import a file', exact: true }).click();
	await page.getByRole('group', { name: 'What is in the file', exact: true }).getByRole('button', { name: 'Leads', exact: true }).click();
	await page.locator('input[type="file"]').setInputFiles({ name: 'leads.csv', mimeType: 'text/csv', buffer: Buffer.from('Name,Phone\nSynthetic Queued Enquiry,0500000000\n') });
	await page.getByRole('button', { name: 'Import 1 rows', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'Import a file', exact: true })).toHaveCount(0);
	await expect(page.getByText('Import queued', { exact: true })).toBeVisible();
	completed = true;
	await expect(page.getByRole('region', { name: 'Enquiries', exact: true }).getByRole('button', { name: /Synthetic Queued Enquiry/ })).toBeVisible({ timeout: 15_000 });
	expect(historyReads).toBeGreaterThan(0);
});
