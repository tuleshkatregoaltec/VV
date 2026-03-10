<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import TextInput from '$lib/components/auth/TextInput.svelte';
	import {
		client,
		get_session,
		sign_in_with_magic_link_to,
		update_user_profile,
		verify_otp
	} from '$lib/api/auth';
	import {
		acceptInvite,
		validateInviteToken,
		type InviteConflictResponse,
		type ValidateInviteTokenResponse
	} from '$lib/api/organization';
	import { clearUser, refreshUser } from '$lib/stores/user.svelte';

	type Step = 'loading' | 'verify-code' | 'profile' | 'accept' | 'mismatch' | 'error';

	let step = $state<Step>('loading');
	let inviteToken = $state('');
	let inviteDetails = $state<ValidateInviteTokenResponse | null>(null);
	let firstName = $state('');
	let lastName = $state('');
	let verificationCode = $state('');
	let currentEmail = $state('');
	let loading = $state(false);
	let error = $state('');
	let conflictMessage = $state('');

	let fieldErrors = $state({
		firstName: '',
		lastName: '',
		verificationCode: ''
	});

	onMount(async () => {
		inviteToken = new URL(window.location.href).searchParams.get('token') || '';
		await syncInviteState();
	});

	function resetMessages() {
		error = '';
		conflictMessage = '';
		fieldErrors.firstName = '';
		fieldErrors.lastName = '';
		fieldErrors.verificationCode = '';
	}

	function setProfileStep(first: string, last: string) {
		firstName = first;
		lastName = last;
		step = first && last ? 'accept' : 'profile';
	}

	async function syncInviteState() {
		resetMessages();

		if (!inviteToken) {
			error = 'Invitation token is missing.';
			step = 'error';
			return;
		}

		step = 'loading';

		try {
			inviteDetails = await validateInviteToken(inviteToken);
		} catch (err: any) {
			error = err.message || 'Invalid invitation link. Please contact your administrator.';
			step = 'error';
			return;
		}

		const session = await get_session();
		if (!session?.user?.email) {
			currentEmail = '';
			step = 'verify-code';
			return;
		}

		currentEmail = session.user.email;
		if (session.user.email.toLowerCase() !== inviteDetails.email.toLowerCase()) {
			step = 'mismatch';
			return;
		}

		const user = await refreshUser();
		setProfileStep(
			user?.first_name ?? (session.user.user_metadata?.first_name as string) ?? '',
			user?.last_name ?? (session.user.user_metadata?.last_name as string) ?? ''
		);
	}

	async function sendCode() {
		if (!inviteDetails) return;

		loading = true;
		error = '';
		try {
			const result = await sign_in_with_magic_link_to(
				inviteDetails.email,
				`/invite?token=${inviteToken}`
			);
			if (result.success) {
				step = 'verify-code';
			} else {
				error = result.error || 'Failed to send sign-in code.';
			}
		} finally {
			loading = false;
		}
	}

	async function verifyCode() {
		fieldErrors.verificationCode = '';
		if (verificationCode.trim().length !== 6) {
			fieldErrors.verificationCode = 'Please enter the 6-digit code.';
			return;
		}

		if (!inviteDetails) return;

		loading = true;
		error = '';
		try {
			const result = await verify_otp(inviteDetails.email, verificationCode.trim(), 'magiclink');
			if (!result.success) {
				error = result.error || 'Invalid verification code.';
				return;
			}

			verificationCode = '';
			await syncInviteState();
		} finally {
			loading = false;
		}
	}

	async function joinOrganization() {
		resetMessages();

		if (step === 'profile') {
			if (!firstName.trim()) {
				fieldErrors.firstName = 'First name is required';
			}
			if (!lastName.trim()) {
				fieldErrors.lastName = 'Last name is required';
			}
			if (fieldErrors.firstName || fieldErrors.lastName) {
				return;
			}
		}

		loading = true;
		try {
			if (step === 'profile') {
				await update_user_profile(firstName.trim(), lastName.trim());
			}

			const result = await acceptInvite(inviteToken);
			if ('conflict' in result && result.conflict) {
				conflictMessage = getConflictMessage(result);
				return;
			}

			await refreshUser();
			goto('/dashboard');
		} catch (err: any) {
			if (err.status === 409 && err.details?.detail) {
				conflictMessage = getConflictMessage(err.details.detail as InviteConflictResponse);
				return;
			}
			error = err.message || 'Failed to join organization. Please try again.';
		} finally {
			loading = false;
		}
	}

	async function switchAccount() {
		await client.signOut();
		clearUser();
		await goto(`/invite?token=${inviteToken}`);
		step = 'verify-code';
	}

	function getConflictMessage(conflict: InviteConflictResponse): string {
		if (conflict.current_role === 'owner') {
			return `You already own ${conflict.current_org_name}. Transfer ownership or cancel that organization before joining another one.`;
		}

		return `You are already a member of ${conflict.current_org_name}. Leave that organization before joining another one.`;
	}
</script>

<svelte:head>
	<title>Organization Invite - Vitevue</title>
</svelte:head>

<div class="min-h-screen bg-slate-50 px-4 py-12">
	<div class="mx-auto max-w-xl rounded-2xl bg-white p-8 shadow-sm">
		{#if step === 'loading'}
			<div class="space-y-3 text-center">
				<h1 class="text-2xl font-semibold text-slate-900">Loading invitation…</h1>
				<p class="text-sm text-slate-600">Checking your invite details.</p>
			</div>
		{:else if step === 'error'}
			<div class="space-y-4 text-center">
				<h1 class="text-2xl font-semibold text-slate-900">Invitation Unavailable</h1>
				<p class="text-sm text-red-600">{error}</p>
			</div>
		{:else}
			<div class="space-y-6">
				<div class="space-y-2 text-center">
					<h1 class="text-3xl font-semibold text-slate-900">
						{step === 'profile'
							? 'Complete Your Profile'
							: `Join ${inviteDetails?.organization_name}`}
					</h1>
					<p class="text-sm text-slate-600">
						{#if step === 'profile'}
							Add your name, then you can join {inviteDetails?.organization_name}.
						{:else}
							This invitation is for <span class="font-medium text-slate-900"
								>{inviteDetails?.email}</span
							>.
						{/if}
					</p>
				</div>

				{#if error}
					<div class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
						{error}
					</div>
				{/if}

				{#if conflictMessage}
					<div
						class="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
					>
						{conflictMessage}
					</div>
				{/if}

				{#if step === 'verify-code'}
					<div class="space-y-4">
						<div
							class="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700"
						>
							Enter the code from the invite email sent to <span class="font-medium text-slate-900"
								>{inviteDetails?.email}</span
							>.
						</div>
						<TextInput
							label="Verification Code"
							bind:value={verificationCode}
							error={fieldErrors.verificationCode}
							placeholder="123456"
							autocomplete="off"
						/>
						<button
							type="button"
							class="w-full rounded-lg bg-slate-900 px-4 py-3 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
							onclick={verifyCode}
							disabled={loading}
						>
							{loading ? 'Verifying…' : 'Verify Code'}
						</button>
						<button
							type="button"
							class="w-full rounded-lg border border-slate-300 px-4 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
							onclick={sendCode}
							disabled={loading}
						>
							{loading ? 'Sending…' : 'Resend Code'}
						</button>
					</div>
				{:else if step === 'mismatch'}
					<div class="space-y-4">
						<div
							class="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
						>
							This invite was sent to {inviteDetails?.email}. You are currently signed in as {currentEmail}.
						</div>
						<button
							type="button"
							class="w-full rounded-lg bg-slate-900 px-4 py-3 text-sm font-semibold text-white hover:bg-slate-800"
							onclick={switchAccount}
						>
							Use a Different Account
						</button>
					</div>
				{:else}
					<div class="space-y-4">
						{#if step === 'profile'}
							<TextInput
								label="First Name"
								bind:value={firstName}
								error={fieldErrors.firstName}
								required
								autocomplete="given-name"
							/>
							<TextInput
								label="Last Name"
								bind:value={lastName}
								error={fieldErrors.lastName}
								required
								autocomplete="family-name"
							/>
						{/if}
						<button
							type="button"
							class="w-full rounded-lg bg-slate-900 px-4 py-3 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
							onclick={joinOrganization}
							disabled={loading}
						>
							{loading ? 'Joining…' : 'Join Organization'}
						</button>
					</div>
				{/if}
			</div>
		{/if}
	</div>
</div>
