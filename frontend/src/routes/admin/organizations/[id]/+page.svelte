<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { admin, type OrgDetail, type OrgUser } from '$lib/api/admin';
	import { ApiError } from '$lib/api/client';
	import Modal from '$lib/components/ui/Modal.svelte';
	import ConfirmModal from '$lib/components/ui/ConfirmModal.svelte';

	let org = $state<OrgDetail | null>(null);
	let loading = $state(true);
	let error = $state('');

	// Settings edit state
	let editMaxUsers = $state(0);
	let editIsActive = $state(false);
	let editSubscription = $state('');
	let saving = $state(false);
	let savingSubscription = $state(false);

	// Delete org
	let confirmDeleteOrg = $state(false);
	let deletingOrg = $state(false);

	// Token limit modal
	let selectedUser = $state<OrgUser | null>(null);
	let showTokenModal = $state(false);
	let editedLimit = $state(0);
	let savingLimit = $state(false);
	let limitError = $state('');

	// Delete user
	let confirmDeleteUser = $state<OrgUser | null>(null);
	let deletingUser = $state(false);

	async function fetchOrg() {
		loading = true;
		error = '';
		try {
			org = await admin.organizations.get(page.params.id);
			editMaxUsers = org.max_users;
			editIsActive = org.is_active;
			editSubscription = org.subscription_status;
		} catch (e) {
			error = e instanceof ApiError ? e.message : 'Failed to load organization';
		} finally {
			loading = false;
		}
	}

	async function saveSettings() {
		if (!org) return;
		saving = true;
		try {
			await admin.organizations.update(org.id, {
				max_users: editMaxUsers,
				is_active: editIsActive
			});
			await fetchOrg();
		} catch (e) {
			error = e instanceof ApiError ? e.message : 'Failed to save';
		} finally {
			saving = false;
		}
	}

	async function saveSubscription() {
		if (!org) return;
		savingSubscription = true;
		try {
			await admin.organizations.setSubscription(org.id, editSubscription);
			await fetchOrg();
		} catch (e) {
			error = e instanceof ApiError ? e.message : 'Failed to update subscription';
		} finally {
			savingSubscription = false;
		}
	}

	async function deleteOrg() {
		if (!org) return;
		deletingOrg = true;
		try {
			await admin.organizations.delete(org.id);
			goto('/admin/organizations');
		} catch (e) {
			error = e instanceof ApiError ? e.message : 'Failed to delete';
			deletingOrg = false;
			confirmDeleteOrg = false;
		}
	}

	function openTokenModal(user: OrgUser) {
		selectedUser = user;
		editedLimit = user.daily_token_limit;
		limitError = '';
		showTokenModal = true;
	}

	async function saveTokenLimit() {
		if (!selectedUser) return;
		savingLimit = true;
		limitError = '';
		try {
			await admin.users.updateTokenLimit(selectedUser.id, editedLimit);
			showTokenModal = false;
			await fetchOrg();
		} catch (e) {
			limitError = e instanceof ApiError ? e.message : 'Failed to update limit';
		} finally {
			savingLimit = false;
		}
	}

	async function deleteUser() {
		if (!confirmDeleteUser) return;
		deletingUser = true;
		try {
			await admin.users.delete(confirmDeleteUser.id);
			confirmDeleteUser = null;
			await fetchOrg();
		} catch (e) {
			alert(e instanceof ApiError ? e.message : 'Failed to delete user');
		} finally {
			deletingUser = false;
		}
	}

	function fullName(u: OrgUser) {
		const name = `${u.first_name || ''} ${u.last_name || ''}`.trim();
		return name || u.email;
	}

	function formatDate(d: string | null) {
		if (!d) return '—';
		return new Date(d).toLocaleDateString(undefined, {
			month: 'short',
			day: 'numeric',
			year: 'numeric'
		});
	}

	function usageColor(pct: number) {
		if (pct >= 90) return 'bg-red-500';
		if (pct >= 70) return 'bg-yellow-500';
		return 'bg-green-500';
	}

	function statusBadge(status: string) {
		switch (status) {
			case 'active':
				return 'bg-green-100 text-green-800';
			case 'trialing':
				return 'bg-blue-100 text-blue-800';
			case 'past_due':
				return 'bg-orange-100 text-orange-800';
			case 'canceled':
				return 'bg-red-100 text-red-800';
			default:
				return 'bg-gray-100 text-gray-600';
		}
	}

	onMount(fetchOrg);
</script>

<div class="max-w-7xl mx-auto px-4 py-6">
	{#if loading}
		<div class="text-center py-16 text-gray-400">Loading...</div>
	{:else if error && !org}
		<div class="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm mb-4">
			{error}
		</div>
		<button
			onclick={() => goto('/admin/organizations')}
			class="text-blue-600 hover:underline text-sm"
		>
			← Back to Organizations
		</button>
	{:else if org}
		<!-- Header -->
		<div class="flex items-start justify-between mb-6">
			<div>
				<button
					onclick={() => goto('/admin/organizations')}
					class="text-sm text-gray-400 hover:text-gray-600 mb-2 flex items-center gap-1"
				>
					← Organizations
				</button>
				<h1 class="text-2xl font-bold text-gray-900">{org.name}</h1>
				<p class="text-sm text-gray-400 mt-0.5">Owner: {org.owner_email}</p>
			</div>
			<button
				onclick={() => (confirmDeleteOrg = true)}
				class="text-sm font-medium text-red-600 hover:text-red-800 border border-red-200 hover:bg-red-50 px-3 py-1.5 rounded-lg transition-colors"
			>
				Delete Org
			</button>
		</div>

		{#if error}
			<div class="bg-red-50 border border-red-200 rounded-lg p-3 text-red-700 text-sm mb-4">
				{error}
			</div>
		{/if}

		<!-- Settings row -->
		<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
			<!-- Org settings -->
			<div class="bg-white border border-gray-200 rounded-xl p-5">
				<h2 class="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-4">Settings</h2>
				<div class="space-y-4">
					<div>
						<label class="block text-xs font-medium text-gray-500 mb-1">Max Users</label>
						<input
							type="number"
							bind:value={editMaxUsers}
							min="1"
							class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
						/>
					</div>
					<label class="flex items-center gap-2 text-sm text-gray-700">
						<input type="checkbox" bind:checked={editIsActive} class="rounded" />
						Organization active
					</label>
					<button
						onclick={saveSettings}
						disabled={saving}
						class="w-full bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium py-2 rounded-lg transition-colors disabled:opacity-50"
					>
						{saving ? 'Saving...' : 'Save Settings'}
					</button>
				</div>
			</div>

			<!-- Subscription -->
			<div class="bg-white border border-gray-200 rounded-xl p-5">
				<h2 class="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-4">
					Subscription
				</h2>
				<div class="space-y-4">
					<div class="flex items-center gap-2">
						<span class="text-xs text-gray-500">Current:</span>
						<span
							class="inline-flex px-2.5 py-0.5 rounded-full text-xs font-semibold {statusBadge(
								org.subscription_status
							)}"
						>
							{org.subscription_status}
						</span>
					</div>
					<div>
						<label class="block text-xs font-medium text-gray-500 mb-1">Set Status</label>
						<select
							bind:value={editSubscription}
							class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
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
						class="w-full bg-gray-800 hover:bg-gray-900 text-white text-sm font-medium py-2 rounded-lg transition-colors disabled:opacity-50"
					>
						{savingSubscription ? 'Updating...' : 'Update Subscription'}
					</button>
				</div>
			</div>
		</div>

		<!-- Users table -->
		<div class="bg-white border border-gray-200 rounded-xl overflow-hidden">
			<div class="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
				<h2 class="text-sm font-semibold text-gray-700 uppercase tracking-wider">
					Members ({org.users.length} / {org.max_users})
				</h2>
			</div>

			{#if org.users.length === 0}
				<div class="px-5 py-12 text-center text-sm text-gray-400">No members yet.</div>
			{:else}
				<table class="min-w-full divide-y divide-gray-100">
					<thead>
						<tr class="bg-gray-50">
							<th
								class="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider"
								>User</th
							>
							<th
								class="px-5 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wider"
								>Role</th
							>
							<th
								class="px-5 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wider"
								>Token Usage</th
							>
							<th
								class="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider"
								>Last Login</th
							>
							<th class="px-5 py-3"></th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-100">
						{#each org.users as user}
							<tr class="hover:bg-gray-50 transition-colors">
								<td class="px-5 py-4">
									<div class="font-medium text-sm text-gray-900">{fullName(user)}</div>
									<div class="text-xs text-gray-400">{user.email}</div>
								</td>
								<td class="px-5 py-4 text-center">
									<span
										class="text-xs font-medium px-2 py-0.5 rounded-full {user.role === 'owner'
											? 'bg-purple-100 text-purple-700'
											: 'bg-gray-100 text-gray-600'}"
									>
										{user.role}
									</span>
								</td>
								<td class="px-5 py-4">
									<div class="flex flex-col items-center gap-1">
										<span class="text-xs text-gray-500">
											{user.tokens_used_today.toLocaleString()} / {user.daily_token_limit.toLocaleString()}
										</span>
										<div class="w-24 bg-gray-200 rounded-full h-1.5 overflow-hidden">
											<div
												class="h-full {usageColor(user.usage_percentage)}"
												style="width: {Math.min(user.usage_percentage, 100)}%"
											></div>
										</div>
									</div>
								</td>
								<td class="px-5 py-4 text-sm text-gray-400">{formatDate(user.last_login)}</td>
								<td class="px-5 py-4">
									<div class="flex items-center justify-end gap-2">
										<button
											onclick={() => openTokenModal(user)}
											class="text-xs font-medium text-blue-600 hover:text-blue-800 px-2.5 py-1 rounded-md hover:bg-blue-50 transition-colors"
										>
											Edit Limit
										</button>
										<button
											onclick={() => (confirmDeleteUser = user)}
											class="text-xs font-medium text-red-500 hover:text-red-700 px-2.5 py-1 rounded-md hover:bg-red-50 transition-colors"
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
				<p class="text-sm font-medium text-gray-800">{fullName(selectedUser)}</p>
				<p class="text-xs text-gray-400">{selectedUser.email}</p>
			</div>
			<div>
				<label class="block text-xs font-medium text-gray-500 mb-1">Daily Token Limit</label>
				<input
					type="number"
					bind:value={editedLimit}
					min="0"
					step="10000"
					class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
				/>
				<p class="text-xs text-gray-400 mt-1">
					Current usage today: {selectedUser.tokens_used_today.toLocaleString()} tokens
				</p>
			</div>
			{#if limitError}
				<p class="text-sm text-red-600">{limitError}</p>
			{/if}
			<div class="flex justify-end gap-3 pt-2">
				<button
					onclick={() => (showTokenModal = false)}
					class="px-4 py-2 text-sm text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
				>
					Cancel
				</button>
				<button
					onclick={saveTokenLimit}
					disabled={savingLimit || editedLimit === selectedUser.daily_token_limit}
					class="px-4 py-2 text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white rounded-lg disabled:opacity-50 transition-colors"
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
