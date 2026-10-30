<script lang="ts">
import { onDestroy, onMount } from 'svelte'
import { goto } from '$app/navigation'
import {
	login_with_email_pass,
	request_password_reset,
	resend_otp,
	sign_in_with_magic_link_to,
	sign_up_with_password,
	verify_otp
} from '$lib/api/auth'
import AuthFlowShell from '$lib/components/auth/AuthFlowShell.svelte'
import OTPInput from '$lib/components/auth/OTPInput.svelte'
import PasswordInput from '$lib/components/auth/PasswordInput.svelte'
import TextInput from '$lib/components/auth/TextInput.svelte'
import { storeSelectedTier } from '$lib/utils/onboarding'

type View =
	| 'login'
	| 'signup'
	| 'verify-otp'
	| 'email-auth'
	| 'email-auth-otp'
	| 'forgot-password'
	| 'forgot-password-otp'

let currentView = $state<View>('login')
let email = $state('')
let password = $state('')
let confirmPassword = $state('')
let otpCode = $state('')
let selectedTierName = $state('')
let nextPath = $state<string | null>(null)

let loading = $state(false)
let error = $state('')
let resendCountdown = $state(0)
let otpSubmissionKey = $state<string | null>(null)

let fieldErrors = $state({
	email: '',
	password: '',
	confirmPassword: ''
})

function requireEmail(): boolean {
	fieldErrors.email = ''
	if (email.trim()) return true
	fieldErrors.email = 'Email is required'
	return false
}

onMount(() => {
	const urlParams = new URLSearchParams(window.location.search)
	const view = urlParams.get('view')
	const tier = urlParams.get('tier')
	const next = urlParams.get('next')
	if (view === 'signup') {
		currentView = 'signup'
	}
	if (tier === 'tier1' || tier === 'tier2') {
		storeSelectedTier(tier)
		selectedTierName = tier === 'tier2' ? 'Professional' : 'Starter'
	}
	if (next?.startsWith('/') && !next.startsWith('//')) {
		nextPath = next
	}
})

onDestroy(() => {
	if (countdownInterval) {
		clearInterval(countdownInterval)
	}
})

let countdownInterval: number | undefined

function clearMessages() {
	error = ''
	fieldErrors.email = ''
	fieldErrors.password = ''
	fieldErrors.confirmPassword = ''
}

function setView(nextView: View) {
	currentView = nextView
	clearMessages()
	if (!nextView.includes('otp')) {
		otpCode = ''
	}
	if (countdownInterval && !nextView.includes('otp')) {
		clearInterval(countdownInterval)
		resendCountdown = 0
	}
}

function startResendCountdown() {
	if (countdownInterval) {
		clearInterval(countdownInterval)
	}

	resendCountdown = 60
	countdownInterval = window.setInterval(() => {
		resendCountdown--
		if (resendCountdown <= 0 && countdownInterval) {
			clearInterval(countdownInterval)
		}
	}, 1000)
}

function goBack() {
	setView('login')
	password = ''
	confirmPassword = ''
}

function getPostAuthPath(defaultPath: '/dashboard' | '/setup' | '/reset') {
	return nextPath ?? defaultPath
}

function navigateAfterAuth(path: string = '/dashboard') {
	goto(path)
}

function requireOtpCode(): boolean {
	if (loading) return false
	if (otpCode.length === 6) return true
	error = 'Enter the 6-digit code'
	return false
}

function getTitle() {
	switch (currentView) {
		case 'signup':
			return 'Create your account'
		case 'verify-otp':
			return 'Verify your email'
		case 'email-auth':
			return 'Sign in without a password'
		case 'email-auth-otp':
			return 'Check your inbox'
		case 'forgot-password':
			return 'Reset your password'
		case 'forgot-password-otp':
			return 'Check your inbox'
		default:
			return 'Sign in to Vitevue'
	}
}

function getDescription() {
	switch (currentView) {
		case 'signup':
			return selectedTierName ? `Continue with the ${selectedTierName} plan.` : ''
		case 'verify-otp':
			return `Enter the code sent to ${email}.`
		case 'email-auth':
			return ''
		case 'email-auth-otp':
			return `Enter the code sent to ${email}.`
		case 'forgot-password':
			return ''
		case 'forgot-password-otp':
			return `Enter the code sent to ${email}.`
		default:
			return ''
	}
}

async function verifyOtpFlow(type: 'signup' | 'magiclink' | 'recovery', successPath: string) {
	if (!requireOtpCode()) return
	const submissionKey = `${type}:${email}:${otpCode}`
	if (otpSubmissionKey === submissionKey) return

	otpSubmissionKey = submissionKey
	loading = true
	error = ''

	try {
		const result = await verify_otp(email, otpCode, type)
		if (result.success) {
			navigateAfterAuth(successPath)
		} else {
			error = result.error || 'Invalid verification code'
		}
	} finally {
		loading = false
		otpSubmissionKey = null
	}
}

async function resendCodeFlow(send: () => Promise<{ success: boolean; error?: string }>) {
	if (loading) return

	loading = true
	error = ''

	try {
		const result = await send()
		if (result.success) {
			startResendCountdown()
		} else {
			error = result.error || 'Failed to resend code'
		}
	} finally {
		loading = false
	}
}

async function handleLogin() {
	fieldErrors.password = ''
	if (!password) {
		fieldErrors.password = 'Password is required'
		return
	}

	loading = true
	error = ''

	try {
		const result = await login_with_email_pass(email, password)
		if (result.success) {
			navigateAfterAuth(getPostAuthPath('/dashboard'))
		} else {
			error = result.error || 'Invalid email or password'
		}
	} finally {
		loading = false
	}
}

async function handleSignup() {
	fieldErrors.password = ''
	fieldErrors.confirmPassword = ''

	if (!password) {
		fieldErrors.password = 'Password is required'
		return
	}
	if (password.length < 8) {
		fieldErrors.password = 'Password must be at least 8 characters'
		return
	}
	if (!confirmPassword) {
		fieldErrors.confirmPassword = 'Please confirm your password'
		return
	}
	if (password !== confirmPassword) {
		fieldErrors.confirmPassword = 'Passwords do not match'
		return
	}

	loading = true
	error = ''

	try {
		const result = await sign_up_with_password(email, password, '', '', getPostAuthPath('/setup'))
		if (result.success) {
			if (result.data?.session) {
				navigateAfterAuth(getPostAuthPath('/setup'))
			} else {
				setView('verify-otp')
				startResendCountdown()
			}
		} else {
			error = result.error || 'Sign up failed'
		}
	} catch {
		error = 'Sign up failed. Try again.'
	} finally {
		loading = false
	}
}

async function handleVerifyOTP() {
	await verifyOtpFlow('signup', getPostAuthPath('/setup'))
}

async function handleResendOTP() {
	await resendCodeFlow(() => resend_otp(email, 'signup'))
}

async function handleEmailAuth() {
	if (!requireEmail()) return

	loading = true
	error = ''

	try {
		const result = await sign_in_with_magic_link_to(email, getPostAuthPath('/dashboard'))
		if (result.success) {
			setView('email-auth-otp')
			startResendCountdown()
		} else {
			error = result.error || 'Failed to send verification code'
		}
	} finally {
		loading = false
	}
}

async function handleEmailAuthOTP() {
	await verifyOtpFlow('magiclink', getPostAuthPath('/dashboard'))
}

async function handleResendEmailAuthOTP() {
	await resendCodeFlow(() => sign_in_with_magic_link_to(email, getPostAuthPath('/dashboard')))
}

async function handleForgotPassword() {
	if (!requireEmail()) return

	loading = true
	error = ''

	try {
		const result = await request_password_reset(email)
		if (result.success) {
			setView('forgot-password-otp')
			startResendCountdown()
		} else {
			error = result.error || 'Failed to send reset email'
		}
	} catch {
		error = 'Failed to send reset email. Please try again.'
	} finally {
		loading = false
	}
}

async function handleForgotPasswordOTP() {
	await verifyOtpFlow('recovery', '/reset')
}

async function handleResendForgotPasswordOTP() {
	try {
		await resendCodeFlow(() => request_password_reset(email))
	} catch {
		error = 'Failed to resend code. Please try again.'
	}
}
</script>

<svelte:head>
	<title>Sign In - Vitevue</title>
</svelte:head>

<AuthFlowShell
	title={getTitle()}
	description={getDescription()}
	eyebrow="Vitevue"
	sideAccent="Workspace"
	sideTitle="One place for transactions, feasibility work, and commercial decisions."
	cardViewportFill={false}
	panelClass="lg:min-h-[min(calc(100vh-2rem),49rem)]"
	sectionWidthClass="lg:max-w-xl xl:max-w-2xl lg:h-auto"
	cardClass="lg:self-stretch"
	headerClass="min-h-[7.25rem] sm:min-h-[6.5rem]"
>
	<svelte:fragment slot="side">
		<div class="space-y-4">
			{#if selectedTierName}
				<div class="rounded-lg border border-[rgba(246,241,231,0.16)] bg-[color:rgba(246,241,231,0.06)] p-5">
					<p
						class="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-on-navy-muted"
					>
						Selected plan
					</p>
					<p class="mt-3 font-display text-4xl font-normal text-on-navy">
						{selectedTierName}
					</p>
				</div>
			{/if}

			<div class="rounded-lg border border-[rgba(246,241,231,0.14)] bg-[color:rgba(246,241,231,0.05)] p-4">
				<p class="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-on-navy-muted">
					Market data
				</p>
				<p class="mt-2 font-display text-[2.15rem] font-normal leading-none text-on-navy">
					10M+ transactions
				</p>
			</div>

			<div class="divide-y divide-[rgba(246,241,231,0.12)] rounded-lg border border-[rgba(246,241,231,0.12)] bg-[color:rgba(246,241,231,0.04)] px-4">
				<div class="py-2.5">
					<p class="text-sm font-semibold text-on-navy">Sales and rentals</p>
				</div>
				<div class="py-2.5">
					<p class="text-sm font-semibold text-on-navy">Feasibility workflow</p>
				</div>
				<div class="py-2.5">
					<p class="text-sm font-semibold text-on-navy">Team access</p>
				</div>
			</div>
		</div>
	</svelte:fragment>

	<div class="flex flex-col gap-4">
		{#if currentView === 'login' || currentView === 'signup'}
			<div class="grid grid-cols-2 rounded-lg border border-border bg-panel p-1">
				<button
					type="button"
					onclick={() => setView('login')}
					class="rounded-md border px-4 py-2.5 text-sm font-medium transition {currentView ===
					'login'
						? 'border-action bg-action text-on-action shadow-xs'
						: 'border-transparent text-fg-3 hover:border-strong hover:bg-card hover:text-fg-1'}"
				>
					Sign in
				</button>
				<button
					type="button"
					onclick={() => setView('signup')}
					class="rounded-md border px-4 py-2.5 text-sm font-medium transition {currentView ===
					'signup'
						? 'border-action bg-action text-on-action shadow-xs'
						: 'border-transparent text-fg-3 hover:border-strong hover:bg-card hover:text-fg-1'}"
				>
					Create account
				</button>
			</div>
		{:else}
			<button
				type="button"
				onclick={goBack}
				class="inline-flex items-center gap-2 text-sm font-medium text-fg-3 transition hover:text-fg-1"
			>
				<svg
					class="h-4 w-4"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					viewBox="0 0 24 24"
					aria-hidden="true"
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
				</svg>
				Back to sign in
			</button>
		{/if}

		{#if error}
			<div class="rounded-lg border border-error-border bg-error-bg px-4 py-3 text-sm text-error">
				{error}
			</div>
		{/if}

		{#if currentView === 'login'}
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

				<div class="flex items-center justify-between gap-3">
					<button
						type="button"
						onclick={() => setView('forgot-password')}
						class="text-sm font-medium text-fg-4 transition hover:text-fg-1"
					>
						Forgot password?
					</button>
				</div>

				<button
					type="submit"
					disabled={loading}
					class="w-full rounded-md bg-action px-4 py-3.5 text-sm font-semibold text-on-action transition hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
				>
					{loading ? 'Signing in...' : 'Sign in'}
				</button>

				<button
					type="button"
					onclick={() => setView('email-auth')}
					class="w-full rounded-md border border-border bg-card px-4 py-3 text-sm font-medium text-fg-2 transition hover:border-strong hover:bg-panel hover:text-fg-1"
				>
					Sign in with email code instead
				</button>
			</form>
		{:else if currentView === 'email-auth'}
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

				<div class="flex items-center justify-between gap-3">
					<button
						type="button"
						onclick={() => setView('forgot-password')}
						class="text-sm font-medium text-fg-4 transition hover:text-fg-1"
					>
						Need a password reset?
					</button>
					<button
						type="button"
						onclick={() => setView('login')}
						class="text-sm font-medium text-fg-4 transition hover:text-fg-1"
					>
						Use password instead
					</button>
				</div>

				<button
					type="submit"
					disabled={loading}
					class="w-full rounded-md bg-action px-4 py-3.5 text-sm font-semibold text-on-action transition hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
				>
					{loading ? 'Sending code...' : 'Send sign-in code'}
				</button>
			</form>
		{:else if currentView === 'signup'}
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
					label="Confirm password"
					bind:value={confirmPassword}
					placeholder="Confirm your password"
					error={fieldErrors.confirmPassword}
					required
					autocomplete="new-password"
				/>

				<button
					type="submit"
					disabled={loading}
					class="w-full rounded-md bg-action px-4 py-3.5 text-sm font-semibold text-on-action transition hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
				>
					{loading ? 'Creating account...' : 'Create account'}
				</button>
			</form>
		{:else if currentView === 'verify-otp' || currentView === 'email-auth-otp' || currentView === 'forgot-password-otp'}
			<div class="space-y-6">
				<OTPInput
					bind:value={otpCode}
					disabled={loading}
					onComplete={currentView === 'verify-otp'
						? handleVerifyOTP
						: currentView === 'email-auth-otp'
							? handleEmailAuthOTP
							: handleForgotPasswordOTP}
					error={error && otpCode.length === 6 ? error : ''}
				/>

				<button
					type="button"
					onclick={currentView === 'verify-otp'
						? handleVerifyOTP
						: currentView === 'email-auth-otp'
							? handleEmailAuthOTP
							: handleForgotPasswordOTP}
					disabled={loading || otpCode.length !== 6}
					class="w-full rounded-md bg-action px-4 py-3.5 text-sm font-semibold text-on-action transition hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
				>
					{loading ? 'Verifying...' : 'Verify code'}
				</button>

				<div
					class="rounded-md border border-border bg-panel px-4 py-3 text-sm text-fg-3"
				>
					{#if resendCountdown > 0}
						Resend code in {resendCountdown}s
					{:else if currentView === 'verify-otp'}
						<button
							type="button"
							onclick={handleResendOTP}
							disabled={loading}
							class="font-medium text-fg-1 transition hover:text-fg-3 disabled:opacity-50"
						>
							Resend code
						</button>
					{:else if currentView === 'email-auth-otp'}
						<button
							type="button"
							onclick={handleResendEmailAuthOTP}
							disabled={loading}
							class="font-medium text-fg-1 transition hover:text-fg-3 disabled:opacity-50"
						>
							Resend code
						</button>
					{:else}
						<button
							type="button"
							onclick={handleResendForgotPasswordOTP}
							disabled={loading}
							class="font-medium text-fg-1 transition hover:text-fg-3 disabled:opacity-50"
						>
							Resend code
						</button>
					{/if}
				</div>
			</div>
		{:else if currentView === 'forgot-password'}
			<form
				onsubmit={(e) => {
					e.preventDefault();
					handleForgotPassword();
				}}
				class="space-y-5"
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
					class="w-full rounded-md bg-action px-4 py-3.5 text-sm font-semibold text-on-action transition hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
				>
					{loading ? 'Sending reset email...' : 'Send reset email'}
				</button>
			</form>
		{/if}
	</div>
</AuthFlowShell>
