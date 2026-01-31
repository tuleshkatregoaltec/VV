<script lang="ts">
	import { fly } from 'svelte/transition';
	import { cubicOut } from 'svelte/easing';

	let isVisible = $state(false);

	$effect(() => {
		isVisible = true;
	});

	const tiers = [
		{
			name: 'Starter',
			price: '199',
			popular: false,
			features: [
				'Real-time transaction data',
				'AI-powered market insights',
				'Advanced analytics dashboard',
				'Unlimited project tracking',
				'Email support'
			],
			href: '/auth?view=signup'
		},
		{
			name: 'Professional',
			price: '499',
			popular: true,
			savings: '100',
			features: [
				'Everything in Starter',
				'Automated deliverables',
				'5x Vitevue AI usage',
				'Industry-grade comparables',
				''
			],
			href: '/auth?view=signup'
		},
		{
			name: 'Enterprise',
			price: 'Custom',
			popular: false,
			features: [
				'Everything in Professional',
				'Dedicated account manager',
				'Custom integrations',
				'SLA guarantees',
				'White-label options'
			],
			href: 'mailto:contact@vitevue.com',
			isContact: true
		}
	];
</script>

<section class="py-24 bg-gradient-to-b from-white via-slate-50 to-white relative">
	<div class="max-w-6xl mx-auto px-6 lg:px-8">
		<div class="text-center mb-16">
			<!-- Section badge -->
			<div
				class="inline-flex items-center gap-2 px-4 py-2 bg-slate-50 border border-slate-200 rounded-full mb-6"
			>
				<svg class="w-4 h-4 text-slate-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
					></path>
				</svg>
				<span class="text-sm font-semibold text-slate-700">Pricing</span>
			</div>

			<h2 class="text-4xl sm:text-5xl font-bold text-slate-900 mb-4">
				Simple, transparent pricing
			</h2>
			<p class="text-xl text-slate-600 max-w-2xl mx-auto">
				Per-seat subscription with no hidden fees. Pay only for what you need.
			</p>
		</div>

		<div class="grid grid-cols-1 md:grid-cols-3 gap-8 max-w-5xl mx-auto">
			{#each tiers as tier, i}
				{#if isVisible}
					<div
						transition:fly={{ y: 20, duration: 600, delay: i * 100, easing: cubicOut }}
						class="relative bg-white rounded-2xl shadow-sm border border-slate-200 p-8 flex flex-col {tier.popular
							? 'ring-2 ring-slate-900'
							: ''}"
					>
						{#if tier.popular}
							<div
								class="absolute -top-4 left-1/2 -translate-x-1/2 px-4 py-1 bg-slate-900 text-white text-sm font-semibold rounded-full"
							>
								Most Popular
							</div>
						{/if}

						<div class="flex-1">
							<h3 class="text-2xl font-bold text-slate-900 mb-2">{tier.name}</h3>
							<div class="mb-6">
								{#if tier.price === 'Custom'}
									<p class="text-sm text-slate-600 mt-1">{tier.seats}</p>
								{:else}
									<div class="flex items-baseline gap-2">
										<span class="text-4xl font-bold text-slate-900">{tier.price}</span>
										<span class="text-slate-600">AED/seat/month</span>
									</div>
									{#if tier.savings}
										<div class="inline-block mt-2 px-2 py-1 bg-green-100 text-green-800 text-xs font-semibold rounded">
											Save {tier.savings} AED/seat
										</div>
									{/if}
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

						<a
							href={tier.href}
							class="block w-full text-center px-6 py-3 rounded-lg font-semibold transition-all {tier.popular
								? 'bg-slate-900 text-white hover:bg-slate-800'
								: 'bg-slate-100 text-slate-900 hover:bg-slate-200'}"
						>
							{tier.isContact ? 'Contact Sales' : 'Get Started'}
						</a>
					</div>
				{/if}
			{/each}
		</div>
	</div>
</section>
