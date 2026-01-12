<script lang="ts">
	import { fly } from 'svelte/transition';
	import { cubicOut } from 'svelte/easing';
	import PersonaCard from './PersonaCard.svelte';

	let isVisible = $state(false);

	$effect(() => {
		isVisible = true;
	});

	const personas = [
		{
			icon: '🏢',
			title: 'Brokers & Agents',
			description: 'Price properties with confidence using live market data and AI-powered comparables.'
		},
		{
			icon: '💼',
			title: 'Institutional Investors',
			description: 'Identify high-yield opportunities with comprehensive trend analytics and market intelligence.'
		},
		{
			icon: '📈',
			title: 'Consultants & Valuers',
			description: 'Generate client-ready insights in minutes with AI-assisted analysis and reporting.'
		},
		{
			icon: '🏗️',
			title: 'Developers',
			description: 'Track supply, demand, and competition in real-time across Dubai developments.'
		}
	];
</script>

<section class="py-24 bg-gradient-to-b from-background to-background-surface relative">
	<!-- Decorative elements -->
	<div class="absolute top-1/2 left-0 w-72 h-72 bg-gradient-to-br from-[#009999]/10 to-transparent rounded-full blur-3xl"></div>
	<div class="absolute bottom-1/4 right-0 w-96 h-96 bg-gradient-to-br from-purple-500/10 to-transparent rounded-full blur-3xl"></div>

	<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
		<div class="text-center mb-20">
			<div class="inline-block px-4 py-2 bg-purple-500/10 rounded-full mb-6">
				<span class="text-purple-600 font-bold text-sm tracking-wide">WHO IT'S FOR</span>
			</div>
			<h2 class="text-4xl sm:text-5xl md:text-6xl font-black text-gray-900 mb-6 leading-tight">
				Built for professionals<br />
				<span class="bg-gradient-to-r from-purple-600 to-pink-600 bg-clip-text text-transparent">
					who demand the best
				</span>
			</h2>
			<p class="text-xl sm:text-2xl text-gray-600 max-w-3xl mx-auto">
				Trusted by Dubai's leading real estate experts
			</p>
		</div>

		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
			{#each personas as persona, i}
				{#if isVisible}
					<div in:fly={{ y: 20, duration: 600, delay: i * 100, easing: cubicOut }}>
						<PersonaCard {...persona} />
					</div>
				{/if}
			{/each}
		</div>
	</div>
</section>
