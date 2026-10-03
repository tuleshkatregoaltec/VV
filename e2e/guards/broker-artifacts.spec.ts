import { expect, test } from '../fixtures/guards';

const now = '2026-10-03T10:00:00Z';
const conversation = { id: 987657, user_id: 'browser-fixture', title: 'Broker artifacts', created_at: now, updated_at: now };
const savedDocument = {
    id: 'fixture-document', status: 'completed', kind: 'quotation', title: 'Saved quotation', version: 2,
    error: null, created_at: now, download_url: 'https://untrusted.invalid/never-follow',
    document: {
        brand: 'ViteVue', title: 'Saved quotation', reference: 'Q-42', version: 2, valid_until: '2026-10-17', prepared_at: now,
        properties: [], sections: [], limitations: ['Transfer charge not supplied.'],
        quotation: { currency: 'AED', lines: [], known_total: '1122000.00', estimated_total: '500.50', total: null, missing_charges: ['Transfer charge'] }
    }
};

test('saved broker document polls to completion and downloads only through authenticated ID route', async ({ page, usePersona }) => {
    await usePersona('active-owner');
    const artifact = { id: 'broker-doc-1', type: 'broker_document', status: 'ready', title: 'Saved quotation', created_at: now, data: { ...savedDocument, status: 'queued' } };
    await page.route('**/api/v1/chat/conversations?*', route => route.fulfill({ json: { conversations: [conversation], total: 1 } }));
    await page.route('**/api/v1/chat/conversations/987657/messages?*', route => route.fulfill({ json: [
        { id: 1, conversation_id: conversation.id, role: 'assistant', content: 'Saved document.', created_at: now, meta_data: { artifacts: [artifact] } }
    ] }));
    let reads = 0;
    let downloadRequests = 0;
    let remoteRequests = 0;
    await page.route('https://untrusted.invalid/**', route => { remoteRequests++; return route.abort(); });
    await page.route('**/api/v1/crm/broker/documents/fixture-document', route => {
        reads++;
        return route.fulfill({ json: { ...savedDocument, status: reads === 1 ? 'running' : 'completed' } });
    });
    await page.route('**/api/v1/crm/broker/documents/fixture-document/download', route => {
        downloadRequests++;
        expect(route.request().headers().authorization).toMatch(/^Bearer mock-access-token-/);
        return route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.4\n% mocked transport only\n%%EOF' });
    });
    await page.goto('/chat');
    await page.getByRole('button', { name: 'Select Broker artifacts. Double-click to rename.' }).click();
    await expect(page.getByText('Preparing document…')).toBeVisible();
    const downloadButton = page.getByRole('button', { name: 'Download PDF · Version 2' });
    await expect(downloadButton).toBeVisible();
    await expect(page.getByText('AED 1122000.00', { exact: true })).toBeVisible();
    await expect(page.getByText('Not available — charges are missing')).toBeVisible();
    const completedReads = reads;
    const download = page.waitForEvent('download');
    await downloadButton.click();
    expect((await download).suggestedFilename()).toBe('Q-42-v2.pdf');
    expect(downloadRequests).toBe(1);
    expect(remoteRequests).toBe(0);
    expect(reads).toBe(completedReads);
});

test('broker action requires a click, discloses failed confirmation and only then shows persisted success', async ({ page, usePersona }) => {
    await usePersona('active-owner');
    const proposal = { proposal_id: 'proposal-1', enquiry_id: 12, action: 'note', body: 'Requested a second viewing.', due_date: null, scope: 'mine', status: 'proposed', expected_updated_at: now, created_at: now };
    const artifact = { id: 'broker-action-1', type: 'broker_action', status: 'ready', title: 'Review note', created_at: now, data: { status: 'proposal', proposal, requires_confirmation: true } };
    await page.route('**/api/v1/chat/conversations?*', route => route.fulfill({ json: { conversations: [conversation], total: 1 } }));
    await page.route('**/api/v1/chat/conversations/987657/messages?*', route => route.fulfill({ json: [
        { id: 1, conversation_id: conversation.id, role: 'assistant', content: 'Review before saving.', created_at: now, meta_data: { artifacts: [artifact] } }
    ] }));
    let confirmations = 0;
    await page.route('**/api/v1/crm/broker/actions/confirm', route => {
        confirmations++;
        expect(route.request().postDataJSON()).toEqual({ proposal_id: 'proposal-1' });
        if (confirmations === 1) return route.fulfill({ status: 503, json: { detail: 'Confirmation is temporarily unavailable.' } });
        return route.fulfill({ json: { status: 'completed', proposal: { ...proposal, status: 'completed' }, already_completed: false } });
    });
    await page.goto('/chat');
    await page.getByRole('button', { name: 'Select Broker artifacts. Double-click to rename.' }).click();
    const button = page.getByRole('button', { name: 'Confirm action' });
    await expect(button).toBeVisible();
    expect(confirmations).toBe(0);
    await expect(page.getByText('Requested a second viewing.', { exact: true })).toBeVisible();
    await button.click();
    await expect(page.getByRole('alert')).toContainText('Confirmation is temporarily unavailable');
    await expect(page.getByText('Note saved.', { exact: true })).toHaveCount(0);
    await button.click();
    await expect(page.getByText('Note saved.', { exact: true })).toBeVisible();
    await expect(button).toHaveCount(0);
    expect(confirmations).toBe(2);
});
