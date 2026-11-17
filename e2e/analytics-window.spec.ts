import { test, expect, type Page } from '@playwright/test';
import path from 'node:path';

test('Analytics headline metrics use the selected window beside property usage', async ({ page }, testInfo) => {
    test.setTimeout(180_000);
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    const summaryResponse = (days?: number, usage = 'auto', project?: string) => page.waitForResponse(response => {
        const url = new URL(response.url());
        return response.ok() && url.pathname === '/api/v1/analytics/project/summary'
            && url.searchParams.get('summary_days') === (days ? String(days) : null)
            && url.searchParams.get('usage') === usage
            && url.searchParams.get('project') === (project ?? null);
    });
    const metrics = page.getByRole('region', { name: 'Summary metrics' });
    async function verify(summary: any) {
        const number = (n: number) => n.toLocaleString('en-AE');
        const money = (n: number) => n > 0 ? `AED ${n.toLocaleString('en-AE', { maximumFractionDigits: 2 })}` : '—';
        const card = (label: string) => metrics.getByText(label, { exact: true }).locator('..');
        await expect(card('Total Sales').locator('p').nth(1)).toHaveText(number(summary.sales.transaction_count));
        await expect(card('Avg Sale Price').locator('p').nth(1)).toHaveText(money(summary.sales.avg_price));
        await expect(card('Median Annual Rent').locator('p').nth(1)).toHaveText(money(summary.rentals.median_annual_rent));
        await expect(card('Median Annual Rent')).toContainText(`${number(summary.rentals.contract_count)} contracts`);
        const yieldText = summary.overall_gross_yield_pct == null ? '—'
            : `${summary.overall_gross_yield_pct.toLocaleString('en-AE', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
        await expect(card('Gross Yield').locator('p').nth(1)).toHaveText(yieldText);
        for (const usage of ['Residential', 'Commercial']) {
            const counts = summary.usage_counts[usage];
            const button = page.getByRole('group', { name: 'Property usage' }).getByRole('button', { name: new RegExp(`^${usage}`) });
            if (counts.sales) await expect(button).toContainText(`${number(counts.sales)} ${counts.sales === 1 ? 'sale' : 'sales'}`);
            if (counts.leases) await expect(button).toContainText(`${number(counts.leases)} ${counts.leases === 1 ? 'lease' : 'leases'}`);
            if (!counts.sales && !counts.leases) await expect(button).toContainText('No records');
        }
    }
    async function screenshot(name: string) {
        const file = process.env.ANALYTICS_SCREENSHOTS
            ? path.join(process.env.ANALYTICS_SCREENSHOTS, `${name}.png`)
            : testInfo.outputPath(`${name}.png`);
        await page.screenshot({ path: file, animations: 'disabled' });
        await testInfo.attach(name, { path: file, contentType: 'image/png' });
    }
    await page.setViewportSize({ width: 1440, height: 1100 });
    const initial = summaryResponse(365);
    await page.goto('/analytics');
    const year = await (await initial).json();
    await verify(year);
    await expect(page.getByRole('button', { name: 'Summary window', exact: true })).toHaveText('Last Year');
    const usageBox = await page.getByRole('group', { name: 'Property usage' }).boundingBox();
    const windowBox = await page.getByRole('button', { name: 'Summary window', exact: true }).boundingBox();
    expect(windowBox!.x).toBeGreaterThan(usageBox!.x + usageBox!.width);
    await screenshot('analytics-one-year');
    await page.getByRole('button', { name: 'Summary window', exact: true }).click();
    await screenshot('analytics-window-options');
    const monthResponse = summaryResponse(30);
    await page.getByRole('button', { name: 'Last Month', exact: true }).click();
    const month = await (await monthResponse).json();
    await verify(month);
    expect(month.sales.transaction_count).toBeLessThanOrEqual(year.sales.transaction_count);
    // Historical configuration comparisons must not lose their previous-year data.
    expect(month.configuration_analysis).toEqual(year.configuration_analysis);
    await screenshot('analytics-one-month');
    const commercialResponse = summaryResponse(30, 'Commercial');
    await page.getByRole('group', { name: 'Property usage' }).getByRole('button', { name: /^Commercial/ }).click();
    await verify(await (await commercialResponse).json());
    for (const [label, days] of [['Last Week', 7], ['Last 3 Months', 90], ['Last 6 Months', 180], ['All time', undefined]] as const) {
        const response = summaryResponse(days, 'Commercial');
        await choose(page, label);
        await verify(await (await response).json());
    }
    const selectedResponse = summaryResponse(undefined, 'auto', '23 Marina');
    await page.getByRole('combobox', { name: 'Project A', exact: true }).fill('23 Marina');
    await page.getByRole('option', { name: '23 Marina Project · Dubai Marina', exact: true }).click();
    await verify(await (await selectedResponse).json());
    await expect(page.getByRole('button', { name: 'Summary window', exact: true })).toHaveText('All time');
    const projectYear = summaryResponse(365, 'auto', '23 Marina');
    await choose(page, 'Last Year');
    await verify(await (await projectYear).json());
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: 'Summary window', exact: true }).scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await screenshot('analytics-window-mobile');
    await choose(page, 'Last Month');
    await expect(metrics).toBeVisible();
    expect(errors).toEqual([]);
});

async function choose(page: Page, label: string) {
    await page.getByRole('button', { name: 'Summary window', exact: true }).click();
    await page.getByRole('button', { name: label, exact: true }).click();
}
