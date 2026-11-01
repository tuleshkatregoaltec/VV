import { expect, test } from '../fixtures/guards';

for (const complete of [true, false]) {
    test(`chat ${complete ? 'accepts explicit completion after heartbeats' : 'reports an interrupted stream'}`, async ({ page, usePersona }) => {
        await usePersona('active-owner');
        const now = '2026-11-01T00:00:00Z';
        const conversation = { id: 901, user_id: 'fixture', title: 'Stream reliability', created_at: now, updated_at: now };
        let sent = false;
        await page.route('**/api/v1/chat/conversations?*', route => route.fulfill({ json: { conversations: [conversation], total: 1 } }));
        await page.route('**/api/v1/chat/conversations/901/messages?*', route => route.fulfill({ json: sent && complete ? [
            { id: 1, conversation_id: 901, role: 'user', content: 'Show my leads', created_at: now, meta_data: {} },
            { id: 2, conversation_id: 901, role: 'assistant', content: 'Validated answer', created_at: now, meta_data: {} }
        ] : [] }));
        await page.route('**/api/v1/assistant/actions/proposals?*', route => route.fulfill({ json: [] }));
        await page.route('**/api/v1/chat/conversations/901/messages/stream', route => {
            sent = true;
            return route.fulfill({ contentType: 'text/event-stream', body:
                ': keep-alive\n\ndata: {"type":"content","content":"Validated answer"}\n\n' +
                (complete ? ': keep-alive\n\ndata: {"type":"done"}\n\n' : '') });
        });
        await page.goto('/chat');
        await page.getByRole('button', { name: 'Select Stream reliability. Double-click to rename.' }).click();
        await page.getByPlaceholder('Ask anything about Dubai real estate...').fill('Show my leads');
        await page.getByRole('button', { name: 'Send message', exact: true }).click();
        if (complete) {
            await expect(page.getByText('Validated answer', { exact: true })).toBeVisible();
            await expect(page.getByText('The assistant could not complete this request. Please try again.', { exact: true })).toHaveCount(0);
        } else {
            await expect(page.getByText('The assistant could not complete this request. Please try again.', { exact: true })).toBeVisible();
        }
        await expect(page.getByRole('button', { name: 'Stop streaming' })).toHaveCount(0);
        await expect(page.getByText('keep-alive', { exact: true })).toHaveCount(0);
    });
}
