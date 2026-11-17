import { test as base } from '@playwright/test';

import { personas, type TestPersona } from './personas';

type GuardFixtures = {
	usePersona: (persona: TestPersona) => Promise<void>;
	useAnonymous: () => Promise<void>;
};

function makeSession(user: { id: string; email: string }) {
	const { email } = user;
	const now = Math.floor(Date.now() / 1000);

	return {
		access_token: `mock-access-token-${email}`,
		token_type: 'bearer',
		expires_in: 3600,
		expires_at: now + 3600,
		refresh_token: `mock-refresh-token-${email}`,
		user: {
			id: user.id,
			aud: '',
			role: 'user',
			email,
			email_confirmed_at: new Date().toISOString(),
			phone: '',
			confirmed_at: new Date().toISOString(),
			last_sign_in_at: new Date().toISOString(),
			app_metadata: {
				provider: 'email',
				providers: ['email']
			},
			user_metadata: {
				email,
				email_verified: true
			},
			identities: [],
			created_at: new Date().toISOString(),
			updated_at: new Date().toISOString(),
			is_anonymous: false
		}
	};
}

export const test = base.extend<GuardFixtures>({
	usePersona: async ({ page }, use) => {
		await use(async (persona: TestPersona) => {
			const user = personas[persona];
			const session = makeSession(user);

			// Redirect guards can land on the dashboard. Its background reads must remain
			// synthetic too: a fake session must never reach the real API and trigger a 401 loop.
			await page.route('**/api/v1/**', async route => {
				const path = new URL(route.request().url()).pathname;
				if (path === '/api/v1/analytics/market-trend') return route.fulfill({ json: { data: [], total_transactions: 0 } });
				if (path === '/api/v1/analytics/project/pipeline') return route.fulfill({ json: { projects: [], total: 0 } });
				if (path === '/api/v1/transactions/sales') return route.fulfill({ json: { transactions: [], total: 0 } });
				if (path === '/api/v1/supply/upcoming-projects') return route.fulfill({ json: { projects: [], total: 0 } });
				if (path === '/api/v1/news/articles') return route.fulfill({ json: { articles: [], total: 0 } });
				if (path === '/api/v1/news/summary') return route.fulfill({ json: { article_count: 0, macro: { title: 'Market conditions', bullets: [] }, real_estate: { title: 'Property news', bullets: [] } } });
				return route.abort('failed');
			});
			await page.route('**/api/v1/auth/me', async (route) => {
				await route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify(user)
				});
			});

			await page.addInitScript(
				({ authSession }) => {
					window.localStorage.setItem('authentication', JSON.stringify(authSession));
				},
				{ authSession: session }
			);
		});
	},
	useAnonymous: async ({ page }, use) => {
		await use(async () => {
			await page.addInitScript(() => {
				window.localStorage.removeItem('authentication');
			});
		});
	},
});

export { expect } from '@playwright/test';
