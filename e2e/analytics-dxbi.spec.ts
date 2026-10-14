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
    // Analytics groups by DLD's project names (the DXBI profile): DXBI's "23 Marina" is DLD's.
    await page.getByRole('option', { name: '23 MARINA Project', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Delta is Project B minus Project A', exact: true })).toBeVisible();
    await expect.poll(() => summaries.has('Dubai') && summaries.has('23 MARINA')).toBe(true);
    const metricTable = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Delta is Project B minus Project A', exact: true }) });
    for (const [label, field] of [['Total sales', 'transaction_count'], ['Avg price / sq ft', 'avg_price_sqft']]) {
        const row = metricTable.getByText(label, { exact: true }).first().locator('..');
        for (const [index, name] of ['Dubai', '23 MARINA'].entries()) {
            const value = summaries.get(name).sales[field];
            const text = field === 'transaction_count' ? value.toLocaleString('en-AE') : `AED ${value.toLocaleString('en-AE', { maximumFractionDigits: 2 })}/sq ft`;
            await expect(row.locator(':scope > div').nth(index + 1)).toHaveText(text);
        }
    }
    await expect.poll(() => trends.has('Dubai') && trends.has('23 MARINA')).toBe(true);
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
    const dates = [...new Set([...trends.get('Dubai').data, ...trends.get('23 MARINA').data].map((p: any) => p.date))].sort();
    for (const [index, name] of ['Dubai', '23 MARINA'].entries()) {
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
    // DXBI's "(D1) District One Residences" buildings are DLD projects of one master community.
    test.setTimeout(180000);
    await page.goto('/analytics');
    await expect(page.getByRole('heading', { name: 'Configuration Analysis', exact: true })).toBeVisible();
    const input = page.getByRole('combobox').first();
    const master = 'Mohammed Bin Rashid AL Maktoum City -District -1 Community';
    await input.fill('District -1 Community');
    const response = page.waitForResponse(r => r.ok() && r.url().includes('/analytics/project/summary?'));
    await page.getByRole('option', { name: `${master} Master`, exact: true }).click();
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
    await panel.screenshot({ path: path.resolve('../docs/audits/analytics-dxbi-2026-10-11/screenshots/district-one-corrected.png') });
});

test('an office tower shows its commercial records, with the usage and its counts named', async ({ page }) => {
    test.setTimeout(120000);
    await page.goto('/analytics');
    await expect(page.getByRole('heading', { name: 'Configuration Analysis', exact: true })).toBeVisible();
    const summary = page.waitForResponse(r => r.ok() && r.url().includes('/analytics/project/summary?project=014'));
    await page.getByRole('combobox').first().fill('014 TOWER');
    await page.getByRole('option', { name: '014 TOWER Project', exact: true }).click();
    const data = await (await summary).json();
    expect(data.usage).toBe('Commercial');
    const usage = page.getByTestId('analytics-usage');
    await expect(usage.getByRole('button', { name: /^Commercial/ })).toHaveAttribute('aria-pressed', 'true');
    await expect(usage.getByRole('button', { name: /^Residential/ })).toBeDisabled();
    await expect(page.getByTestId('analytics-usage-note')).toHaveText(/no residential sales or leases/);
    const sales = data.usage_counts.Commercial.sales.toLocaleString('en-AE');
    await expect(page.locator('section').filter({ hasText: 'Total Sales' }).first()).toContainText(sales);
    const config = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Configuration Analysis', exact: true }) }).last();
    await expect(config.getByRole('cell', { name: 'Office', exact: true })).toBeVisible();

    // A mixed project opens on its homes; Commercial switches every figure to its offices.
    await page.getByRole('combobox').first().fill('LAKE SHORE TOWER');
    await page.getByRole('option', { name: 'LAKE SHORE TOWER Project', exact: true }).click();
    await expect(usage.getByRole('button', { name: /^Residential/ })).toHaveAttribute('aria-pressed', 'true');
    const switched = page.waitForResponse(r => r.ok() && r.url().includes('/analytics/project/summary?') && r.url().includes('usage=Commercial'));
    await usage.getByRole('button', { name: /^Commercial/ }).click();
    expect((await (await switched).json()).usage).toBe('Commercial');
    await expect(page.getByTestId('analytics-usage-note')).toHaveText(/residential records are under Residential/);
});
