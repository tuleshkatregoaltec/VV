<script lang="ts">
	import { goto } from '$app/navigation';
	import { update_user_profile } from '$lib/api/auth';
	import TextInput from '$lib/components/auth/TextInput.svelte';
	import { refreshUser } from '$lib/stores/user.svelte';

	let firstName = $state('');
	let lastName = $state('');
	let loading = $state(false);
	let error = $state('');

	let fieldErrors = $state({
		firstName: '',
		lastName: ''
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
			await update_user_profile(firstName.trim(), lastName.trim());
			await refreshUser();
			const selectedTier = localStorage.getItem('selected_tier');
			goto(selectedTier ? `/organization-setup?tier=${selectedTier}` : '/organization-setup');
		} catch (err: any) {
			error = err.message || 'Failed to complete profile setup. Please try again.';
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>Complete Your Profile - Vitevue</title>
</svelte:head>

<div
	class="min-h-screen bg-gradient-to-br from-slate-50 to-white flex items-center justify-center p-4"
>
	<div class="w-full max-w-md">
		<div class="bg-white rounded-xl shadow-lg p-8">
			<!-- Header -->
			<div class="mb-8 text-center">
				<h1 class="text-3xl font-bold text-slate-900 mb-2">Complete Your Profile</h1>
				<p class="text-slate-600">Let's set up your account</p>
			</div>

			{#if error}
				<div class="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
					{error}
				</div>
			{/if}

			<form
				onsubmit={(e) => {
					e.preventDefault();
					handleSubmit();
				}}
				class="space-y-5"
			>
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
					{loading ? 'Setting up...' : 'Continue'}
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
