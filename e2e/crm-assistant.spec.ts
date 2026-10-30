import { test, expect } from '@playwright/test';

/**
 * The CRM Assistant page. The assistant API is mocked, so no model is called: these checks guard
 * the page, the streamed reply and the confirm card, not the model's answers.
 */

const action = {
    action_id: 'a1b2c3',
    action_type: 'status',
    lead_id: 7,
    summary: 'Move Ahmed Khan to qualified',
    before: { status: 'contacted' },
    after: { status: 'qualified' },
    status: 'pending',
};

test('assistant page shows the chat, not the placeholder', async ({ page }) => {
    await page.route('**/api/v1/crm/assistant/conversations?*', route =>
        route.fulfill({ json: { conversations: [], total: 0 } }));
    await page.goto('/crm/assistant');
    await expect(page.getByText('being built')).toHaveCount(0);
    await expect(page.getByText('In build')).toHaveCount(0);
    for (const prompt of [
        'Leads with follow-ups due today',
        'Summarise my new leads this week',
        'Move Ahmed to qualified',
        "Share Sara's lead with Omar",
    ]) {
        await expect(page.getByRole('button', { name: prompt })).toBeVisible();
    }
    await expect(page.getByRole('textbox', { name: 'Message the assistant' })).toBeEnabled();
});

test('a proposed change waits for Confirm, then runs once', async ({ page }) => {
    let confirms = 0;
    await page.route('**/api/v1/crm/assistant/conversations?*', route =>
        route.fulfill({ json: { conversations: [], total: 0 } }));
    await page.route('**/api/v1/crm/assistant/conversations', route =>
        route.fulfill({ json: { id: 41, title: 'New conversation', created_at: '2026-10-30T09:00:00Z', updated_at: '2026-10-30T09:00:00Z' } }));
    await page.route('**/api/v1/crm/assistant/conversations/41/messages?*', route => route.fulfill({ json: [] }));
    await page.route('**/api/v1/crm/assistant/conversations/41/messages/stream', route =>
        route.fulfill({
            contentType: 'text/event-stream',
            body: [
                { type: 'tool-status', tool: 'propose_status_change', label: 'Preparing a change…' },
                { type: 'action-proposed', action },
                { type: 'text-delta', content: 'Please confirm the change on the card.' },
                { type: 'done' },
            ].map(event => `data: ${JSON.stringify(event)}\n\n`).join(''),
        }));
    await page.route('**/api/v1/crm/assistant/actions/a1b2c3/confirm', route => {
        confirms += 1;
        return route.fulfill({ json: { action_id: 'a1b2c3', status: 'confirmed', lead_id: 7 } });
    });

    await page.goto('/crm/assistant');
    await page.getByRole('button', { name: 'Move Ahmed to qualified' }).click();

    await expect(page.getByText('Move Ahmed Khan to qualified')).toBeVisible();
    await expect(page.getByText('Please confirm the change on the card.')).toBeVisible();
    expect(confirms).toBe(0);

    await page.getByRole('button', { name: 'Confirm', exact: true }).click();
    await expect(page.getByText('Confirmed', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Confirm', exact: true })).toHaveCount(0);
    expect(confirms).toBe(1);
});
