<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import PasswordInput from '$lib/components/auth/PasswordInput.svelte';
	import { get_session, update_password } from '$lib/api/auth';
	import { refreshUser } from '$lib/stores/user.svelte';

	let newPassword = $state('');
	let confirmPassword = $state('');
	let loading = $state(false);
	let error = $state('');
	let success = $state(false);
	let hasValidSession = $state(false);

	let fieldErrors = $state({
		newPassword: '',
		confirmPassword: ''
	});

	onMount(async () => {
		const session = await get_session();
		if (!session) {
			error = 'Invalid or expired reset link. Please request a new password reset.';
		} else {
			hasValidSession = true;
		}
	});

	function validateForm(): boolean {
		fieldErrors = {
			newPassword: '',
			confirmPassword: ''
		};

		let isValid = true;

		if (!newPassword) {
			fieldErrors.newPassword = 'Password is required';
			isValid = false;
		} else if (newPassword.length < 8) {
			fieldErrors.newPassword = 'Password must be at least 8 characters';
			isValid = false;
		}

		if (!confirmPassword) {
			fieldErrors.confirmPassword = 'Please confirm your password';
			isValid = false;
		} else if (newPassword !== confirmPassword) {
			fieldErrors.confirmPassword = 'Passwords do not match';
			isValid = false;
		}

		return isValid;
	}

	async function handleResetPassword() {
		if (!validateForm()) return;

		loading = true;
		error = '';

		try {
			const result = await update_password(newPassword);
			if (result.success) {
				await refreshUser();
				success = true;
				setTimeout(() => {
					goto('/dashboard');
				}, 2000);
			} else {
				error = result.error || 'Failed to update password';
			}
		} finally {
			loading = false;
		}
	}
</script>

<div class="min-h-screen bg-background flex items-center justify-center p-4">
	<div class="w-full max-w-md">
		<div class="bg-white rounded-xl shadow-lg p-8">
			{#if success}
				<div class="text-center">
					<div class="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							class="h-8 w-8 text-green-600"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M5 13l4 4L19 7"
							/>
						</svg>
					</div>
					<h1 class="text-3xl font-bold text-black mb-2">Password Updated</h1>
					<p class="text-gray-600">Your password has been successfully updated. Redirecting to dashboard...</p>
				</div>
			{:else if !hasValidSession && error}
				<div class="text-center">
					<div class="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							class="h-8 w-8 text-red-600"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M6 18L18 6M6 6l12 12"
							/>
						</svg>
					</div>
					<h1 class="text-3xl font-bold text-black mb-2">Invalid Link</h1>
					<p class="text-gray-600 mb-6">{error}</p>
					<a
						href="/auth"
						class="inline-block bg-primary hover:bg-primary-dark text-white rounded-lg px-6 py-3 transition-colors"
					>
						Back to Sign In
					</a>
				</div>
			{:else}
				<div class="mb-8">
					<h1 class="text-3xl font-bold text-black mb-2">Reset Password</h1>
					<p class="text-gray-600">Enter your new password below</p>
				</div>

				{#if error}
					<div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
						{error}
					</div>
				{/if}

				<form
					onsubmit={(e) => {
						e.preventDefault();
						handleResetPassword();
					}}
					class="space-y-4"
				>
					<PasswordInput
						label="New Password"
						bind:value={newPassword}
						placeholder="Enter new password"
						error={fieldErrors.newPassword}
						required
						autocomplete="new-password"
						showStrength={true}
					/>

					<PasswordInput
						label="Confirm Password"
						bind:value={confirmPassword}
						placeholder="Confirm new password"
						error={fieldErrors.confirmPassword}
						required
						autocomplete="new-password"
					/>

					<button
						type="submit"
						disabled={loading}
						class="w-full bg-primary hover:bg-primary-dark text-white rounded-lg px-4 py-3
                               transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
					>
						{loading ? 'Updating...' : 'Update Password'}
					</button>
				</form>
			{/if}
		</div>
	</div>
</div>
