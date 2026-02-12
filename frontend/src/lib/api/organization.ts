import { api } from './client';
import { client } from './auth';

export interface CreateOrganizationRequest {
	name: string;
	max_users: number;
}

export interface CreateOrganizationResponse {
	organization_id: string;
	name: string;
	max_users: number;
	is_new: boolean;
}

export async function createOrganization(
	name: string,
	maxUsers: number
): Promise<CreateOrganizationResponse> {
	return api<CreateOrganizationResponse>('/api/v1/organization/create', {
		method: 'POST',
		body: {
			name,
			max_users: maxUsers
		}
	});
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
	return api<{ success: boolean }>('/api/v1/organization/complete-profile', {
		method: 'POST',
		body: { organization_id: organizationId }
	});
}

export interface ValidateInviteTokenResponse {
	organization_name: string;
	organization_id: string;
	role: string;
	email: string;
	expires_at: string;
	status: string;
}

export interface AcceptInviteResponse {
	success: boolean;
	organization_id: string;
	organization_name: string;
	role: string;
}

export interface InviteConflictResponse {
	conflict: true;
	current_org_id: string;
	current_org_name: string;
	current_role: string;
	member_count: number;
	is_single_seat: boolean;
}

export async function validateInviteToken(
	token: string
): Promise<ValidateInviteTokenResponse> {
	return api<ValidateInviteTokenResponse>(
		`/api/v1/organization/validate-invite-token?token=${token}`
	);
}

export async function acceptInvite(
	token: string
): Promise<AcceptInviteResponse | InviteConflictResponse> {
	return api<AcceptInviteResponse | InviteConflictResponse>(
		'/api/v1/organization/accept-invite',
		{
			method: 'POST',
			body: { token }
		}
	);
}

export interface OrganizationMember {
	id: string;
	email: string;
	first_name: string;
	last_name: string;
	role: string;
	is_active: boolean;
}

export interface Subscription {
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

export async function getOrganizationMembers(): Promise<OrganizationMember[]> {
	return api<OrganizationMember[]>('/api/v1/organization/members');
}

export async function getOrganizationSubscription(): Promise<Subscription> {
	return api<Subscription>('/api/v1/organization/subscription');
}

export async function getCustomerPortalUrl(): Promise<{ url: string }> {
	return api<{ url: string }>('/api/v1/organization/customer-portal');
}

export async function deactivateUser(userId: string): Promise<{ success: boolean }> {
	return api<{ success: boolean }>(`/api/v1/organization/users/${userId}/deactivate`, {
		method: 'POST'
	});
}
