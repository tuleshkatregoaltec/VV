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

	type Tab = 'signin' | 'signup';
	type Method = 'password' | 'magic';
	type View = 'form' | 'verify-otp' | 'magic-sent' | 'forgot-password' | 'reset-sent';

	let activeTab = $state<Tab>('signin');
	let authMethod = $state<Method>('password');
	let currentView = $state<View>('form');

	let firstName = $state('');
	let lastName = $state('');
	let email = $state('');
	let password = $state('');
	let confirmPassword = $state('');
	let otpCode = $state('');

	let loading = $state(false);
	let error = $state('');
	let resendCountdown = $state(0);

	let fieldErrors = $state({
		firstName: '',
		lastName: '',
		email: '',
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

	function validateForm(): boolean {
		fieldErrors = {
			firstName: '',
			lastName: '',
			email: '',
			password: '',
			confirmPassword: ''
		};

		let isValid = true;

		if (activeTab === 'signup') {
			if (!firstName.trim()) {
				fieldErrors.firstName = 'First name is required';
				isValid = false;
			}
			if (!lastName.trim()) {
				fieldErrors.lastName = 'Last name is required';
				isValid = false;
			}
		}

		if (!email.trim()) {
			fieldErrors.email = 'Email is required';
			isValid = false;
		} else if (!validateEmail(email)) {
			fieldErrors.email = 'Invalid email address';
			isValid = false;
		}

		if (authMethod === 'password') {
			if (!password) {
				fieldErrors.password = 'Password is required';
				isValid = false;
			} else if (activeTab === 'signup' && password.length < 8) {
				fieldErrors.password = 'Password must be at least 8 characters';
				isValid = false;
			}

			if (activeTab === 'signup') {
				if (!confirmPassword) {
					fieldErrors.confirmPassword = 'Please confirm your password';
					isValid = false;
				} else if (password !== confirmPassword) {
					fieldErrors.confirmPassword = 'Passwords do not match';
					isValid = false;
				}
			}
		}

		return isValid;
	}

	async function handleSignIn() {
		if (!validateForm()) return;

		loading = true;
		error = '';

		try {
			if (authMethod === 'password') {
				const result = await login_with_email_pass(email, password);
				if (result.success) {
					// Identify user on successful login
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

	async function handleSignUp() {
		if (!validateForm()) return;

		loading = true;
		error = '';

		try {
			if (authMethod === 'password') {
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
				// Identify user on successful login
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
		if (!email.trim()) {
			fieldErrors.email = 'Email is required';
			return;
		}
		if (!validateEmail(email)) {
			fieldErrors.email = 'Invalid email address';
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

	function switchTab(tab: Tab) {
		activeTab = tab;
		error = '';
		fieldErrors = {
			firstName: '',
			lastName: '',
			email: '',
			password: '',
			confirmPassword: ''
		};
	}

	function switchMethod(method: Method) {
		authMethod = method;
		error = '';
		password = '';
		confirmPassword = '';
	}

	function goBackToForm() {
		currentView = 'form';
		error = '';
		otpCode = '';
		if (countdownInterval) {
			clearInterval(countdownInterval);
		}
	}
</script>

<div class="min-h-screen bg-gradient-to-br from-primary-pale via-white to-accent-pale flex items-center justify-center p-4">
	<div class="w-full max-w-md">
		<div class="bg-white/80 backdrop-blur-xl rounded-xl shadow-lg border border-primary-pale p-8">
			{#if currentView === 'form'}
				<div class="mb-8">
					<h1 class="text-3xl font-bold text-primary mb-2">
						{activeTab === 'signin' ? 'Welcome Back' : 'Create Account'}
					</h1>
					<p class="text-gray-600">
						{activeTab === 'signin'
							? 'Sign in to access your dashboard'
							: 'Sign up to get started'}
					</p>
				</div>

				<div class="flex gap-2 mb-6 bg-gray-100 p-1 rounded-lg">
					<button
						onclick={() => switchTab('signin')}
						class="flex-1 py-2 px-4 rounded-md text-sm font-medium transition-all
                               {activeTab === 'signin'
							? 'bg-white text-primary shadow-sm'
							: 'text-gray-600 hover:text-primary'}"
					>
						Sign In
					</button>
					<button
						onclick={() => switchTab('signup')}
						class="flex-1 py-2 px-4 rounded-md text-sm font-medium transition-all
                               {activeTab === 'signup'
							? 'bg-white text-primary shadow-sm'
							: 'text-gray-600 hover:text-primary'}"
					>
						Sign Up
					</button>
				</div>

				<div class="flex gap-2 mb-6">
					<button
						onclick={() => switchMethod('password')}
						class="flex-1 py-2 px-4 border rounded-lg text-sm font-medium transition-all
                               {authMethod === 'password'
							? 'border-primary bg-primary/5 text-primary'
							: 'border-gray-200 text-gray-600 hover:border-primary/50'}"
					>
						Password
					</button>
					<button
						onclick={() => switchMethod('magic')}
						class="flex-1 py-2 px-4 border rounded-lg text-sm font-medium transition-all
                               {authMethod === 'magic'
							? 'border-primary bg-primary/5 text-primary'
							: 'border-gray-200 text-gray-600 hover:border-primary/50'}"
					>
						Magic Link
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
						activeTab === 'signin' ? handleSignIn() : handleSignUp();
					}}
					class="space-y-4"
				>
					{#if activeTab === 'signup'}
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
					{/if}

					<TextInput
						label="Email"
						type="email"
						bind:value={email}
						placeholder="you@example.com"
						error={fieldErrors.email}
						required
						autocomplete="email"
					/>

					{#if authMethod === 'password'}
						<PasswordInput
							label="Password"
							bind:value={password}
							placeholder="Enter your password"
							error={fieldErrors.password}
							required
							autocomplete={activeTab === 'signin' ? 'current-password' : 'new-password'}
							showStrength={activeTab === 'signup'}
						/>

						{#if activeTab === 'signup'}
							<PasswordInput
								label="Confirm Password"
								bind:value={confirmPassword}
								placeholder="Confirm your password"
								error={fieldErrors.confirmPassword}
								required
								autocomplete="new-password"
							/>
						{/if}

						{#if activeTab === 'signin'}
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
					{/if}

					<button
						type="submit"
						disabled={loading}
						class="w-full bg-primary hover:bg-primary-dark text-white rounded-lg px-4 py-3
                               transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
					>
						{#if loading}
							Processing...
						{:else if activeTab === 'signin'}
							{authMethod === 'password' ? 'Sign In' : 'Send Magic Link'}
						{:else}
							{authMethod === 'password' ? 'Create Account' : 'Send Magic Link'}
						{/if}
					</button>
				</form>
			{:else if currentView === 'verify-otp'}
				<div class="mb-8">
					<button
						onclick={goBackToForm}
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
					<h1 class="text-3xl font-bold text-primary mb-2">Verify Your Email</h1>
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
					<h1 class="text-3xl font-bold text-primary mb-2">Check Your Email</h1>
					<p class="text-gray-600 mb-6">
						We've sent a magic link to <span class="font-medium">{email}</span>. Click the link in
						the email to sign in.
					</p>
					<button
						onclick={goBackToForm}
						class="text-primary hover:text-primary-dark transition-colors"
					>
						Back to sign in
					</button>
				</div>
			{:else if currentView === 'forgot-password'}
				<div class="mb-8">
					<button
						onclick={goBackToForm}
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
					<h1 class="text-3xl font-bold text-primary mb-2">Reset Password</h1>
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
					<h1 class="text-3xl font-bold text-primary mb-2">Check Your Email</h1>
					<p class="text-gray-600 mb-6">
						We've sent a password reset link to <span class="font-medium">{email}</span>. Click
						the link in the email to reset your password.
					</p>
					<button
						onclick={goBackToForm}
						class="text-primary hover:text-primary-dark transition-colors"
					>
						Back to sign in
					</button>
				</div>
			{/if}
		</div>
	</div>
</div>
