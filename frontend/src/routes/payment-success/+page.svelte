<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { syncAfterCheckout } from '$lib/api/billing';
	import { inviteUserByEmail } from '$lib/api/organization';
	import { refreshUser } from '$lib/stores/user.svelte';

	let status = $state<'syncing' | 'completed' | 'failed'>('syncing');
	let organizationId = $state('');
	let showInviteModal = $state(false);
	let seats = $state(0);
	let inviteEmails = $state<string[]>(['']);
	let invitationErrors = $state<string[]>([]);
	let sendingInvites = $state(false);
	let error = $state('');

	onMount(async () => {
		const sessionId = $page.url.searchParams.get('session_id');

		if (!sessionId) {
			error = 'Invalid payment session';
			status = 'failed';
			return;
		}

		try {
			// Eager sync - no polling, direct call
			const result = await syncAfterCheckout(sessionId);

			if (result.status === 'active') {
				organizationId = result.organization_id;
				seats = result.seats;

				// Refresh user data to update subscription status
				await refreshUser();

				// Skip invite modal for single-seat orgs
				if (result.seats <= 1) {
					goto('/dashboard');
					return;
				}

				status = 'completed';
				setTimeout(() => {
					showInviteModal = true;
				}, 500);
			} else {
				status = 'failed';
				error = `Subscription status: ${result.status}. Please contact support if this persists.`;
			}
		} catch (err: any) {
			console.error('Sync error:', err);
			status = 'failed';
			error = err.message || 'Failed to sync subscription. Please contact support.';
		}
	});

	function addEmailField() {
		inviteEmails = [...inviteEmails, ''];
	}

	function removeEmailField(index: number) {
		inviteEmails = inviteEmails.filter((_, i) => i !== index);
	}

	function validateEmail(email: string): boolean {
		return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
	}

	async function handleSendInvitations() {
		invitationErrors = [];

		// Filter out empty emails and validate
		const validEmails = inviteEmails.filter((email) => email.trim());

		if (validEmails.length === 0) {
			// Skip invitations, go to dashboard
			goto('/dashboard');
			return;
		}

		// Validate email format
		const invalidEmails = validEmails.filter((email) => !validateEmail(email));
		if (invalidEmails.length > 0) {
			invitationErrors = invalidEmails.map((email) => `Invalid email format: ${email}`);
			return;
		}

		sendingInvites = true;

		const redirectUrl = `${window.location.origin}/profile-setup?organization_id=${organizationId}`;

		// Send invitations
		const results = await Promise.all(
			validEmails.map(async (email) => {
				try {
					const result = await inviteUserByEmail(email, organizationId, redirectUrl);
					return { email, success: result.success, error: result.error };
				} catch (err: any) {
					return { email, success: false, error: err.message };
				}
			})
		);

		// Collect errors
		const errors = results.filter((r) => !r.success).map((r) => `${r.email}: ${r.error}`);

		if (errors.length > 0) {
			invitationErrors = errors;
			sendingInvites = false;
		} else {
			// All invitations sent successfully
			goto('/dashboard');
		}
	}

	function handleSkipInvitations() {
		goto('/dashboard');
	}
</script>

<svelte:head>
	<title>Payment Successful - Vitevue</title>
</svelte:head>

<div class="min-h-screen bg-gradient-to-br from-slate-50 to-white flex items-center justify-center p-4">
	<div class="w-full max-w-2xl">
		{#if status === 'syncing'}
			<div class="bg-white rounded-xl shadow-lg p-12 text-center">
				<div class="mb-6">
					<div class="inline-block animate-spin rounded-full h-16 w-16 border-4 border-slate-200 border-t-slate-900"></div>
				</div>
				<h1 class="text-2xl font-bold text-slate-900 mb-2">Setting up your organization...</h1>
				<p class="text-slate-600">This will only take a moment</p>
			</div>
		{:else if status === 'failed'}
			<div class="bg-white rounded-xl shadow-lg p-12 text-center">
				<div class="mb-6">
					<svg class="w-16 h-16 text-red-500 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
					</svg>
				</div>
				<h1 class="text-2xl font-bold text-slate-900 mb-2">Payment Failed</h1>
				<p class="text-slate-600 mb-6">{error || 'Something went wrong with your payment'}</p>
				<a
					href="/organization-setup"
					class="inline-flex items-center gap-2 px-6 py-3 bg-slate-900 text-white font-semibold rounded-lg hover:bg-slate-800 transition-colors"
				>
					Try Again
				</a>
			</div>
		{:else if status === 'completed' && showInviteModal}
			<div class="bg-white rounded-xl shadow-lg p-8">
				<div class="mb-8 text-center">
					<div class="mb-4">
						<svg class="w-16 h-16 text-green-500 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
						</svg>
					</div>
					<h1 class="text-3xl font-bold text-slate-900 mb-2">Payment Successful!</h1>
					<p class="text-slate-600">Your organization has been created</p>
				</div>

				<div class="mb-6">
					<div class="flex items-center justify-between mb-4">
						<h2 class="text-xl font-semibold text-slate-900">Invite Your Team</h2>
						<span class="text-sm text-slate-500">(Optional)</span>
					</div>
					<p class="text-slate-600 text-sm mb-4">
						Invite team members now or do it later from settings. Each member will receive an email invitation.
					</p>
				</div>

				{#if invitationErrors.length > 0}
					<div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
						<p class="text-sm font-medium text-red-800 mb-2">Some invitations failed:</p>
						{#each invitationErrors as error}
							<p class="text-xs text-red-600">{error}</p>
						{/each}
					</div>
				{/if}

				<div class="space-y-3 mb-6">
					{#each inviteEmails as email, index}
						<div class="flex items-center gap-2">
							<input
								type="email"
								bind:value={inviteEmails[index]}
								placeholder="colleague@company.com"
								class="flex-1 px-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-slate-900 focus:border-transparent"
							/>
							{#if inviteEmails.length > 1}
								<button
									type="button"
									onclick={() => removeEmailField(index)}								aria-label="Remove email field"									class="p-2 text-slate-400 hover:text-red-500 transition-colors"
								>
									<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
									</svg>
								</button>
							{/if}
						</div>
					{/each}
				</div>

				<button
					type="button"
					onclick={addEmailField}
					class="mb-6 text-sm text-slate-600 hover:text-slate-900 flex items-center gap-1"
				>
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
					</svg>
					Add another email
				</button>

				<div class="flex gap-3">
					<button
						type="button"
						onclick={handleSendInvitations}
						disabled={sendingInvites}
						class="flex-1 bg-slate-900 hover:bg-slate-800 text-white font-semibold rounded-lg px-6 py-3 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
					>
						{sendingInvites ? 'Sending...' : 'Send Invitations'}
					</button>
					<button
						type="button"
						onclick={handleSkipInvitations}
						disabled={sendingInvites}
						class="px-6 py-3 border border-slate-300 text-slate-700 font-semibold rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
					>
						Skip for Now
					</button>
				</div>
			</div>
		{/if}
	</div>
</div>
