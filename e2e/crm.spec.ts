import { test, expect } from '@playwright/test';

test('inbound contact, notes and consent survive a real API reload', async ({ page }) => {
    // The setup project provisions a fresh organization for this run.
    const name = `Migration contact ${Date.now()}`;
    const note = 'Confirm requirements before matching inventory.';
    await page.goto('/crm/inbound');
    await page.getByRole('button', { name: 'Add contact', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Full name', { exact: true }).fill(name);
    const created = page.waitForResponse(response => response.url().endsWith('/crm/inbound/enquiries') && response.request().method() === 'POST');
    await dialog.getByRole('button', { name: 'Add to qualification queue' }).click();
    const response = await created;
    expect(response.ok()).toBeTruthy();
    const enquiry = await response.json();
    expect(enquiry.intent).toBe('unknown');
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
    await page.getByPlaceholder('Add a qualification or follow-up note…').fill(note);
    const noted = page.waitForResponse(response => response.url().endsWith(`/enquiries/${enquiry.id}/notes`) && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Add note', exact: true }).click();
    expect((await noted).ok()).toBeTruthy();
    const consent = page.waitForResponse(response => response.url().endsWith(`/enquiries/${enquiry.id}`) && response.request().method() === 'PATCH');
    await page.getByLabel('Do not contact', { exact: true }).check();
    expect((await consent).ok()).toBeTruthy();
    await page.reload();
    await page.getByRole('button', { name: 'Needs qualification', exact: true }).click();
    await page.getByPlaceholder('Search name, campaign, message, area…').fill(name);
    await page.getByRole('button').filter({ has: page.getByText(name, { exact: true }) }).click();
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
    await expect(page.getByText(note, { exact: true })).toBeVisible();
    await expect(page.getByLabel('Do not contact', { exact: true })).toBeChecked();
});
