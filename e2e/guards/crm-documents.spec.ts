import type { Page, Request } from '@playwright/test';

import { expect, test } from '../fixtures/guards';

/**
 * Listing documents, end to end in the browser with the CRM API mocked: the Documents tab,
 * saving information, generating once per click, missing details, downloads, and the
 * CRM › Documents page. Backend rules themselves are covered by backend tests.
 */

const LISTING = {
	reference: 'PF-123',
	listing_key: '123',
	agent_name: 'Big Firm · Navi',
	agent_phone: null,
	mode: 'sale',
	title: 'Marina Gate 2BR',
	property_type: 'Apartment',
	bedrooms: 2,
	size_sqft: 1200,
	price_aed: 2500000,
	area_name: 'Dubai Marina',
	building_name: 'Marina Gate',
	unit_number: null,
	status: 'active',
	listed_at: '2026-11-01T00:00:00Z',
	broker_id: 'B1',
	broker_name: 'Big Firm',
	managed: true
};

const EMPTY_FIELDS = { owner: {}, lease: {}, a2a: {}, marketing: {} };

function doc(id: string, doc_type: string, status = 'ready') {
	return {
		id,
		source: 'property_finder',
		listing_key: '123',
		listing_title: 'Marina Gate 2BR',
		doc_type,
		template_version: 'draft-1',
		status,
		failure_code: status === 'failed' ? 'render_failed' : null,
		size_bytes: 31000,
		created_by_user_id: 'u1',
		created_at: '2026-11-11T10:00:00Z'
	};
}

type Api = {
	listing?: typeof LISTING;
	documents: ReturnType<typeof doc>[];
	revision: number;
	generate?: (body: Record<string, unknown>) => { status: number; body: unknown };
	calls: { method: string; path: string; body: unknown }[];
};

const json = (status: number, body: unknown) => ({
	status,
	contentType: 'application/json',
	body: JSON.stringify(body)
});

async function mockApi(page: Page, api: Api) {
	// Anything this spec does not describe: an empty answer, so the shell still renders.
	await page.route('**/api/v1/**', (route) => route.fulfill(json(404, { detail: 'Not found' })));
	await page.route('**/api/v1/crm/**', async (route) => {
		const request: Request = route.request();
		const url = new URL(request.url());
		const path = url.pathname.replace('/api/v1/crm', '');
		const body = request.postDataJSON?.() ?? null;
		api.calls.push({ method: request.method(), path: path + url.search, body });
		const listing = api.listing ?? LISTING;

		if (path === '/company-listings/123') return route.fulfill(json(200, listing));
		if (path === '/listing-document-info' && request.method() === 'GET')
			return route.fulfill(
				json(200, { listing, fields: EMPTY_FIELDS, revision: api.revision })
			);
		if (path === '/listing-document-info' && request.method() === 'PUT') {
			if (body.expected_revision !== api.revision) return route.fulfill(json(409, { detail: 'stale_revision' }));
			api.revision += 1;
			return route.fulfill(json(200, { listing, fields: body.fields, revision: api.revision }));
		}
		if (path === '/documents' && request.method() === 'POST') {
			const answer = api.generate?.(body) ?? { status: 201, body: doc(`d-${api.documents.length + 1}`, body.doc_type) };
			if (answer.status < 300) api.documents.unshift(answer.body as ReturnType<typeof doc>);
			return route.fulfill(json(answer.status, answer.body));
		}
		if (path === '/documents' && request.method() === 'GET') {
			const type = url.searchParams.get('doc_type');
			const items = api.documents.filter((d) => !type || d.doc_type === type);
			return route.fulfill(json(200, { items, total: items.length, limit: 50, offset: 0 }));
		}
		if (/^\/documents\/[^/]+\/download$/.test(path))
			return route.fulfill(
				json(200, { url: 'http://127.0.0.1:5173/__signed/noc.pdf', expires_at: '2026-11-11T10:05:00Z' })
			);
		return route.fulfill(json(404, { detail: 'Not found' }));
	});
	await page.route('**/__signed/**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/pdf',
			headers: { 'Content-Disposition': 'attachment; filename="noc-123.pdf"' },
			body: '%PDF-1.7'
		})
	);
}

const fresh = (): Api => ({ documents: [], revision: 0, calls: [] });

test('an agent saves owner details, generates an NOC once and downloads it', async ({ page, usePersona }) => {
	const api = fresh();
	await mockApi(page, api);
	await usePersona('active-member');

	await page.goto('/crm/documents?listing=PF-123&tab=documents');

	const generator = page.getByRole('region', { name: 'Generate PDF' });
	await expect(page.getByRole('heading', { name: 'Owner information' })).toBeVisible();
	await expect(page.getByText('Save the document information first')).toBeVisible();
	await expect(generator.getByRole('button', { name: 'NOC', exact: true })).toBeDisabled();

	await page.getByLabel('Owner name').fill('Aisha Khan');
	await page.getByLabel('Title deed number').fill('TD-2024-1');
	await page.getByLabel('Emirates ID / passport number').fill('784-1990-1234567-1');
	await page.getByRole('button', { name: 'Save information' }).click();

	await expect.poll(() => api.revision).toBe(1);
	const saved = api.calls.find((c) => c.method === 'PUT');
	expect(saved?.body).toMatchObject({
		listing_key: '123',
		expected_revision: 0,
		fields: { owner: { full_name: 'Aisha Khan', title_deed_number: 'TD-2024-1' } }
	});

	const noc = generator.getByRole('button', { name: 'NOC', exact: true });
	await expect(noc).toBeEnabled();
	await noc.dblclick();

	await expect(page.getByText('NOC PDF ready to download')).toBeVisible();
	// A double click is one request: the buttons lock while the PDF is being made.
	expect(api.calls.filter((c) => c.method === 'POST' && c.path === '/documents')).toHaveLength(1);
	expect(api.calls.find((c) => c.path === '/documents' && c.method === 'POST')?.body).toMatchObject({
		doc_type: 'noc',
		expected_revision: 1
	});

	const download = page.waitForEvent('download');
	// The panel sits over the page's own list; its Download comes last in the page.
	await page.getByRole('button', { name: 'Download' }).last().click();
	expect((await download).suggestedFilename()).toBe('noc-123.pdf');
	await expect(generator).toBeVisible();
});

test('missing lease terms are named and nothing is offered for download', async ({ page, usePersona }) => {
	const api = fresh();
	api.revision = 1;
	api.generate = () => ({
		status: 422,
		body: { detail: { code: 'missing_fields', fields: ['lease.tenant_name', 'lease.annual_rent_aed'] } }
	});
	await mockApi(page, api);
	await usePersona('active-member');

	await page.goto('/crm/documents?listing=PF-123&tab=documents');
	await page.getByRole('region', { name: 'Generate PDF' }).getByRole('button', { name: 'Lease Agreement' }).click();

	await expect(page.getByRole('alert')).toContainText('Lease Agreement needs: Tenant name, Annual rent (AED).');
	await expect(page.getByText('No PDFs generated for this listing yet.')).toBeVisible();
});

test("another company's listing has no Documents tab", async ({ page, usePersona }) => {
	const api = fresh();
	api.listing = { ...LISTING, managed: false };
	await mockApi(page, api);
	await usePersona('active-member');

	await page.goto('/crm/documents?listing=PF-123&tab=documents');

	await expect(page.getByText('Marina Gate 2BR').first()).toBeVisible();
	await expect(page.getByRole('tab', { name: 'Documents' })).toHaveCount(0);
	await expect(page.getByRole('heading', { name: 'Owner information' })).toHaveCount(0);
	expect(api.calls.some((c) => c.path.startsWith('/listing-document-info'))).toBe(false);
});

test('CRM › Documents lists generated PDFs, filters by type and links to the listing', async ({ page, usePersona }) => {
	const api = fresh();
	api.documents = [doc('d-2', 'lease', 'failed'), doc('d-1', 'noc')];
	await mockApi(page, api);
	await usePersona('active-member');

	await page.goto('/crm/documents');

	await expect(page.getByRole('link', { name: /^Documents\b/ })).toHaveAttribute('aria-current', 'page');
	await expect(page.getByText('Generated documents · 2')).toBeVisible();
	await expect(page.getByText('Failed')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Download' })).toHaveCount(1);

	await page.getByRole('radio', { name: 'NOC' }).or(page.getByRole('button', { name: 'NOC', exact: true })).first().click();
	await expect(page).toHaveURL(/type=noc/);
	await expect(page.getByText('Generated documents · 1')).toBeVisible();

	await expect(page.getByRole('link', { name: 'Marina Gate 2BR' })).toHaveAttribute(
		'href',
		'/crm/assets?listing=PF-123&tab=documents'
	);
});
