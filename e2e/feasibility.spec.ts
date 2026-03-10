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
	await expect(page.getByRole('heading', { name: 'Select an area' })).toBeVisible({ timeout: 10_000 });
});

test('feasibility page area search input is visible', async ({ page }) => {
	await page.goto('/feasibility');
	await expect(page.getByText('Choose the Dubai area where your project will be located.')).toBeVisible({ timeout: 10_000 });
});

test('feasibility step progress indicator is visible', async ({ page }) => {
	await page.goto('/feasibility');
	// StepProgress renders step labels on steps 1-3
	await expect(page.getByText('Select Area')).toBeVisible({ timeout: 10_000 });
	await expect(page.getByText('Choose Plot')).toBeVisible({ timeout: 10_000 });
});
