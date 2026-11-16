import { client } from './client'
import type {
	AcceptInviteResponse,
	AppOrganizationRouterOrganizationMemberResponse,
	CustomerPortalResponse,
	InviteUserResponse,
	OperationSuccessResponse,
	OrganizationInvitationResponse,
	OwnerOrganizationCreateResponse,
	SubscriptionResponse,
	TeamMemberInput,
	TeamsResponse,
	ValidateInviteTokenResponse
} from './generated/hey-api/types.gen'

export type {
	AcceptInviteResponse,
	AppOrganizationRouterOrganizationMemberResponse,
	CustomerPortalResponse,
	InviteUserResponse,
	OperationSuccessResponse,
	OrganizationInvitationResponse,
	OwnerOrganizationCreateResponse,
	TeamMemberInput,
	TeamsResponse,
	ValidateInviteTokenResponse
}

export async function createOrganization(
	name: string,
	maxUsers: number
): Promise<OwnerOrganizationCreateResponse> {
	return client.post<OwnerOrganizationCreateResponse>('/api/v1/organization/create', {
		name,
		max_users: maxUsers
	})
}

export async function inviteUserByEmail(email: string): Promise<InviteUserResponse> {
	return client.post<InviteUserResponse>('/api/v1/organization/invite-user', { email })
}

export interface InviteConflictResponse {
	conflict: true
	current_org_id: string
	current_org_name: string
	current_role: string
	member_count: number
	is_single_seat: boolean
}

export async function validateInviteToken(token: string): Promise<ValidateInviteTokenResponse> {
	return client.get<ValidateInviteTokenResponse>(
		client.withQuery('/api/v1/organization/validate-invite-token', { token })
	)
}

export async function acceptInvite(
	token: string
): Promise<AcceptInviteResponse | InviteConflictResponse> {
	return client.post<AcceptInviteResponse | InviteConflictResponse>(
		'/api/v1/organization/accept-invite',
		{ token }
	)
}

export async function getOrganizationMembers(): Promise<
	AppOrganizationRouterOrganizationMemberResponse[]
> {
	return client.get<AppOrganizationRouterOrganizationMemberResponse[]>(
		'/api/v1/organization/members'
	)
}

export async function getOrganizationInvitations(): Promise<OrganizationInvitationResponse[]> {
	return client.get<OrganizationInvitationResponse[]>('/api/v1/organization/invitations')
}

export async function deleteOrganizationInvitation(
	invitationId: string
): Promise<OperationSuccessResponse> {
	return client.delete<OperationSuccessResponse>(`/api/v1/organization/invitations/${invitationId}`)
}

export async function getOrganizationSubscription(): Promise<SubscriptionResponse> {
	return client.get<SubscriptionResponse>('/api/v1/organization/subscription')
}

export async function getCustomerPortalUrl(): Promise<CustomerPortalResponse> {
	return client.get<CustomerPortalResponse>('/api/v1/organization/customer-portal')
}

export async function removeOrganizationMember(userId: string): Promise<OperationSuccessResponse> {
	return client.delete<OperationSuccessResponse>(`/api/v1/organization/members/${userId}`)
}

/* ── teams (organization administrators) ── */

export async function getTeams(): Promise<TeamsResponse> {
	return client.get<TeamsResponse>('/api/v1/organization/teams')
}

export async function createTeam(name: string): Promise<TeamsResponse> {
	return client.post<TeamsResponse>('/api/v1/organization/teams', { name })
}

export async function renameTeam(teamId: string, name: string): Promise<TeamsResponse> {
	return client.patch<TeamsResponse>(`/api/v1/organization/teams/${teamId}`, { name })
}

/** The complete membership of a team; anyone left out leaves it. */
export async function setTeamMembers(
	teamId: string,
	members: TeamMemberInput[]
): Promise<TeamsResponse> {
	return client.put<TeamsResponse>(`/api/v1/organization/teams/${teamId}/members`, { members })
}

export async function deleteTeam(teamId: string): Promise<OperationSuccessResponse> {
	return client.delete<OperationSuccessResponse>(`/api/v1/organization/teams/${teamId}`)
}

/** Owners only: make a member an organization administrator, or stop that. */
export async function setOrganizationAdmin(
	userId: string,
	organizationAdmin: boolean
): Promise<OperationSuccessResponse> {
	return client.put<OperationSuccessResponse>(
		`/api/v1/organization/members/${userId}/organization-admin`,
		{ organization_admin: organizationAdmin }
	)
}
