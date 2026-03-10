<script lang="ts">
	import { goto } from '$app/navigation';
	import { logout } from '$lib/api/auth';
	import { getCustomerPortalUrl } from '$lib/api/organization';
	import { currentUser } from '$lib/stores/user.svelte';

	// Layout ensures user is authenticated with profile + org before this page loads
	// and that subscription is NOT active (otherwise redirects to dashboard)
	let user = $derived(currentUser.data);
	let processingRenewal = $state(false);
	let error = $state('');

	function getStatusMessage() {
		if (!user) return 'Loading...';

		const status = user.subscription_status;

		switch (status) {
			case 'past_due':
				return 'Your organization subscription payment is past due.';
			case 'canceled':
				return 'Your organization subscription has been canceled.';
			case 'incomplete':
				return 'Your organization subscription setup is incomplete.';
			case null:
			case 'none':
				return 'Your organization does not have an active subscription.';
			default:
				return 'Your organization subscription is inactive.';
		}
	}

	function getOwnerActionMessage() {
		const status = user?.subscription_status;

		if (status === 'past_due') {
			return 'Update your payment method to restore access for your entire team.';
		}

		return 'Renew your subscription to restore access for your entire team.';
	}

	function getMemberActionMessage() {
		return 'Please contact your organization owner to renew the subscription.';
	}

	async function handleManageSubscription() {
		try {
			const result = await getCustomerPortalUrl();
			window.location.href = result.url;
		} catch (err: any) {
			error = err.message || 'Failed to open subscription management';
		}
	}
</script>

<svelte:head>
	<title>Subscription Renewal Required - Vitevue</title>
</svelte:head>

<div
	class="min-h-screen flex flex-col items-center justify-center bg-gradient-to-br from-slate-50 to-white px-4"
>
	<div class="max-w-md w-full bg-white rounded-xl shadow-lg p-8">
		<!-- Icon -->
		<div class="flex items-center justify-center w-16 h-16 rounded-full bg-amber-100 mx-auto mb-4">
			<svg class="w-8 h-8 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
				></path>
			</svg>
		</div>

		<!-- Title -->
		<h1 class="text-2xl font-bold text-center mb-3 text-slate-900">
			{user?.is_owner ? 'Subscription Renewal Required' : 'Subscription Inactive'}
		</h1>

		<!-- Status Message -->
		<p class="text-slate-600 mb-2 text-center">{getStatusMessage()}</p>

		<!-- Organization Info -->
		{#if user?.organization_name}
			<div class="mb-4 p-3 bg-slate-50 rounded-lg border border-slate-200">
				<p class="text-sm text-slate-600">Organization</p>
				<p class="font-semibold text-slate-900">{user.organization_name}</p>
				<p class="text-xs text-slate-500 mt-1">
					Your role: {user.is_owner ? 'Owner' : 'Member'}
				</p>
			</div>
		{/if}

		<!-- Role-based Action Message -->
		<p class="text-sm text-slate-500 mb-6 text-center">
			{user?.is_owner ? getOwnerActionMessage() : getMemberActionMessage()}
		</p>

		<!-- Error Message -->
		{#if error}
			<div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
				{error}
			</div>
		{/if}

		<!-- Action Buttons -->
		<div class="space-y-3">
			{#if user?.is_owner}
				<!-- Owner: Show Renew Button -->
				{#if user.subscription_status === 'past_due' || user.subscription_status === 'canceled'}
					<button
						onclick={handleManageSubscription}
						disabled={processingRenewal}
						class="w-full bg-slate-900 hover:bg-slate-800 text-white font-semibold rounded-lg px-6 py-3 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
					>
						{processingRenewal ? 'Processing...' : 'Manage Subscription'}
					</button>
				{:else}
					<button
						onclick={() => goto('/organization-setup')}
						disabled={processingRenewal}
						class="w-full bg-slate-900 hover:bg-slate-800 text-white font-semibold rounded-lg px-6 py-3 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
					>
						{processingRenewal ? 'Processing...' : 'Complete Setup'}
					</button>
				{/if}
			{:else}
				<!-- Member: Show Contact Admin Message -->
				<div class="p-4 bg-blue-50 border border-blue-200 rounded-lg">
					<p class="text-sm text-blue-800 font-medium mb-1">Contact Your Organization Owner</p>
					<p class="text-xs text-blue-600">
						Only the organization owner can renew the subscription. Please reach out to them to
						restore access.
					</p>
				</div>
			{/if}

			<!-- Sign Out Button -->
			<button
				onclick={logout}
				class="w-full border border-slate-300 text-slate-700 font-semibold rounded-lg px-6 py-3 hover:bg-slate-50 transition-colors"
			>
				Sign Out
			</button>
		</div>

		<!-- Help Footer -->
		<p class="text-center text-sm text-slate-500 mt-6">
			Need help? Contact
			<a href="mailto:contact@vitevue.com" class="text-slate-900 hover:underline">
				contact@vitevue.com
			</a>
		</p>
	</div>
</div>
