<script lang="ts">
	import { onMount } from 'svelte';
	import { me } from '$lib/api/auth';
	import { getOrganizationSubscription } from '$lib/api/organization';
	import { logout } from '$lib/api/auth';

	let loading = $state(true);
	let user = $state<any>(null);
	let subscription = $state<any>(null);
	let error = $state('');

	onMount(async () => {
		try {
			user = await me();

			if (user.organization_id) {
				try {
					subscription = await getOrganizationSubscription();
				} catch (err) {
					error = 'Failed to load subscription details';
				}
			}
		} catch (err) {
			error = 'Failed to load user details';
		} finally {
			loading = false;
		}
	});

	function getStatusMessage() {
		if (!user) return 'Loading...';

		if (!user.organization_id) {
			return 'Your account is not connected to an organization.';
		}

		if (!subscription) {
			return 'Unable to verify your organization subscription.';
		}

		switch (subscription.status) {
			case 'past_due':
				return 'Your organization subscription payment is past due.';
			case 'canceled':
				return 'Your organization subscription has been canceled.';
			case 'incomplete':
				return 'Your organization subscription setup is incomplete.';
			case 'unpaid':
				return 'Your organization subscription is unpaid.';
			default:
				return 'Your organization subscription is not active.';
		}
	}

	function getActionMessage() {
		if (!user?.organization_id) {
			return 'Please contact support at contact@vitevue.com if you believe this is a mistake.';
		}

		if (user.role === 'owner' || user.role === 'organization_admin') {
			return 'As an organization admin, you can manage your subscription to restore access.';
		}

		return 'Please contact your organization administrator to resolve this issue.';
	}

	async function handleManageSubscription() {
		try {
			const { getCustomerPortalUrl } = await import('$lib/api/organization');
			const result = await getCustomerPortalUrl();
			window.location.href = result.url;
		} catch (err: any) {
			alert(err.message || 'Failed to open subscription management');
		}
	}
</script>

<svelte:head>
	<title>Subscription Required - Vitevue</title>
</svelte:head>

<div class="min-h-screen flex flex-col items-center justify-center bg-gradient-to-br from-slate-50 to-white px-4">
	{#if loading}
		<div class="animate-spin rounded-full h-12 w-12 border-4 border-slate-200 border-t-slate-900"></div>
	{:else}
		<div class="max-w-md w-full bg-white rounded-xl shadow-lg p-8">
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

			<h1 class="text-2xl font-bold text-center mb-3 text-slate-900">Subscription Required</h1>

			<p class="text-slate-600 mb-2 text-center">{getStatusMessage()}</p>

			<p class="text-sm text-slate-500 mb-6 text-center">{getActionMessage()}</p>

			{#if error}
				<div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
					{error}
				</div>
			{/if}

			{#if subscription && subscription.status === 'past_due'}
				<div class="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
					<p class="text-sm text-blue-800 mb-2">
						Your payment is overdue. Update your payment method to restore access.
					</p>
					<p class="text-xs text-blue-600">
						Period ends: {new Date(subscription.current_period_end).toLocaleDateString()}
					</p>
				</div>
			{/if}

			<div class="space-y-3">
				{#if user?.role === 'owner' || user?.role === 'organization_admin'}
					<button
						onclick={handleManageSubscription}
						class="w-full bg-slate-900 hover:bg-slate-800 text-white font-semibold rounded-lg px-6 py-3 transition-colors"
					>
						Manage Subscription
					</button>
				{/if}

				<button
					onclick={logout}
					class="w-full border border-slate-300 text-slate-700 font-semibold rounded-lg px-6 py-3 hover:bg-slate-50 transition-colors"
				>
					Sign Out
				</button>
			</div>

			<p class="text-center text-sm text-slate-500 mt-6">
				Need help? Contact
				<a href="mailto:contact@vitevue.com" class="text-slate-900 hover:underline">
					contact@vitevue.com
				</a>
			</p>
		</div>
	{/if}
</div>
