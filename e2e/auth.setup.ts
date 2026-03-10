import { test as setup, expect } from '@playwright/test';
import path from 'path';

const authFile = path.join(__dirname, '.auth/user.json');

/**
 * Runs once before other tests to authenticate and save session state.
 * Requires TEST_EMAIL and TEST_PASSWORD environment variables.
 *
 * Run with:
 *   TEST_EMAIL=you@example.com TEST_PASSWORD=yourpassword bunx playwright test --project=setup
 */
setup('authenticate', async ({ page }) => {
	const email = process.env.TEST_EMAIL;
	const password = process.env.TEST_PASSWORD;

	if (!email || !password) {
		throw new Error('TEST_EMAIL and TEST_PASSWORD environment variables are required for auth setup');
	}

	await page.goto('/auth');
	await expect(page.getByRole('heading', { name: 'Sign in to Vitevue' })).toBeVisible();

	// Fill login form
	await page.getByLabel('Email').fill(email);
	await page.getByLabel('Password').fill(password);
	await page.getByRole('button', { name: 'Sign in', exact: true }).click();

	// Wait for redirect to dashboard
	await page.waitForURL(/\/dashboard/, { timeout: 15_000 });

	// Save auth state (cookies + localStorage)
	await page.context().storageState({ path: authFile });
});
