import { test, expect } from '@playwright/test';
import path from 'node:path';

for (const kind of ['sales', 'rentals'] as const) {
  test(`${kind}: unified location keyword search reconciles rows and resets`, async ({ page }) => {
    test.setTimeout(120000);
    await page.addInitScript(() => {
      localStorage.setItem('filter-propertyType', JSON.stringify('Residential'));
      localStorage.setItem('filter-timeframe', JSON.stringify('Last Year'));
    });
    await page.goto(`/transactions/${kind}`);
    const input = page.getByLabel('Location keywords', { exact: true });
    await expect(input).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Location', exact: true })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Building', exact: true })).toHaveCount(0);
    await expect(page.getByRole('columnheader', { name: 'Project', exact: true })).toHaveCount(0);
    const loaded = page.waitForResponse(r => new URL(r.url()).pathname === `/api/v1/transactions/${kind}` && new URL(r.url()).searchParams.get('location_search') === 'dubai marina' && r.ok());
    await input.fill('dubai marina');
    const result = await (await loaded).json();
    expect(result.total).toBeGreaterThan(0);
    expect(result.limit).toBe(10);
    await expect(page.getByText(`${result.total.toLocaleString('en-US')} matching ${kind === 'sales' ? 'transactions' : 'contracts'}`, { exact: true })).toBeVisible();
    await expect(page.locator('tbody tr')).toHaveCount(Math.min(10, result.total));
    await page.getByText('More filters', { exact: false }).first().click();
    await expect(page.getByRole('button', { name: 'Building', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Project', exact: true })).toHaveCount(0);
    await expect(page.getByRole('region', { name: 'Transaction filters' })).toHaveAttribute('aria-busy', 'false', { timeout: 60000 });
    await page.screenshot({ path: path.resolve(`../docs/audits/location-unification-2026-10-12/${kind}-desktop.png`), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: path.resolve(`../docs/audits/location-unification-2026-10-12/${kind}-mobile.png`), fullPage: true });
    await page.getByRole('button', { name: 'Clear location search', exact: true }).click();
    await expect(input).toHaveValue('');
  });
}

test('Analytics identifies a building scope without stripping its numbered name', async ({ page }) => {
  test.setTimeout(120000);
  await page.goto('/analytics');
  const search = page.getByRole('combobox').first();
  await search.fill('08 life');
  // DLD registers it as a project; the numbered name stays whole.
  const option = page.getByRole('option', { name: '08 Life Residences Project', exact: true });
  await expect(option).toBeVisible({ timeout: 60000 });
  await page.screenshot({ path: path.resolve('../docs/audits/location-unification-2026-10-12/analytics-building.png') });
});
