<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { update_user_profile } from '$lib/api/auth';
	import { validateInviteToken, acceptInvite } from '$lib/api/organization';
	import type { ValidateInviteTokenResponse, InviteConflictResponse } from '$lib/api/organization';
	import TextInput from '$lib/components/auth/TextInput.svelte';
	import { refreshUser } from '$lib/stores/user.svelte';

	let inviteToken = $state('');
	let inviteDetails = $state<ValidateInviteTokenResponse | null>(null);
	let isInvited = $state(false);
	let firstName = $state('');
	let lastName = $state('');
	let loading = $state(false);
	let error = $state('');
	let showConflictModal = $state(false);
	let conflictDetails = $state<InviteConflictResponse | null>(null);

	let fieldErrors = $state({
		firstName: '',
		lastName: ''
	});

	// Layout ensures user is authenticated before this page loads
	onMount(async () => {
		inviteToken = $page.url.searchParams.get('token') || '';

		if (inviteToken) {
			isInvited = true;
			try {
				inviteDetails = await validateInviteToken(inviteToken);
			} catch (err: any) {
				error = err.message || 'Invalid invitation link. Please contact your administrator.';
			}
		}
	});

	async function handleSubmit() {
		// Reset errors
		fieldErrors.firstName = '';
		fieldErrors.lastName = '';
		error = '';

		// Validate
		if (!firstName.trim()) {
			fieldErrors.firstName = 'First name is required';
			return;
		}

		if (!lastName.trim()) {
			fieldErrors.lastName = 'Last name is required';
			return;
		}

		loading = true;

		try {
			// Update profile via backend
			await update_user_profile(firstName.trim(), lastName.trim());

			if (isInvited && inviteToken) {
				// Invited user flow - accept invitation
				try {
					const result = await acceptInvite(inviteToken);

					if ('conflict' in result && result.conflict) {
						// Conflict detected - show modal
						conflictDetails = result;
						showConflictModal = true;
						loading = false;
						return;
					}

					// Success - refresh user data to update org/subscription
					await refreshUser();

					// Redirect to dashboard
					goto('/dashboard');
				} catch (err: any) {
					if (err.status === 409 && err.details?.detail) {
						conflictDetails = err.details.detail;
						showConflictModal = true;
						loading = false;
						return;
					}
					throw err;
				}
			} else {
				// Self-signup flow - refresh store so layout sees updated names
				await refreshUser();
				const selectedTier = localStorage.getItem('selected_tier');
				goto(selectedTier ? `/organization-setup?tier=${selectedTier}` : '/organization-setup');
			}
		} catch (err: any) {
			error = err.message || 'Failed to complete profile setup. Please try again.';
		} finally {
			loading = false;
		}
	}

	function getConflictMessage(): string {
		if (!conflictDetails) return '';

		if (conflictDetails.current_role === 'owner') {
			if (conflictDetails.is_single_seat) {
				return `You currently own "${conflictDetails.current_org_name}" (single seat). You must cancel that subscription before joining another organization.`;
			} else {
				return `You are the owner of "${conflictDetails.current_org_name}" with ${conflictDetails.member_count} members. You must transfer ownership before joining another organization.`;
			}
		} else {
			return `You are already a member of "${conflictDetails.current_org_name}". You must leave that organization first.`;
		}
	}
</script>

<svelte:head>
	<title>Complete Your Profile - Vitevue</title>
</svelte:head>

<div class="min-h-screen bg-gradient-to-br from-slate-50 to-white flex items-center justify-center p-4">
	<div class="w-full max-w-md">
		<div class="bg-white rounded-xl shadow-lg p-8">
			<!-- Header -->
			<div class="mb-8 text-center">
				<h1 class="text-3xl font-bold text-slate-900 mb-2">
					{isInvited ? 'Welcome to Vitevue!' : 'Complete Your Profile'}
				</h1>
				{#if isInvited && inviteDetails}
					<p class="text-slate-600">
						You're joining <span class="font-semibold">{inviteDetails.organization_name}</span>
					</p>
				{:else}
					<p class="text-slate-600">Let's set up your account</p>
				{/if}
			</div>

			{#if error}
				<div class="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
					{error}
				</div>
			{/if}

			<form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }} class="space-y-5">
				<!-- Name Fields -->
				<TextInput
					label="First Name"
					bind:value={firstName}
					placeholder="John"
					error={fieldErrors.firstName}
					required
					autocomplete="given-name"
				/>

				<TextInput
					label="Last Name"
					bind:value={lastName}
					placeholder="Doe"
					error={fieldErrors.lastName}
					required
					autocomplete="family-name"
				/>

				<!-- Submit Button -->
				<button
					type="submit"
					disabled={loading}
					class="w-full bg-slate-900 hover:bg-slate-800 text-white font-semibold rounded-lg px-6 py-3 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
				>
					{loading ? 'Setting up...' : isInvited ? 'Join Organization' : 'Continue'}
				</button>
			</form>

			<!-- Help Text -->
			<p class="text-center text-sm text-slate-500 mt-6">
				Need help? Contact
				<a href="mailto:contact@vitevue.com" class="text-slate-900 hover:underline">
					contact@vitevue.com
				</a>
			</p>
		</div>
	</div>
</div>

<!-- Conflict Modal -->
{#if showConflictModal && conflictDetails}
	<div
		class="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50"
		role="presentation"
	>
		<div
			class="bg-white rounded-lg shadow-xl max-w-md w-full p-6"
			role="dialog"
			aria-modal="true"
		>
			<div class="mb-4">
				<div class="w-12 h-12 rounded-full bg-amber-100 flex items-center justify-center mb-4">
					<svg class="w-6 h-6 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
						></path>
					</svg>
				</div>
				<h3 class="text-xl font-semibold text-slate-900 mb-2">Already in an Organization</h3>
				<p class="text-slate-600 mb-4">{getConflictMessage()}</p>

				{#if conflictDetails.current_role === 'member'}
					<p class="text-sm text-slate-500">
						Please go to your organization settings to leave your current organization, then try
						accepting this invitation again.
					</p>
				{:else if conflictDetails.is_single_seat}
					<p class="text-sm text-slate-500">
						Go to your organization settings to manage your subscription and cancel it, then try
						accepting this invitation again.
					</p>
				{:else}
					<p class="text-sm text-slate-500">
						Go to your organization settings to transfer ownership to another member, then try
						accepting this invitation again.
					</p>
				{/if}
			</div>

			<div class="flex gap-3">
				<a
					href="/settings/organization"
					class="flex-1 bg-slate-900 hover:bg-slate-800 text-white font-semibold rounded-lg px-4 py-2 text-center transition-colors"
				>
					Go to Settings
				</a>
				<button
					onclick={() => (showConflictModal = false)}
					class="px-4 py-2 border border-slate-300 text-slate-700 font-semibold rounded-lg hover:bg-slate-50 transition-colors"
				>
					Cancel
				</button>
			</div>
		</div>
	</div>
{/if}
