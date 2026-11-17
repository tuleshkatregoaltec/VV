import { createServer } from 'node:http';
import { expect, test } from '../fixtures/guards';

const conversation = (id: number) => ({
	id,
	title: `Review conversation ${id}`,
	created_at: '2026-11-17T05:00:00Z',
	updated_at: '2026-11-17T05:00:00Z'
});

async function mockCrm(page: import('@playwright/test').Page) {
	await page.route('**/api/v1/**', (route) => {
		const path = new URL(route.request().url()).pathname;
		let json: unknown = {};
		if (path.endsWith('/inbound/enquiries')) json = { enquiries: [], total: 0 };
		else if (path.endsWith('/email/status')) json = { configured: false };
		else if (path.endsWith('/whatsapp/status')) json = { configured: false, connected: false };
		else if (path.endsWith('/assistant/conversations')) {
			json = route.request().method() === 'POST' ? conversation(7) : { conversations: [], total: 0 };
		} else if (path.endsWith('/messages')) json = [];
		return route.fulfill({ json });
	});
}

test('older conversations remain reachable after the first fifty', async ({ page, usePersona }) => {
	await mockCrm(page);
	await usePersona('active-owner');
	await page.route('**/assistant/conversations?*', (route) => {
		const offset = Number(new URL(route.request().url()).searchParams.get('offset') ?? 0);
		const rows = Array.from({ length: 51 }, (_, i) => conversation(51 - i));
		return route.fulfill({ json: { conversations: rows.slice(offset, offset + 50), total: 51 } });
	});
	await page.goto('/crm/assistant');
	await expect(page.getByRole('button', { name: 'Load older conversations' })).toBeVisible();
	await expect(page.getByText('Review conversation 1', { exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: 'Load older conversations' }).click();
	await expect(page.getByText('Review conversation 1', { exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Load older conversations' })).toHaveCount(0);
});

test('a long conversation retains its newest answer and can load its oldest message', async ({ page, usePersona }) => {
	await mockCrm(page);
	await usePersona('active-owner');
	await page.route('**/assistant/conversations?*', (route) => route.fulfill({ json: { conversations: [conversation(7)], total: 1 } }));
	await page.route('**/assistant/conversations/7/messages?*', (route) => {
		const offset = Number(new URL(route.request().url()).searchParams.get('offset') ?? 0);
		const rows = Array.from({ length: 201 }, (_, i) => ({ id: i + 1, role: 'assistant', content: `History message ${i + 1}`, meta_data: {}, created_at: '2026-11-17T05:00:00Z' }));
		const end = rows.length - offset;
		return route.fulfill({ json: rows.slice(Math.max(0, end - 200), end) });
	});
	await page.goto('/crm/assistant');
	await page.getByText('Review conversation 7', { exact: true }).click();
	await expect(page.getByText('History message 201', { exact: true })).toBeVisible();
	await expect(page.getByText('History message 1', { exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: 'Load earlier messages' }).click();
	await expect(page.getByText('History message 1', { exact: true })).toBeAttached();
	await expect(page.getByText('History message 201', { exact: true })).toBeAttached();
});

test('closing the assistant widget aborts its active HTTP response', async ({ page, usePersona }) => {
	let closed = false;
	const server = createServer((request, response) => {
		response.setHeader('Access-Control-Allow-Origin', 'http://localhost:5173');
		response.setHeader('Access-Control-Allow-Credentials', 'true');
		response.setHeader('Access-Control-Allow-Headers', 'authorization, content-type');
		if (request.method === 'OPTIONS') { response.writeHead(204).end(); return; }
		response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
		response.write(`data: ${JSON.stringify({ type: 'text-delta', content: 'Streaming review response' })}\n\n`);
		response.on('close', () => { closed = true; });
	});
	await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
	const address = server.address();
	if (!address || typeof address === 'string') throw new Error('Local fixture server did not bind');
	try {
		await mockCrm(page);
		await usePersona('active-owner');
		await page.route('**/assistant/conversations/7/messages/stream', (route) => route.continue({ url: `http://127.0.0.1:${address.port}/stream` }));
		await page.goto('/crm/connectors');
		await page.getByRole('button', { name: 'Open the assistant', exact: true }).click();
		await page.getByRole('textbox', { name: 'Message the assistant' }).fill('Synthetic teardown check');
		await page.getByRole('button', { name: 'Send', exact: true }).click();
		await expect(page.getByText('Streaming review response', { exact: true })).toBeVisible();
		await page.getByRole('button', { name: 'Close the assistant' }).click();
		await expect.poll(() => closed).toBe(true);
	} finally {
		server.closeAllConnections();
		await new Promise<void>((resolve) => server.close(() => resolve()));
	}
});
