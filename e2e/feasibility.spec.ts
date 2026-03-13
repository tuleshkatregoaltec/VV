import { test, expect } from '@playwright/test';

/**
 * Tests for the feasibility wizard. Runs with authenticated session.
 */

test('feasibility page loads without redirecting', async ({ page }) => {
	await page.goto('/feasibility');
	await expect(page).not.toHaveURL(/\/auth/);
});

test('feasibility page shows the area selection step on load', async ({ page }) => {
	await page.goto('/feasibility');
	await expect(page.getByRole('heading', { name: 'Select a plot' })).toBeVisible({
		timeout: 10_000
	});
});

test('feasibility page area search input is visible', async ({ page }) => {
	await page.goto('/feasibility');
	await expect(page.getByPlaceholder('Filter areas...')).toBeVisible({ timeout: 10_000 });
});

test('feasibility step progress indicator is visible', async ({ page }) => {
	await page.goto('/feasibility');
	await expect(page.getByRole('button', { name: /1 Select Plot/ })).toBeVisible({
		timeout: 10_000
	});
	await expect(page.getByRole('button', { name: /2 Plot & HBU/ })).toBeVisible({
		timeout: 10_000
	});
});
