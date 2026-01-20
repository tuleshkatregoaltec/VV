import { api } from './client';

// Types
export interface OrganizationMember {
	id: string;
	email: string;
	first_name: string;
	last_name: string;
	is_active: boolean;
	role: string;
}

export interface SubscriptionDetails {
	id: string;
	organization_id: string;
	status: string;
	seats: number;
	current_period_end: string;
	cancel_at_period_end: boolean;
	current_members: number;
	available_seats: number;
	excess_users: number;
	within_paid_period: boolean;
}

export interface CustomerPortalResponse {
	url: string;
}

// API Functions
export async function getOrganizationMembers(): Promise<OrganizationMember[]> {
	return api<OrganizationMember[]>('/api/v1/organization/members');
}

export async function deactivateUser(userId: string): Promise<{ success: boolean }> {
	return api<{ success: boolean }>(`/api/v1/organization/deactivate-user/${userId}`, {
		method: 'POST'
	});
}

export async function getOrganizationSubscription(): Promise<SubscriptionDetails> {
	return api<SubscriptionDetails>('/api/v1/organization/subscription');
}

export async function getCustomerPortalUrl(): Promise<CustomerPortalResponse> {
	return api<CustomerPortalResponse>('/api/v1/organization/customer-portal');
}
