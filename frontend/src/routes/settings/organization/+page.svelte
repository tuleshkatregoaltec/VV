<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import {
	deleteOrganizationInvitation,
	getCustomerPortalUrl,
	inviteUserByEmail,
	removeOrganizationMember
} from '$lib/api/organization'
import { getQueryClient } from '$lib/queries/client'
import { organizationKeys, organizationQueries } from '$lib/queries/organization'
import { currentUser as userStore } from '$lib/stores/user.svelte'

let currentUser = $derived(userStore.data)
let isOwner = $derived(currentUser?.is_owner === true)
const queryClient = getQueryClient()

let showInviteModal = $state(false)
let inviteEmail = $state('')
let inviteLoading = $state(false)
let inviteError = $state('')
let inviteSuccess = $state(false)
let resendingEmail = $state('')
let cancelingInvitationId = $state('')

const membersQuery = createQuery(() => organizationQueries.members(isOwner))

const subscriptionQuery = createQuery(() => organizationQueries.subscription(isOwner))

const invitationsQuery = createQuery(() => organizationQueries.invitations(isOwner))

const members = $derived(membersQuery.data ?? [])
const invitations = $derived(invitationsQuery.data ?? [])
const subscription = $derived(subscriptionQuery.data)
const availableSeats = $derived(subscription?.available_seats ?? 0)
const hasExcessUsers = $derived((subscription?.excess_users ?? 0) > 0)
const withinPaidPeriod = $derived(subscription?.within_paid_period ?? false)

function normalizeInviteEmail(email: string): string {
	return email.trim().toLowerCase()
}

function validateInviteEmail(email: string): string | null {
	if (!email) return 'Email is required'
	if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return 'Invalid email format'
	return null
}

async function sendInvite(email: string): Promise<void> {
	await inviteUserByEmail(email)
}

async function invalidateOrganizationQueries(keys: ReadonlyArray<readonly unknown[]>) {
	await Promise.all(keys.map((queryKey) => queryClient.invalidateQueries({ queryKey })))
}

async function handleManageSubscription() {
	try {
		const result = await getCustomerPortalUrl()
		window.location.href = result.url
	} catch (err: any) {
		alert(err.message || 'Failed to open subscription management')
	}
}

async function handleRemoveMember(userId: string, userName: string) {
	if (!confirm(`Remove ${userName} from this organization?`)) return
	try {
		await removeOrganizationMember(userId)
		await invalidateOrganizationQueries([
			organizationKeys.members(),
			organizationKeys.subscription()
		])
	} catch (err: any) {
		alert(err.message || 'Failed to remove member')
	}
}

async function handleResendInvitation(email: string) {
	resendingEmail = email
	try {
		await sendInvite(email)
		await invalidateOrganizationQueries([
			organizationKeys.invitations(),
			organizationKeys.subscription()
		])
		alert(`Invitation resent to ${email}`)
	} catch (err: any) {
		alert(err.message || 'Failed to resend invitation')
	} finally {
		resendingEmail = ''
	}
}

async function handleCancelInvitation(invitationId: string, email: string) {
	if (!confirm(`Cancel the pending invitation for ${email}?`)) return
	cancelingInvitationId = invitationId
	try {
		await deleteOrganizationInvitation(invitationId)
		await invalidateOrganizationQueries([
			organizationKeys.invitations(),
			organizationKeys.subscription()
		])
	} catch (err: any) {
		alert(err.message || 'Failed to cancel invitation')
	} finally {
		cancelingInvitationId = ''
	}
}

async function handleInviteUser() {
	inviteError = ''
	inviteSuccess = false
	const email = normalizeInviteEmail(inviteEmail)

	const validationError = validateInviteEmail(email)
	if (validationError) {
		inviteError = validationError
		return
	}

	if (subscription && availableSeats <= 0) {
		inviteError = 'No available seats. Please upgrade your subscription first.'
		return
	}

	inviteLoading = true

	try {
		await sendInvite(email)
		await invalidateOrganizationQueries([
			organizationKeys.invitations(),
			organizationKeys.subscription()
		])
		inviteSuccess = true
		inviteEmail = ''
		setTimeout(() => {
			showInviteModal = false
			inviteSuccess = false
		}, 2000)
	} catch (err: any) {
		inviteError = err.message || 'Failed to send invitation'
	} finally {
		inviteLoading = false
	}
}

function formatDate(dateString: string): string {
	return new Date(dateString).toLocaleDateString('en-US', {
		year: 'numeric',
		month: 'long',
		day: 'numeric'
	})
}

function roleLabel(role: string): string {
	return role === 'owner' ? 'Owner' : 'Member'
}
</script>

<svelte:head>
	<title>Organization Settings - Vitevue</title>
</svelte:head>

<div class="bg-slate-50 p-6 min-h-full">
	<div class="max-w-2xl mx-auto">
		<!-- Header -->
		<div class="mb-8">
			<h1 class="text-3xl font-semibold text-[var(--color-fg-1)] mb-2">Organization Settings</h1>
			<p class="text-[var(--color-fg-3)]">Manage your organization members and subscription</p>
		</div>

		{#if !isOwner}
			<div class="bg-white rounded-lg shadow p-8 text-center">
				<svg
					class="w-16 h-16 text-slate-300 mx-auto mb-4"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
					></path>
				</svg>
				<h2 class="text-xl font-semibold text-slate-900 mb-2">Access Restricted</h2>
				<p class="text-slate-600">Only the organization owner can access these settings.</p>
			</div>
		{:else}
			<!-- Subscription Info -->
			<div class="bg-white rounded-lg shadow mb-6">
				<div class="p-6 border-b border-slate-200">
					<h2 class="text-xl font-semibold text-slate-900">Subscription</h2>
				</div>
				<div class="p-6">
					{#if subscriptionQuery.isLoading}
						<div class="animate-pulse space-y-3">
							<div class="h-4 bg-slate-200 rounded w-1/3"></div>
							<div class="h-4 bg-slate-200 rounded w-1/2"></div>
						</div>
					{:else if subscription}
						<div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
							<div>
								<p class="text-sm text-slate-600 mb-1">Status</p>
								<p class="text-lg font-semibold text-slate-900 capitalize">{subscription.status}</p>
							</div>
							<div>
								<p class="text-sm text-slate-600 mb-1">Seats Used</p>
								<p class="text-lg font-semibold text-slate-900">
									{subscription.current_members} / {subscription.seats} used
								</p>
							</div>
							<div>
								<p class="text-sm text-slate-600 mb-1">Billing Period Ends</p>
								<p class="text-lg font-semibold text-slate-900">
									{formatDate(subscription.current_period_end)}
								</p>
							</div>
						</div>

						{#if hasExcessUsers && withinPaidPeriod}
							<div class="mb-6 rounded-lg border border-[rgba(165,90,19,0.2)] bg-[var(--color-warning-bg)] p-4">
								<div class="flex items-start gap-3">
									<svg
										class="mt-0.5 h-5 w-5 flex-shrink-0 text-[var(--color-warning)]"
										fill="none"
										stroke="currentColor"
										viewBox="0 0 24 24"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
										></path>
									</svg>
									<div>
										<p class="mb-1 font-medium text-[var(--color-warning)]">
											Action Required After Billing Period
										</p>
										<p class="mb-2 text-sm text-[var(--color-warning)]">
											You have {subscription?.excess_users} too many users for your subscription ({subscription?.current_members}
											users, {subscription?.seats} seats).
										</p>
										<p class="text-sm text-[var(--color-warning)]">
											All users will remain active until {new Date(
												subscription?.current_period_end || ''
											).toLocaleDateString()}. After this date, you must either remove {subscription?.excess_users}
											{subscription?.excess_users === 1 ? 'member' : 'members'} or upgrade your subscription.
										</p>
									</div>
								</div>
							</div>
						{:else if hasExcessUsers && !withinPaidPeriod}
							<div class="mb-6 rounded-lg border border-[rgba(163,36,36,0.2)] bg-[var(--color-error-bg)] p-4">
								<div class="flex items-start gap-3">
									<svg
										class="mt-0.5 h-5 w-5 flex-shrink-0 text-[var(--color-error)]"
										fill="none"
										stroke="currentColor"
										viewBox="0 0 24 24"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
										></path>
									</svg>
									<div>
										<p class="mb-1 font-medium text-[var(--color-error)]">Immediate Action Required</p>
										<p class="mb-2 text-sm text-[var(--color-error)]">
											You have {subscription?.excess_users} too many users ({subscription?.current_members}
											users, {subscription?.seats} seats). Your billing period has ended.
										</p>
										<p class="text-sm text-[var(--color-error)]">
											Please remove {subscription?.excess_users}
											{subscription?.excess_users === 1 ? 'member' : 'members'} immediately or upgrade
											your subscription to prevent service disruption.
										</p>
									</div>
								</div>
							</div>
						{:else if availableSeats > 0}
							<div class="mb-6 rounded-lg border border-[rgba(17,122,72,0.2)] bg-[var(--color-success-bg)] p-4">
								<div class="flex items-center gap-3">
									<svg
										class="h-5 w-5 text-[var(--color-success)]"
										fill="none"
										stroke="currentColor"
										viewBox="0 0 24 24"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d="M5 13l4 4L19 7"
										></path>
									</svg>
									<p class="text-sm text-[var(--color-success)]">
										You have {availableSeats} available {availableSeats === 1 ? 'seat' : 'seats'}.
										Invite new members!
									</p>
								</div>
							</div>
						{/if}

						<button
							onclick={handleManageSubscription}
							class="px-6 py-2 bg-slate-900 text-white font-semibold rounded-lg hover:bg-slate-800 transition-colors"
						>
							Manage Subscription
						</button>
					{:else}
						<p class="text-slate-600">No subscription information available</p>
					{/if}
				</div>
			</div>

			<!-- Team Members -->
			<div class="bg-white rounded-lg shadow">
				<div class="p-6 border-b border-slate-200 flex items-center justify-between">
					<h2 class="text-xl font-semibold text-slate-900">Team Members</h2>
					<button
						onclick={() => (showInviteModal = true)}
						disabled={subscription !== undefined && availableSeats <= 0}
						class="px-4 py-2 bg-slate-900 text-white font-semibold rounded-lg hover:bg-slate-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
					>
						Invite Member
					</button>
				</div>
				<div class="p-6">
					{#if membersQuery.isLoading}
						<div class="animate-pulse space-y-4">
							{#each [1, 2, 3] as skeleton (skeleton)}
								<div class="h-16 bg-slate-200 rounded"></div>
							{/each}
						</div>
					{:else if members.length > 0}
						<div class="space-y-3">
							{#each members as member (member.id)}
								<div
									class="flex items-center justify-between p-4 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
								>
									<div class="flex items-center gap-4">
										<div
											class="w-10 h-10 rounded-full bg-slate-200 flex items-center justify-center"
										>
											<span class="text-slate-700 font-semibold">
												{member.first_name?.[0]}{member.last_name?.[0]}
											</span>
										</div>
										<div>
											<p class="font-medium text-slate-900">
												{member.first_name}
												{member.last_name}
											</p>
											<p class="text-sm text-slate-600">{member.email}</p>
										</div>
									</div>
									<div class="flex items-center gap-3">
										<span
											class="rounded-sm border border-[rgba(17,122,72,0.2)] bg-[var(--color-success-bg)] px-3 py-1 text-xs font-semibold text-[var(--color-success)]"
										>
											Active
										</span>
										<span
											class="rounded-sm border border-[var(--color-border)] bg-slate-100 px-3 py-1 text-xs font-semibold capitalize text-[var(--color-fg-3)]"
										>
											{roleLabel(member.role)}
										</span>
										{#if member.id !== currentUser?.id && member.role !== 'owner'}
											<button
												onclick={() =>
													handleRemoveMember(member.id, `${member.first_name} ${member.last_name}`)}
												class="{hasExcessUsers && !withinPaidPeriod
													? 'bg-[var(--color-error-bg)] text-[var(--color-error)] hover:opacity-90'
													: 'text-[var(--color-error)] hover:opacity-80'} rounded-md px-3 py-1 text-sm font-medium transition-colors"
											>
												Remove
											</button>
										{/if}
									</div>
								</div>
							{/each}
						</div>
					{:else}
						<p class="text-slate-600 text-center py-8">No team members found</p>
					{/if}
				</div>
			</div>

			<!-- Pending Invitations -->
			<div class="bg-white rounded-lg shadow mt-6">
				<div class="p-6 border-b border-slate-200">
					<h2 class="text-xl font-semibold text-slate-900">Pending Invitations</h2>
				</div>
				<div class="p-6">
					{#if invitationsQuery.isLoading}
						<div class="animate-pulse space-y-4">
							{#each [1, 2] as skeleton (skeleton)}
								<div class="h-16 bg-slate-200 rounded"></div>
							{/each}
						</div>
					{:else if invitations.length > 0}
						<div class="space-y-3">
							{#each invitations as invitation (invitation.id)}
								<div
									class="flex items-center justify-between p-4 border border-slate-200 rounded-lg"
								>
									<div>
										<p class="font-medium text-slate-900">{invitation.email}</p>
										<p class="text-sm text-slate-600">
											Expires {formatDate(invitation.expires_at)}
										</p>
									</div>
									<div class="flex items-center gap-3">
										<span
											class="rounded-sm border border-[rgba(165,90,19,0.2)] bg-[var(--color-warning-bg)] px-3 py-1 text-xs font-semibold text-[var(--color-warning)]"
										>
											Pending
										</span>
										<button
											onclick={() => handleResendInvitation(invitation.email)}
											disabled={resendingEmail === invitation.email ||
												cancelingInvitationId === invitation.id}
											class="text-sm font-medium text-[var(--color-navy-700)] hover:text-[var(--color-navy-900)] disabled:cursor-not-allowed disabled:opacity-50"
										>
											{resendingEmail === invitation.email ? 'Sending...' : 'Resend Invite'}
										</button>
										<button
											onclick={() => handleCancelInvitation(invitation.id, invitation.email)}
											disabled={cancelingInvitationId === invitation.id ||
												resendingEmail === invitation.email}
											class="text-sm font-medium text-[var(--color-error)] hover:opacity-80 disabled:cursor-not-allowed disabled:opacity-50"
										>
											{cancelingInvitationId === invitation.id ? 'Canceling...' : 'Cancel Invite'}
										</button>
									</div>
								</div>
							{/each}
						</div>
					{:else}
						<p class="text-slate-600 text-center py-8">No pending invitations</p>
					{/if}
				</div>
			</div>
		{/if}
	</div>
</div>

<!-- Invite Modal -->
{#if showInviteModal}
	<div
		class="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50"
		role="presentation"
		onkeydown={(e) => e.key === 'Escape' && (showInviteModal = false)}
		onclick={() => (showInviteModal = false)}
	>
		<div
			class="bg-white rounded-lg shadow-xl max-w-md w-full p-6"
			role="dialog"
			aria-modal="true"
			tabindex="-1"
			onkeydown={(e) => e.key === 'Escape' && (showInviteModal = false)}
			onclick={(e) => e.stopPropagation()}
		>
			<div class="flex items-center justify-between mb-4">
				<h3 class="text-xl font-semibold text-slate-900">Invite Team Member</h3>
				<button
					onclick={() => (showInviteModal = false)}
					aria-label="Close invite modal"
					class="text-slate-400 hover:text-slate-600"
				>
					<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M6 18L18 6M6 6l12 12"
						></path>
					</svg>
				</button>
			</div>

			{#if inviteSuccess}
				<div class="mb-4 rounded-lg border border-[rgba(17,122,72,0.2)] bg-[var(--color-success-bg)] p-4">
					<p class="text-sm text-[var(--color-success)]">Invitation sent successfully!</p>
				</div>
			{/if}

			{#if inviteError}
				<div class="mb-4 rounded-lg border border-[rgba(163,36,36,0.2)] bg-[var(--color-error-bg)] p-4">
					<p class="text-sm text-[var(--color-error)]">{inviteError}</p>
				</div>
			{/if}

			<form
				onsubmit={(e) => {
					e.preventDefault();
					handleInviteUser();
				}}
			>
				<div class="mb-4">
					<label for="inviteEmail" class="block text-sm font-medium text-slate-700 mb-2">
						Email Address
					</label>
					<input
						id="inviteEmail"
						type="email"
						bind:value={inviteEmail}
						placeholder="colleague@company.com"
						class="w-full px-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-slate-900 focus:border-transparent"
						required
					/>
				</div>

				<div class="flex gap-3">
					<button
						type="submit"
						disabled={inviteLoading}
						class="flex-1 bg-slate-900 hover:bg-slate-800 text-white font-semibold rounded-lg px-4 py-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
					>
						{inviteLoading ? 'Sending...' : 'Send Invitation'}
					</button>
					<button
						type="button"
						onclick={() => (showInviteModal = false)}
						class="px-4 py-2 border border-slate-300 text-slate-700 font-semibold rounded-lg hover:bg-slate-50 transition-colors"
					>
						Cancel
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}
