import { test, expect, type Page } from '@playwright/test';
import path from 'node:path';

// Real local data and authenticated session. Only the explicit failure case mocks an API.
const screenshots = path.resolve(__dirname, '../docs/audits/transaction-filters-2026-10-10/screenshots');
type Kind = 'sales' | 'rentals';
function response(page: Page, route: string, params: Record<string, string> = {}) {
    return page.waitForResponse(r => {
        const url = new URL(r.url());
        return url.pathname === route && r.status() === 200 &&
            Object.entries(params).every(([key, value]) => url.searchParams.get(key) === value);
    });
}
async function open(page: Page, kind: Kind) {
    await page.addInitScript(() => {
        localStorage.setItem('filter-propertyType', JSON.stringify('Residential'));
        localStorage.setItem('filter-timeframe', JSON.stringify('Last Month'));
    });
    const options = response(page, `/api/v1/filters/${kind}`);
    await page.goto(`/transactions/${kind}`);
    await ready(page);
    return (await options).json();
}
async function ready(page: Page) {
    await expect(page.getByRole('region', { name: 'Transaction filters' })).toHaveAttribute('aria-busy', 'false');
    await expect(page.getByLabel('Location keywords', { exact: true })).toBeEnabled();
}
async function select(page: Page, kind: Kind, label: string, value: string, search?: string) {
    await ready(page);
    if (label !== 'Location') await page.getByRole('button', { name: label, exact: true }).click();
    if (search && label !== 'Location') await page.getByRole('textbox', { name: `Search options for ${label}` }).fill(search);
    // A previous list request may still be in flight after facets finish. Assert against
    // the response for this selection, not whichever response happens to arrive first.
    const selected: Record<string, string> = label === 'Property Type' ? { property_type: value }
        : label === 'Location' ? { location_search: value }
        : label === 'Period' && value === 'Last Year' ? { timeframe_days: '365' } : {};
    const list = response(page, `/api/v1/transactions/${kind}`, selected);
    if (label === 'Location') await page.getByLabel('Location keywords', { exact: true }).fill(value);
    else await page.getByRole('button', { name: value, exact: true }).last().click();
    const result = await (await list).json();
    await ready(page);
    await expect(page.getByText(`${new Intl.NumberFormat('en-US').format(result.total)} matching ${kind === 'sales' ? 'transactions' : 'contracts'}`, { exact: true })).toBeVisible();
    return result;
}

for (const kind of ['sales', 'rentals'] as const) {
    test(`${kind}: compact desktop and responsive controls`, async ({ page }) => {
        await open(page, kind);
        const controls = page.getByTestId('primary-filters').getByRole('button');
        await expect(controls).toHaveCount(3);
        const boxes = await controls.evaluateAll(elements => elements.map(e => e.getBoundingClientRect().top));
        expect(Math.max(...boxes) - Math.min(...boxes)).toBeLessThan(2);
        await expect(page.getByRole('button', { name: 'Building', exact: true })).toBeHidden();
        await page.screenshot({ path: path.join(screenshots, `${kind}-desktop.png`) });
        await page.getByText('More filters', { exact: false }).first().click();
        await expect(page.getByRole('button', { name: 'Building', exact: true })).toHaveCount(0);
        await page.screenshot({ path: path.join(screenshots, `${kind}-expanded.png`) });
        await page.setViewportSize({ width: 390, height: 844 });
        await expect(page.getByLabel('Location keywords', { exact: true })).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        await page.getByText('More filters', { exact: false }).first().click();
        await page.waitForTimeout(250); // Allow the disclosure icon transition to finish for evidence.
        await page.screenshot({ path: path.join(screenshots, `${kind}-mobile.png`) });
        await page.getByLabel('Location keywords', { exact: true }).fill('duabi marna');
        await expect(page.locator(`#${kind}-location-suggestions option[value="Dubai Marina"]`)).toHaveCount(1);

    });

    test(`${kind}: genuine suggestions, combinations, clear and period preservation`, async ({ page }) => {
        const baseline = await open(page, kind);
        expect(baseline.property_types.length).toBeGreaterThan(1);
        await select(page, kind, 'Property Type', baseline.property_types[0]);
        await page.getByRole('button', { name: 'Property Type', exact: true }).click();
        await expect(page.getByRole('button', { name: baseline.property_types[1], exact: true })).toBeVisible();
        await page.keyboard.press('Escape');
        await page.getByRole('button', { name: 'Clear Property Type', exact: true }).click();
        await ready(page);
        const marina = await select(page, kind, 'Location', 'Dubai Marina', 'duabi marna');
        expect(marina.total).toBeGreaterThan(0);
        await page.getByText('More filters', { exact: false }).first().click();
        await expect(page.getByRole('button', { name: 'Building', exact: true })).toHaveCount(0);
        await select(page, kind, 'Period', 'Last Year');
        await expect(page.getByLabel('Location keywords', { exact: true })).toHaveValue('Dubai Marina');
        await page.getByRole('button', { name: 'Reset filters', exact: true }).click();
        await expect(page.getByLabel('Location keywords', { exact: true })).toHaveValue('');

    });

    test(`${kind}: unavailable options cannot masquerade as a valid All-only menu`, async ({ page }) => {
        let failing = true;
        await page.route(`**/api/v1/filters/${kind}?**`, route => failing
            ? route.fulfill({ status: 503, json: { detail: 'Injected filter failure' } })
            : route.continue());
        await page.goto(`/transactions/${kind}`);
        await expect(page.getByRole('button', { name: 'Property Type', exact: true })).toBeDisabled();
        await expect(page.getByRole('alert')).toContainText('Error loading filters', { timeout: 20000 });
        failing = false;
        await page.getByRole('button', { name: 'Retry filters', exact: true }).click();
        await ready(page);
        await expect(page.getByRole('alert')).toHaveCount(0);
        await page.getByLabel('Location keywords', { exact: true }).fill('Dubai Marina');
        await expect(page.locator(`#${kind}-location-suggestions option[value="Dubai Marina"]`)).toHaveCount(1);

    });
}
