<script lang="ts">
	import { fly, fade, scale } from 'svelte/transition';
	import { cubicOut } from 'svelte/easing';
	import { onMount } from 'svelte';

	let isVisible = $state(false);
	let scrollY = $state(0);
	let heroElement: HTMLElement;

	$effect(() => {
		isVisible = true;
	});

	onMount(() => {
		const handleScroll = () => {
			scrollY = window.scrollY;
		};
		window.addEventListener('scroll', handleScroll);
		return () => window.removeEventListener('scroll', handleScroll);
	});

	function scrollToPreview() {
		document.getElementById('preview')?.scrollIntoView({ behavior: 'smooth' });
	}

	// Parallax calculations
	const opacity = $derived(Math.max(1 - scrollY / 500, 0));
	const translateY = $derived(scrollY * 0.5);
</script>

<section class="relative min-h-[95vh] bg-white flex items-center justify-center overflow-hidden">
	<!-- Subtle background -->
	<div class="absolute inset-0 bg-gradient-to-b from-slate-50 via-white to-slate-50/50"></div>

	<div class="relative z-10 max-w-6xl mx-auto px-6 lg:px-8 py-20 text-center"
	     style="opacity: {opacity}; transform: translateY({translateY}px)">
		{#if isVisible}
		<div in:fly={{ y: 20, duration: 600, easing: cubicOut }}>
			<!-- Badge with hover -->
			<div class="inline-flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-full mb-8 shadow-sm hover:shadow-md hover:scale-105 transition-all duration-300 cursor-default">
				<svg class="w-4 h-4 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path>
				</svg>
				<span class="text-sm font-semibold text-slate-700">Operational market intelligence</span>
			</div>

			<h1 class="text-5xl sm:text-6xl md:text-7xl font-bold leading-[1.3] mb-8 tracking-tight text-slate-900 hover:scale-[1.02] transition-transform duration-500">
				Redefining Dubai Real Estate<br />
				<span class="bg-gradient-to-r from-teal-600 to-cyan-600 bg-clip-text text-transparent inline-block">
					with AI-powered Insights
				</span>
			</h1>

			<p class="text-xl sm:text-2xl text-slate-600 max-w-3xl mx-auto mb-12 leading-relaxed">
				Operate with an edge; shorter cycles, sharper pitches, more deals
			</p>

			<div class="flex flex-col sm:flex-row gap-4 justify-center items-center mb-16">
				<a
					href="/auth?view=signup"
					class="group inline-flex items-center gap-2 px-8 py-4 bg-slate-900 text-white font-semibold rounded-lg hover:bg-slate-800 hover:scale-105 transition-all shadow-sm hover:shadow-lg text-base"
				>
					Get Started
					<svg class="w-4 h-4 group-hover:translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"></path>
					</svg>
				</a>
				<button
					onclick={scrollToPreview}
					class="group inline-flex items-center gap-2 px-8 py-4 bg-white text-slate-900 font-semibold rounded-lg hover:bg-slate-50 hover:scale-105 transition-all border border-slate-200 hover:border-slate-300 text-base"
				>
					See Platform
					<svg class="w-4 h-4 group-hover:translate-y-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
					</svg>
				</button>
			</div>

			<!-- Enhanced stats with icons and hover -->
			<div class="flex flex-wrap justify-center gap-12 pt-8 border-t border-slate-200">
				<div class="group flex items-center gap-3 cursor-default">
					<div class="w-10 h-10 bg-slate-100 rounded-lg flex items-center justify-center group-hover:bg-teal-50 group-hover:scale-110 transition-all duration-300">
						<svg class="w-5 h-5 text-slate-700 group-hover:text-teal-600 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path>
						</svg>
					</div>
					<div class="text-left">
						<div class="text-2xl font-bold text-slate-900 group-hover:text-teal-600 transition-colors">10M+</div>
						<div class="text-sm text-slate-600">Transactions</div>
					</div>
				</div>
				<div class="group flex items-center gap-3 cursor-default">
					<div class="w-10 h-10 bg-slate-100 rounded-lg flex items-center justify-center group-hover:bg-teal-50 group-hover:scale-110 transition-all duration-300">
						<svg class="w-5 h-5 text-slate-700 group-hover:text-teal-600 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"></path>
						</svg>
					</div>
					<div class="text-left">
						<div class="text-2xl font-bold text-slate-900 group-hover:text-teal-600 transition-colors">3000+</div>
						<div class="text-sm text-slate-600">Projects</div>
					</div>
				</div>
				<div class="group flex items-center gap-3 cursor-default">
					<div class="w-10 h-10 bg-slate-100 rounded-lg flex items-center justify-center group-hover:bg-teal-50 group-hover:scale-110 transition-all duration-300">
						<svg class="w-5 h-5 text-slate-700 group-hover:text-teal-600 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path>
						</svg>
					</div>
					<div class="text-left">
						<div class="text-2xl font-bold text-slate-900 group-hover:text-teal-600 transition-colors">Real-time</div>
						<div class="text-sm text-slate-600">Data Updates</div>
					</div>
				</div>
			</div>
		</div>
		{/if}
	</div>
</section>
