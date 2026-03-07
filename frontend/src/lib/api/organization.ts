import { api } from './client';

export interface InviteUserResponse {
	success: boolean;
	invitation_token: string;
}

export interface CustomerPortalUrlResponse {
	url: string;
}

export interface OperationSuccessResponse {
	success: boolean;
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
	email: string
): Promise<InviteUserResponse> {
	return api<InviteUserResponse>('/api/v1/organization/invite-user', {
		method: 'POST',
		body: { email }
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
}

export interface OrganizationInvitation {
	id: string;
	email: string;
	role: string;
	status: string;
	expires_at: string;
	created_at: string;
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

export async function getOrganizationInvitations(): Promise<OrganizationInvitation[]> {
	return api<OrganizationInvitation[]>('/api/v1/organization/invitations');
}

export async function getOrganizationSubscription(): Promise<Subscription> {
	return api<Subscription>('/api/v1/organization/subscription');
}

export async function getCustomerPortalUrl(): Promise<CustomerPortalUrlResponse> {
	return api<CustomerPortalUrlResponse>('/api/v1/organization/customer-portal');
}

export async function removeOrganizationMember(userId: string): Promise<OperationSuccessResponse> {
	return api<OperationSuccessResponse>(`/api/v1/organization/members/${userId}`, {
		method: 'DELETE'
	});
}
