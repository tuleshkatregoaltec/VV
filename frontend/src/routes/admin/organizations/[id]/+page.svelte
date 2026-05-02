<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { goto } from '$app/navigation'
import { page } from '$app/state'
import { admin, type OrgUserResponse } from '$lib/api/admin'
import { ApiError } from '$lib/api/client'
import ConfirmModal from '$lib/components/ui/ConfirmModal.svelte'
import Modal from '$lib/components/ui/Modal.svelte'
import { adminKeys, adminQueries } from '$lib/queries/admin'
import { getQueryClient } from '$lib/queries/client'

let error = $state('')
const queryClient = getQueryClient()
let lastSyncedOrg = $state('')

// Settings edit state
let editMaxUsers = $state(0)
let editSubscription = $state('')
let saving = $state(false)
let savingSubscription = $state(false)

// Delete org
let confirmDeleteOrg = $state(false)
let deletingOrg = $state(false)

// Token limit modal
let selectedUser = $state<OrgUserResponse | null>(null)
let showTokenModal = $state(false)
let editedLimit = $state(0)
let savingLimit = $state(false)
let limitError = $state('')

// Delete user
let confirmDeleteUser = $state<OrgUserResponse | null>(null)
let deletingUser = $state(false)

const organizationId = $derived(page.params.id ?? '')

const orgQuery = createQuery(() => adminQueries.organizations.detail(organizationId))

const org = $derived(orgQuery.data ?? null)
const loadError = $derived.by(() => {
	if (!organizationId) return 'Organization ID is missing'
	if (!orgQuery.isError) return ''
	return orgQuery.error instanceof ApiError ? orgQuery.error.message : 'Failed to load organization'
})

$effect(() => {
	if (!org) return

	const syncKey = `${org.id}:${org.max_users}:${org.subscription_status}`
	if (syncKey !== lastSyncedOrg) {
		editMaxUsers = org.max_users
		editSubscription = org.subscription_status
		lastSyncedOrg = syncKey
	}
})

async function refreshOrganization() {
	if (!organizationId) return

	await Promise.all([
		queryClient.invalidateQueries({ queryKey: adminKeys.organization(organizationId) }),
		queryClient.invalidateQueries({ queryKey: adminKeys.organizations() })
	])
}

async function saveSettings() {
	if (!org) return
	error = ''
	saving = true
	try {
		await admin.organizations.update(org.id, {
			max_users: editMaxUsers
		})
		await refreshOrganization()
	} catch (e) {
		error = e instanceof ApiError ? e.message : 'Failed to save'
	} finally {
		saving = false
	}
}

async function saveSubscription() {
	if (!org) return
	error = ''
	savingSubscription = true
	try {
		await admin.organizations.setSubscription(org.id, editSubscription)
		await refreshOrganization()
	} catch (e) {
		error = e instanceof ApiError ? e.message : 'Failed to update subscription'
	} finally {
		savingSubscription = false
	}
}

async function deleteOrg() {
	if (!org) return
	error = ''
	deletingOrg = true
	try {
		await admin.organizations.delete(org.id)
		await queryClient.invalidateQueries({ queryKey: adminKeys.organizations() })
		goto('/admin/organizations')
	} catch (e) {
		error = e instanceof ApiError ? e.message : 'Failed to delete'
		deletingOrg = false
		confirmDeleteOrg = false
	}
}

function openTokenModal(user: OrgUserResponse) {
	selectedUser = user
	editedLimit = user.daily_token_limit
	limitError = ''
	showTokenModal = true
}

async function saveTokenLimit() {
	if (!selectedUser) return
	savingLimit = true
	limitError = ''
	try {
		await admin.users.updateTokenLimit(selectedUser.id, editedLimit)
		showTokenModal = false
		await refreshOrganization()
	} catch (e) {
		limitError = e instanceof ApiError ? e.message : 'Failed to update limit'
	} finally {
		savingLimit = false
	}
}

async function deleteUser() {
	if (!confirmDeleteUser) return
	error = ''
	deletingUser = true
	try {
		await admin.users.delete(confirmDeleteUser.id)
		confirmDeleteUser = null
		await refreshOrganization()
	} catch (e) {
		alert(e instanceof ApiError ? e.message : 'Failed to delete user')
	} finally {
		deletingUser = false
	}
}

function fullName(u: OrgUserResponse) {
	const name = `${u.first_name || ''} ${u.last_name || ''}`.trim()
	return name || u.email
}

function formatDate(d: string | null) {
	if (!d) return '—'
	return new Date(d).toLocaleDateString(undefined, {
		month: 'short',
		day: 'numeric',
		year: 'numeric'
	})
}

function usageColor(pct: number) {
	if (pct >= 90) return 'bg-[var(--color-error)]'
	if (pct >= 70) return 'bg-[var(--color-warning)]'
	return 'bg-[var(--color-success)]'
}

function statusBadge(status: string) {
	switch (status) {
		case 'active':
			return 'bg-[var(--color-success-bg)] text-[var(--color-success)]'
		case 'trialing':
			return 'bg-[var(--color-navy-50)] text-[var(--color-navy-900)]'
		case 'past_due':
			return 'bg-[var(--color-warning-bg)] text-[var(--color-warning)]'
		case 'canceled':
			return 'bg-[var(--color-error-bg)] text-[var(--color-error)]'
		default:
			return 'bg-[var(--color-bone-100)] text-[var(--color-fg-3)]'
	}
}
</script>

<div class="max-w-7xl mx-auto px-4 py-6">
	{#if orgQuery.isPending}
		<div class="py-16 text-center text-[var(--color-fg-4)]">Loading...</div>
	{:else if loadError && !org}
		<div class="mb-4 rounded-lg border border-[rgba(163,36,36,0.2)] bg-[var(--color-error-bg)] p-4 text-sm text-[var(--color-error)]">
			{loadError}
		</div>
		<button
			onclick={() => goto('/admin/organizations')}
			class="text-sm text-[var(--color-navy-700)] hover:underline"
		>
			← Back to Organizations
		</button>
	{:else if org}
		<!-- Header -->
		<div class="flex items-start justify-between mb-6">
			<div>
				<button
					onclick={() => goto('/admin/organizations')}
					class="mb-2 flex items-center gap-1 text-sm text-[var(--color-fg-4)] hover:text-[var(--color-fg-2)]"
				>
					← Organizations
				</button>
				<h1 class="text-2xl font-bold text-[var(--color-fg-1)]">{org.name}</h1>
				<p class="mt-0.5 text-sm text-[var(--color-fg-4)]">Owner: {org.owner_email}</p>
			</div>
			<button
				onclick={() => (confirmDeleteOrg = true)}
				class="rounded-md border border-[rgba(163,36,36,0.2)] px-3 py-1.5 text-sm font-medium text-[var(--color-error)] transition-colors hover:bg-[var(--color-error-bg)]"
			>
				Delete Org
			</button>
		</div>

		{#if error}
			<div class="mb-4 rounded-lg border border-[rgba(163,36,36,0.2)] bg-[var(--color-error-bg)] p-3 text-sm text-[var(--color-error)]">
				{error}
			</div>
		{/if}

		<!-- Settings row -->
		<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
			<!-- Org settings -->
			<div class="rounded-xl border border-[var(--color-border)] bg-white p-5">
				<h2 class="mb-4 text-sm font-semibold uppercase tracking-wider text-[var(--color-fg-3)]">Settings</h2>
				<div class="space-y-4">
					<div>
						<label for="org-max-users" class="mb-1 block text-xs font-medium text-[var(--color-fg-4)]">
							Max Users
						</label>
						<input
							id="org-max-users"
							type="number"
							bind:value={editMaxUsers}
							min="1"
							class="w-full rounded-md border border-[var(--color-border)] px-3 py-2 text-sm text-[var(--color-fg-1)] focus:outline-none focus:ring-2 focus:ring-[rgba(11,27,43,0.12)]"
						/>
					</div>
					<button
						onclick={saveSettings}
						disabled={saving}
						class="w-full rounded-md bg-[var(--color-navy-900)] py-2 text-sm font-medium text-[var(--color-fg-on-navy)] transition-colors hover:bg-[var(--color-navy-800)] disabled:opacity-50"
					>
						{saving ? 'Saving...' : 'Save Settings'}
					</button>
				</div>
			</div>

			<!-- Subscription -->
			<div class="rounded-xl border border-[var(--color-border)] bg-white p-5">
				<h2 class="mb-4 text-sm font-semibold uppercase tracking-wider text-[var(--color-fg-3)]">
					Subscription
				</h2>
				<div class="space-y-4">
					<div class="flex items-center gap-2">
						<span class="text-xs text-[var(--color-fg-4)]">Current:</span>
						<span
							class="inline-flex rounded-sm px-2.5 py-0.5 text-xs font-semibold {statusBadge(
								org.subscription_status
							)}"
						>
							{org.subscription_status}
						</span>
					</div>
					<div>
						<label for="org-subscription-status" class="mb-1 block text-xs font-medium text-[var(--color-fg-4)]">
							Set Status
						</label>
						<select
							id="org-subscription-status"
							bind:value={editSubscription}
							class="w-full rounded-md border border-[var(--color-border)] px-3 py-2 text-sm text-[var(--color-fg-1)] focus:outline-none focus:ring-2 focus:ring-[rgba(11,27,43,0.12)]"
						>
							<option value="active">active</option>
							<option value="trialing">trialing</option>
							<option value="pending">pending</option>
							<option value="past_due">past_due</option>
							<option value="canceled">canceled</option>
							<option value="none">none</option>
						</select>
					</div>
					<button
						onclick={saveSubscription}
						disabled={savingSubscription || editSubscription === org.subscription_status}
						class="w-full rounded-md bg-[var(--color-navy-900)] py-2 text-sm font-medium text-[var(--color-fg-on-navy)] transition-colors hover:bg-[var(--color-navy-800)] disabled:opacity-50"
					>
						{savingSubscription ? 'Updating...' : 'Update Subscription'}
					</button>
				</div>
			</div>
		</div>

		<!-- Users table -->
		<div class="overflow-hidden rounded-xl border border-[var(--color-border)] bg-white">
			<div class="flex items-center justify-between border-b border-[var(--color-border)] px-5 py-4">
				<h2 class="text-sm font-semibold uppercase tracking-wider text-[var(--color-fg-3)]">
					Members ({org.users.length} / {org.max_users})
				</h2>
			</div>

			{#if org.users.length === 0}
				<div class="px-5 py-12 text-center text-sm text-[var(--color-fg-4)]">No members yet.</div>
			{:else}
				<table class="min-w-full divide-y divide-[var(--color-border)]">
					<thead>
						<tr class="bg-slate-50">
							<th
								class="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--color-fg-4)]"
								>User</th
							>
							<th
								class="px-5 py-3 text-center text-xs font-semibold uppercase tracking-wider text-[var(--color-fg-4)]"
								>Role</th
							>
							<th
								class="px-5 py-3 text-center text-xs font-semibold uppercase tracking-wider text-[var(--color-fg-4)]"
								>Token Usage</th
							>
							<th
								class="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--color-fg-4)]"
								>Last Login</th
							>
							<th class="px-5 py-3"></th>
						</tr>
					</thead>
					<tbody class="divide-y divide-[var(--color-border)]">
						{#each org.users as user (user.id)}
							<tr class="transition-colors hover:bg-slate-50">
								<td class="px-5 py-4">
									<div class="text-sm font-medium text-[var(--color-fg-1)]">{fullName(user)}</div>
									<div class="text-xs text-[var(--color-fg-4)]">{user.email}</div>
								</td>
								<td class="px-5 py-4 text-center">
									<span
										class="rounded-sm px-2 py-0.5 text-xs font-medium {user.role === 'owner'
											? 'bg-[var(--color-navy-50)] text-[var(--color-navy-900)]'
											: 'bg-[var(--color-bone-100)] text-[var(--color-fg-3)]'}"
									>
										{user.role}
									</span>
								</td>
								<td class="px-5 py-4">
									<div class="flex flex-col items-center gap-1">
										<span class="text-xs text-[var(--color-fg-4)]">
											{user.tokens_used_today.toLocaleString()} / {user.daily_token_limit.toLocaleString()}
										</span>
										<div class="h-1.5 w-24 overflow-hidden rounded-full bg-slate-200">
											<div
												class="h-full {usageColor(user.usage_percentage)}"
												style="width: {Math.min(user.usage_percentage, 100)}%"
											></div>
										</div>
									</div>
								</td>
								<td class="px-5 py-4 text-sm text-[var(--color-fg-4)]">{formatDate(user.last_login)}</td>
								<td class="px-5 py-4">
									<div class="flex items-center justify-end gap-2">
										<button
											onclick={() => openTokenModal(user)}
											class="rounded-md px-2.5 py-1 text-xs font-medium text-[var(--color-navy-700)] transition-colors hover:bg-[var(--color-navy-50)] hover:text-[var(--color-navy-900)]"
										>
											Edit Limit
										</button>
										<button
											onclick={() => (confirmDeleteUser = user)}
											class="rounded-md px-2.5 py-1 text-xs font-medium text-[var(--color-error)] transition-colors hover:bg-[var(--color-error-bg)] hover:opacity-90"
										>
											Delete
										</button>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</div>
	{/if}
</div>

<!-- Token limit modal -->
<Modal
	open={showTokenModal}
	onClose={() => (showTokenModal = false)}
	title="Edit Token Limit"
	size="md"
>
	{#if selectedUser}
		<div class="space-y-4">
			<div>
				<p class="text-sm font-medium text-[var(--color-fg-1)]">{fullName(selectedUser)}</p>
				<p class="text-xs text-[var(--color-fg-4)]">{selectedUser.email}</p>
			</div>
			<div>
				<label for="daily-token-limit" class="mb-1 block text-xs font-medium text-[var(--color-fg-4)]">
					Daily Token Limit
				</label>
				<input
					id="daily-token-limit"
					type="number"
					bind:value={editedLimit}
					min="0"
					step="10000"
					class="w-full rounded-md border border-[var(--color-border)] px-3 py-2 text-sm text-[var(--color-fg-1)] focus:outline-none focus:ring-2 focus:ring-[rgba(11,27,43,0.12)]"
				/>
				<p class="mt-1 text-xs text-[var(--color-fg-4)]">
					Current usage today: {selectedUser.tokens_used_today.toLocaleString()} tokens
				</p>
			</div>
			{#if limitError}
				<p class="text-sm text-[var(--color-error)]">{limitError}</p>
			{/if}
			<div class="flex justify-end gap-3 pt-2">
				<button
					onclick={() => (showTokenModal = false)}
					class="rounded-md border border-[var(--color-border)] px-4 py-2 text-sm text-[var(--color-fg-2)] transition-colors hover:bg-slate-50"
				>
					Cancel
				</button>
				<button
					onclick={saveTokenLimit}
					disabled={savingLimit || editedLimit === selectedUser.daily_token_limit}
					class="rounded-md bg-[var(--color-navy-900)] px-4 py-2 text-sm font-medium text-[var(--color-fg-on-navy)] transition-colors hover:bg-[var(--color-navy-800)] disabled:opacity-50"
				>
					{savingLimit ? 'Saving...' : 'Save'}
				</button>
			</div>
		</div>
	{/if}
</Modal>

<ConfirmModal
	open={confirmDeleteUser !== null}
	title="Delete User"
	message={`Delete ${confirmDeleteUser?.email}? This removes them from Supabase and this organization.`}
	confirmText={deletingUser ? 'Deleting...' : 'Delete User'}
	confirmVariant="danger"
	onConfirm={deleteUser}
	onCancel={() => (confirmDeleteUser = null)}
/>

<ConfirmModal
	open={confirmDeleteOrg}
	title="Delete Organization"
	message={`Delete '${org?.name}'? This removes the organization. Users will lose access immediately.`}
	confirmText={deletingOrg ? 'Deleting...' : 'Delete Organization'}
	confirmVariant="danger"
	onConfirm={deleteOrg}
	onCancel={() => (confirmDeleteOrg = false)}
/>
