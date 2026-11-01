import { expect, test } from '@playwright/test';

test('enterprise preview completes exact approvals without accessing application APIs', async ({ page }) => {
    const apiRequests: string[] = [];
    page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/')) apiRequests.push(request.url()); });
    await page.goto('/demo/assistant');
    await expect(page.getByText('Demo · Sample data', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Approve lead', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Maya Hassan', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Ask on WhatsApp' }).click();
    await expect(page.getByRole('button', { name: '15:00 Busy' })).toBeDisabled();
    await page.getByRole('button', { name: '17:30 Available' }).click();
    await page.getByRole('button', { name: 'Review booking' }).click();
    await expect(page.getByText('Tuesday · 17:30–18:00 · Dubai (UTC+4)', { exact: true })).toBeVisible();
    await page.getByRole('checkbox', { name: 'Send a calendar invitation' }).uncheck();
    const exactReply = 'Hi Maya, I will meet you in the Marina Gate lobby at 17:30. — Sara';
    await page.getByLabel('Message for Maya').fill(exactReply);
    await page.getByRole('button', { name: 'Approve in demo', exact: true }).click();
    await expect(page.getByText('Viewing added to the demo calendar', { exact: true })).toBeVisible();
    await expect(page.getByText('Calendar invitation previewed', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Sample data only. No messages sent or real events created.', { exact: true })).toBeVisible();
    await page.getByRole('tab', { name: 'Customer inbox', exact: true }).click();
    const customer = page.getByRole('tabpanel', { name: 'Customer WhatsApp inbox' });
    await expect(customer.getByText(exactReply, { exact: true })).toBeVisible();
    await expect(customer.getByText('You have a meeting at 15:00.', { exact: false })).toHaveCount(0);
    expect(apiRequests).toEqual([]);
    await page.getByRole('button', { name: 'Restart demo', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Approve lead', exact: true })).toBeVisible();
    await expect(page.getByText('Viewing added to the demo calendar', { exact: true })).toHaveCount(0);
});

test('connection previews switch providers and disconnect only sample accounts', async ({ page }) => {
    await page.goto('/demo/assistant');
    await page.getByRole('button', { name: 'Manage mail demo connection' }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('button', { name: 'Outlook', exact: true }).click();
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
    await expect(page.getByRole('heading', { name: 'Outlook', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Manage calendar demo connection' }).click();
    await dialog.getByRole('button', { name: 'Microsoft Calendar', exact: true }).click();
    await dialog.getByRole('button', { name: 'Disconnect demo account' }).click();
    await expect(page.getByRole('button', { name: 'Approve lead', exact: true })).toBeDisabled();
    await page.getByRole('button', { name: 'Manage calendar demo connection' }).click();
    await dialog.getByRole('button', { name: 'Connect sample account' }).click();
    await expect(page.getByRole('heading', { name: 'Microsoft Calendar', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Approve lead', exact: true })).toBeEnabled();
});

test('changing an approved time requires a new demo approval', async ({ page }) => {
    await page.goto('/demo/assistant');
    await page.getByRole('button', { name: 'Approve lead', exact: true }).click();
    await page.getByRole('button', { name: 'Ask on WhatsApp' }).click();
    await page.getByRole('button', { name: 'Review booking' }).click();
    await page.getByRole('button', { name: 'Approve in demo', exact: true }).click();
    await page.getByRole('button', { name: 'Find a viewing', exact: true }).click();
    await page.getByRole('button', { name: '17:30 Available' }).click();
    await page.getByRole('button', { name: 'Review booking' }).click();
    await expect(page.getByRole('button', { name: 'Approve in demo', exact: true })).toBeVisible();
    await expect(page.getByLabel('Message for Maya')).toHaveValue(/17:30/);
});

for (const width of [375, 768, 1024, 1440]) {
    test(`enterprise preview fits ${width}px in both appearances`, async ({ page }, testInfo) => {
        await page.setViewportSize({ width, height: 1050 });
        await page.goto('/demo/assistant');
        const switchToLight = page.getByRole('button', { name: 'Switch to light', exact: true });
        if (await switchToLight.isVisible()) await switchToLight.click();
        await expect(page.getByRole('button', { name: 'Approve lead', exact: true })).toBeVisible();
        let lightBackground = '';
        for (const theme of ['light', 'dark']) {
            if (theme === 'dark') await page.getByRole('button', { name: 'Switch to dark', exact: true }).click();
            expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
            const background = await page.locator('.demo-page').evaluate(element => getComputedStyle(element).backgroundColor);
            if (theme === 'light') lightBackground = background;
            else expect(background).not.toEqual(lightBackground);
            await page.screenshot({ path: testInfo.outputPath(`assistant-demo-${width}-${theme}.png`), fullPage: true, animations: 'disabled' });
        }
    });
}
