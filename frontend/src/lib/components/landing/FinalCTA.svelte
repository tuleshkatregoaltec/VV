<script lang="ts">
import { cubicOut } from 'svelte/easing'
import { fly } from 'svelte/transition'

let isVisible = $state(false)

$effect(() => {
	isVisible = true
})
</script>

<section id="get-started" class="py-24 bg-slate-50 relative overflow-hidden">
	<!-- Subtle gradient overlay -->
	<div
		class="absolute inset-0 bg-gradient-to-br from-slate-100/50 via-white/30 to-slate-100/50"
	></div>

	<!-- Floating decorative elements -->
	<div
		class="absolute top-1/4 right-10 w-32 h-32 bg-teal-100 rounded-full blur-3xl opacity-30 animate-float-slow"
	></div>
	<div
		class="absolute bottom-1/4 left-10 w-40 h-40 bg-cyan-100 rounded-full blur-3xl opacity-30 animate-float-delayed"
	></div>

	<div class="max-w-4xl mx-auto px-6 lg:px-8 text-center relative">
		{#if isVisible}
			<div in:fly={{ y: 20, duration: 600, easing: cubicOut }}>
				<!-- Icon badge -->
				<div
					class="inline-flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-full mb-8 shadow-sm hover:scale-105 hover:shadow-md transition-all duration-300"
				>
					<svg class="w-4 h-4 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M17 8h2a2 2 0 012 2v6a2 2 0 01-2 2h-2v4l-4-4H9a1.994 1.994 0 01-1.414-.586m0 0L11 14h4a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2v4l.586-.586z"
						></path>
					</svg>
					<span class="text-sm font-semibold text-slate-700">Get started</span>
				</div>

				<h2
					class="text-4xl sm:text-5xl font-bold text-slate-900 mb-6 leading-tight hover:scale-[1.02] transition-transform duration-500"
				>
					Ready to
					<span class="bg-gradient-to-r from-teal-600 to-cyan-600 bg-clip-text text-transparent">
						transform
					</span>
					your workflow?
				</h2>
				<p class="text-xl text-slate-600 mb-10 max-w-2xl mx-auto leading-relaxed">
					Join Dubai's leading real estate professionals in making faster, data-driven decisions
				</p>

				<div class="flex flex-col sm:flex-row gap-4 justify-center mb-10">
					<button
						type="button"
						disabled
						class="inline-flex items-center justify-center gap-2 px-8 py-4 bg-slate-200 text-slate-400 font-semibold rounded-lg cursor-not-allowed text-base"
					>
						Get Started
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M13 7l5 5m0 0l-5 5m5-5H6"
							></path>
						</svg>
					</button>
					<button
						type="button"
						disabled
						class="inline-flex items-center justify-center gap-2 px-8 py-4 bg-slate-200 text-slate-400 font-semibold rounded-lg cursor-not-allowed text-base"
					>
						Your Dashboard
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
							></path>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
							></path>
						</svg>
					</button>
				</div>

				<!-- Visual feature badges -->
				<div class="flex flex-wrap justify-center gap-4 text-sm">
					<div
						class="group flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-lg shadow-sm hover:scale-105 hover:shadow-md hover:border-slate-300 transition-all duration-300"
					>
						<svg
							class="w-4 h-4 text-teal-600 group-hover:scale-110 transition-transform"
							fill="none"
							stroke="currentColor"
							viewBox="0 0 24 24"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
							></path>
						</svg>
						<span class="font-medium text-slate-700">Data first</span>
					</div>
					<div
						class="group flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-lg shadow-sm hover:scale-105 hover:shadow-md hover:border-slate-300 transition-all duration-300"
					>
						<svg
							class="w-4 h-4 text-teal-600 group-hover:scale-110 transition-transform"
							fill="none"
							stroke="currentColor"
							viewBox="0 0 24 24"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M13 10V3L4 14h7v7l9-11h-7z"
							></path>
						</svg>
						<span class="font-medium text-slate-700">Instant insights</span>
					</div>
					<div
						class="group flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-lg shadow-sm hover:scale-105 hover:shadow-md hover:border-slate-300 transition-all duration-300"
					>
						<svg
							class="w-4 h-4 text-teal-600 group-hover:scale-110 transition-transform"
							fill="none"
							stroke="currentColor"
							viewBox="0 0 24 24"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M18.364 5.636l-3.536 3.536m0 5.656l3.536 3.536M9.172 9.172L5.636 5.636m3.536 9.192l-3.536 3.536M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-5 0a4 4 0 11-8 0 4 4 0 018 0z"
							></path>
						</svg>
						<span class="font-medium text-slate-700">Expert support</span>
					</div>
				</div>
			</div>
		{/if}
	</div>
</section>
