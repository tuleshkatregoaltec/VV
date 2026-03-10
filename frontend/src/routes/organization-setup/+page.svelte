<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { createCheckoutSession } from '$lib/api/billing';
	import { createOrganization } from '$lib/api/organization';
	import { currentUser } from '$lib/stores/user.svelte';

	let organizationName = $state('');
	let seats = $state(3);
	let customSeats = $state('');
	let useCustomSeats = $state(false);
	let loading = $state(false);
	let loadingStep = $state<'creating-org' | 'creating-checkout' | null>(null);
	let error = $state('');
	let userLoaded = $state(false);
	let selectedTier = $state<'tier1' | 'tier2'>('tier1');

	const commonSeatOptions = [1, 3, 5, 10, 20];

	// Pricing tiers
	const TIER1_PRICE = 199;
	const TIER2_PRICE = 499;
	const TIER1_NAME = 'Starter';
	const TIER2_NAME = 'Professional';

	// Computed values
	const isValidSeatCount = $derived(seats >= 1);
	const pricePerSeat = $derived(selectedTier === 'tier1' ? TIER1_PRICE : TIER2_PRICE);
	const totalMonthly = $derived(seats * pricePerSeat);
	const tierName = $derived(selectedTier === 'tier1' ? TIER1_NAME : TIER2_NAME);

	// Layout ensures user is authenticated with complete profile before this page loads
	onMount(() => {
		const user = currentUser.data;

		// Get tier from URL parameter or localStorage
		const tierParam = $page.url.searchParams.get('tier');
		if (tierParam === 'tier1' || tierParam === 'tier2') {
			selectedTier = tierParam;
			localStorage.removeItem('selected_tier');
		} else {
			const storedTier = localStorage.getItem('selected_tier');
			if (storedTier === 'tier1' || storedTier === 'tier2') {
				selectedTier = storedTier;
				localStorage.removeItem('selected_tier');
			}
		}

		organizationName = user ? `${user.first_name}'s Organization` : '';
		userLoaded = true;
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

		loading = true;
		error = '';

		try {
			// Step 1: Create organization (idempotent - reuses existing if present)
			loadingStep = 'creating-org';
			const orgResult = await createOrganization(organizationName.trim(), seats);

			console.log('Organization created/updated:', orgResult);

			// Step 2: Create Stripe checkout session with org_id
			loadingStep = 'creating-checkout';
			const checkoutResult = await createCheckoutSession(
				orgResult.organization_id,
				seats,
				selectedTier
			);

			console.log('Checkout session created:', checkoutResult);

			// Step 3: Redirect to Stripe
			if (!checkoutResult.checkout_url) {
				throw new Error('No checkout URL returned from server');
			}

			window.location.href = checkoutResult.checkout_url;
		} catch (err: any) {
			console.error('Payment setup failed:', err);
			const step =
				loadingStep === 'creating-org' ? 'organization creation' : 'checkout session creation';

			// Show detailed error message
			if (err.message) {
				error = `Failed during ${step}: ${err.message}`;
			} else {
				error = `Failed during ${step}. Please try again or contact support.`;
			}

			loading = false;
			loadingStep = null;
		}
	}
</script>

<svelte:head>
	<title>Organization Setup - Vitevue</title>
</svelte:head>

<div
	class="min-h-screen bg-gradient-to-br from-slate-50 to-white flex items-center justify-center p-4"
>
	<div class="w-full max-w-2xl">
		<div class="bg-white rounded-xl shadow-lg p-8">
			<!-- Header -->
			<div class="mb-8">
				<h1 class="text-3xl font-bold text-slate-900 mb-2">Set up your organization</h1>
				<p class="text-slate-600">
					Complete your {tierName} plan setup
				</p>
			</div>

			<!-- Tier Selection -->
			<div>
				<p class="block text-sm font-medium text-slate-700 mb-3">Select Plan</p>
				<div class="grid grid-cols-2 gap-3 mb-6">
					<button
						type="button"
						onclick={() => (selectedTier = 'tier1')}
						class="p-4 rounded-lg border-2 text-left transition-all {selectedTier === 'tier1'
							? 'border-slate-900 bg-slate-900 text-white'
							: 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'}"
					>
						<p class="font-semibold">{TIER1_NAME}</p>
						<p class="text-2xl font-bold mt-1">
							{TIER1_PRICE} <span class="text-sm font-normal">AED/seat/mo</span>
						</p>
					</button>
					<button
						type="button"
						onclick={() => (selectedTier = 'tier2')}
						class="p-4 rounded-lg border-2 text-left transition-all {selectedTier === 'tier2'
							? 'border-slate-900 bg-slate-900 text-white'
							: 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'}"
					>
						<p class="font-semibold">{TIER2_NAME}</p>
						<p class="text-2xl font-bold mt-1">
							{TIER2_PRICE} <span class="text-sm font-normal">AED/seat/mo</span>
						</p>
					</button>
				</div>
			</div>

			{#if error}
				<div class="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
					{error}
				</div>
			{/if}

			{#if userLoaded}
				<form
					onsubmit={(e) => {
						e.preventDefault();
						handleSubmit();
					}}
					class="space-y-6"
				>
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
						<div class="block text-sm font-medium text-slate-700 mb-3">Number of Seats</div>
						<div class="flex gap-2 mb-4">
							{#each commonSeatOptions as option}
								<button
									type="button"
									onclick={() => handleSeatSelection(option)}
									class="px-4 py-3 rounded-lg border-2 font-medium transition-all {seats ===
										option && !useCustomSeats
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
							<label for="customSeats" class="text-sm text-slate-600"> Custom amount </label>
						</div>

						{#if useCustomSeats}
							<div class="mt-2">
								<input
									type="number"
									bind:value={customSeats}
									oninput={handleCustomSeatsChange}
									min="1"
									placeholder="Enter number of seats"
									class="w-full px-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-slate-900 focus:border-transparent"
								/>
							</div>
						{/if}
					</div>

					<!-- Pricing Display -->
					{#if isValidSeatCount}
						<div class="bg-slate-50 rounded-lg p-6 border border-slate-200">
							<div class="flex items-center justify-between py-3">
								<span class="text-slate-700"
									>{seats} {seats === 1 ? 'seat' : 'seats'} × {pricePerSeat} AED</span
								>
								<span class="text-2xl font-bold text-slate-900">{totalMonthly} AED/month</span>
							</div>

							<p class="text-xs text-slate-500 mt-4">Billed monthly. Cancel anytime.</p>
						</div>
					{/if}

					<!-- Submit Button -->
					{#if isValidSeatCount}
						<button
							type="submit"
							disabled={loading}
							class="w-full bg-slate-900 hover:bg-slate-800 text-white font-semibold rounded-lg px-6 py-4 transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-lg"
						>
							{#if loading}
								{loadingStep === 'creating-org'
									? 'Creating organization...'
									: loadingStep === 'creating-checkout'
										? 'Setting up payment...'
										: 'Processing...'}
							{:else}
								Continue to Payment
							{/if}
						</button>
					{/if}
				</form>

				<!-- Features List -->
				<div class="mt-8 pt-8 border-t border-slate-200">
					<p class="text-sm font-medium text-slate-700 mb-3">All plans include:</p>
					<div class="grid grid-cols-2 gap-3">
						{#each ['Real-time transaction data', 'AI-powered insights', 'Advanced analytics', 'Unlimited projects', 'Email support', 'Export capabilities'] as feature}
							<div class="flex items-center gap-2 text-sm text-slate-600">
								<svg
									class="w-5 h-5 text-slate-900 flex-shrink-0"
									fill="none"
									stroke="currentColor"
									viewBox="0 0 24 24"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M5 13l4 4L19 7"
									></path>
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
