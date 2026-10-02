import { expect, test } from '../fixtures/guards';

const now = '2026-10-03T00:00:00+00:00';
const conversation = { id: 987655, user_id: 'browser-fixture', title: 'Grounded chat', created_at: now, updated_at: now };

test('chat sends retry identity and reports an incomplete stream as an error', async ({ page, usePersona }) => {
    await usePersona('active-owner');
    await page.route('**/api/v1/chat/conversations?*', route => route.fulfill({ json: { conversations: [conversation], total: 1 } }));
    await page.route('**/api/v1/chat/conversations/987655/messages?*', route => route.fulfill({ json: [] }));
    await page.route('**/api/v1/chat/conversations/987655/messages/stream', route => {
        const body = route.request().postDataJSON();
        expect(body.message).toBe('Average sale price last month');
        expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/);
        return route.fulfill({ contentType: 'text/event-stream', body: 'data: {"type":"thinking"}\n\ndata: {"type":"content","content":"Partial response"}\n\n' });
    });
    await page.goto('/chat');
    await page.getByRole('button', { name: 'Select Grounded chat. Double-click to rename.' }).click();
    await page.getByPlaceholder('Ask anything about Dubai real estate...').fill('Average sale price last month');
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    await expect(page.getByText(/Stream ended before completion/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Stop streaming' })).toHaveCount(0);
});

test('cancelled persisted turns stay explicit after reload', async ({ page, usePersona }) => {
    await usePersona('active-owner');
    await page.route('**/api/v1/chat/conversations?*', route => route.fulfill({ json: { conversations: [conversation], total: 1 } }));
    await page.route('**/api/v1/chat/conversations/987655/messages?*', route => route.fulfill({ json: [{
        id: 1, conversation_id: conversation.id, role: 'user', content: 'Interrupted question', created_at: now,
        meta_data: { request_id: 'persisted-request', turn_status: 'cancelled' }
    }] }));
    await page.goto('/chat');
    await page.getByRole('button', { name: 'Select Grounded chat. Double-click to rename.' }).click();
    await expect(page.getByText('The last response was cancelled. Send a new message to continue.')).toBeVisible();
    await page.reload();
    await page.getByRole('button', { name: 'Select Grounded chat. Double-click to rename.' }).click();
    await expect(page.getByText('The last response was cancelled. Send a new message to continue.')).toBeVisible();
});
