<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import TextInput from '$lib/components/auth/TextInput.svelte';
	import PasswordInput from '$lib/components/auth/PasswordInput.svelte';
	import OTPInput from '$lib/components/auth/OTPInput.svelte';
	import {
		login_with_email_pass,
		sign_up_with_password,
		sign_in_with_magic_link,
		verify_otp,
		resend_otp,
		request_password_reset
	} from '$lib/api/auth';

	type View =
		| 'login'
		| 'signup'
		| 'verify-otp'
		| 'email-auth'
		| 'email-auth-otp'
		| 'forgot-password'
		| 'forgot-password-otp';

	let currentView = $state<View>('login');
	let email = $state('');
	let password = $state('');
	let confirmPassword = $state('');
	let otpCode = $state('');
	let termsAccepted = $state(false);

	let loading = $state(false);
	let error = $state('');
	let resendCountdown = $state(0);

	let fieldErrors = $state({
		email: '',
		password: '',
		confirmPassword: ''
	});

	// Layout handles redirect for authenticated users.
	// Only capture tier param here.
	onMount(() => {
		const urlParams = new URLSearchParams(window.location.search);
		const tier = urlParams.get('tier');
		if (tier === 'tier1' || tier === 'tier2') {
			localStorage.setItem('selected_tier', tier);
		}
	});

	let countdownInterval: number | undefined;

	function startResendCountdown() {
		resendCountdown = 60;
		countdownInterval = window.setInterval(() => {
			resendCountdown--;
			if (resendCountdown <= 0 && countdownInterval) {
				clearInterval(countdownInterval);
			}
		}, 1000);
	}

	function goBack() {
		currentView = 'login';
		error = '';
		password = '';
		confirmPassword = '';
		otpCode = '';
		if (countdownInterval) {
			clearInterval(countdownInterval);
		}
	}

	/** After any successful auth, navigate to dashboard — layout will redirect to correct step */
	function navigateAfterAuth() {
		goto('/dashboard');
	}

	function requireOtpCode(): boolean {
		if (otpCode.length === 6) return true;
		error = 'Please enter the complete 6-digit code';
		return false;
	}

	async function verifyOtpFlow(type: 'signup' | 'magiclink' | 'recovery') {
		if (!requireOtpCode()) return;

		loading = true;
		error = '';

		try {
			const result = await verify_otp(email, otpCode, type);
			if (result.success) {
				navigateAfterAuth();
			} else {
				error = result.error || 'Invalid verification code';
			}
		} finally {
			loading = false;
		}
	}

	async function resendCodeFlow(send: () => Promise<{ success: boolean; error?: string }>) {
		loading = true;
		error = '';

		try {
			const result = await send();
			if (result.success) {
				startResendCountdown();
				error = '';
			} else {
				error = result.error || 'Failed to resend code';
			}
		} finally {
			loading = false;
		}
	}

	async function handleLogin() {
		fieldErrors.password = '';
		if (!password) {
			fieldErrors.password = 'Password is required';
			return;
		}

		loading = true;
		error = '';

		try {
			const result = await login_with_email_pass(email, password);
			if (result.success) {
				navigateAfterAuth();
			} else {
				error = result.error || 'Invalid email or password';
			}
		} finally {
			loading = false;
		}
	}

	async function handleSignup() {
		fieldErrors.password = '';
		fieldErrors.confirmPassword = '';

		if (!password) {
			fieldErrors.password = 'Password is required';
			return;
		}
		if (password.length < 8) {
			fieldErrors.password = 'Password must be at least 8 characters';
			return;
		}
		if (!confirmPassword) {
			fieldErrors.confirmPassword = 'Please confirm your password';
			return;
		}
		if (password !== confirmPassword) {
			fieldErrors.confirmPassword = 'Passwords do not match';
			return;
		}
		if (!termsAccepted) {
			error = 'You must accept the Terms of Service and Privacy Policy';
			return;
		}

		loading = true;
		error = '';

		try {
			const result = await sign_up_with_password(email, password, '', '');
			if (result.success) {
				if (result.data?.session) {
					navigateAfterAuth();
				} else {
					// Manual confirmation required
					currentView = 'verify-otp';
					startResendCountdown();
				}
			} else {
				error = result.error || 'Sign up failed';
			}
		} catch {
			error = 'An unexpected error occurred during sign up. Please try again.';
		} finally {
			loading = false;
		}
	}

	async function handleVerifyOTP() {
		await verifyOtpFlow('signup');
	}

	async function handleResendOTP() {
		await resendCodeFlow(() => resend_otp(email, 'signup'));
	}

	async function handleEmailAuth() {
		fieldErrors.email = '';
		if (!email.trim()) {
			fieldErrors.email = 'Email is required';
			return;
		}

		loading = true;
		error = '';

		try {
			const result = await sign_in_with_magic_link(email);
			if (result.success) {
				currentView = 'email-auth-otp';
				startResendCountdown();
			} else {
				error = result.error || 'Failed to send verification code';
			}
		} finally {
			loading = false;
		}
	}

	async function handleEmailAuthOTP() {
		await verifyOtpFlow('magiclink');
	}

	async function handleResendEmailAuthOTP() {
		await resendCodeFlow(() => sign_in_with_magic_link(email));
	}

	async function handleForgotPassword() {
		fieldErrors.email = '';
		if (!email.trim()) {
			fieldErrors.email = 'Email is required';
			return;
		}

		loading = true;
		error = '';

		try {
			const result = await request_password_reset(email);
			if (result.success) {
				currentView = 'forgot-password-otp';
				startResendCountdown();
			} else {
				error = result.error || 'Failed to send reset email';
			}
		} catch {
			error = 'Failed to send reset email. Please try again.';
		} finally {
			loading = false;
		}
	}

	async function handleForgotPasswordOTP() {
		await verifyOtpFlow('recovery');
	}

	async function handleResendForgotPasswordOTP() {
		try {
			await resendCodeFlow(() => request_password_reset(email));
		} catch {
			error = 'Failed to resend code. Please try again.';
		}
	}
</script>

<div class="min-h-screen bg-background flex items-center justify-center p-4">
	<div class="w-full max-w-md">
		<div class="bg-white rounded-xl shadow-lg p-8">
			{#if currentView === 'login'}
				<div class="mb-8 flex items-start justify-between">
					<div>
						<h1 class="text-3xl font-bold text-black mb-2">Sign In</h1>
						<p class="text-gray-600">Welcome back to your account</p>
					</div>
					<button
						type="button"
						onclick={() => (currentView = 'signup')}
						class="text-sm text-primary hover:text-primary-dark transition-colors whitespace-nowrap ml-4"
					>
						Sign up
					</button>
				</div>

				{#if error}
					<div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
						{error}
					</div>
				{/if}

				<form
					onsubmit={(e) => {
						e.preventDefault();
						handleLogin();
					}}
					class="space-y-4"
				>
					<TextInput
						label="Email"
						type="email"
						bind:value={email}
						placeholder="you@example.com"
						error={fieldErrors.email}
						required
						autocomplete="email"
					/>
					<PasswordInput
						label="Password"
						bind:value={password}
						placeholder="Enter your password"
						error={fieldErrors.password}
						required
						autocomplete="current-password"
					/>

					<div class="text-right">
						<button
							type="button"
							onclick={() => (currentView = 'forgot-password')}
							class="text-sm text-primary hover:text-primary-dark transition-colors"
						>
							Forgot password?
						</button>
					</div>

					<button
						type="submit"
						disabled={loading}
						class="w-full bg-primary hover:bg-primary-dark text-white rounded-lg px-4 py-3
                               transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
					>
						{loading ? 'Processing...' : 'Sign In'}
					</button>

					<div class="relative my-6">
						<div class="absolute inset-0 flex items-center">
							<div class="w-full border-t border-gray-200"></div>
						</div>
						<div class="relative flex justify-center text-sm">
							<span class="px-2 bg-white text-gray-500">Or</span>
						</div>
					</div>

					<button
						type="button"
						onclick={() => (currentView = 'email-auth')}
						class="w-full border border-gray-200 hover:border-primary text-slate-700 hover:text-primary rounded-lg px-4 py-3
                               transition-colors font-medium"
					>
						Sign in with Email
					</button>
				</form>
			{:else if currentView === 'signup'}
				<div class="mb-8 flex items-start justify-between">
					<div>
						<h1 class="text-3xl font-bold text-black mb-2">Create Account</h1>
						<p class="text-gray-600">Sign up to get started</p>
					</div>
					<button
						type="button"
						onclick={() => (currentView = 'login')}
						class="text-sm text-primary hover:text-primary-dark transition-colors whitespace-nowrap ml-4"
					>
						Sign in
					</button>
				</div>

				{#if error}
					<div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
						{error}
					</div>
				{/if}

				<form
					onsubmit={(e) => {
						e.preventDefault();
						handleSignup();
					}}
					class="space-y-4"
				>
					<TextInput
						label="Email"
						type="email"
						bind:value={email}
						placeholder="you@example.com"
						error={fieldErrors.email}
						required
						autocomplete="email"
					/>

					<PasswordInput
						label="Password"
						bind:value={password}
						placeholder="Create a strong password"
						error={fieldErrors.password}
						required
						autocomplete="new-password"
						showStrength
					/>

					<PasswordInput
						label="Confirm Password"
						bind:value={confirmPassword}
						placeholder="Confirm your password"
						error={fieldErrors.confirmPassword}
						required
						autocomplete="new-password"
					/>

					<div class="flex items-start gap-2">
						<input
							type="checkbox"
							id="terms"
							bind:checked={termsAccepted}
							class="mt-1 h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
						/>
						<label for="terms" class="text-sm text-gray-600">
							I agree to the
							<a href="/terms" target="_blank" class="text-primary hover:text-primary-dark">
								Terms of Service
							</a>
							and
							<a href="/privacy" target="_blank" class="text-primary hover:text-primary-dark">
								Privacy Policy
							</a>
						</label>
					</div>

					<button
						type="submit"
						disabled={loading}
						class="w-full bg-primary hover:bg-primary-dark text-white rounded-lg px-4 py-3
                               transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
					>
						{loading ? 'Creating...' : 'Create Account'}
					</button>
				</form>
			{:else if currentView === 'verify-otp'}
				<div class="mb-8">
					<button
						onclick={goBack}
						class="text-sm text-primary hover:text-primary-dark transition-colors mb-4 flex items-center gap-1"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							class="h-4 w-4"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M15 19l-7-7 7-7"
							/>
						</svg>
						Back
					</button>
					<h1 class="text-3xl font-bold text-black mb-2">Verify Your Email</h1>
					<p class="text-gray-600">
						We've sent a 6-digit code to <span class="font-medium">{email}</span>
					</p>
				</div>

				{#if error}
					<div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
						{error}
					</div>
				{/if}

				<div class="space-y-6">
					<OTPInput
						bind:value={otpCode}
						onComplete={handleVerifyOTP}
						error={error && otpCode.length === 6 ? error : ''}
					/>

					<button
						type="button"
						onclick={handleVerifyOTP}
						disabled={loading || otpCode.length !== 6}
						class="w-full bg-primary hover:bg-primary-dark text-white rounded-lg px-4 py-3
                               transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
					>
						{loading ? 'Verifying...' : 'Verify Code'}
					</button>

					<div class="text-center">
						{#if resendCountdown > 0}
							<p class="text-sm text-gray-600">Resend code in {resendCountdown}s</p>
						{:else}
							<button
								type="button"
								onclick={handleResendOTP}
								disabled={loading}
								class="text-sm text-primary hover:text-primary-dark transition-colors disabled:opacity-50"
							>
								Resend code
							</button>
						{/if}
					</div>
				</div>
			{:else if currentView === 'email-auth'}
				<div class="mb-8">
					<button
						onclick={goBack}
						class="text-sm text-primary hover:text-primary-dark transition-colors mb-4 flex items-center gap-1"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							class="h-4 w-4"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M15 19l-7-7 7-7"
							/>
						</svg>
						Back
					</button>
					<h1 class="text-3xl font-bold text-black mb-2">Sign in with Email</h1>
					<p class="text-gray-600">Enter your email to receive a verification code</p>
				</div>

				{#if error}
					<div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
						{error}
					</div>
				{/if}

				<form
					onsubmit={(e) => {
						e.preventDefault();
						handleEmailAuth();
					}}
					class="space-y-4"
				>
					<TextInput
						label="Email"
						type="email"
						bind:value={email}
						placeholder="you@example.com"
						error={fieldErrors.email}
						required
						autocomplete="email"
					/>

					<button
						type="submit"
						disabled={loading}
						class="w-full bg-primary hover:bg-primary-dark text-white rounded-lg px-4 py-3
                               transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
					>
						{loading ? 'Sending...' : 'Continue with Email'}
					</button>
				</form>
			{:else if currentView === 'email-auth-otp'}
				<div class="mb-8">
					<button
						onclick={goBack}
						class="text-sm text-primary hover:text-primary-dark transition-colors mb-4 flex items-center gap-1"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							class="h-4 w-4"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M15 19l-7-7 7-7"
							/>
						</svg>
						Back
					</button>
					<h1 class="text-3xl font-bold text-black mb-2">Check Your Email</h1>
					<p class="text-gray-600">
						We've sent a verification code to <span class="font-medium">{email}</span>. Enter the
						6-digit code below or click the link in the email.
					</p>
				</div>

				{#if error}
					<div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
						{error}
					</div>
				{/if}

				<div class="space-y-6">
					<OTPInput
						bind:value={otpCode}
						onComplete={handleEmailAuthOTP}
						error={error && otpCode.length === 6 ? error : ''}
					/>

					<button
						type="button"
						onclick={handleEmailAuthOTP}
						disabled={loading || otpCode.length !== 6}
						class="w-full bg-primary hover:bg-primary-dark text-white rounded-lg px-4 py-3
                               transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
					>
						{loading ? 'Verifying...' : 'Verify Code'}
					</button>

					<div class="text-center">
						{#if resendCountdown > 0}
							<p class="text-sm text-gray-600">Resend code in {resendCountdown}s</p>
						{:else}
							<button
								type="button"
								onclick={handleResendEmailAuthOTP}
								disabled={loading}
								class="text-sm text-primary hover:text-primary-dark transition-colors disabled:opacity-50"
							>
								Resend code
							</button>
						{/if}
					</div>
				</div>
			{:else if currentView === 'forgot-password'}
				<div class="mb-8">
					<button
						onclick={() => (currentView = 'login')}
						class="text-sm text-primary hover:text-primary-dark transition-colors mb-4 flex items-center gap-1"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							class="h-4 w-4"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M15 19l-7-7 7-7"
							/>
						</svg>
						Back
					</button>
					<h1 class="text-3xl font-bold text-black mb-2">Reset Password</h1>
					<p class="text-gray-600">Enter your email to receive a password reset link</p>
				</div>

				{#if error}
					<div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
						{error}
					</div>
				{/if}

				<form
					onsubmit={(e) => {
						e.preventDefault();
						handleForgotPassword();
					}}
					class="space-y-4"
				>
					<TextInput
						label="Email"
						type="email"
						bind:value={email}
						placeholder="you@example.com"
						error={fieldErrors.email}
						required
						autocomplete="email"
					/>

					<button
						type="submit"
						disabled={loading}
						class="w-full bg-primary hover:bg-primary-dark text-white rounded-lg px-4 py-3
                               transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
					>
						{loading ? 'Sending...' : 'Send Reset Link'}
					</button>
				</form>
			{:else if currentView === 'forgot-password-otp'}
				<div class="mb-8">
					<button
						onclick={() => (currentView = 'forgot-password')}
						class="text-sm text-primary hover:text-primary-dark transition-colors mb-4 flex items-center gap-1"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							class="h-4 w-4"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M15 19l-7-7 7-7"
							/>
						</svg>
						Back
					</button>
					<h1 class="text-3xl font-bold text-black mb-2">Check Your Email</h1>
					<p class="text-gray-600">
						We've sent a password reset code to <span class="font-medium">{email}</span>. Enter the
						6-digit code below or click the link in the email.
					</p>
				</div>

				{#if error}
					<div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
						{error}
					</div>
				{/if}

				<div class="space-y-6">
					<OTPInput
						bind:value={otpCode}
						onComplete={handleForgotPasswordOTP}
						error={error && otpCode.length === 6 ? error : ''}
					/>

					<button
						type="button"
						onclick={handleForgotPasswordOTP}
						disabled={loading || otpCode.length !== 6}
						class="w-full bg-primary hover:bg-primary-dark text-white rounded-lg px-4 py-3
                               transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
					>
						{loading ? 'Verifying...' : 'Verify Code'}
					</button>

					<div class="text-center">
						{#if resendCountdown > 0}
							<p class="text-sm text-gray-600">Resend code in {resendCountdown}s</p>
						{:else}
							<button
								type="button"
								onclick={handleResendForgotPasswordOTP}
								disabled={loading}
								class="text-sm text-primary hover:text-primary-dark transition-colors disabled:opacity-50"
							>
								Resend code
							</button>
						{/if}
					</div>
				</div>
			{/if}
		</div>
	</div>
</div>
