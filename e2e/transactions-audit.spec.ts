import { test, expect, type Page } from '@playwright/test';
import path from 'node:path';

// Run with the local audit config and an authenticated test session. Responses are real except
// in explicitly injected latency/failure cases. No database changes are made by these tests.
const evidence = process.env.TRANSACTION_AUDIT_SCREENSHOTS ?? path.resolve(
    __dirname,
    '../docs/audits/resolution-2026-10-10/screenshots',
);
async function open(page: Page, kind: 'sales' | 'rentals') {
    await page.addInitScript(() => {
        localStorage.setItem('filter-propertyType', JSON.stringify('All'));
        localStorage.setItem('filter-timeframe', JSON.stringify('Last Month'));
    });
    const response = page.waitForResponse(
        (r) =>
            new URL(r.url()).pathname === `/api/v1/transactions/${kind}` &&
            r.status() === 200,
    );
    await page.goto(`/transactions/${kind}`);
    const body = await (await response).json();
    await expect(
        page.locator('tbody input[aria-label="Select row"]').first(),
    ).toBeVisible({ timeout: 120000 });
    return body;
}

for (const kind of ['sales', 'rentals'] as const) {
    test(`${kind}: all displayed fields equal API values`, async ({ page }) => {
        const body = await open(page, kind);
        await page
            .getByRole('button', { name: 'Column Settings', exact: true })
            .click();
        await page
            .getByRole('button', { name: 'Show all', exact: true })
            .click();
        await page.keyboard.press('Escape');
        const fields =
            kind === 'sales'
                ? [
                      'transaction_date',
                      'unit_number',
                      'combined_location',
                      'property_type',
                      'bedrooms',
                      'size_sqft',
                      'price_aed',
                      'price_per_sqft_aed',
                      'status',
                  ]
                : [
                      'lease_start',
                      'lease_end',
                      'unit_number',
                      'combined_location',
                      'property_type',
                      'bedrooms',
                      'size_sqft',
                      'annual_rent_aed',
                      'contract_amount_aed',
                      'term_months',
                      'contract_type',
                  ];
        const rows = body[kind === 'sales' ? 'transactions' : 'contracts'];
        for (let i = 0; i < 3; i++) {
            const cells = await page
                .locator('tbody tr')
                .nth(i)
                .locator('td')
                .allInnerTexts();
            const expected = fields.map((key) =>
                key === 'combined_location'
                    ? [rows[i].building_name, rows[i].project_name, rows[i].location_name]
                        .filter((value, index, all) => value?.trim() && all.findIndex(v => v?.trim().toLowerCase() === value.trim().toLowerCase()) === index)
                        .map(value => value.trim()).join(' · ') || 'Location unavailable'
                    : rows[i][key] == null
                    ? '-'
                    : typeof rows[i][key] === 'number'
                      ? new Intl.NumberFormat('en-US', {
                            maximumFractionDigits:
                                key === 'term_months' ? 1 : 0,
                        }).format(rows[i][key])
                      : String(rows[i][key]),
            );
            expect(cells.slice(1).map((x) => x.trim())).toEqual(expected);
        }
        await page.screenshot({
            path: path.join(evidence, `${kind}-desktop.png`),
            fullPage: false,
        });
    });

    test(`${kind}: pending page must not allow selection of the previous page`, async ({
        page,
    }) => {
        await open(page, kind);
        let release!: () => void;
        const barrier = new Promise<void>((resolve) => (release = resolve));
        await page.route(`**/api/v1/transactions/${kind}?**`, async (route) => {
            if (
                new URL(route.request().url()).searchParams.get('offset') ===
                '10'
            )
                await barrier;
            await route.continue();
        });
        await page
            .getByRole('button', { name: 'Next page', exact: true })
            .click();
        await expect(
            page.getByRole('navigation', { name: 'Pagination' }),
        ).toContainText('11');
        await page.screenshot({
            path: path.join(evidence, `${kind}-pending-page.png`),
            fullPage: true,
        });
        const previousRow = page
            .locator('tbody input[aria-label="Select row"]')
            .first();
        // Financial evidence must not be selectable under the wrong page/filter label.
        try {
            await expect(previousRow).toHaveCount(0, { timeout: 1000 });
            await expect(
                page.getByText('Loading...', { exact: true }).first(),
            ).toBeVisible();
        } finally {
            release();
        }
    });

    test(`${kind}: filter-option failure must be visible to users`, async ({
        page,
    }) => {
        let failing = true;
        await page.route(`**/api/v1/filters/${kind}?**`, (route) =>
            failing
                ? route.fulfill({
                      status: 503,
                      json: { detail: 'Audit injected facet failure' },
                  })
                : route.continue(),
        );
        await open(page, kind);
        await page.waitForTimeout(8500); // Query's default retries use 1+2+4 second backoff.
        await expect(page.locator(`#${kind}-filters-selectedPropertyType-input-button`)).toBeDisabled();
        await page.waitForTimeout(300);
        await page.screenshot({
            path: path.join(evidence, `${kind}-facet-error.png`),
            fullPage: false,
        });
        await expect(
            page.getByText(
                /error loading filters|failed to load filters|Audit injected facet failure/i,
            ),
        ).toBeVisible({ timeout: 1000 });
        failing = false;
        const recovered = page.waitForResponse(
            (r) =>
                r.url().includes(`/api/v1/filters/${kind}`) &&
                r.status() === 200,
        );
        await page
            .getByRole('button', { name: 'Retry filters', exact: true })
            .click();
        await recovered;
        await expect(page.getByText(/error loading filters/i)).toHaveCount(0);
    });
}

test('sale detail dialog must receive focus and contain keyboard navigation', async ({
    page,
}) => {
    await open(page, 'sales');
    await page.locator('tbody tr').first().click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await page.screenshot({
        path: path.join(evidence, 'sale-details.png'),
        fullPage: false,
    });
    expect
        .soft(
            await dialog.evaluate((el) => el.contains(document.activeElement)),
        )
        .toBe(true);
    await page.getByRole('button', { name: 'Close modal' }).focus();
    await page.keyboard.press('Tab');
    expect
        .soft(
            await dialog.evaluate((el) => el.contains(document.activeElement)),
        )
        .toBe(true);
    await page.keyboard.press('Shift+Tab');
    expect(
        await dialog.evaluate((el) => el.contains(document.activeElement)),
    ).toBe(true);
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
});

test('mobile rental rent dropdown can select its last option', async ({
    page,
}) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript(() => localStorage.setItem('theme', 'light'));
    // open() waits on desktop rows; mobile uses cards instead.
    await page.addInitScript(() => {
        localStorage.setItem('filter-propertyType', JSON.stringify('All'));
        localStorage.setItem('filter-timeframe', JSON.stringify('Last Month'));
    });
    await page.goto('/transactions/rentals');
    await expect(
        page.getByRole('checkbox', { name: 'Select row' }).first(),
    ).toBeVisible({ timeout: 120000 });
    await page.locator('details > summary').click();
    await page
        .locator('#rentals-filters-rentRange-input-button')
        .click();
    const option = page
        .locator('#rentals-filters-rentRange-input-menu')
        .getByRole('button', { name: '200k+', exact: true });
    await page.screenshot({
        path: path.join(evidence, 'rentals-mobile-dropdown.png'),
        fullPage: false,
    });
    await option.click({ timeout: 3000 });
    await expect(
        page.locator('#rentals-filters-rentRange-input-button'),
    ).toHaveText('200k+');
});

for (const kind of ['sales', 'rentals'] as const) {
    test(`${kind}: selection, column controls and navigation remain usable`, async ({
        page,
    }) => {
        await open(page, kind);
        await page
            .getByRole('checkbox', {
                name: 'Select all 10 rows on this page',
                exact: true,
            })
            .check();
        await expect(
            page.getByText('10 selected', { exact: true }),
        ).toBeVisible();
        await page
            .getByRole('checkbox', {
                name: 'Deselect all 10 rows on this page',
                exact: true,
            })
            .uncheck();
        await expect(
            page.getByRole('button', { name: 'Clear selection' }),
        ).toHaveCount(0);
        await page
            .getByRole('checkbox', { name: 'Select row', exact: true })
            .first()
            .check();
        await page.getByRole('button', { name: 'Clear selection' }).click();
        await expect(
            page
                .getByRole('checkbox', { name: 'Select row', exact: true })
                .first(),
        ).not.toBeChecked();
        await page
            .getByRole('button', { name: 'Column Settings', exact: true })
            .click();
        const menu = page.locator('#column-visibility-menu');
        await menu
            .getByRole('button', { name: 'Show all', exact: true })
            .click();
        const boxes = menu.getByRole('checkbox');
        for (let i = 0; i < (await boxes.count()); i++) {
            await boxes.nth(i).uncheck();
            await boxes.nth(i).check();
        }
        await page.keyboard.press('Escape');
        if (kind === 'sales') {
            for (const method of ['close', 'escape', 'backdrop']) {
                await page.locator('tbody tr').first().click();
                await expect(page.getByRole('dialog')).toBeVisible();
                if (method === 'close')
                    await page
                        .getByRole('button', { name: 'Close modal' })
                        .click();
                else if (method === 'escape')
                    await page.keyboard.press('Escape');
                else
                    await page
                        .getByRole('dialog')
                        .locator('..')
                        .click({ position: { x: 5, y: 5 } });
                await expect(page.getByRole('dialog')).toHaveCount(0);
            }
        }
        const other = kind === 'sales' ? 'Rentals' : 'Sales';
        await page
            .getByRole('navigation', { name: 'Transaction type' })
            .getByRole('link', { name: other, exact: true })
            .click();
        await expect(page).toHaveURL(
            new RegExp(`/transactions/${other.toLowerCase()}$`),
        );
        await expect(
            page
                .getByRole('checkbox', { name: 'Select row', exact: true })
                .first(),
        ).toBeVisible();
    });
}

test('mobile sales cards show API values and open and close details in dark mode', async ({
    page,
}) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.addInitScript(() => {
        localStorage.setItem('theme', 'dark');
        localStorage.setItem('filter-propertyType', JSON.stringify('All'));
        localStorage.setItem('filter-timeframe', JSON.stringify('Last Month'));
    });
    const response = page.waitForResponse(
        (r) =>
            new URL(r.url()).pathname === '/api/v1/transactions/sales' &&
            r.status() === 200,
    );
    await page.goto('/transactions/sales');
    const sale = (await (await response).json()).transactions[0];
    const box = page
        .getByRole('checkbox', { name: 'Select row', exact: true })
        .first();
    await expect(box).toBeVisible({ timeout: 120000 });
    const card = box.locator('..');
    await expect(card).toContainText(String(sale.transaction_date));
    await expect(card).toContainText(
        new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(
            sale.price_aed,
        ),
    );
    await box.check();
    await expect(page.getByText('1 selected', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Clear selection' }).click();
    await card.getByRole('button').click();
    await expect(page.getByRole('dialog')).toContainText(sale.transaction_id);
    await page.getByRole('button', { name: 'Close modal' }).click();
    await page.screenshot({
        path: path.join(evidence, 'sales-mobile-dark.png'),
        fullPage: false,
    });
});
