import { api } from './client';

export interface CheckoutSession {
	checkout_url: string;
	session_id: string;
	organization_id: string;
}

export interface SyncResponse {
	status: string;
	organization_id: string;
	seats: number;
}

export async function createCheckoutSession(
	organizationId: string,
	seats: number,
	priceTier: 'tier1' | 'tier2'
): Promise<CheckoutSession> {
	return api<CheckoutSession>('/api/v1/billing/create-checkout', {
		method: 'POST',
		body: {
			organization_id: organizationId,
			seats,
			price_tier: priceTier
		}
	});
}

export async function syncAfterCheckout(sessionId: string): Promise<SyncResponse> {
	return api<SyncResponse>('/api/v1/billing/sync-after-checkout', {
		method: 'POST',
		body: { session_id: sessionId }
	});
}
