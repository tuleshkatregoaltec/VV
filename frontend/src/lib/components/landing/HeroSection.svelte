<script lang="ts">
	import { fly, fade } from 'svelte/transition';
	import { cubicOut } from 'svelte/easing';

	let isVisible = $state(false);

	$effect(() => {
		isVisible = true;
	});

	function scrollToPreview() {
		document.getElementById('preview')?.scrollIntoView({ behavior: 'smooth' });
	}
</script>

<section class="relative min-h-[95vh] bg-gradient-to-b from-background via-background to-background-surface flex items-center justify-center overflow-hidden">
	<!-- Animated background elements -->
	<div class="absolute inset-0 overflow-hidden">
		<div class="absolute top-1/4 left-1/4 w-96 h-96 bg-gradient-to-br from-[#009999]/20 to-blue-500/20 rounded-full blur-3xl animate-float"></div>
		<div class="absolute bottom-1/3 right-1/4 w-80 h-80 bg-gradient-to-br from-purple-500/20 to-pink-500/20 rounded-full blur-3xl animate-float-delayed"></div>
		<div class="absolute top-1/2 right-1/3 w-72 h-72 bg-gradient-to-br from-orange-500/15 to-yellow-500/15 rounded-full blur-3xl animate-float-slow"></div>
	</div>

	<div class="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12 text-center">
		{#if isVisible}
		<div in:fly={{ y: 32, duration: 700, easing: cubicOut }}>
			<h1 class="text-5xl sm:text-6xl md:text-7xl lg:text-8xl font-black leading-[1.05] mb-8 tracking-tight text-gray-900">
				The platform that gives<br />
				<span class="relative inline-block pb-3">
					<span class="bg-gradient-to-r from-[#009999] via-blue-600 to-purple-600 bg-clip-text text-transparent">
						you the edge
					</span>
				</span>
			</h1>

			<p class="text-xl sm:text-2xl md:text-3xl text-gray-600 font-medium max-w-4xl mx-auto mb-4 leading-relaxed">
				Stop drowning in spreadsheets. Start making <span class="text-[#009999] font-bold">AI-powered</span> decisions.
			</p>
			<p class="text-lg sm:text-xl text-gray-500 max-w-3xl mx-auto mb-12">
				Trusted by Dubai's leading brokers, investors, and consultants
			</p>

			<div class="flex flex-col sm:flex-row gap-4 justify-center items-center mb-12">
				<a
					href="mailto:contact@vitevue.com"
					class="group px-10 py-5 bg-gradient-to-r from-[#009999] to-[#007788] text-white font-bold rounded-xl hover:shadow-2xl transition-all duration-300 shadow-xl text-lg"
				>
					<span class="flex items-center gap-2">
						Contact Sales
						<svg class="w-5 h-5 group-hover:translate-x-1 transition-transform duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"></path>
						</svg>
					</span>
				</a>
				<button
					onclick={scrollToPreview}
					class="group px-10 py-5 bg-white/80 backdrop-blur-sm text-gray-900 font-bold rounded-xl hover:shadow-2xl transition-all duration-300 shadow-lg border-2 border-gray-200 hover:border-[#009999]/30 text-lg"
				>
					<span class="flex items-center gap-2">
						See How It Works
						<svg class="w-5 h-5 group-hover:translate-y-1 transition-transform duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
						</svg>
					</span>
				</button>
			</div>
		</div>

		<!-- Social proof badges - moved below -->
		
		{/if}
	</div>
</section>
