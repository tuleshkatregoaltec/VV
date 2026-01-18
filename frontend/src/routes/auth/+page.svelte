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
		sign_up_with_magic_link,
		verify_otp,
		resend_otp,
		request_password_reset,
		get_session,
		identifyUser,
		me
	} from '$lib/api/auth';

	type View = 'login' | 'signup' | 'verify-otp' | 'magic-sent' | 'forgot-password' | 'reset-sent';
	type SignupMethod = 'password' | 'magic';
	type LoginMethod = 'password' | 'magic';

	let currentView = $state<View>('login');
	let email = $state('');
	let firstName = $state('');
	let lastName = $state('');
	let password = $state('');
	let confirmPassword = $state('');
	let otpCode = $state('');

	let loading = $state(false);
	let error = $state('');
	let resendCountdown = $state(0);
	let signupMethod = $state<SignupMethod>('password');
	let loginMethod = $state<LoginMethod>('password');

	let fieldErrors = $state({
		email: '',
		firstName: '',
		lastName: '',
		password: '',
		confirmPassword: ''
	});

	onMount(async () => {
		const session = await get_session();
		if (session) {
			goto('/dashboard');
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

	function validateEmail(email: string): boolean {
		return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
	}

	function goBack() {
		currentView = 'login';
		error = '';
		password = '';
		confirmPassword = '';
		otpCode = '';
		firstName = '';
		lastName = '';
		signupMethod = 'password';
		if (countdownInterval) {
			clearInterval(countdownInterval);
		}
	}

	async function handleLogin() {
		fieldErrors.password = '';
		if (loginMethod === 'password') {
			if (!password) {
				fieldErrors.password = 'Password is required';
				return;
			}
		}

		loading = true;
		error = '';

		try {
			if (loginMethod === 'password') {
				const result = await login_with_email_pass(email, password);
				if (result.success) {
					const user = await me();
					identifyUser(user);
					goto('/dashboard');
				} else {
					error = result.error || 'Invalid email or password';
				}
			} else {
				const result = await sign_in_with_magic_link(email);
				if (result.success) {
					currentView = 'magic-sent';
				} else {
					error = result.error || 'Failed to send magic link';
				}
			}
		} finally {
			loading = false;
		}
	}

	async function handleSignup() {
		fieldErrors.firstName = '';
		fieldErrors.lastName = '';
		fieldErrors.password = '';
		fieldErrors.confirmPassword = '';

		if (!firstName.trim()) {
			fieldErrors.firstName = 'First name is required';
			return;
		}
		if (!lastName.trim()) {
			fieldErrors.lastName = 'Last name is required';
			return;
		}

		if (signupMethod === 'password') {
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
		}

		loading = true;
		error = '';

		try {
			if (signupMethod === 'password') {
				const result = await sign_up_with_password(email, password, firstName, lastName);
				if (result.success) {
					currentView = 'verify-otp';
					startResendCountdown();
				} else {
					error = result.error || 'Sign up failed';
				}
			} else {
				const result = await sign_up_with_magic_link(email, firstName, lastName);
				if (result.success) {
					currentView = 'magic-sent';
				} else {
					error = result.error || 'Failed to send magic link';
				}
			}
		} finally {
			loading = false;
		}
	}

	async function handleVerifyOTP() {
		if (otpCode.length !== 6) {
			error = 'Please enter the complete 6-digit code';
			return;
		}

		loading = true;
		error = '';

		try {
			const result = await verify_otp(email, otpCode, 'signup');
			if (result.success) {
				const user = await me();
				identifyUser(user);
				goto('/dashboard');
			} else {
				error = result.error || 'Invalid verification code';
			}
		} finally {
			loading = false;
		}
	}

	async function handleResendOTP() {
		loading = true;
		error = '';

		try {
			const result = await resend_otp(email, 'signup');
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
				currentView = 'reset-sent';
			} else {
				error = result.error || 'Failed to send reset email';
			}
		} finally {
			loading = false;
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

				<div class="flex gap-2 mb-6">
					<button
						type="button"
						onclick={() => (loginMethod = 'password')}
						class="flex-1 py-2 px-4 border rounded-lg text-sm font-medium transition-all
                               {loginMethod === 'password'
							? 'border-primary bg-primary/5 text-primary'
							: 'border-gray-200 text-gray-600 hover:border-primary/50'}"
					>
						Password
					</button>
					<button
						type="button"
						onclick={() => (loginMethod = 'magic')}
						class="flex-1 py-2 px-4 border rounded-lg text-sm font-medium transition-all
                               {loginMethod === 'magic'
							? 'border-primary bg-primary/5 text-primary'
							: 'border-gray-200 text-gray-600 hover:border-primary/50'}"
					>
						Magic Link
					</button>
				</div>

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
					{#if loginMethod === 'password'}
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
					{/if}

					<button
						type="submit"
						disabled={loading}
						class="w-full bg-primary hover:bg-primary-dark text-white rounded-lg px-4 py-3
                               transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
					>
						{#if loading}
							Processing...
						{:else if loginMethod === 'password'}
							Sign In
						{:else}
							Send Magic Link
						{/if}
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

				<div class="flex gap-2 mb-6">
					<button
						type="button"
						onclick={() => (signupMethod = 'password')}
						class="flex-1 py-2 px-4 border rounded-lg text-sm font-medium transition-all
                               {signupMethod === 'password'
							? 'border-primary bg-primary/5 text-primary'
							: 'border-gray-200 text-gray-600 hover:border-primary/50'}"
					>
						Password
					</button>
					<button
						type="button"
						onclick={() => (signupMethod = 'magic')}
						class="flex-1 py-2 px-4 border rounded-lg text-sm font-medium transition-all
                               {signupMethod === 'magic'
							? 'border-primary bg-primary/5 text-primary'
							: 'border-gray-200 text-gray-600 hover:border-primary/50'}"
					>
						Magic Link
					</button>
				</div>

				<form
					onsubmit={(e) => {
						e.preventDefault();
						handleSignup();
					}}
					class="space-y-4"
				>
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

					<TextInput
						label="Email"
						type="email"
						bind:value={email}
						placeholder="you@example.com"
						disabled
					/>

					{#if signupMethod === 'password'}
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
					{/if}

					<button
						type="submit"
						disabled={loading}
						class="w-full bg-primary hover:bg-primary-dark text-white rounded-lg px-4 py-3
                               transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
					>
						{#if loading}
							Creating...
						{:else if signupMethod === 'password'}
							Create Account
						{:else}
							Send Magic Link
						{/if}
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
			{:else if currentView === 'magic-sent'}
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
								d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
							/>
						</svg>
					</div>
					<h1 class="text-3xl font-bold text-black mb-2">Check Your Email</h1>
					<p class="text-gray-600 mb-6">
						We've sent a magic link to <span class="font-medium">{email}</span>. Click the link in
						the email to sign in.
					</p>
					<button
						type="button"
						onclick={goBack}
						class="text-primary hover:text-primary-dark transition-colors"
					>
						Back to sign in
					</button>
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
			{:else if currentView === 'reset-sent'}
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
								d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
							/>
						</svg>
					</div>
					<h1 class="text-3xl font-bold text-black mb-2">Check Your Email</h1>
					<p class="text-gray-600 mb-6">
						We've sent a password reset link to <span class="font-medium">{email}</span>. Click
						the link in the email to reset your password.
					</p>
					<button
						type="button"
						onclick={goBack}
						class="text-primary hover:text-primary-dark transition-colors"
					>
						Back to sign in
					</button>
				</div>
			{/if}
		</div>
	</div>
</div>
