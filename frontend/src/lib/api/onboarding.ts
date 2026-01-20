import { api } from './client';
import { client } from './auth';

// Types
export interface CheckoutSession {
	checkout_url: string;
	session_id: string;
}

export interface PaymentStatus {
	status: 'pending' | 'completed' | 'failed';
	organization_id: string | null;
}

export interface SyncUserResponse {
	success: boolean;
	organization_id: string;
	is_active: boolean;
	role: string;
}

export interface PaymentSyncResponse {
	payment_completed: boolean;
	organization_id: string | null;
	organization_status: string | null;
	message: string;
}

// API Functions
export async function createCheckoutSession(
	organizationName: string,
	seats: number
): Promise<CheckoutSession> {
	return api<CheckoutSession>('/api/v1/onboarding/checkout', {
		method: 'POST',
		body: { organization_name: organizationName, seats }
	});
}

export async function checkPaymentStatus(sessionId: string): Promise<PaymentStatus> {
	return api<PaymentStatus>(`/api/v1/onboarding/check-payment-status/${sessionId}`);
}

export async function inviteUserByEmail(
	email: string,
	organizationId: string,
	redirectUrl: string
): Promise<{ success: boolean; error?: string }> {
	try {
		return api<{ success: boolean; error?: string }>('/api/v1/organization/invite-user', {
			method: 'POST',
			body: { email, organization_id: organizationId, redirect_url: redirectUrl }
		});
	} catch (error) {
		return { success: false, error: (error as Error).message };
	}
}

export async function completeProfile(organizationId: string): Promise<{ success: boolean }> {
	return api<{ success: boolean }>('/api/v1/onboarding/complete-profile', {
		method: 'POST',
		body: { organization_id: organizationId }
	});
}

export async function completeProfileSetup(
	firstName: string,
	lastName: string,
	password: string | null,
	organizationId: string
): Promise<{ success: boolean }> {
	// Update user metadata via Supabase client
	const { error: metadataError } = await client.updateUser({
		data: {
			first_name: firstName,
			last_name: lastName
		}
	});

	if (metadataError) throw metadataError;

	// Set password if provided
	if (password) {
		const { error: passwordError } = await client.updateUser({
			password: password
		});
		if (passwordError) throw passwordError;
	}

	// Add user to organization in backend (adds to org.users array)
	await completeProfile(organizationId);

	// Sync user's organization membership and app_metadata
	await syncUserAuth();

	return { success: true };
}

export async function syncUserAuth(): Promise<SyncUserResponse> {
	return api<SyncUserResponse>('/api/v1/auth/sync');
}

export async function syncPaymentStatus(sessionId: string): Promise<PaymentSyncResponse> {
	return api<PaymentSyncResponse>(`/api/v1/stripe/sync?session_id=${sessionId}`);
}
