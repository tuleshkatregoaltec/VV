<script lang="ts">
	import { fly } from 'svelte/transition';
	import { cubicOut } from 'svelte/easing';

	let isVisible = $state(false);

	$effect(() => {
		isVisible = true;
	});

	function handleTierClick(tier: 'tier1' | 'tier2') {
		// Store selected tier in localStorage
		localStorage.setItem('selected_tier', tier);
	}

	const tiers = [
		{
			name: 'Starter',
			price: '199',
			originalPrice: '249',
			tier: 'tier1' as const,
			features: [
				'Real-time transaction data',
				'AI-powered market insights',
				'Advanced analytics dashboard',
				'Unlimited project tracking'
			],
			href: '/auth?view=signup&tier=tier1',
			comingSoon: true
		},
		{
			name: 'Professional',
			price: '499',
			originalPrice: '799',
			tier: 'tier2' as const,
			features: [
				'Everything in Starter',
				'Automated deliverables',
				'5x Vitevue AI usage',
				'Industry-grade comparables',
				'Priority support'
			],
			href: '/auth?view=signup&tier=tier2',
			comingSoon: true
		},
		{
			name: 'Enterprise',
			price: 'Custom',
			tier: null,
			features: [
				'Tailored to your organization',
				'Early access to advanced features',
				'Custom integrations',
				'Bespoke product suite'
			],
			href: 'mailto:contact@vitevue.com',
			isContact: true
		}
	];
</script>

<section id="pricing" class="py-24 bg-gradient-to-b from-white via-slate-50 to-white relative">
	<div class="max-w-6xl mx-auto px-6 lg:px-8">
		<div class="text-center mb-16">
			<h2 class="text-4xl sm:text-5xl font-bold text-slate-900 mb-4">Early bird pricing</h2>
			<p class="text-xl text-slate-600 max-w-2xl mx-auto mb-4">
				Lock in our launch pricing before rates increase
			</p>
			<div
				class="inline-flex items-center gap-2 px-4 py-2 bg-teal-50 border border-teal-200 rounded-full"
			>
				<svg class="w-4 h-4 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
					></path>
				</svg>
				<span class="text-sm font-semibold text-teal-700">Limited time offer</span>
			</div>
		</div>

		<div class="grid grid-cols-1 md:grid-cols-3 gap-8 max-w-5xl mx-auto">
			{#each tiers as tier, i}
				{#if isVisible}
					<div
						transition:fly={{ y: 20, duration: 600, delay: i * 100, easing: cubicOut }}
						class="relative bg-white rounded-2xl shadow-sm border border-slate-200 p-8 flex flex-col hover:shadow-lg hover:border-slate-300 transition-all"
					>
						{#if tier.originalPrice}
							<div
								class="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 bg-gradient-to-r from-teal-600 to-cyan-600 text-white text-xs font-semibold rounded-full"
							>
								Early Bird
							</div>
						{/if}

						<div class="flex-1">
							<h3 class="text-2xl font-bold text-slate-900 mb-2">{tier.name}</h3>
							<div class="mb-6">
								{#if tier.price === 'Custom'}
									<div class="text-4xl font-bold text-slate-900 mb-1">Custom</div>
									<p class="text-sm text-slate-600">Contact us for pricing</p>
								{:else}
									<div class="mb-2">
										{#if tier.originalPrice}
											<div class="flex items-baseline gap-2 mb-1">
												<span class="text-lg text-slate-400 line-through">{tier.originalPrice}</span
												>
												<span
													class="text-xs font-semibold text-teal-600 bg-teal-50 px-2 py-0.5 rounded"
												>
													Save {Math.round(
														(1 - parseInt(tier.price) / parseInt(tier.originalPrice)) * 100
													)}%
												</span>
											</div>
										{/if}
										<div class="flex items-baseline gap-2">
											<span class="text-4xl font-bold text-slate-900">{tier.price}</span>
											<span class="text-slate-600">AED/seat/month</span>
										</div>
									</div>
								{/if}
							</div>

							<ul class="space-y-3 mb-8">
								{#each tier.features as feature}
									<li class="flex items-start gap-3">
										<svg
											class="w-5 h-5 text-slate-900 flex-shrink-0 mt-0.5"
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
										<span class="text-slate-700">{feature}</span>
									</li>
								{/each}
							</ul>
						</div>

						{#if tier.comingSoon}
							<button
								type="button"
								disabled
								class="block w-full text-center px-6 py-3 rounded-lg font-semibold bg-slate-200 text-slate-400 cursor-not-allowed"
							>
								Get Started
							</button>
						{:else}
							<a
								href={tier.href}
								onclick={() => tier.tier && handleTierClick(tier.tier)}
								class="block w-full text-center px-6 py-3 rounded-lg font-semibold transition-all bg-slate-900 text-white hover:bg-slate-800 hover:scale-105"
							>
								{tier.isContact ? 'Contact Sales' : 'Get Started'}
							</a>
						{/if}
					</div>
				{/if}
			{/each}
		</div>
	</div>
</section>
