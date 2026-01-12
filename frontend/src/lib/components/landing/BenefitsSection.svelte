<script lang="ts">
	import { fly } from 'svelte/transition';
	import { cubicOut } from 'svelte/easing';
	import BenefitCard from './BenefitCard.svelte';

	let isVisible = $state(false);

	$effect(() => {
		isVisible = true;
	});

	const benefits = [
		{
			icon: '🎯',
			title: 'Close deals 3x faster',
			description: 'AI-powered market insights at your fingertips. Get instant answers to complex market questions in seconds.',
			gradient: 'from-blue-500/5 to-cyan-500/5',
			accentColor: 'text-blue-600'
		},
		{
			icon: '📊',
			title: 'Spot opportunities first',
			description: 'Real-time transaction tracking across 200+ projects. Stay ahead of market trends before your competitors.',
			gradient: 'from-purple-500/5 to-pink-500/5',
			accentColor: 'text-purple-600'
		},
		{
			icon: '💡',
			title: 'Stop drowning in data',
			description: 'Ask questions in plain English, get intelligent answers instantly. No more endless spreadsheet analysis.',
			gradient: 'from-green-500/5 to-teal-500/5',
			accentColor: 'text-green-600'
		},
		{
			icon: '✨',
			title: 'Impress every client',
			description: 'Professional, data-backed insights that close conversations. Show up to every meeting fully prepared.',
			gradient: 'from-orange-500/5 to-yellow-500/5',
			accentColor: 'text-orange-600'
		}
	];
</script>

<section class="py-24 bg-gradient-to-b from-background-surface to-background relative overflow-hidden">
	<!-- Background decoration -->
	<div class="absolute top-0 left-0 w-full h-px bg-gradient-to-r from-transparent via-gray-300 to-transparent"></div>

	<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
		<div class="text-center mb-20">
			<div class="inline-block px-4 py-2 bg-[#009999]/10 rounded-full mb-6">
				<span class="text-[#009999] font-bold text-sm tracking-wide">WHY VITEVUE</span>
			</div>
			<h2 class="text-4xl sm:text-5xl md:text-6xl font-black text-gray-900 mb-6 leading-tight">
				Work smarter, not harder
			</h2>
			<p class="text-xl sm:text-2xl text-gray-600 max-w-3xl mx-auto">
				See what happens when AI meets Dubai real estate
			</p>
		</div>

		<div class="grid grid-cols-1 md:grid-cols-2 gap-8">
			{#each benefits as benefit, i}
				{#if isVisible}
					<div in:fly={{ y: 20, duration: 600, delay: i * 100, easing: cubicOut }}>
						<BenefitCard {...benefit} />
					</div>
				{/if}
			{/each}
		</div>
	</div>
</section>
