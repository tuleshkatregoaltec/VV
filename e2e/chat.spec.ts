import { test, expect } from '@playwright/test';

test('conversation creation, rename, reload and deletion use persisted state', async ({ page }) => {
    await page.goto('/chat');
    const created = page.waitForResponse(response => response.url().endsWith('/api/v1/chat/conversations') && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'New chat', exact: true }).click();
    const response = await created;
    expect(response.ok()).toBeTruthy();
    const conversation = await response.json();
    const title = `Migration chat ${conversation.id}`;
    await page.getByRole('button', { name: 'Select New conversation. Double-click to rename.' }).dblclick();
    // The search box has a placeholder; the inline rename field does not.
    const input = page.locator('aside input[type="text"]:not([placeholder])');
    await input.fill(title);
    const updated = page.waitForResponse(response => response.url().endsWith(`/conversations/${conversation.id}`) && response.request().method() === 'PATCH');
    await input.press('Enter');
    expect((await updated).ok()).toBeTruthy();
    await page.reload();
    const select = page.getByRole('button', { name: `Select ${title}. Double-click to rename.` });
    await expect(select).toBeVisible();
    await select.click();
    await select.locator('..').getByRole('button', { name: 'Conversation options' }).click();
    await page.getByRole('menuitem', { name: 'Delete', exact: true }).click();
    const deleted = page.waitForResponse(response => response.url().endsWith(`/conversations/${conversation.id}`) && response.request().method() === 'DELETE');
    await page.getByRole('button', { name: 'Delete', exact: true }).click();
    expect((await deleted).status()).toBe(204);
    await page.reload();
    await expect(select).toHaveCount(0);
});

test('chat renders existing SSE artifacts and keeps them after message refresh', async ({ page }) => {
    const now = '2026-05-05T00:00:00+00:00';
    const conversation = { id: 987654, user_id: 'browser-fixture', title: 'SSE contract', created_at: now, updated_at: now };
    const artifact = {
        id: 'show_chart:call-1', type: 'custom_chart', status: 'ready', title: 'Migration market chart', created_at: now,
        query: { dataset: 'sales', group_by: 'area' },
        data: { chart_type: 'horizontal_bar', metric: 'transaction_count', metric_label: 'Transactions', dimension: 'area', dimension_label: 'Area', points: [{ label: 'Dubai Marina', value: 42, record_count: 42 }], series: [] }
    };
    let sent = false;
    await page.route('**/api/v1/chat/conversations?*', route => route.fulfill({ json: { conversations: [conversation], total: 1 } }));
    await page.route('**/api/v1/chat/conversations/987654/messages?*', route => route.fulfill({ json: sent ? [
        { id: 1, conversation_id: conversation.id, role: 'user', content: 'Show market activity', created_at: now, meta_data: {} },
        { id: 2, conversation_id: conversation.id, role: 'assistant', content: 'Existing streaming contract preserved.', created_at: now, meta_data: { artifacts: [artifact], total_tokens: 17 } }
    ] : [] }));
    await page.route('**/api/v1/market-chat/conversations/987654/messages/stream', route => {
        expect(route.request().postDataJSON()).toEqual({ message: 'Show market activity' });
        sent = true;
        const events = [
            { type: 'thinking' }, { type: 'tool_call_start', tool: 'show_chart', tool_call_id: 'call-1' },
            { type: 'artifact_opened', artifact: { ...artifact, status: 'loading' } },
            { type: 'artifact_updated', artifact },
            { type: 'tool_call_result', tool: 'show_chart', tool_call_id: 'call-1' },
            { type: 'content', content: 'Existing streaming contract preserved.' }, { type: 'done' }
        ];
        return route.fulfill({ contentType: 'text/event-stream', body: events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('') });
    });
    await page.goto('/chat');
    await page.getByRole('button', { name: 'Select SSE contract. Double-click to rename.' }).click();
    await page.getByPlaceholder('Ask anything about Dubai real estate...').fill('Show market activity');
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    await expect(page.getByText('Existing streaming contract preserved.', { exact: true })).toBeVisible();
    await expect(page.getByText('Migration market chart', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Stop streaming' })).toHaveCount(0);
    await page.reload();
    await page.getByRole('button', { name: 'Select SSE contract. Double-click to rename.' }).click();
    await expect(page.getByText('Migration market chart', { exact: true })).toBeVisible();
});

test('CRM assistant reuses authenticated chat and persists its answer', async ({ page }) => {
    const now = '2026-10-31T00:00:00+00:00';
    const conversation = { id: 987655, user_id: 'browser-fixture', title: 'Private CRM', created_at: now, updated_at: now };
    const question = 'Summarize my CRM leads by status.';
    const answer = 'You have 2 CRM leads: 1 new and 1 qualified. These counts cover your records only.';
    let sent = false;
    await page.route('**/api/v1/chat/conversations?*', route => route.fulfill({ json: { conversations: [conversation], total: 1 } }));
    await page.route('**/api/v1/chat/conversations/987655/messages?*', route => route.fulfill({ json: sent ? [
        { id: 1, conversation_id: conversation.id, role: 'user', content: question, created_at: now, meta_data: {} },
        { id: 2, conversation_id: conversation.id, role: 'assistant', content: answer, created_at: now, meta_data: {} }
    ] : [] }));
    await page.route('**/api/v1/chat/conversations/987655/messages/stream', route => {
        // User and organization selectors are never sent by the chat UI.
        expect(route.request().postDataJSON()).toEqual({ message: question });
        sent = true;
        const events = [
            { type: 'thinking' },
            { type: 'tool_call_start', tool: 'query_my_crm_records', tool_call_id: 'crm-1' },
            { type: 'tool_call_result', tool: 'query_my_crm_records', tool_call_id: 'crm-1' },
            { type: 'content', content: answer }, { type: 'done' }
        ];
        return route.fulfill({ contentType: 'text/event-stream', body: events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('') });
    });
    await page.goto('/crm/assistant');
    await expect(page.getByText('Same lead access as your CRM · Confirm changes', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Select Private CRM. Double-click to rename.' }).click();
    await page.getByRole('button', { name: 'My CRM pipeline' }).click();
    await expect(page.getByText(answer, { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText(answer, { exact: true })).toBeVisible();
});

test('older conversation selection follows the user across chat and CRM', async ({ page }) => {
    const now = '2026-10-31T00:00:00Z';
    const conversations = [2, 1].map(id => ({ id, user_id: 'fixture', title: `Shared ${id}`, created_at: now, updated_at: now }));
    await page.route('**/api/v1/chat/conversations?*', route => route.fulfill({ json: { conversations, total: 2 } }));
    await page.route('**/api/v1/chat/conversations/*/messages?*', route => {
        const id = Number(route.request().url().match(/conversations\/(\d+)/)?.[1]);
        return route.fulfill({ json: [{ id, conversation_id: id, role: 'assistant', content: `History for ${id}`, created_at: now, meta_data: {} }] });
    });
    await page.goto('/chat');
    await page.getByRole('button', { name: 'Select Shared 1. Double-click to rename.' }).click();
    await expect(page.getByText('History for 1', { exact: true })).toBeVisible();
    await page.goto('/crm/assistant');
    await expect(page.getByText('History for 1', { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText('History for 1', { exact: true })).toBeVisible();
});

for (const outcome of ['succeeded', 'not_connected', 'expired', 'cancelled'] as const) {
    test(`action review uses canonical state and handles ${outcome}`, async ({ page }) => {
        const now = '2026-10-31T00:00:00Z';
        const conversation = { id: 987656, user_id: 'fixture', title: 'Action review fixture', created_at: now, updated_at: now };
        let status = 'awaiting_confirmation';
        let writes = 0;
        const action = () => ({ id: 'proposal-1', kind: 'add_note', status, title: 'Add note to lead', preview: { lead_id: 41, body: 'Call tomorrow' }, created_at: now, expires_at: '2099-01-01T00:00:00Z', result: null });
        await page.route('**/api/v1/chat/conversations?*', route => route.fulfill({ json: { conversations: [conversation], total: 1 } }));
        await page.route('**/api/v1/chat/conversations/987656/messages?*', route => route.fulfill({ json: [{ id: 1, conversation_id: conversation.id, role: 'assistant', content: 'Please review. [Unsafe](https://tracker.example/collect?phone=private) [CRM](/crm/leads)', meta_data: { actions: [{ id: 'proposal-1', status: 'succeeded' }] }, created_at: now }] }));
        await page.route('**/api/v1/assistant/actions/proposal-1', route => route.fulfill({ json: action() }));
        await page.route('**/api/v1/assistant/actions/proposal-1/*', async route => {
            writes += 1;
            expect(route.request().postData()).toBeNull();
            expect(route.request().url()).toContain(outcome === 'cancelled' ? '/cancel' : '/confirm');
            status = outcome;
            await new Promise(resolve => setTimeout(resolve, 200));
            return route.fulfill(outcome === 'expired' ? { status: 409, json: { detail: 'Expired' } } : { json: action() });
        });
        await page.goto('/chat');
        const card = page.getByRole('region', { name: 'Action review' });
        await expect(card.getByText('Awaiting your confirmation', { exact: true })).toBeVisible();
        await expect(card.getByText('Call tomorrow', { exact: true })).toBeVisible();
        expect(writes).toBe(0);
        await expect(page.locator('a[href*="tracker.example"]')).toHaveCount(0);
        await expect(page.getByRole('main').getByRole('link', { name: 'CRM', exact: true })).toHaveAttribute('href', '/crm/leads');
        await card.getByRole('button', { name: outcome === 'cancelled' ? 'Cancel' : 'Confirm', exact: true }).click();
        await expect(card.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled();
        const label = { succeeded: 'Completed', not_connected: 'Provider not connected — nothing sent or booked', expired: 'Expired — request a new proposal', cancelled: 'Cancelled' }[outcome];
        await expect(card.getByText(label, { exact: true })).toBeVisible();
        expect(writes).toBe(1);
        await expect(card.getByRole('button', { name: 'Confirm', exact: true })).toHaveCount(0);
        await page.reload();
        await expect(card.getByText(label, { exact: true })).toBeVisible();
    });
}

test('older messages prepend chronologically without losing the newest page', async ({ page }) => {
    const now = '2026-10-31T00:00:00Z';
    let sent = false;
    const conversation = { id: 987657, user_id: 'fixture', title: 'Paged history', created_at: now, updated_at: now };
    await page.route('**/api/v1/chat/conversations?*', route => route.fulfill({ json: { conversations: [conversation], total: 1 } }));
    await page.route('**/api/v1/chat/conversations/987657/messages?*', route => {
        const before = new URL(route.request().url()).searchParams.get('before_id');
        if (before) expect(before).toBe('101');
        const ids = before ? [99, 100] : Array.from({ length: 100 }, (_, i) => i + (sent ? 103 : 101));
        return route.fulfill({ json: ids.map(id => ({ id, conversation_id: conversation.id, role: 'assistant', content: `Paged message ${id}`, created_at: now, meta_data: {} })) });
    });
    await page.route('**/api/v1/market-chat/conversations/987657/messages/stream', route => {
        sent = true;
        return route.fulfill({ contentType: 'text/event-stream', body: 'data: {"type":"content","content":"Paged message 202"}\n\ndata: {"type":"done"}\n\n' });
    });
    await page.goto('/chat');
    await page.getByRole('button', { name: 'Load older messages', exact: true }).click();
    const messages = page.getByText(/^Paged message \d+$/, { exact: true });
    await expect(messages).toHaveCount(102);
    expect(await messages.allTextContents()).toEqual(Array.from({ length: 102 }, (_, i) => `Paged message ${i + 99}`));
    await expect(page.getByRole('button', { name: 'Load older messages', exact: true })).toHaveCount(0);
    await page.getByPlaceholder('Ask anything about Dubai real estate...').fill('Continue');
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    await expect(messages).toHaveCount(104);
    expect(await messages.allTextContents()).toEqual(Array.from({ length: 104 }, (_, i) => `Paged message ${i + 99}`));
});

test('a redacted unavailable action proposal cannot be confirmed despite its pending status', async ({ page }) => {
    const now = '2026-10-31T00:00:00Z';
    const conversation = { id: 987658, user_id: 'fixture', title: 'Unavailable action', created_at: now, updated_at: now };
    let writes = 0;
    await page.route('**/api/v1/chat/conversations?*', route => route.fulfill({ json: { conversations: [conversation], total: 1 } }));
    await page.route('**/api/v1/chat/conversations/987658/messages?*', route => route.fulfill({ json: [{ id: 1, conversation_id: conversation.id, role: 'assistant', content: 'Please review.', created_at: now, meta_data: { actions: [{ id: 'unavailable-1' }] } }] }));
    await page.route('**/api/v1/assistant/actions/unavailable-1', route => route.fulfill({ json: { id: 'unavailable-1', kind: 'add_note', status: 'awaiting_confirmation', title: 'Unavailable action', preview: { available: false }, created_at: now, expires_at: '2099-01-01T00:00:00Z', result: null } }));
    await page.route('**/api/v1/assistant/actions/unavailable-1/*', route => {
        writes += 1;
        return route.fulfill({ status: 409, json: { detail: 'Unavailable' } });
    });
    await page.goto('/chat');
    const card = page.getByRole('region', { name: 'Action review' });
    await expect(card.getByText('This action is unavailable — request a new proposal', { exact: true })).toBeVisible();
    await expect(card.getByRole('button', { name: 'Confirm', exact: true })).toHaveCount(0);
    await expect(card.getByRole('button', { name: 'Cancel', exact: true })).toHaveCount(0);
    expect(writes).toBe(0);
});
