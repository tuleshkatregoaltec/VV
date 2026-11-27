import { expect, test } from '../fixtures/guards';

// Reported: "Show me the first five leads with their names, team, handler and next follow-up"
// arrived as one run-together paragraph. A Markdown table answer must render as a table, one
// row per lead, each field in its own cell. Synthetic records; every request is mocked.
const answer = [
    '7 leads match; showing the first 5.',
    '',
    '| # | Lead | Team | Handler | Next follow-up |',
    '|---|---|---|---|---|',
    ...[1, 2, 3, 4, 5].map((n) => `| ${n} | Synthetic Lead ${n} | North | Track ${n % 2 ? 1 : 3} | 2026-12-0${n} |`),
    '',
    // Allowing tables must not let anything else through.
    '<script>window.__injected = true</script><iframe src="https://example.test"></iframe>'
].join('\n');

test('a multi-lead answer renders as a table with one row per lead', async ({ page, usePersona }) => {
    await usePersona('active-owner');
    // Nothing leaves the machine: only the local app is reachable.
    await page.route(/^https?:\/\/(?!localhost|127\.0\.0\.1)/, (route) => route.abort('blockedbyclient'));
    const now = '2026-11-26T00:00:00Z';
    const conversation = { id: 902, user_id: 'fixture', title: 'Five leads', created_at: now, updated_at: now };
    await page.route('**/api/v1/chat/conversations?*', (route) =>
        route.fulfill({ json: { conversations: [conversation], total: 1 } })
    );
    await page.route('**/api/v1/chat/conversations/902/messages?*', (route) =>
        route.fulfill({
            json: [
                { id: 1, conversation_id: 902, role: 'user', content: 'Show me the first five leads', created_at: now, meta_data: {} },
                { id: 2, conversation_id: 902, role: 'assistant', content: answer, created_at: now, meta_data: { guardrail_version: 1 } }
            ]
        })
    );
    // The only conversation opens by itself.
    await page.goto('/crm/assistant');

    const table = page.getByRole('table');
    await expect(table).toBeVisible({ timeout: 20_000 }); // A cold dev server compiles slowly.
    await expect(table.getByRole('columnheader')).toHaveText(['#', 'Lead', 'Team', 'Handler', 'Next follow-up']);
    const rows = table.locator('tbody tr');
    await expect(rows).toHaveCount(5);
    await expect(rows.nth(0).getByRole('cell')).toHaveText(['1', 'Synthetic Lead 1', 'North', 'Track 1', '2026-12-01']);
    await expect(rows.nth(1).getByRole('cell')).toHaveText(['2', 'Synthetic Lead 2', 'North', 'Track 3', '2026-12-02']);
    // The partial-list sentence stays its own paragraph, outside the table.
    await expect(page.getByText('7 leads match; showing the first 5.', { exact: true })).toBeVisible();
    // Markup outside the allowlist is still removed from the answer.
    const message = table.locator('xpath=ancestor::div[1]');
    await expect(message.locator('script, iframe')).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { __injected?: boolean }).__injected)).toBeUndefined();
});
