<script lang="ts">
	import Modal from '$lib/components/ui/Modal.svelte';
	import { admin, type OrganizationUser } from '$lib/api/admin';
	import { ApiError } from '$lib/api/client';

	let {
		open = false,
		user,
		onClose,
		onUpdated
	}: {
		open: boolean;
		user: OrganizationUser | null;
		onClose: () => void;
		onUpdated: () => void;
	} = $props();

	let editedLimit = $state(0);
	let saving = $state(false);
	let error = $state('');

	// Sync edited limit when user changes
	$effect(() => {
		if (user) {
			editedLimit = user.daily_token_limit;
		}
	});

	function formatNumber(num: number): string {
		return num.toLocaleString();
	}

	function getUsageColor(percentage: number): string {
		if (percentage >= 90) return 'bg-red-500';
		if (percentage >= 70) return 'bg-yellow-500';
		return 'bg-green-500';
	}

	function getUsageTextColor(percentage: number): string {
		if (percentage >= 90) return 'text-red-700';
		if (percentage >= 70) return 'text-yellow-700';
		return 'text-green-700';
	}

	async function saveLimit() {
		if (!user) return;

		saving = true;
		error = '';

		try {
			await admin.users.updateTokenLimit(user.id, editedLimit);

			// Update local user object
			user.daily_token_limit = editedLimit;

			onUpdated();
			onClose();
		} catch (e) {
			error = e instanceof ApiError ? e.message : 'Failed to update token limit';
		} finally {
			saving = false;
		}
	}

	function fullName(u: OrganizationUser): string {
		const name = `${u.first_name || ''} ${u.last_name || ''}`.trim();
		return name || u.email;
	}
</script>

<Modal {open} {onClose} title="User Token Usage" size="lg">
	{#if user}
		<!-- User Info -->
		<div class="mb-6">
			<h3 class="text-lg font-semibold text-gray-900 mb-2">{fullName(user)}</h3>
			<p class="text-sm text-gray-600">{user.email}</p>
			<span
				class="mt-2 inline-flex px-2 py-1 text-xs font-semibold rounded-full {user.is_active
					? 'bg-green-100 text-green-800'
					: 'bg-gray-100 text-gray-800'}"
			>
				{user.is_active ? 'Active' : 'Inactive'}
			</span>
		</div>

		<!-- Token Usage Stats -->
		<div class="bg-gray-50 rounded-lg p-4 mb-6">
			<h4 class="text-sm font-medium text-gray-700 mb-3">Today's Usage</h4>

			<!-- Progress Bar -->
			<div class="mb-4">
				<div class="flex justify-between text-sm mb-1">
					<span class="font-medium {getUsageTextColor(user.usage_percentage)}">
						{formatNumber(user.tokens_used_today)} / {formatNumber(user.daily_token_limit)} tokens
					</span>
					<span class="font-medium {getUsageTextColor(user.usage_percentage)}">
						{user.usage_percentage.toFixed(1)}%
					</span>
				</div>
				<div class="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
					<div
						class="h-full transition-all duration-300 {getUsageColor(user.usage_percentage)}"
						style="width: {Math.min(user.usage_percentage, 100)}%"
					></div>
				</div>
			</div>

			<!-- Stats Grid -->
			<div class="grid grid-cols-2 gap-4">
				<div>
					<p class="text-xs text-gray-500">Remaining Today</p>
					<p class="text-lg font-semibold text-gray-900">
						{formatNumber(Math.max(0, user.daily_token_limit - user.tokens_used_today))}
					</p>
				</div>
				<div>
					<p class="text-xs text-gray-500">Daily Limit</p>
					<p class="text-lg font-semibold text-gray-900">
						{formatNumber(user.daily_token_limit)}
					</p>
				</div>
			</div>
		</div>

		<!-- Edit Token Limit -->
		<div class="border-t pt-4">
			<h4 class="text-sm font-medium text-gray-700 mb-3">Configure Daily Limit</h4>

			<div class="mb-4">
				<label for="token-limit-input" class="block text-sm font-medium text-gray-700 mb-2">
					Daily Token Limit
				</label>
				<input
					id="token-limit-input"
					type="number"
					bind:value={editedLimit}
					min="0"
					step="1000"
					class="shadow-sm border rounded w-full py-2 px-3 text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
				/>
				<p class="text-xs text-gray-500 mt-1">Set to 0 for unlimited usage (not recommended)</p>
			</div>

			{#if error}
				<div class="mb-4 bg-red-50 border border-red-200 rounded p-3">
					<p class="text-red-600 text-sm">{error}</p>
				</div>
			{/if}

			<div class="flex justify-end gap-3">
				<button
					onclick={onClose}
					disabled={saving}
					class="px-4 py-2 bg-gray-200 hover:bg-gray-300 rounded disabled:opacity-50 transition-colors"
				>
					Cancel
				</button>
				<button
					onclick={saveLimit}
					disabled={saving || editedLimit === user.daily_token_limit}
					class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded disabled:opacity-50 transition-colors"
				>
					{saving ? 'Saving...' : 'Save Changes'}
				</button>
			</div>
		</div>
	{/if}
</Modal>
