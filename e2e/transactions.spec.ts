import { test, expect, type Page, type Response } from '@playwright/test';

// The Transactions pages show what the API returns, control by control. The API itself is checked
// against the DXBI tables by backend/scripts/clickhouse/verify_dxbi_transactions.py; together they
// tie every number on screen to the warehouse. These run against the local dev stack and its data:
// they assert that the screen equals the API's answer and that each control sends the query it
// stands for, not particular counts.

type Kind = 'sales' | 'rentals';
type Query = Record<string, string | number>;
type Listing = { total: number; rows: Record<string, unknown>[]; params: URLSearchParams };

const PAGE_SIZE = 30;
const ROW_LABEL = { sales: 'transactions', rentals: 'contracts' } as const;
const TIMEFRAMES = [
    ['Last Week', 7],
    ['Last Month', 30],
    ['Last 3 Months', 90],
    ['Last 6 Months', 180],
    ['Last Year', 365]
] as const;
const USAGES = ['Residential', 'Commercial', 'All'] as const;
const count = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

// Half-open bands, as the pages define them: '500-1,000' is 500 up to, not including, 1,000.
const SIZE = { '<500': [, 500], '500-1,000': [500, 1000], '1,000-2,000': [1000, 2000], '2,000-5,000': [2000, 5000], '5,000+': [5000] };
const PRICE = { '<500k': [, 500000], '500k-1M': [500000, 1000000], '1M-2M': [1000000, 2000000], '2M-5M': [2000000, 5000000], '5M+': [5000000] };
const PRICE_SQFT = { '<1,000': [, 1000], '1,000-2,000': [1000, 2000], '2,000-3,000': [2000, 3000], '3,000+': [3000] };
const RENT = { '<50k': [, 50000], '50k-100k': [50000, 100000], '100k-200k': [100000, 200000], '200k+': [200000] };

type Filter = { id: string; param: string; bands?: Record<string, (number | undefined)[]> };
const FILTERS: Record<Kind, Filter[]> = {
    sales: [
        { id: 'selectedLocation', param: 'location' },
        { id: 'selectedBuilding', param: 'building' },
        { id: 'selectedPropertyType', param: 'property_type' },
        { id: 'selectedBedrooms', param: 'bedrooms' },
        { id: 'selectedStatus', param: 'status' },
        { id: 'sizeRange', param: 'size', bands: SIZE },
        { id: 'priceRange', param: 'price', bands: PRICE },
        { id: 'pricePerSqFtRange', param: 'price_per_sqft', bands: PRICE_SQFT }
    ],
    rentals: [
        { id: 'selectedLocation', param: 'location' },
        { id: 'selectedBuilding', param: 'building' },
        { id: 'selectedPropertyType', param: 'property_type' },
        { id: 'selectedBedrooms', param: 'bedrooms' },
        { id: 'selectedContractType', param: 'contract_type' },
        { id: 'sizeRange', param: 'size', bands: SIZE },
        { id: 'rentRange', param: 'rent', bands: RENT }
    ]
};

/** The query parameters a filter value stands for. */
function filterQuery(filter: Filter, value: string): Query {
    if (!filter.bands) return { [filter.param]: value };
    const [low, high] = filter.bands[value];
    return {
        ...(low !== undefined ? { [`${filter.param}_min`]: low } : {}),
        ...(high !== undefined ? { [`${filter.param}_max`]: high } : {})
    };
}

/**
 * Every list response the page receives for `kind`, by its exact query. The page caches its
 * queries, so a state reached twice (or passed through between two clicks) is fetched once: a
 * test looks the state up here instead of waiting for a request.
 */
function recordListings(page: Page, kind: Kind) {
    const seen: Listing[] = [];
    page.on('response', async (response: Response) => {
        const url = new URL(response.url());
        if (!url.pathname.endsWith(`/api/v1/transactions/${kind}`)) return;
        if (response.request().method() !== 'GET' || response.status() !== 200) return;
        const body = await response.json();
        seen.push({
            total: body.total,
            rows: kind === 'sales' ? body.transactions : body.contracts,
            params: url.searchParams
        });
    });
    /** The listing for exactly this query (page size included). */
    return async (query: Query): Promise<Listing> => {
        const key = (params: URLSearchParams) => {
            const sorted = new URLSearchParams(params);
            sorted.sort();
            return sorted.toString();
        };
        const want = key(new URLSearchParams(
            Object.entries({ limit: PAGE_SIZE, offset: 0, ...query }).map(([k, v]) => [k, String(v)])
        ));
        const find = () => seen.filter((listing) => key(listing.params) === want).at(-1);
        await expect.poll(() => find() !== undefined, { timeout: 120_000, message: want }).toBe(true);
        return find()!;
    };
}

function usageQuery(usage: string, days: number): Query {
    return usage === 'All' ? { timeframe_days: days } : { property_usage: usage, timeframe_days: days };
}

const rowBoxes = (page: Page) => page.getByRole('checkbox', { name: 'Select row' });
const bodyRows = (page: Page) => page.locator('tbody tr').filter({ has: rowBoxes(page) });

/** The screen shows the listing: its total and its page of rows, in order. */
async function expectScreenShows(page: Page, kind: Kind, listing: Listing) {
    await expect(
        page.getByText(`${count.format(listing.total)} matching ${ROW_LABEL[kind]}`)
    ).toBeVisible();
    const offset = Number(listing.params.get('offset'));
    expect(listing.rows.length).toBe(Math.min(PAGE_SIZE, Math.max(0, listing.total - offset)));
    await expect(rowBoxes(page)).toHaveCount(listing.rows.length);
    for (const [index, row] of listing.rows.slice(0, 3).entries()) {
        await expect(bodyRows(page).nth(index)).toContainText(
            String(kind === 'sales' ? row.transaction_date : row.lease_start)
        );
        await expect(bodyRows(page).nth(index)).toContainText(String(row.unit_number ?? '-'));
    }
}

async function openMenu(page: Page, control: string) {
    const button = page.locator(`#${control}-button`);
    if ((await button.getAttribute('aria-expanded')) !== 'true') await button.click();
    return page.locator(`#${control}-menu`);
}

async function closeMenu(page: Page, control: string) {
    const button = page.locator(`#${control}-button`);
    if ((await button.getAttribute('aria-expanded')) === 'true') await button.click();
}

async function choose(page: Page, control: string, option: string) {
    const menu = await openMenu(page, control);
    // A searchable list (locations, buildings) shows what matches what is typed.
    const search = menu.getByRole('textbox');
    if (await search.count()) await search.fill(option);
    await menu.getByRole('button', { name: option, exact: true }).click();
}

async function openPage(page: Page, kind: Kind, usage: string, timeframe: string) {
    await page.addInitScript(
        ([u, t]) => {
            localStorage.setItem('filter-propertyType', JSON.stringify(u));
            localStorage.setItem('filter-timeframe', JSON.stringify(t));
        },
        [usage, timeframe]
    );
    const listing = recordListings(page, kind);
    await page.goto(`/transactions/${kind}`);
    return listing;
}

for (const kind of ['sales', 'rentals'] as const) {
    test.describe(`${kind} page`, () => {
        test.setTimeout(300_000);

        test('every usage and period shows the rows and total the API returns', async ({ page }) => {
            const listing = await openPage(page, kind, 'All', 'Last Year');
            await expectScreenShows(page, kind, await listing(usageQuery('All', 365)));
            for (const usage of USAGES) {
                for (const [label, days] of TIMEFRAMES) {
                    await page
                        .getByRole('group', { name: 'Property usage' })
                        .getByRole('button', { name: usage, exact: true })
                        .click();
                    await choose(page, 'transactions-timeframe', label);
                    await expectScreenShows(page, kind, await listing(usageQuery(usage, days)));
                }
            }
        });

        test('each filter value sends its query and shows the API rows', async ({ page }) => {
            const listing = await openPage(page, kind, 'Residential', 'Last Year');
            const base = usageQuery('Residential', 365);
            const unfiltered = await listing(base);
            await expectScreenShows(page, kind, unfiltered);
            for (const filter of FILTERS[kind]) {
                const control = `${kind}-filters-desktop-${filter.id}-input`;
                const menu = await openMenu(page, control);
                const offered = (await menu.getByRole('button').allInnerTexts())
                    .map((text) => text.trim())
                    .filter((value) => value && value !== 'All');
                // Bands: every band. Lists: the first and last values the facets offer.
                const values = filter.bands ? offered : [...new Set([offered[0], offered.at(-1)!])];
                expect(values.length, `${filter.id} offers values`).toBeGreaterThan(0);
                await closeMenu(page, control);
                for (const value of values) {
                    await choose(page, control, value);
                    const shown = await listing({ ...base, ...filterQuery(filter, value) });
                    await expectScreenShows(page, kind, shown);
                    if (filter.param === 'property_type' || filter.param === 'bedrooms') {
                        for (const row of shown.rows) expect(row[filter.param]).toBe(value);
                    }
                    if (filter.param === 'building') {
                        for (const row of shown.rows) expect(String(row.building_name).trim()).toBe(value);
                    }
                    // The options narrow to the current filters: reset before the next value.
                    await page.getByRole('button', { name: 'Reset filters' }).first().click();
                    await expectScreenShows(page, kind, unfiltered);
                }
            }
        });

        test('pagination walks the pages as the API pages them', async ({ page }) => {
            const listing = await openPage(page, kind, 'All', 'Last Year');
            const base = usageQuery('All', 365);
            const first = await listing(base);
            expect(first.total).toBeGreaterThan(PAGE_SIZE * 2);
            const last = Math.floor((first.total - 1) / PAGE_SIZE) * PAGE_SIZE;
            for (const [button, offset] of [
                ['Next page', PAGE_SIZE],
                ['Next page', PAGE_SIZE * 2],
                ['Previous page', PAGE_SIZE],
                ['Last page', last],
                ['First page', 0]
            ] as const) {
                await page.getByRole('button', { name: button, exact: true }).click();
                await expectScreenShows(page, kind, await listing({ ...base, offset }));
            }
        });

        test('column settings show and hide a column', async ({ page }) => {
            const listing = await openPage(page, kind, 'Residential', 'Last Month');
            await listing(usageQuery('Residential', 30));
            const header = page.locator('thead').getByText('Project', { exact: true });
            await expect(header).toHaveCount(0);
            await page.locator('#column-visibility-button').click();
            await page.locator('#column-visibility-menu').getByText('Project', { exact: true }).click();
            await expect(header).toBeVisible();
            await page.locator('#column-visibility-menu').getByText('Project', { exact: true }).click();
            await expect(header).toHaveCount(0);
        });

        test('exports carry the filtered rows, or only the selected ones', async ({ page }) => {
            // The shortest period with rows to tick (the local copy may stop short of today).
            const listing = await openPage(page, kind, 'Residential', 'Last Week');
            let first = await listing(usageQuery('Residential', 7));
            let days: number = 7;
            for (const [label, period] of TIMEFRAMES.slice(1)) {
                if (first.total >= 2) break;
                await choose(page, 'transactions-timeframe', label);
                [first, days] = [await listing(usageQuery('Residential', period)), period];
            }
            await expectScreenShows(page, kind, first);
            const ids = kind === 'sales' ? 'transaction_ids' : 'contract_ids';
            const idOf = (row: Record<string, unknown>) =>
                String(kind === 'sales' ? row.transaction_id : row.contract_id);
            const exportWith = async (label: 'CSV' | 'Excel') => {
                const request = page.waitForRequest((r) => r.url().includes(`/transactions/${kind}/export?`));
                const download = page.waitForEvent('download');
                await page.getByRole('button', { name: label, exact: true }).click();
                return { sent: new URL((await request).url()).searchParams, file: await download };
            };
            const csvRows = async (file: Awaited<ReturnType<typeof exportWith>>['file']) => {
                expect(await file.failure()).toBeNull();
                const text = await readAll(await file.createReadStream());
                return text.replace(/^﻿/, '').trim().split(/\r?\n/).length - 1;
            };

            // Filtered: the export asks for the page's filters and returns all their rows.
            let { sent, file } = await exportWith('CSV');
            expect(Object.fromEntries(sent)).toMatchObject({
                format: 'csv',
                timeframe_days: String(days),
                property_usage: 'Residential'
            });
            expect(sent.has(ids)).toBe(false);
            expect(file.suggestedFilename()).toMatch(new RegExp(`^${kind}_export_\\d+\\.csv$`));
            expect(await csvRows(file)).toBe(Math.min(first.total, 50_000));

            // Selected: exactly the ticked rows, whatever the filters match.
            await rowBoxes(page).nth(0).check();
            await rowBoxes(page).nth(1).check();
            ({ sent, file } = await exportWith('CSV'));
            expect(sent.get(ids)?.split(',').sort()).toEqual(first.rows.slice(0, 2).map(idOf).sort());
            expect(await csvRows(file)).toBe(2);

            ({ sent, file } = await exportWith('Excel'));
            expect(sent.get('format')).toBe('xlsx');
            expect(file.suggestedFilename()).toMatch(new RegExp(`^${kind}_export_\\d+\\.xlsx$`));
            expect(await file.failure()).toBeNull();
        });
    });
}

test('a sale opens its details with the values the API returned', async ({ page }) => {
    const listing = await openPage(page, 'sales', 'All', 'Last Month');
    const sale = (await listing(usageQuery('All', 30))).rows[0];
    await bodyRows(page).first().click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Transaction Details')).toBeVisible();
    const field = (label: string) =>
        dialog.getByText(label, { exact: true }).locator('xpath=following-sibling::p[1]');
    await expect(field('Transaction ID')).toHaveText(String(sale.transaction_id));
    await expect(field('Date')).toHaveText(String(sale.transaction_date));
    await expect(field('Unit')).toHaveText(String(sale.unit_number ?? '-'));
    await expect(field('Price')).toHaveText(
        sale.price_aed == null ? '-' : `${count.format(Number(sale.price_aed))} AED`
    );
});

async function readAll(stream: NodeJS.ReadableStream | null): Promise<string> {
    if (!stream) return '';
    const chunks: Buffer[] = [];
    for await (const chunk of stream) chunks.push(Buffer.from(chunk));
    return Buffer.concat(chunks).toString('utf8');
}
