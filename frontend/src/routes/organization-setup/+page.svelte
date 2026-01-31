<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { me } from '$lib/api/auth';
	import { createCheckoutSession } from '$lib/api/billing';

	let firstName = $state('');
	let lastName = $state('');
	let organizationName = $state('');
	let seats = $state(3);
	let customSeats = $state('');
	let useCustomSeats = $state(false);
	let loading = $state(false);
	let error = $state('');
	let userLoaded = $state(false);
	let selectedTier = $state<'tier1' | 'tier2'>('tier1');

	const commonSeatOptions = [1, 3, 5, 8, 10];

	// Pricing tiers
	const TIER1_PRICE = 990;
	const TIER2_PRICE = 890;
	const TIER1_NAME = 'Professional';
	const TIER2_NAME = 'Enterprise';

	// Computed values
	const isValidSeatCount = $derived(seats >= 1 && seats <= 10);
	const isEnterpriseRange = $derived(seats > 10);
	const pricePerSeat = $derived(selectedTier === 'tier1' ? TIER1_PRICE : TIER2_PRICE);
	const totalMonthly = $derived(seats * pricePerSeat);
	const tierName = $derived(selectedTier === 'tier1' ? TIER1_NAME : TIER2_NAME);

	onMount(async () => {
		try {
			const user = await me();
			firstName = user.first_name || '';
			lastName = user.last_name || '';

			// Redirect to profile setup if name not set
			if (!firstName || !lastName) {
				goto('/profile-setup');
				return;
			}

			// Get tier from URL parameter or localStorage
			const tierParam = $page.url.searchParams.get('tier');
			if (tierParam === 'tier1' || tierParam === 'tier2') {
				selectedTier = tierParam;
				// Clear from localStorage since we got it from URL
				localStorage.removeItem('selected_tier');
			} else {
				// Fallback to localStorage if no URL param
				const storedTier = localStorage.getItem('selected_tier');
				if (storedTier === 'tier1' || storedTier === 'tier2') {
					selectedTier = storedTier;
					localStorage.removeItem('selected_tier');
				}
			}

			organizationName = `${firstName}'s Organization`;
			userLoaded = true;
		} catch (err) {
			// User not authenticated, redirect to auth
			goto('/auth?view=signup');
		}
	});

	function handleSeatSelection(value: number) {
		useCustomSeats = false;
		customSeats = '';
		seats = value;
	}

	function handleCustomSeatsChange() {
		const parsed = parseInt(customSeats);
		if (!isNaN(parsed) && parsed >= 1) {
			seats = parsed;
		}
	}

	async function handleSubmit() {
		if (!organizationName.trim()) {
			error = 'Organization name is required';
			return;
		}

		if (!isValidSeatCount) {
			error = 'Please select a valid number of seats';
			return;
		}

		if (isEnterpriseRange) {
			error = 'For 11+ seats, please contact sales at contact@vitevue.com';
			return;
		}

		loading = true;
		error = '';

		try {
			const result = await createCheckoutSession(
				firstName.trim(),
				lastName.trim(),
				organizationName.trim(),
				seats,
				selectedTier
			);
			// Redirect to Stripe Checkout
			window.location.href = result.checkout_url;
		} catch (err: any) {
			error = err.message || 'Failed to create checkout session. Please try again.';
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>Organization Setup - Vitevue</title>
</svelte:head>

<div class="min-h-screen bg-gradient-to-br from-slate-50 to-white flex items-center justify-center p-4">
	<div class="w-full max-w-2xl">
		<div class="bg-white rounded-xl shadow-lg p-8">
			<!-- Header -->
			<div class="mb-8">
				<h1 class="text-3xl font-bold text-slate-900 mb-2">Set up your organization</h1>
				<p class="text-slate-600">
					Complete your {tierName} plan setup
				</p>
			</div>

			<!-- Selected Tier Display -->
			<div class="mb-6 p-4 bg-slate-50 border border-slate-200 rounded-lg flex items-center justify-between">
				<div>
					<p class="text-sm text-slate-600">Selected Plan</p>
					<p class="text-lg font-semibold text-slate-900">{tierName}</p>
				</div>
				<div class="text-right">
					<p class="text-sm text-slate-600">Price per seat</p>
					<p class="text-lg font-semibold text-slate-900">{pricePerSeat} AED/month</p>
				</div>
			</div>

			{#if error}
				<div class="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
					{error}
				</div>
			{/if}

			{#if userLoaded}
				<form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }} class="space-y-6">
					<!-- Organization Name -->
				<div>
					<label for="orgName" class="block text-sm font-medium text-slate-700 mb-2">
						Organization Name
					</label>
					<input
						id="orgName"
						type="text"
						bind:value={organizationName}
						placeholder="Your Company Name"
						class="w-full px-4 py-3 border border-slate-300 rounded-lg focus:ring-2 focus:ring-slate-900 focus:border-transparent"
						required
					/>
				</div>

				<!-- Seat Selection -->
				<div>
				<div class="block text-sm font-medium text-slate-700 mb-3">
					Number of Seats
				</div>
				<div class="flex gap-2 mb-4">
					{#each commonSeatOptions as option}
						<button
							type="button"
							onclick={() => handleSeatSelection(option)}
							class="px-4 py-3 rounded-lg border-2 font-medium transition-all {seats === option && !useCustomSeats
								? 'border-slate-900 bg-slate-900 text-white'
								: 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'}"
						>
							{option}
						</button>
					{/each}
				</div>

				<div class="flex items-center gap-2">
					<input
						type="checkbox"
						id="customSeats"
						bind:checked={useCustomSeats}
						class="h-4 w-4 rounded border-gray-300 text-slate-900 focus:ring-slate-900"
					/>
					<label for="customSeats" class="text-sm text-slate-600">
						Custom amount (1-10 seats)
					</label>
				</div>

					{#if useCustomSeats}
						<div class="mt-2">
							<input
								type="number"
								bind:value={customSeats}
								oninput={handleCustomSeatsChange}
								min="1"
								max="10"
								placeholder="Enter number of seats"
								class="w-full px-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-slate-900 focus:border-transparent"
							/>
						</div>
					{/if}
				</div>

				<!-- Pricing Display -->
				{#if isValidSeatCount && !isEnterpriseRange}
					<div class="bg-slate-50 rounded-lg p-6 border border-slate-200">
						<div class="flex items-center justify-between py-3">
							<span class="text-slate-700">{seats} {seats === 1 ? 'seat' : 'seats'} × {pricePerSeat} AED</span>
							<span class="text-2xl font-bold text-slate-900">{totalMonthly} AED/month</span>
						</div>

						<p class="text-xs text-slate-500 mt-4">
							Billed monthly. Cancel anytime.
						</p>
					</div>
				{:else if isEnterpriseRange}
					<div class="bg-blue-50 rounded-lg p-6 border border-blue-200">
						<h3 class="text-lg font-semibold text-blue-900 mb-2">Enterprise Pricing</h3>
						<p class="text-blue-800 mb-4">
							For organizations with 11 or more seats, we offer custom enterprise plans with volume discounts and dedicated support.
						</p>
						<a
							href="mailto:contact@vitevue.com"
							class="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 transition-colors"
						>
							Contact Sales
							<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"></path>
							</svg>
						</a>
					</div>
				{/if}

				<!-- Submit Button -->
				{#if isValidSeatCount && !isEnterpriseRange}
					<button
						type="submit"
						disabled={loading}
						class="w-full bg-slate-900 hover:bg-slate-800 text-white font-semibold rounded-lg px-6 py-4 transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-lg"
					>
						{loading ? 'Processing...' : 'Continue to Payment'}
					</button>
				{/if}
			</form>

			<!-- Features List -->
			<div class="mt-8 pt-8 border-t border-slate-200">
				<p class="text-sm font-medium text-slate-700 mb-3">All plans include:</p>
				<div class="grid grid-cols-2 gap-3">
					{#each ['Real-time transaction data', 'AI-powered insights', 'Advanced analytics', 'Unlimited projects', 'Email support', 'Export capabilities'] as feature}
						<div class="flex items-center gap-2 text-sm text-slate-600">
							<svg class="w-5 h-5 text-slate-900 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
							</svg>
							<span>{feature}</span>
						</div>
					{/each}
				</div>
			</div>
		{/if}
	</div>
</div>
</div>
