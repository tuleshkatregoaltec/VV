<script lang="ts">
	import { fly } from 'svelte/transition';
	import { cubicOut } from 'svelte/easing';

	let isVisible = $state(false);

	$effect(() => {
		isVisible = true;
	});
</script>

<section class="py-32 bg-gradient-to-b from-background-surface to-background relative overflow-hidden">
	<!-- Background elements -->
	<div class="absolute inset-0">
		<div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-gradient-to-br from-[#009999]/20 via-purple-500/10 to-transparent rounded-full blur-3xl animate-pulse-slow"></div>
	</div>

	<div class="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 text-center relative z-10">
		{#if isVisible}
		<div in:fly={{ y: 40, duration: 800, easing: cubicOut }} class="bg-white/60 backdrop-blur-xl rounded-3xl p-12 sm:p-16 shadow-2xl border border-gray-200">
			<h2 class="text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-black text-gray-900 mb-6 leading-tight">
				Ready to gain<br />
				<span class="bg-gradient-to-r from-[#009999] via-blue-600 to-purple-600 bg-clip-text text-transparent">
					your edge?
				</span>
			</h2>
			<p class="text-xl sm:text-2xl text-gray-600 mb-12 max-w-2xl mx-auto leading-relaxed">
				Join the professionals making faster, smarter decisions with AI-powered intelligence.
			</p>
			<div class="flex flex-col sm:flex-row gap-4 justify-center mb-8">
				<a
					href="mailto:contact@vitevue.com"
					class="group px-12 py-6 bg-gradient-to-r from-[#009999] to-[#007788] text-white font-bold rounded-xl hover:shadow-2xl transition-all duration-300 shadow-xl text-xl"
				>
					<span class="flex items-center justify-center gap-2">
						Contact Sales
						<svg class="w-6 h-6 group-hover:translate-x-1 transition-transform duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"></path>
						</svg>
					</span>
				</a>
				<a
					href="/dashboard"
					class="px-12 py-6 bg-white text-gray-900 font-bold rounded-xl hover:shadow-2xl transition-all duration-300 shadow-lg border-2 border-gray-300 hover:border-[#009999]/50 text-xl"
				>
					View Dashboard
				</a>
			</div>
			<p class="text-sm text-gray-500">
				Enterprise-grade platform • Verified data • AI-powered insights
			</p>
		</div>
		{/if}
	</div>
</section>
