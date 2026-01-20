<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { completeProfileSetup } from '$lib/api/onboarding';
	import { get_session, me } from '$lib/api/auth';
	import TextInput from '$lib/components/auth/TextInput.svelte';
	import PasswordInput from '$lib/components/auth/PasswordInput.svelte';

	let organizationId = $state('');
	let organizationName = $state('');
	let firstName = $state('');
	let lastName = $state('');
	let password = $state('');
	let usePassword = $state(true);
	let termsAccepted = $state(false);
	let loading = $state(false);
	let error = $state('');

	let fieldErrors = $state({
		firstName: '',
		lastName: '',
		password: ''
	});

	onMount(async () => {
		// Check if user is authenticated
		const session = await get_session();
		if (!session) {
			goto('/auth?view=signup');
			return;
		}

		// Get organization ID from URL or user metadata
		organizationId = $page.url.searchParams.get('organization_id') || '';

		if (!organizationId) {
			try {
				const user = await me();
				organizationId = user.organization_id || '';
			} catch (err) {
				// No organization ID available
			}
		}

		if (!organizationId) {
			error = 'Invalid invitation link. Please contact your administrator.';
		}
	});

	async function handleSubmit() {
		// Reset errors
		fieldErrors.firstName = '';
		fieldErrors.lastName = '';
		fieldErrors.password = '';
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

		if (usePassword) {
			if (!password) {
				fieldErrors.password = 'Password is required';
				return;
			}
			if (password.length < 8) {
				fieldErrors.password = 'Password must be at least 8 characters';
				return;
			}
		}

		if (!termsAccepted) {
			error = 'You must accept the Terms of Service and Privacy Policy';
			return;
		}

		if (!organizationId) {
			error = 'Organization ID is missing. Please contact your administrator.';
			return;
		}

		loading = true;

		try {
			await completeProfileSetup(
				firstName.trim(),
				lastName.trim(),
				usePassword ? password : null,
				organizationId
			);

			// Success - redirect to dashboard
			goto('/dashboard');
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

<div class="min-h-screen bg-gradient-to-br from-slate-50 to-white flex items-center justify-center p-4">
	<div class="w-full max-w-md">
		<div class="bg-white rounded-xl shadow-lg p-8">
			<!-- Header -->
			<div class="mb-8 text-center">
				<h1 class="text-3xl font-bold text-slate-900 mb-2">Welcome to Vitevue!</h1>
				<p class="text-slate-600">
					Complete your profile to get started
				</p>
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

				<!-- Auth Method Selection -->
				<div class="border-t border-slate-200 pt-5">
				<div class="block text-sm font-medium text-slate-700 mb-3">
					Choose Authentication Method
				</div>

					<div class="space-y-3">
						<label class="flex items-start gap-3 p-4 border-2 rounded-lg cursor-pointer transition-all {usePassword ? 'border-slate-900 bg-slate-50' : 'border-slate-200 hover:border-slate-300'}">
							<input
								type="radio"
								bind:group={usePassword}
								value={true}
								class="mt-1 h-4 w-4 text-slate-900 focus:ring-slate-900"
							/>
							<div class="flex-1">
								<div class="font-medium text-slate-900">Set a Password</div>
								<div class="text-sm text-slate-600">Create a password for your account</div>
							</div>
						</label>

						<label class="flex items-start gap-3 p-4 border-2 rounded-lg cursor-pointer transition-all {!usePassword ? 'border-slate-900 bg-slate-50' : 'border-slate-200 hover:border-slate-300'}">
							<input
								type="radio"
								bind:group={usePassword}
								value={false}
								class="mt-1 h-4 w-4 text-slate-900 focus:ring-slate-900"
							/>
							<div class="flex-1">
								<div class="font-medium text-slate-900">Passwordless Login</div>
								<div class="text-sm text-slate-600">Use magic links sent to your email</div>
							</div>
						</label>
					</div>
				</div>

				<!-- Password Field (conditional) -->
				{#if usePassword}
					<PasswordInput
						label="Password"
						bind:value={password}
						placeholder="Create a strong password"
						error={fieldErrors.password}
						required
						autocomplete="new-password"
						showStrength
					/>
				{/if}

				<!-- Terms Checkbox -->
				<div class="flex items-start gap-2 pt-2">
					<input
						type="checkbox"
						id="terms"
						bind:checked={termsAccepted}
						class="mt-1 h-4 w-4 rounded border-gray-300 text-slate-900 focus:ring-slate-900"
					/>
					<label for="terms" class="text-sm text-gray-600">
						I agree to the
						<a href="/terms" target="_blank" class="text-slate-900 hover:underline font-medium">
							Terms of Service
						</a>
						and
						<a href="/privacy" target="_blank" class="text-slate-900 hover:underline font-medium">
							Privacy Policy
						</a>
					</label>
				</div>

				<!-- Submit Button -->
				<button
					type="submit"
					disabled={loading}
					class="w-full bg-slate-900 hover:bg-slate-800 text-white font-semibold rounded-lg px-6 py-3 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
				>
					{loading ? 'Setting up...' : 'Complete Setup'}
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
