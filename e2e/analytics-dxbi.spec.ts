import { test, expect as baseExpect } from '@playwright/test';
import path from 'node:path';
const expect = baseExpect.configure({ timeout: 30000 });

test('comparison numbers and plotted values match both DXBI API selections', async ({ page }) => {
    test.setTimeout(180000);
    const errors: string[] = [];
    const summaries = new Map<string, any>();
    const trends = new Map<string, any>();
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('response', async (response) => {
        const url = new URL(response.url());
        if (!response.ok() || !url.pathname.includes('/analytics/project/')) return;
        const name = url.searchParams.get('project') ?? 'Dubai';
        if (url.pathname.endsWith('/summary')) summaries.set(name, await response.json());
        if (url.pathname.endsWith('/trends')) trends.set(name, await response.json());
    });
    await page.goto('/analytics');
    await expect(page.getByRole('heading', { name: 'Configuration Analysis', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Compare', exact: true }).click();
    const input = page.getByRole('combobox', { name: 'Project B', exact: true });
    await input.fill('23 Marina');
    await page.getByRole('option', { name: '23 Marina Project', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Delta is Project B minus Project A', exact: true })).toBeVisible();
    await expect.poll(() => summaries.has('Dubai') && summaries.has('23 Marina')).toBe(true);
    const metricTable = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Delta is Project B minus Project A', exact: true }) });
    for (const [label, field] of [['Total sales', 'transaction_count'], ['Avg price / sq ft', 'avg_price_sqft']]) {
        const row = metricTable.getByText(label, { exact: true }).first().locator('..');
        for (const [index, name] of ['Dubai', '23 Marina'].entries()) {
            const value = summaries.get(name).sales[field];
            const text = field === 'transaction_count' ? value.toLocaleString('en-AE') : `AED ${value.toLocaleString('en-AE', { maximumFractionDigits: 2 })}/sq ft`;
            await expect(row.locator(':scope > div').nth(index + 1)).toHaveText(text);
        }
    }
    await expect.poll(() => trends.has('Dubai') && trends.has('23 Marina')).toBe(true);
    await page.getByRole('button', { name: 'AED / sq ft', exact: true }).click();
    const plotted = async () => page.evaluate(async () => {
        const modules = performance.getEntriesByType('resource').map((r) => r.name).filter((name) => /chart.*\.js/.test(name));
        for (const url of modules) {
            const module = await import(/* @vite-ignore */ url);
            if (!module.Chart) continue;
            const canvas = document.querySelector('canvas');
            const chart = canvas ? module.Chart.getChart(canvas) : null;
            if (chart) { chart.update('none'); return chart.data.datasets.map((d: any) => ({ label: d.label, data: Array.from(d.data) })); }
        }
        return null;
    });
    await expect.poll(plotted).not.toBeNull();
    const datasets = await plotted();
    const dates = [...new Set([...trends.get('Dubai').data, ...trends.get('23 Marina').data].map((p: any) => p.date))].sort();
    for (const [index, name] of ['Dubai', '23 Marina'].entries()) {
        const points = new Map(trends.get(name).data.map((p: any) => [p.date, p.avg_price_sqft]));
        expect(datasets[index].data).toEqual(dates.map((date) => points.get(date) ?? null));
    }
    await page.locator('section').filter({ has: page.getByRole('heading', { name: 'One market signal, two selections', exact: true }) }).screenshot({ path: path.resolve('../docs/audits/analytics-dxbi-2026-10-11/screenshots/compare-chart.png') });
    await page.getByRole('heading', { name: 'Dubai market analytics', exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.resolve('../docs/audits/analytics-dxbi-2026-10-11/screenshots/compare-verified.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: path.resolve('../docs/audits/analytics-dxbi-2026-10-11/screenshots/compare-verified-mobile.png'), fullPage: true });
    await page.getByRole('group', { name: 'Project B', exact: true }).getByRole('button', { name: 'Clear selection' }).click();
    await expect(page.getByText(/Search for Project B above/)).toBeVisible();
    await page.getByRole('button', { name: 'Exit compare', exact: true }).click();
    await expect(page.getByRole('combobox', { name: 'Project B', exact: true })).toHaveCount(0);
    expect(errors).toEqual([]);
});


test('District One keeps sparse bedrooms and uses all-history counts in every tab', async ({ page }) => {
    test.setTimeout(180000);
    await page.goto('/analytics');
    await expect(page.getByRole('heading', { name: 'Configuration Analysis', exact: true })).toBeVisible();
    const input = page.getByRole('combobox').first();
    await input.fill('(D1) District One Residences');
    const response = page.waitForResponse(r => r.ok() && r.url().includes('/analytics/project/summary?project='));
    await page.getByRole('option', { name: '(D1) District One Residences Project', exact: true }).click();
    const summary = await (await response).json();
    const panel = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Configuration Analysis', exact: true }) }).last();
    await expect(panel.getByText(/Sales, prices and sizes cover all recorded dates/)).toBeVisible();
    for (const [label, segment] of [['All', 'all'], ['Off-Plan', 'off_plan'], ['Secondary', 'secondary']]) {
        await panel.getByRole('button', { name: label, exact: true }).click();
        const expected = summary.configuration_analysis.filter((r: any) => r.market_segment === segment);
        await expect(panel.locator('tbody tr')).toHaveCount(expected.length);
        for (const config of expected) {
            const row = panel.locator('tbody tr').filter({ has: page.getByRole('cell', { name: config.rooms, exact: true }) });
            await expect(row.locator('td').nth(1)).toHaveText(config.sale_count.toLocaleString('en-AE'));
        }
    }
    await panel.getByRole('button', { name: 'All', exact: true }).click();
    await expect(panel.getByRole('cell', { name: '4 B/R', exact: true })).toBeVisible();
    await expect(panel.getByRole('cell', { name: '5 B/R', exact: true })).toBeVisible();
    expect(summary.configuration_analysis.filter((r: any) => r.market_segment === 'off_plan').every((r: any) => r.sales_last_12m === 0)).toBe(true);
    await panel.screenshot({ path: path.resolve('../docs/audits/analytics-dxbi-2026-10-11/screenshots/district-one-corrected.png') });
});
