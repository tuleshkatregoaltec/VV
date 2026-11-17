import { test, expect as baseExpect } from '@playwright/test';
import path from 'node:path';
const expect = baseExpect.configure({ timeout: 30000 });

const shots = path.resolve('../docs/audits/analytics-hierarchy-2026-10-21/screenshots');

// A building is its own scope: its figures cover that building only, its header names its
// project and master (each a link up), and its units come from a named register.
test('a building opens its own analytics and leads up to its project and master', async ({ page }) => {
    test.setTimeout(180000);
    const errors: string[] = [];
    const summaries: { url: URL; body: any }[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('response', async (response) => {
        const url = new URL(response.url());
        if (response.ok() && url.pathname.endsWith('/analytics/project/summary')) {
            summaries.push({ url, body: await response.json() });
        }
    });
    await page.goto('/analytics');
    await expect(page.getByRole('heading', { name: 'Configuration Analysis', exact: true })).toBeVisible();

    const input = page.getByRole('combobox').first();
    await input.fill('Skyrise Tower A');
    const option = page.getByRole('option', { name: /^Binghatti Skyrise - Tower A Building · Binghatti Skyrise · Business Bay$/ });
    await option.click();
    await expect.poll(() => summaries.some((s) => s.url.searchParams.get('building_id'))).toBe(true);
    const tower = summaries.find((s) => s.url.searchParams.get('building_id'))!.body;
    expect(tower.project.scope_level).toBe('building');
    expect(tower.project.parent_project).toBe('Binghatti Skyrise');

    await expect(page.getByRole('heading', { name: 'Binghatti Skyrise - Tower A', level: 2 })).toBeVisible();
    const breadcrumb = page.getByTestId('analytics-breadcrumb');
    await expect(breadcrumb).toContainText('Business Bay');
    await expect(breadcrumb).toContainText('Binghatti Skyrise');
    await expect(page.getByTestId('analytics-units')).toHaveText(tower.project.no_of_units.toLocaleString('en-US'));
    await page.screenshot({ path: `${shots}/building.png`, fullPage: true });

    // Up to the project: every building, listed with its units.
    await breadcrumb.getByRole('button', { name: 'Binghatti Skyrise', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Binghatti Skyrise', level: 2 })).toBeVisible();
    const buildings = page.getByTestId('analytics-buildings');
    await expect(buildings.getByRole('row')).toHaveCount(5);
    await expect(page.getByTestId('analytics-units')).toHaveText('3,358');
    const project = summaries.at(-1)!.body;
    expect(project.buildings.map((b: any) => b.name)).toContain('Binghatti Skyrise - Tower C');
    expect(project.sales.transaction_count).toBeGreaterThan(tower.sales.transaction_count);
    await page.screenshot({ path: `${shots}/project.png`, fullPage: true });

    // Up to the master: its projects' registered units added up.
    await page.getByTestId('analytics-breadcrumb').getByRole('button', { name: 'Business Bay', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Business Bay', level: 2 })).toBeVisible();
    await expect(page.getByText(/of [\d,]+ projects counted/)).toBeVisible();
    await page.screenshot({ path: `${shots}/master.png`, fullPage: true });

    // Back down: a building row opens the building.
    await input.fill('Binghatti Skyrise');
    await page.getByRole('option', { name: /^Binghatti Skyrise Project/ }).click();
    await page.getByTestId('analytics-buildings').getByRole('button', { name: 'Binghatti Skyrise - Tower C' }).click();
    await expect(page.getByRole('heading', { name: 'Binghatti Skyrise - Tower C', level: 2 })).toBeVisible();

    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `${shots}/building-mobile.png`, fullPage: true });
    expect(errors).toEqual([]);
});

// One spelling per project and one master per project: DLD's capitals and DXBI's spelling are
// one search result, and the master a project shows is the one every record of it carries.
test('a project shows one spelling and one master', async ({ page }) => {
    test.setTimeout(120000);
    await page.goto('/analytics');
    const input = page.getByRole('combobox').first();
    await input.fill('merano');
    const listbox = page.getByRole('listbox');
    await expect(listbox.getByRole('option', { name: /^Merano Tower Project/ })).toHaveCount(1);
    await expect(listbox.getByRole('option', { name: /^MERANO TOWER/ })).toHaveCount(0);
    await input.fill('Maple');
    await expect(listbox.getByRole('option', { name: /DUBAI HILLS - MAPLE/ })).toHaveCount(0);
    await expect(listbox.getByRole('option', { name: /^Maple 3 Project · Dubai Hills Estate$/ })).toHaveCount(1);
});
