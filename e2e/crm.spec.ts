import { test, expect } from '@playwright/test';

test('lead and notes survive reload and contact consent persists at the API boundary', async ({ page }) => {
    const name = `Migration contact ${Date.now()}`;
    const note = 'Confirm requirements before matching inventory.';
    await page.goto('/crm/leads');
    await page.getByRole('button', { name: 'New lead', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Name', { exact: true }).fill(name);
    await dialog.getByLabel('Phone', { exact: true }).fill(`+97150${String(Date.now()).slice(-7)}`);
    await dialog.getByLabel('Budget (AED)', { exact: true }).fill('2000000');
    await dialog.getByLabel('Area', { exact: true }).fill('JVC');
    const created = page.waitForResponse(response => response.url().endsWith('/crm/inbound/enquiries') && response.request().method() === 'POST');
    await dialog.getByRole('button', { name: 'Create lead', exact: true }).click();
    const response = await created;
    expect(response.ok()).toBeTruthy();
    const enquiry = await response.json();
    expect(enquiry.intent).toBe('buy');
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
    await dialog.getByRole('button', { name: 'Add note', exact: true }).click();
    await dialog.getByLabel('Note', { exact: true }).fill(note);
    const noted = page.waitForResponse(response => response.url().endsWith(`/enquiries/${enquiry.id}/notes`) && response.request().method() === 'POST');
    await dialog.getByRole('button', { name: 'Save note', exact: true }).click();
    expect((await noted).ok()).toBeTruthy();
    // The current UI has no consent editor; verify the real canonical API round trip.
    const consent = await page.evaluate(async url => {
        const token = JSON.parse(localStorage.getItem('authentication')!).access_token;
        const response = await fetch(url, {
            method: 'PATCH', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ do_not_contact: true })
        });
        return { ok: response.ok, status: response.status };
    }, `${response.url()}/${enquiry.id}`);
    expect(consent.ok).toBeTruthy();
    const reloaded = page.waitForResponse(response => response.url().endsWith(`/enquiries/${enquiry.id}`) && response.request().method() === 'GET');
    await page.reload();
    expect((await (await reloaded).json()).contact.do_not_contact).toBe(true);
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
    await dialog.getByRole('tab', { name: 'History', exact: true }).click();
    await expect(page.getByText(`Note · ${note}`, { exact: true })).toBeVisible();
});
