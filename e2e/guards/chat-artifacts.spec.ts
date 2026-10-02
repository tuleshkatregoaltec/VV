import { expect, test } from '../fixtures/guards';

test('MCP turn preserves chat artifact rendering and message reload', async ({ page, usePersona }) => {
    await usePersona('active-owner');
    const now = '2026-10-03T00:00:00+00:00';
    const conversation = { id: 987656, user_id: 'browser-fixture', title: 'MCP artifacts', created_at: now, updated_at: now };
    const artifact = { id: 'show_chart:call-1', type: 'custom_chart', status: 'ready', title: 'Stored market chart', created_at: now,
        query: { dataset: 'sales', group_by: 'area' },
        data: { chart_type: 'horizontal_bar', metric: 'transaction_count', metric_label: 'Transactions', dimension: 'area', dimension_label: 'Area', points: [{ label: 'Dubai Marina', value: 42, record_count: 42 }], series: [] }
    };
    let sent = false;
    await page.route('**/api/v1/chat/conversations?*', route => route.fulfill({ json: { conversations: [conversation], total: 1 } }));
    await page.route('**/api/v1/chat/conversations/987656/messages?*', route => route.fulfill({ json: sent ? [
        { id: 1, conversation_id: conversation.id, role: 'user', content: 'Show evidence', created_at: now, meta_data: { turn_status: 'complete' } },
        { id: 2, conversation_id: conversation.id, role: 'assistant', content: 'Stored result.', created_at: now, meta_data: { artifacts: [artifact] } }
    ] : [] }));
    await page.route('**/api/v1/chat/conversations/987656/messages/stream', route => {
        sent = true;
        return route.fulfill({ contentType: 'text/event-stream', body: [
            { type: 'thinking' }, { type: 'tool_call_start', tool: 'query_market_metrics', tool_call_id: 'call-1' },
            { type: 'tool_call_result', tool: 'query_market_metrics', tool_call_id: 'call-1' },
            { type: 'artifact_updated', artifact }, { type: 'content', content: 'Stored result.' }, { type: 'done' }
        ].map(event => `data: ${JSON.stringify(event)}\n\n`).join('') });
    });
    await page.goto('/chat');
    await page.getByRole('button', { name: 'Select MCP artifacts. Double-click to rename.' }).click();
    await page.getByPlaceholder('Ask anything about Dubai real estate...').fill('Show evidence');
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    await expect(page.getByText('Stored market chart', { exact: true })).toBeVisible();
    await page.reload();
    await page.getByRole('button', { name: 'Select MCP artifacts. Double-click to rename.' }).click();
    await expect(page.getByText('Stored market chart', { exact: true })).toBeVisible();
});
