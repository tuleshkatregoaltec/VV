import { expect, test } from '@playwright/test';

import {
	DEFAULT_PASSWORD,
	extractOtp,
	loginViaUi,
	seedBrowserSession,
	signupUser,
	uniqueEmail,
	verifyOtp,
	waitForMailboxMessage
} from '../fixtures/real-auth';

test('user can reset password from the emailed recovery link and sign in with the new password', async ({
	page,
	request
}) => {
	const email = uniqueEmail('reset');
	const newPassword = 'NewPassword123!';

	await signupUser(request, {
		email,
		password: DEFAULT_PASSWORD,
		firstName: 'Reset',
		lastName: 'User'
	});

	await page.goto('/auth');
	await page.getByRole('button', { name: 'Need a password reset?' }).click();
	await page.getByLabel('Email').fill(email);
	await page.getByRole('button', { name: 'Send reset email' }).click();
	await expect(page.getByRole('heading', { name: 'Check your inbox' })).toBeVisible();

	const message = await waitForMailboxMessage(request, email, 'Reset Your Password');
	const recoverySession = await verifyOtp(request, email, extractOtp(message), 'recovery');

	await seedBrowserSession(page, recoverySession);
	await page.goto('/auth/reset-password');
	await expect(page.getByRole('heading', { name: 'Create a new password' })).toBeVisible();
	await page.getByLabel('New password').fill(newPassword);
	await page.getByLabel('Confirm password').fill(newPassword);
	await page.getByRole('button', { name: 'Update password' }).click();

	await expect(page.getByText('Password updated successfully')).toBeVisible();
	await expect(page).toHaveURL(/\/setup$/, { timeout: 10_000 });

	await page.context().clearCookies();
	await page.goto('/');
	await page.evaluate(() => window.localStorage.clear());
	await page.goto('/auth');
	await page.getByLabel('Email').fill(email);
	await page.getByLabel('Password').fill(DEFAULT_PASSWORD);
	await page.getByRole('button', { name: 'Sign in', exact: true }).click();
	await expect(page.getByText('Invalid email or password')).toBeVisible();

	await loginViaUi(page, email, newPassword);
	await expect(page).toHaveURL(/\/setup|\/dashboard/);
});
