import { existsSync } from 'node:fs';
import { expect, test } from '@playwright/test';

test.use({ screenshot: 'off', trace: 'off', video: 'off' });

// A real owner workbook goes through the browser into the disposable test organization and is
// deleted afterwards. It holds personal data, so it never lives in the repo: point OWNER_IMPORT_FILE
// at it. Only counts are logged. Screenshots of the report stay in the local test output.
const file = process.env.OWNER_IMPORT_FILE ?? '';
test.skip(!file || !existsSync(file), 'Set OWNER_IMPORT_FILE to a real owner workbook');

const CONFIRMED = ['Confirmed', 'Confirmed, unit inferred', 'Confirmed, no unit', 'Confirmed via mortgage'];
const firstAed = (text: string) => {
    const m = /AED ([\d,]+)/.exec(text);
    return m ? Number(m[1].replaceAll(',', '')) : null;
};

test('a real owner workbook previews its columns, imports and reports units confirmed with a sale', async ({ page }, testInfo) => {
    test.setTimeout(40 * 60_000);
    page.setDefaultTimeout(30_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/crm/owners/imports');
    await page.getByRole('button', { name: 'Upload', exact: true }).first().click();
    await page.locator('input[type=file]').setInputFiles(file);

    // The dialog lists our fields as found or not found and shows the sample under our labels;
    // the file's own column headers are never printed.
    const found = page.getByRole('list', { name: 'Fields in the file' });
    await expect(found).toContainText('Building', { timeout: 180_000 });
    for (const field of ['Owner name', 'Unit number', 'Sale price']) await expect(found).toContainText(field);
    const header = page.locator('.cols thead');
    await expect(header.locator('th').first()).toContainText(/^\D/);
    await expect(header).not.toContainText(/ProcedurePartyTypeNameEn|UnitNumber|NameEn/);
    await page.screenshot({ path: testInfo.outputPath('import-dialog.png'), animations: 'disabled' });

    const importButton = page.getByRole('button', { name: /^Import [\d,]+ rows$/ });
    const posted = page.waitForResponse(
        r => new URL(r.url()).pathname === '/api/v1/crm/contact-imports' && r.request().method() === 'POST',
        { timeout: 35 * 60_000 }
    );
    await importButton.click();
    const response = await posted;
    expect(response.ok()).toBeTruthy();
    const imported = await response.json();
    const authorization = { Authorization: (await response.request().allHeaders()).authorization };
    const importUrl = response.url();
    try {
        expect(imported.status).toBe('completed');
        const units = imported.summary.owner_match.units;
        const percent = Math.round((units.confirmed / units.total) * 100);
        console.log('Owner import result:', JSON.stringify({
            id: imported.id, rows: imported.summary.total_rows, kept: imported.summary.candidate_rows,
            units, percent, rows_without_unit: imported.summary.owner_match.rows_without_unit
        }));
        // Every distinct unit lands in exactly one bucket of the Match result card.
        expect(units.confirmed + units.review + units.property_only + units.not_matched).toBe(units.total);
        // The bar set for a "decent" file: at least 70% of its distinct units confirmed with a sale.
        expect(percent).toBeGreaterThanOrEqual(70);
        const result = page.locator('.kv.result');
        await expect(result).toContainText(new RegExp(`Units identified\\s*${units.total.toLocaleString('en-US')}`));
        await expect(result).toContainText(new RegExp(`Units mapped\\s*${units.confirmed.toLocaleString('en-US')}`));
        await expect(result).toContainText(`${percent}% coverage`);

        await page.getByRole('button', { name: 'Open report', exact: true }).click();
        await expect(page).toHaveURL(`/crm/owners/imports/${imported.id}`);
        const mapped = page.locator('.stat').filter({ has: page.getByText('Units mapped', { exact: true }) });
        await expect(mapped.locator('.big')).toHaveText(units.confirmed.toLocaleString('en-US'), { timeout: 600_000 });
        await expect(mapped).toContainText(`${percent}% coverage`);

        // Confirmed rows: each is tied to a sale at the sheet's price (within AED 2). A mortgage row's
        // amount is a loan, so "Confirmed via mortgage" is checked by its chip only.
        const rows = page.locator('#source-rows tbody tr');
        await page.getByRole('tab', { name: 'Confirmed', exact: true }).click();
        await expect(page.locator('#source-rows .count')).toHaveText(/^Showing 1–/, { timeout: 120_000 });
        await expect(page.locator('#source-rows .stale')).toHaveCount(0);
        const confirmed = await rows.evaluateAll(trs => trs.map(tr => ({
            result: tr.querySelector('[data-label="Result"]')?.textContent?.trim() ?? '',
            sheet: tr.querySelector('[data-label="Property"]')?.textContent ?? '',
            sale: tr.querySelector('[data-label="Matched sale"]')?.textContent ?? ''
        })));
        expect(confirmed.length).toBeGreaterThan(0);
        let priced = 0;
        for (const row of confirmed) {
            expect(CONFIRMED).toContain(row.result);
            if (row.result === 'Confirmed via mortgage') continue;
            const sheet = firstAed(row.sheet);
            const sale = firstAed(row.sale);
            expect(sale, `matched sale of a confirmed row: ${row.sale}`).not.toBeNull();
            expect(Math.abs((sheet ?? 0) - (sale ?? 0))).toBeLessThanOrEqual(2);
            priced += 1;
        }
        console.log('Confirmed rows checked on the first page:', confirmed.length, 'with a sale price:', priced);

        await page.getByRole('tab', { name: 'Lender', exact: true }).click();
        await expect(page.locator('#source-rows .stale')).toHaveCount(0, { timeout: 120_000 });
        for (const result of await rows.locator('[data-label="Result"]').allTextContents()) {
            if (result.trim()) expect(result.trim()).toBe('Lender');
        }
        await page.getByRole('tab', { name: 'All', exact: true }).click();
        await page.screenshot({ path: testInfo.outputPath('import-report.png'), fullPage: false, animations: 'disabled' });

        // The list shows the file the way the mock's import requests card does.
        await page.goto('/crm/owners/imports');
        const listed = page.locator('tbody tr').filter({ has: page.getByRole('button', { name: imported.name, exact: true }) });
        await expect(listed.locator('[data-label="Units mapped"]')).toContainText(`${percent}%`, { timeout: 120_000 });
        await expect(listed.locator('[data-label="Status"]')).toContainText('Completed ·');
        await page.screenshot({ path: testInfo.outputPath('import-list.png'), animations: 'disabled' });
        await page.setViewportSize({ width: 375, height: 812 });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    } finally {
        const removed = await page.request.delete(`${importUrl}/${imported.id}`, { headers: authorization, timeout: 60_000 });
        expect(removed.ok()).toBeTruthy();
    }
});
