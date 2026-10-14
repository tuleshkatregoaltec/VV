import { test, expect as baseExpect, type Page } from '@playwright/test';
import path from 'node:path';
const expect = baseExpect.configure({ timeout: 30000 });
const evidence = path.resolve(
    __dirname,
    '../docs/audits/analytics-dxbi-2026-10-11/screenshots',
);
const section = (page: Page, name: string) =>
    page
        .locator('section')
        .filter({ has: page.getByRole('heading', { name, exact: true }) });
async function open(page: Page) {
    const response = page.waitForResponse(
        (r) =>
            new URL(r.url()).pathname === '/api/v1/analytics/project/summary' &&
            r.status() === 200,
    );
    await page.goto('/analytics');
    const data = await (await response).json();
    await expect(
        page.getByRole('heading', {
            name: 'Configuration Analysis',
            exact: true,
        }),
    ).toBeVisible();
    return data;
}
async function select(page: Page, name: string, index = 0) {
    await page
        .getByPlaceholder('Search building, project or area...')
        .nth(index)
        .fill(name);
    const response = page.waitForResponse(
        (r) =>
            new URL(r.url()).pathname.endsWith('/project/summary') &&
            new URL(r.url()).searchParams.get('project')?.toLowerCase() ===
                name.toLowerCase() &&
            r.status() === 200,
    );
    await page
        .getByRole('listbox')
        .getByRole('option')
        .filter({ has: page.getByText(new RegExp(`^${name}$`, 'i')) })
        .click();
    return await (await response).json();
}

test('market metrics, segment tables, distributions and supply controls', async ({
    page,
}) => {
    const data = await open(page);
    await expect(
        page
            .getByText(data.sales.transaction_count.toLocaleString('en-US'), {
                exact: true,
            })
            .first(),
    ).toBeVisible();
    const config = section(page, 'Configuration Analysis');
    for (const [label, segment] of [
        ['Off-Plan', 'off_plan'],
        ['Secondary', 'secondary'],
        ['All', 'all'],
    ]) {
        await config.getByRole('button', { name: label, exact: true }).click();
        const rows = data.configuration_analysis.filter(
            (r: any) =>
                r.market_segment === segment &&
                /^(Studio|\d+ B\/R|.*Penthouse.*)$/i.test(r.rooms),
        );
        expect(await config.locator('tbody tr').count()).toBe(rows.length);
        for (const row of rows)
            await expect(
                config
                    .locator('tbody tr')
                    .filter({
                        has: page.getByRole('cell', {
                            name: row.rooms,
                            exact: true,
                        }),
                    }),
            ).toContainText(row.sale_count.toLocaleString('en-US'));
    }
    await config.getByRole('button', { name: 'Rental', exact: true }).click();
    for (const row of data.by_rooms.filter(
        (r: any) =>
            r.rental_count > 0 &&
            /^(Studio|\d+ B\/R|.*Penthouse.*)$/i.test(r.rooms),
    ))
        await expect(
            config
                .locator('tbody tr')
                .filter({
                    has: page.getByRole('cell', {
                        name: row.rooms,
                        exact: true,
                    }),
                }),
        ).toContainText(row.rental_count.toLocaleString('en-US'));
    await config.getByRole('button', { name: 'Sales', exact: true }).click();
    const distro = section(page, 'Price Distribution');
    await expect(distro.locator('canvas')).toBeVisible();
    for (const segment of ['All', 'Off-Plan Only']) {
        const pending =
            segment === 'Off-Plan Only'
                ? page.waitForResponse(
                      (r) =>
                          r
                              .url()
                              .includes(
                                  '/analytics/project/price-distribution',
                              ) &&
                          r.url().includes('reg_type=') &&
                          r.status() === 200,
                  )
                : null;
        await distro
            .getByRole('button', { name: segment, exact: true })
            .first()
            .click();
        if (pending) await pending;
        await expect(distro.locator('canvas')).toBeVisible();
        // Each segment has its own bedroom list; collect it after the response.
        const names = (await distro.getByRole('button').allTextContents())
            .slice(2)
            .map((s) => s.trim());
        for (const name of names) {
            await distro
                .getByRole('button', { name, exact: true })
                .last()
                .click();
            await expect(distro.locator('canvas')).toBeVisible();
        }
    }
    const pipeline = page
        .locator('section')
        .filter({
            has: page.getByRole('heading', { name: /Upcoming Supply/ }),
        });
    for (const button of await pipeline.getByRole('button').all()) {
        await button.click();
        await expect(pipeline.locator('canvas')).toBeVisible();
    }
    await page
        .getByRole('button', { name: 'Price / sq ft', exact: true })
        .click();
    await expect(
        page.getByRole('button', { name: 'Price / sq ft', exact: true }),
    ).toHaveClass(/bg-card/);
    await page.screenshot({
        path: path.join(evidence, 'market-controls.png'),
        fullPage: false,
        timeout: 10000,
    });
});

test('master community must be reachable from the real project catalogue', async ({
    page,
}) => {
    await open(page);
    await page
        .getByPlaceholder('Search building, project or area...')
        .fill('Dubai Marina');
    await expect(page.getByRole('listbox')).toBeVisible();
    await expect(
        page.getByRole('listbox').getByText('Master', { exact: true }),
    ).toBeVisible({ timeout: 30000 });
    await page.screenshot({
        path: path.join(evidence, 'master-search.png'),
        fullPage: false,
    });
});

test('real project selection, comparison, reset and mobile layout', async ({
    page,
}) => {
    await open(page);
    const a = await select(page, 'Binghatti Skyrise');
    await expect(
        page.getByRole('heading', { name: 'Binghatti Skyrise', exact: true }),
    ).toBeVisible();
    await page.screenshot({
        path: path.join(evidence, 'project-desktop.png'),
        fullPage: true,
    });
    await page.getByRole('button', { name: 'Compare', exact: true }).click();
    await select(page, 'Sobha Orbis', 1);
    await expect(
        page.getByRole('heading', {
            name: 'Delta is Project B minus Project A',
            exact: true,
        }),
    ).toBeVisible();
    await page
        .getByRole('button', { name: 'AED / sq ft', exact: true })
        .click();
    await expect(
        page.getByRole('button', { name: 'AED / sq ft', exact: true }),
    ).toHaveAttribute('data-active', 'true');
    await page.getByRole('button', { name: 'Avg price', exact: true }).click();
    await page.screenshot({
        path: path.join(evidence, 'compare-desktop.png'),
        fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({
        path: path.join(evidence, 'compare-mobile.png'),
        fullPage: true,
    });
    expect(
        await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
        ),
    ).toBe(true);
    await page
        .getByRole('button', { name: 'Exit compare', exact: true })
        .click();
    await page
        .getByRole('button', { name: 'Dubai market', exact: true })
        .click();
    await expect(
        page.getByRole('heading', { name: 'Dubai', exact: true }),
    ).toBeVisible();
    await page.evaluate(() => localStorage.setItem('theme', 'dark'));
    await page.reload();
    await expect(
        page.getByRole('heading', {
            name: 'Configuration Analysis',
            exact: true,
        }),
    ).toBeVisible();
    await page.screenshot({
        path: path.join(evidence, 'market-mobile-dark.png'),
        fullPage: true,
    });
});

for (const endpoint of ['trends', 'price-distribution', 'pipeline']) {
    test(`${endpoint}: service failure must not masquerade as empty data`, async ({
        page,
    }) => {
        let failing = true;
        await page.route(`**/api/v1/analytics/project/${endpoint}*`, (route) =>
            failing
                ? route.fulfill({
                      status: 503,
                      json: { detail: 'Audit injected service failure' },
                  })
                : route.continue(),
        );
        await open(page);
        const target =
            endpoint === 'trends'
                ? page
                      .locator('section')
                      .filter({
                          has: page.getByText('Recorded pricing trend', {
                              exact: true,
                          }),
                      })
                      .last()
                : endpoint === 'pipeline'
                  ? page
                        .locator('section')
                        .filter({
                            has: page.getByRole('heading', {
                                name: /Upcoming Supply/,
                            }),
                        })
                  : section(page, 'Price Distribution');
        await expect(target.getByRole('alert')).toBeVisible({ timeout: 30000 });
        await target.scrollIntoViewIfNeeded();
        await page.screenshot({
            path: path.join(evidence, `${endpoint}-failure.png`),
            fullPage: false,
        });
        await expect(target).toContainText(/failed|error|retry/i, {
            timeout: 1000,
        });
        failing = false;
        await target
            .getByRole('button', { name: 'Retry', exact: true })
            .click();
        await expect(target.getByRole('alert')).toHaveCount(0);
        await expect(target.locator('canvas')).toBeVisible();
    });
}

test('sub-project buttons support keyboard activation from the live master catalogue', async ({
    page,
}) => {
    await open(page);
    await page
        .getByPlaceholder('Search building, project or area...')
        .fill('Dubai Marina');
    await page
        .getByRole('listbox')
        .getByRole('option')
        .filter({ has: page.getByText('Master', { exact: true }) })
        .click();
    const trigger = page.getByRole('button', { name: /All development \(/ });
    await expect(trigger).toBeVisible();
    await trigger.click();
    const option = page
        .getByPlaceholder('Filter sub-projects...')
        .locator('../..')
        .getByRole('button')
        .nth(1);
    const label = await option.innerText();
    await option.focus();
    await page.keyboard.press('Enter');
    await page.screenshot({
        path: path.join(evidence, 'subproject-keyboard.png'),
        fullPage: false,
    });
    await expect(page.getByPlaceholder('Filter sub-projects...')).toHaveCount(
        0,
        { timeout: 1000 },
    );
    await expect(
        page.getByRole('button', { name: label, exact: true }),
    ).toBeVisible();
});

test('selecting a catalogue name preserves known project sales', async ({
    page,
}) => {
    await open(page);
    const selected = await select(page, '23 Marina');
    await expect(
        page.getByRole('heading', { name: /^23 marina$/i }),
    ).toBeVisible();
    // The section also holds the Market Split donut; the trend chart is its first canvas.
    await expect(
        page
            .locator('section')
            .filter({ has: page.getByText('Price Trend', { exact: true }) })
            .last()
            .locator('canvas'),
    ).toBeVisible({ timeout: 15000 });
    await page.screenshot({
        path: path.join(evidence, 'canonical-project.png'),
        fullPage: false,
    });
    // Compare both names against the same authenticated local API.
    const canonical = await page.evaluate(async () => {
        const session = JSON.parse(localStorage.getItem('authentication')!);
        const response = await fetch(
            '/api/v1/analytics/project/summary?project=23%20MARINA',
            { headers: { Authorization: `Bearer ${session.access_token}` } },
        );
        return response.json();
    });
    expect(canonical.sales.transaction_count).toBeGreaterThan(0);
    expect(selected.sales.transaction_count).toBe(
        canonical.sales.transaction_count,
    );
});

test('supply does not present unsupported bedroom estimates as recorded counts', async ({
    page,
}) => {
    await open(page);
    const pipeline = page
        .locator('section')
        .filter({
            has: page.getByRole('heading', { name: /Upcoming Supply/ }),
        });
    await expect(
        pipeline.getByRole('button', { name: 'Studio', exact: true }),
    ).toHaveCount(0);
    await pipeline.scrollIntoViewIfNeeded();
    await page.screenshot({
        path: path.join(evidence, 'supply-area.png'),
        fullPage: false,
    });
    await expect(pipeline).toContainText('all bedroom types');
});

test('summary failure is explicit', async ({ page }) => {
    await page.route('**/api/v1/analytics/project/summary*', (route) =>
        route.fulfill({
            status: 503,
            json: { detail: 'Audit injected summary failure' },
        }),
    );
    await page.goto('/analytics');
    await expect(
        page.getByText('Failed to load analytics for this project.', {
            exact: true,
        }),
    ).toBeVisible({ timeout: 100000 });
});

test('main project search retains keyboard focus until selection', async ({
    page,
}) => {
    await open(page);
    await page
        .getByPlaceholder('Search building, project or area...')
        .fill('Binghatti Skyrise');
    await expect(page.getByRole('listbox')).toBeVisible();
    await expect(
        page.getByRole('option').filter({ has: page.getByText('Binghatti Skyrise', { exact: true }) }),
    ).toBeVisible();
    await page.keyboard.press('Tab');
    await page.waitForTimeout(250);
    await expect(
        page.getByRole('option').filter({ has: page.getByText('Binghatti Skyrise', { exact: true }) }),
    ).toBeFocused();
    await page.keyboard.press('Enter');
    await page.screenshot({
        path: path.join(evidence, 'search-keyboard.png'),
        fullPage: false,
    });
    await expect(
        page.getByRole('heading', { name: 'Binghatti Skyrise', exact: true }),
    ).toBeVisible({ timeout: 30000 });
});

test('forecast failure is recoverable without hiding recorded trends', async ({
    page,
}) => {
    let failing = true;
    await page.route('**/api/v1/analytics/project/forecast*', (route) =>
        failing
            ? route.fulfill({
                  status: 503,
                  json: { detail: 'Injected forecast failure' },
              })
            : route.continue(),
    );
    await open(page);
    await select(page, 'Binghatti Skyrise');
    const alert = page
        .getByRole('alert')
        .filter({ hasText: 'Failed to load forecast' });
    await expect(alert).toBeVisible({ timeout: 100000 });
    failing = false;
    await alert.getByRole('button', { name: 'Retry', exact: true }).click();
    await expect(alert).toHaveCount(0);
    await expect(
        page
            .locator('section')
            .filter({ has: page.getByText('Price Trend', { exact: true }) })
            .last()
            .locator('canvas'),
    ).toBeVisible();
});

for (const endpoint of ['summary', 'trends']) {
    test(`comparison ${endpoint} failure is explicit and recoverable`, async ({
        page,
    }) => {
        await open(page);
        await select(page, 'Binghatti Skyrise');
        let failing = true;
        await page.route(`**/api/v1/analytics/project/${endpoint}*`, (route) =>
            failing &&
            new URL(route.request().url()).searchParams.get('project') ===
                'Sobha Orbis'
                ? route.fulfill({
                      status: 503,
                      json: { detail: 'Injected comparison failure' },
                  })
                : route.continue(),
        );
        await page
            .getByRole('button', { name: 'Compare', exact: true })
            .click();
        await page
            .getByPlaceholder('Search building, project or area...')
            .nth(1)
            .fill('Sobha Orbis');
        await page
            .getByRole('listbox')
            .getByRole('option')
            .filter({ has: page.getByText('Sobha Orbis', { exact: true }) })
            .click();
        const alert = page
            .getByRole('alert')
            .filter({
                hasText:
                    endpoint === 'summary'
                        ? 'Failed to load comparison analytics.'
                        : 'Failed to load comparison trends.',
            });
        await expect(alert).toBeVisible({ timeout: 100000 });
        failing = false;
        await alert.getByRole('button', { name: 'Retry', exact: true }).click();
        await expect(alert).toHaveCount(0);
        await expect(
            page.getByRole('heading', {
                name: 'Delta is Project B minus Project A',
                exact: true,
            }),
        ).toBeVisible();
    });
}

test('project search supports arrow selection and Escape', async ({ page }) => {
    await open(page);
    const input = page.getByPlaceholder(
        'Search building, project or area...',
    );
    await input.fill('23 MARINA');
    await expect(page.getByRole('option').first()).toBeVisible();
    await input.press('ArrowDown');
    await expect(page.getByRole('option').first()).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('listbox')).toHaveCount(0);
    await expect(input).toBeFocused();
    await input.fill('23 MARINA');
    await expect(page.getByRole('option').first()).toBeVisible();
    await input.press('ArrowDown');
    await page.keyboard.press('Enter');
    await expect(
        page.getByRole('heading', { name: '23 MARINA', exact: true }),
    ).toBeVisible();
});

test('live master comparison and pointer drill-down remain scoped', async ({
    page,
}) => {
    await open(page);
    await page
        .getByPlaceholder('Search building, project or area...')
        .fill('Dubai Marina');
    await page
        .getByRole('option')
        .filter({ has: page.getByText('Master', { exact: true }) })
        .click();
    await expect(
        page.getByRole('button', { name: /All development \(/ }),
    ).toBeVisible();
    await page.getByRole('button', { name: 'Compare', exact: true }).click();
    await select(page, '23 MARINA', 1);
    await expect(
        page.getByRole('heading', {
            name: 'Delta is Project B minus Project A',
            exact: true,
        }),
    ).toBeVisible();
    await expect(
        page.getByRole('heading', {
            name: 'Dubai Marina',
            exact: true,
            level: 2,
        }),
    ).toBeVisible();
    await page
        .getByRole('button', { name: 'Exit compare', exact: true })
        .click();
    await page.getByRole('button', { name: /All development \(/ }).click();
    const input = page.getByPlaceholder('Filter sub-projects...');
    await input.fill('23 MARINA');
    const response = page.waitForResponse(
        (r) =>
            r.url().includes('/project/summary') &&
            new URL(r.url()).searchParams.get('project')?.toLowerCase() === '23 marina' &&
            r.status() === 200,
    );
    await input
        .locator('../..')
        .getByRole('button', { name: '23 MARINA', exact: true })
        .click();
    const data = await (await response).json();
    expect(data.sales.transaction_count).toBeGreaterThan(0);
    await expect(
        page.getByRole('heading', { name: '23 MARINA', exact: true }),
    ).toBeVisible();
    await page.screenshot({
        path: path.join(evidence, 'master-drilldown.png'),
        fullPage: false,
    });
});

test('project search failure can be retried', async ({ page }) => {
    await open(page);
    let failing = true;
    await page.route('**/api/v1/analytics/projects?*', (route) =>
        failing
            ? route.fulfill({
                  status: 503,
                  json: { detail: 'Injected search failure' },
              })
            : route.continue(),
    );
    await page
        .getByPlaceholder('Search building, project or area...')
        .fill('23 MARINA');
    const alert = page
        .getByRole('alert')
        .filter({ hasText: 'Failed to load projects.' });
    await expect(alert).toBeVisible({ timeout: 30000 });
    failing = false;
    await alert.getByRole('button', { name: 'Retry', exact: true }).click();
    await expect(
        page.getByRole('option').filter({ has: page.getByText('23 MARINA', { exact: true }) }),
    ).toBeVisible();
});

test('development list failure can be retried', async ({ page }) => {
    await open(page);
    let failing = true;
    await page.route('**/api/v1/analytics/project/sub-projects*', (route) =>
        failing
            ? route.fulfill({
                  status: 503,
                  json: { detail: 'Injected development failure' },
              })
            : route.continue(),
    );
    await page
        .getByPlaceholder('Search building, project or area...')
        .fill('Dubai Marina');
    await page
        .getByRole('option')
        .filter({ has: page.getByText('Master', { exact: true }) })
        .click();
    const alert = page
        .getByRole('alert')
        .filter({ hasText: 'Failed to load developments.' });
    await expect(alert).toBeVisible({ timeout: 30000 });
    failing = false;
    await alert.getByRole('button', { name: 'Retry', exact: true }).click();
    await expect(alert).toHaveCount(0);
    await expect(
        page.getByRole('button', { name: /All development \(/ }),
    ).toBeVisible();
});
