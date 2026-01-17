<script lang="ts">
	import { fly } from 'svelte/transition';
	import { cubicOut } from 'svelte/easing';
	import { onMount } from 'svelte';

	let isVisible = $state(false);
	let cardsInView = $state<boolean[]>([false, false, false, false]);
	let sectionElement: HTMLElement;

	$effect(() => {
		isVisible = true;
	});

	onMount(() => {
		const observer = new IntersectionObserver(
			(entries) => {
				entries.forEach((entry, index) => {
					if (entry.isIntersecting) {
						const cardIndex = parseInt(entry.target.getAttribute('data-index') || '0');
						cardsInView[cardIndex] = true;
					}
				});
			},
			{ threshold: 0.2 }
		);

		const cards = sectionElement.querySelectorAll('[data-index]');
		cards.forEach((card) => observer.observe(card));

		return () => observer.disconnect();
	});

	const benefits = [
		{
			title: 'Transaction Intelligence',
			description: 'Access comprehensive sales and rental data across 200+ projects. Filter by area, property type, price range, and timing.',
			icon: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z'
		},
		{
			title: 'AI-Powered Analysis',
			description: 'Ask questions in natural language and receive instant, data-backed answers about market trends and opportunities.',
			icon: 'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z'
		},
		{
			title: 'Supply Tracking',
			description: 'Monitor development pipelines, launch schedules, and unit availability to identify market dynamics.',
			icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4'
		},
		{
			title: 'Professional Reports',
			description: 'Generate comprehensive market analyses with charts and insights that demonstrate expertise to clients.',
			icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z'
		}
	];
</script>

<section bind:this={sectionElement} class="py-24 bg-slate-50 relative">
	<!-- Decorative element -->
	<div class="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-slate-300 to-transparent"></div>

	<div class="max-w-6xl mx-auto px-6 lg:px-8">
		<div class="text-center mb-16">
			<!-- Section badge -->
			<div class="inline-flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-full mb-6 shadow-sm">
				<svg class="w-4 h-4 text-slate-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"></path>
				</svg>
				<span class="text-sm font-semibold text-slate-700">Platform Features</span>
			</div>

			<h2 class="text-4xl sm:text-5xl font-bold text-slate-900 mb-4">
				Everything you need to
				<span class="bg-gradient-to-r from-teal-600 to-cyan-600 bg-clip-text text-transparent">
					analyze the market
				</span>
			</h2>
			<p class="text-xl text-slate-600 max-w-2xl mx-auto">
				Comprehensive tools for professional real estate analysis
			</p>
		</div>

		<div class="grid grid-cols-1 md:grid-cols-2 gap-6">
			{#each benefits as benefit, i}
				{#if isVisible}
					<div
						data-index={i}
						class="transition-all duration-700"
						style="transform: scale({cardsInView[i] ? 1 : 0.95}); opacity: {cardsInView[i] ? 1 : 0}"
					>
						<div class="group bg-white p-8 rounded-xl border border-slate-200 h-full hover:border-slate-300 transition-all hover:shadow-lg hover:scale-[1.02] hover:-translate-y-1">
							<!-- Icon with gradient background -->
							<div class="relative mb-5">
								<div class="absolute inset-0 bg-gradient-to-br from-teal-500/10 to-cyan-500/10 rounded-lg blur-lg group-hover:blur-xl transition-all"></div>
								<div class="relative w-12 h-12 bg-slate-900 rounded-lg flex items-center justify-center group-hover:rotate-6 group-hover:scale-110 transition-all duration-300">
									<svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d={benefit.icon}></path>
									</svg>
								</div>
							</div>
							<h3 class="text-xl font-semibold text-slate-900 mb-3 group-hover:text-teal-600 transition-colors">{benefit.title}</h3>
							<p class="text-slate-600 leading-relaxed">{benefit.description}</p>

							<!-- Visual indicator -->
							<div class="mt-5 pt-5 border-t border-slate-100 flex items-center gap-2 text-sm text-slate-500 opacity-0 group-hover:opacity-100 transition-opacity">
								<svg class="w-4 h-4 group-hover:translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
								</svg>
								<span class="font-medium">Learn more</span>
							</div>
						</div>
					</div>
				{/if}
			{/each}
		</div>
	</div>
</section>
