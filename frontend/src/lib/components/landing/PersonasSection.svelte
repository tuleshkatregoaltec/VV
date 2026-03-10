<script lang="ts">
import { cubicOut } from 'svelte/easing'
import { fly } from 'svelte/transition'
import PersonaCard from './PersonaCard.svelte'

let isVisible = $state(false)

$effect(() => {
	isVisible = true
})

const personas = [
	{
		title: 'Brokers & Agents',
		description:
			'Verify your pricing with ease, generate leads, automate your listing descriptions and stand out to clients with commercial-grade analysis.',
		icon: 'M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z'
	},
	{
		title: 'Consultants & Valuers',
		description:
			'Generate client-ready comps and reports instantly, predict hidden market trends with AI-native semantic and quantitative analysis.',
		icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z'
	},
	{
		title: 'Developers',
		description:
			'Track supply and price dynamics, competitive positioning and identify feasibility and configuration opportunities across Dubai.',
		icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4'
	},
	{
		title: 'Institutional Investors',
		description:
			'Obtain KPI-driven benchmarks across all asset classes, generate institutional-grade reports to narrow pipeline and win more mandates.',
		icon: 'M13 7h8m0 0v8m0-8l-8 8-4-4-6 6'
	}
]
</script>

<section id="personas" class="py-24 bg-white relative">
	<!-- Subtle decorative background -->
	<div class="absolute inset-0 bg-gradient-to-b from-white via-slate-50/30 to-white"></div>

	<div class="max-w-6xl mx-auto px-6 lg:px-8 relative">
		<div class="text-center mb-16">
			<!-- Section badge -->
			<div
				class="inline-flex items-center gap-2 px-4 py-2 bg-slate-50 border border-slate-200 rounded-full mb-6 hover:scale-105 hover:shadow-md transition-all duration-300"
			>
				<svg class="w-4 h-4 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"
					></path>
				</svg>
				<span class="text-sm font-semibold text-slate-700">Our partners</span>
			</div>

			<h2 class="text-4xl sm:text-5xl font-bold text-slate-900 mb-4">Be the tip of the spear</h2>
			<p class="text-xl text-slate-600 max-w-2xl mx-auto">
				Equipping Dubai's elite real estate professionals
			</p>
		</div>

		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
			{#each personas as persona, i (persona.title)}
				{#if isVisible}
					<div in:fly={{ y: 20, duration: 600, delay: i * 100, easing: cubicOut }}>
						<div
							class="group bg-slate-50 p-6 rounded-lg border border-slate-200 h-full hover:border-slate-300 hover:shadow-md hover:bg-white transition-all hover:scale-105 hover:-translate-y-2"
						>
							<!-- Icon with visual accent -->
							<div class="relative mb-4">
								<div
									class="w-12 h-12 bg-gradient-to-br from-slate-800 to-slate-900 rounded-lg flex items-center justify-center group-hover:scale-110 group-hover:rotate-12 transition-all duration-300"
								>
									<svg
										class="w-6 h-6 text-white"
										fill="none"
										stroke="currentColor"
										viewBox="0 0 24 24"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d={persona.icon}
										></path>
									</svg>
								</div>
								<!-- Small accent dot with pulse animation -->
								<div
									class="absolute -top-1 -right-1 w-3 h-3 bg-teal-500 rounded-full border-2 border-slate-50 group-hover:animate-pulse"
								></div>
							</div>
							<h3
								class="text-lg font-semibold text-slate-900 mb-2 group-hover:text-teal-600 transition-colors"
							>
								{persona.title}
							</h3>
							<p class="text-slate-600 text-sm leading-relaxed">{persona.description}</p>
						</div>
					</div>
				{/if}
			{/each}
		</div>

		<!-- Visual separator with icons -->
		<div class="mt-16 pt-16 border-t border-slate-200">
			<div class="flex flex-wrap justify-center items-center gap-8 text-sm text-slate-500">
				<div class="flex items-center gap-2">
					<svg class="w-5 h-5 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
						></path>
					</svg>
					<span class="font-medium">Enterprise-grade security</span>
				</div>
				<div class="flex items-center gap-2">
					<svg class="w-5 h-5 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M18.364 5.636l-3.536 3.536m0 5.656l3.536 3.536M9.172 9.172L5.636 5.636m3.536 9.192l-3.536 3.536M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-5 0a4 4 0 11-8 0 4 4 0 018 0z"
						></path>
					</svg>
					<span class="font-medium">24/7 support</span>
				</div>
				<div class="flex items-center gap-2">
					<svg class="w-5 h-5 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"
						></path>
					</svg>
					<span class="font-medium">Continuous updates</span>
				</div>
			</div>
		</div>
	</div>
</section>
